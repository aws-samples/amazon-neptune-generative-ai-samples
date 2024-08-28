"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

import logging
import ast
from DisplayResult import DisplayResult
from typing import List
from llama_index.core.indices.property_graph import TextToCypherRetriever
from langchain_community.chains.graph_qa.cypher_utils import CypherQueryCorrector
from langchain_community.chains.graph_qa.cypher_utils import Schema
from llama_index.graph_stores.neptune import (
    NeptuneQueryException,
    NeptuneDatabasePropertyGraphStore,
)
from llama_index.core import PromptTemplate
from llama_index.llms.bedrock import Bedrock

logger = logging.getLogger(__name__)


class NaturalLanguageQuerying:
    """Perform Natrual Language to OC query generation using Bedrock and LlamaIndex"""

    DEFAULT_RESPONSE_TEMPLATE = "Query:\n{query}\n\nResponse:\n{response}"
    DEFAULT_TEXT_TO_CYPHER_TEMPLATE = """Task:Generate Cypher statement to query a graph database.\nInstructions:\n
    You are an expert in AWS Infrastructure and Software Bill Of Materials. \n
    Use only the provided relationship types and properties in the schema.\n
    Do not use any other relationship types or properties that are not provided.\nSchema:\n{schema}\n
    Note: Do not include any explanations or apologies in your responses.\nDo not respond to any questions that might ask anything else 
    than for you to construct a Cypher statement.\nDo not include any text except the generated Cypher statement.\n\n
    The question is:\n{question}
    Wrap all property names in backticks except for label names.\n
    When asking for the component id return the id().\n
    Ensure that all property names are used in conjunction with the correct node or relationship alias.\n
    All comparisons with string values should be done in lowercase.\n
    Do not use RegexMatch queries, use a lowercase CONTAINS search instead.\n
    Ensure that the relationship directions are correct according to the provided schema.\n
    If you don\'t know how to write a query given the prompt return \'I don\'t know\'
    Insecure IAM policies mean that they are using either the policy name is AdministratorAccess or contain wildcards(*) within the policy text
    """

    REWRITE_TEXT_TO_CYPHER_TEMPLATE = """Task:Given the previous Cypher statement, question, and error message
    You are an expert in AWS Infrastructure and Software Bill Of Materials. \n
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
    When asking for the component id return the id().\n
    Ensure that all property names are used in conjunction with the correct node or relationship alias.\n
    All comparisons with string values should be done in lowercase.\n
    Do not use RegexMatch queries, use a lowercase CONTAINS search instead.\n
    Ensure that the relationship directions are correct according to the provided schema.\n
    If you don\'t know how to write a query given the prompt return \'I don\'t know\'
    Insecure IAM policies mean that they are using either the policy name is AdministratorAccess or contain wildcards(*) within the policy text
    """
    MAX_RETRIES = 3

    def __init__(self, index: NeptuneDatabasePropertyGraphStore, llm: Bedrock):
        self.graph_store = index.property_graph_store
        self.template = self.graph_store.text_to_cypher_template
        # Configure the TextToCypher Retriever
        self.cypher_retriever = TextToCypherRetriever(
            self.graph_store,
            llm=llm,
            response_template=self.DEFAULT_RESPONSE_TEMPLATE,
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
            self.template.template = self.DEFAULT_TEXT_TO_CYPHER_TEMPLATE
            return self.template
        else:
            # Use Partial Formatting on the template to add the previous cypher statement and error
            # https://docs.llamaindex.ai/en/stable/examples/prompts/advanced_prompts/#1-partial-formatting
            self.template.template = self.REWRITE_TEXT_TO_CYPHER_TEMPLATE
            rewrite_template = self.template.partial_format(
                previous_cypher=query, error_message=error_msg
            )
            return rewrite_template

    def run_natural_language_query(self, prompt: str) -> DisplayResult:
        """This takes in the prompt and runs the natural language query against the graph store

        Args:
            prompt (str): The prompt question to answer

        Returns:
            DisplayResult: An object containing the results of the query and the query itself
        """
        retry = 0
        query = None
        error_msg = None
        resp = None
        while retry < self.MAX_RETRIES:
            try:
                self.cypher_retriever.text_to_cypher_template = self.__determine_prompt(
                    query, error_msg
                )
                logger.info(f"Query retry: {retry}")
                resp = self.cypher_retriever.retrieve(prompt)
                break
            except NeptuneQueryException as e:
                if e.details.find("MalformedQueryException") != -1:
                    logger.error(e)
                    raise e
                elif e.details.find("AccessDeniedException") != -1:
                    logger.error(e)
                    return DisplayResult(
                        "You do not have permission to perform this action.  Please try a different question.",
                        explaination=e.args[0]["query"],
                        display_format=DisplayResult.DisplayFormat.STRING,
                        status=DisplayResult.Status.ERROR,
                    )
                else:
                    logger.info(
                        f"Generated Query Failed with the following message: {e}"
                    )
                    query = e.args[0]["query"]
                    error_msg = e.args[0]["details"]
                    retry += 1
        if resp is None or len(resp) == 0:
            return DisplayResult(
                "No results found",
                explaination=results[0].replace("Query:\n", ""),
                display_format=DisplayResult.DisplayFormat.STRING,
            )
        else:
            results = resp[0].text.split("\n\n")
            results[0].split("\n")
            res = ast.literal_eval(results[1].replace("Response:\n", ""))
            dr = DisplayResult(
                res,
                explaination=results[0].replace("Query:\n", ""),
                display_format=DisplayResult.DisplayFormat.NOTSPECIFIED,
            )
            return dr
