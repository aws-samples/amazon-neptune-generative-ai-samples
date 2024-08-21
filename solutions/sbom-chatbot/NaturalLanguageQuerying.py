"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

import logging
import ast
from typing import List
from llama_index.core.indices.property_graph import TextToCypherRetriever
from langchain_community.chains.graph_qa.cypher_utils import CypherQueryCorrector
from langchain_community.chains.graph_qa.cypher_utils import Schema
from llama_index.graph_stores.neptune import NeptuneQueryException
from llama_index.core import PromptTemplate

logger = logging.getLogger(__name__)

DEFAULT_RESPONSE_TEMPLATE = "Query:\n{query}\n\nResponse:\n{response}"
DEFAULT_TEXT_TO_CYPHER_TEMPLATE = """Task:Generate Cypher statement to query a graph database.\nInstructions:\n
Use only the provided relationship types and properties in the schema.\n
Do not use any other relationship types or properties that are not provided.\nSchema:\n{schema}\n
Note: Do not include any explanations or apologies in your responses.\nDo not respond to any questions that might ask anything else 
than for you to construct a Cypher statement.\nDo not include any text except the generated Cypher statement.\n\n
The question is:\n{question}
Wrap all property names in backticks except for label names.\n
Ensure that all property names are used in conjunction with the correct node or relationship alias.\n
All comparisons with string values should be done in lowercase.\n
Do not use RegexMatch queries, use a lowercase CONTAINS search instead.\n
Ensure that the relationship directions are correct according to the provided schema.\n
If you don\'t know how to write a query given the prompt return \'I don\'t know\'"""

REWRITE_TEXT_TO_CYPHER_TEMPLATE = """Task:Given the previous Cypher statement, question, and error message
rewrite the query to answer the question while avoiding the error message described.\n
Instructions:\nUse only the provided relationship types and properties in the schema.\n
Do not use any other relationship types or properties that are not provided.\n
Schema:\n{schema}\n
Note: Do not include any explanations or apologies in your responses.\n
Do not respond to any questions that might ask anything else 
than for you to construct a Cypher statement.\n
Do not include any text except the generated Cypher statement.\n\n
The question is:\n{question}
The previous Cypher statement is:\n{previous_cypher}\n
The previous error message is:\n{error_message}\n\n
Wrap all property names in backticks except for label names.\n
Ensure that all property names are used in conjunction with the correct node or relationship alias.\n
All comparisons with string values should be done in lowercase.\n
Do not use RegexMatch queries, use a lowercase CONTAINS search instead.\n
Ensure that the relationship directions are correct according to the provided schema.\n
If you don\'t know how to write a query given the prompt return \'I don\'t know\'"""
MAX_RETRIES = 3


class NaturalLanguageQuerying:
    # Copying the default template so it doesn't get overwritten

    def __init__(self, index, llm):
        self.graph_store = index.property_graph_store
        self.template = self.graph_store.text_to_cypher_template
        # Configure the TextToCypher Retriever
        self.cypher_retriever = TextToCypherRetriever(
            self.graph_store,
            llm=llm,
            response_template=DEFAULT_RESPONSE_TEMPLATE,
            # Setup the CypherQueryCorrector from LangChain to fix correct relationship direction
            # https://api.python.langchain.com/en/latest/chains/langchain.chains.graph_qa.cypher_utils.CypherQueryCorrector.html
            cypher_validator=CypherQueryCorrector(self.__get_langchain_schema()),
        )

    def __get_langchain_schema(self) -> List[Schema]:
        """This retrieves the schema from the graph store and converts it to a LangChain Schema

        Returns:
            Schema: A List of LangChain Schema object
        """
        edge_schema = []
        for i in self.graph_store.get_schema()["triples"]:
            i = (
                i.replace("(:`", "")
                .replace("`)", "")
                .replace("[:`", "")
                .replace("`]", "")
                .replace(">", "")
            )
            parts = i.split("-")
            if len(parts) == 3:
                edge_schema.append(
                    Schema(left_node=parts[0], relation=parts[1], right_node=parts[2])
                )

        return edge_schema

    def __determine_prompt(self, query: str, error_msg: str) -> PromptTemplate:
        """This determines which prompt template to use based on the error message and query for rewriting the query

        Args:
            query (str): The previous cypher statement that failed to execute
            error_msg (str): The error message returned by the failed query

        Returns:
            PromptTemplate: The appropriate prompt template based on the error message and query
        """
        if query is None or error_msg is None:
            self.template.template = DEFAULT_TEXT_TO_CYPHER_TEMPLATE
            return self.template
        else:
            # Use Partial Formatting on the template to add the previous cypher statement and error
            # https://docs.llamaindex.ai/en/stable/examples/prompts/advanced_prompts/#1-partial-formatting
            self.template.template = REWRITE_TEXT_TO_CYPHER_TEMPLATE
            rewrite_template = self.template.partial_format(
                previous_cypher=query, error_message=error_msg
            )
            return rewrite_template

    def run_natural_language_query(self, prompt: str) -> dict:
        """This takes in the prompt and runs the natural language query against the graph store

        Args:
            prompt (str): The prompt question to answer

        Returns:
            dict: A dictionary containing the results of the query and the query itself
        """
        retry = 0
        query = None
        error_msg = None
        while retry < MAX_RETRIES:
            try:
                self.cypher_retriever.text_to_cypher_template = self.__determine_prompt(
                    query, error_msg
                )
                logger.info(f"Query retry: {retry}")
                resp = self.cypher_retriever.retrieve(prompt)
                break
            except NeptuneQueryException as e:
                if e.message.find("MalformedQueryException") != -1:
                    logger.error(e)
                    raise e
                else:
                    logger.info(
                        f"Generated Query Failed with the following message: {e}"
                    )
                    query = e.args[0]["query"]
                    error_msg = e.args[0]["details"]
                    retry += 1
        if resp is None or len(resp) == 0:
            return {"results": "No results found", "query": prompt}
        else:
            results = resp[0].text.split("\n\n")
            results[0].split("\n")
            res = ast.literal_eval(results[1].replace("Response:\n", ""))

            return {
                "results": res,
                "query": results[0].replace("Query:\n", ""),
            }