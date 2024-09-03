"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

from DisplayResult import DisplayResult
import logging
import ast
from typing import List
from pydantic.v1 import BaseModel, Field
from llama_index.core.indices.property_graph import CypherTemplateRetriever
from llama_index.core.llms import ChatMessage
from llama_index.core import PropertyGraphIndex
from llama_index.llms.bedrock import Bedrock

logger = logging.getLogger(__name__)


class KnowledgeGraphRetriever:
    """This demonstrates how to run Knowledge Graph Retrieval queries using
    the CypherTemplateRetriever and LlamaIndex.  To use this with your own dataset
    you will need to

    * Modify the `ComponentParams` class to highlight the entities
    you are looking to extract from the question
    * Modify the queries below to be the proper templated queries you want to run
    in your application.
    * Modify the `run_retrieval_query` method  top change the `ChatMessage` prompt
    to properly return the names of the acceptable queries to run and the MATCH
    statement to perform the correct case matching logic
    """

    class ComponentParams(BaseModel):
        """Create a pydantic class to represent the params for our templated query.
        The class fields are directly used as params for running the cypher query.
        NOTE: currently v1 of Pydantic is needed"""

        component_name: str = Field(
            description="The component or library name to use for a start location of a query"
        )

    COMPONENT_QUERY: str = """
    MATCH (c:Component {name:  $component_name})
    RETURN c as component
    """

    COMPONENT_EXPLAINABILITY_QUERY: str = """
        MATCH p=(d)-[]-(c:Component {name:  $component_name})-[]-(noe:Vulnerability)
        RETURN id(d) as document_id, noe.id as vulnerability_id, noe.`ratings.severity` as severity, noe.`source.url` as reference
        ORDER by severity, document_id
    """

    SHARED_COMPONENT_QUERY: str = """
        MATCH p=()-[]-(c:Component {name: $component_name})-[]-(:Vulnerability)-[]-(:Component)
        UNWIND nodes(p) as n
        RETURN {nodes: collect(DISTINCT n), edges: null} as res
        UNION ALL
        MATCH p=(n)-[]-(c:Component {name: $component_name})-[]-(:Vulnerability)-[]-(:Component)
        UNWIND relationships(p) as e
        RETURN {nodes: null, edges: collect(DISTINCT e)} as res
    """

    COMPONENT_LIST_QUERY: str = """
        MATCH (c:Component) WHERE exists(c.name) RETURN c.name as name ORDER BY c.name
    """

    def __init__(self, index: PropertyGraphIndex, llm: Bedrock):
        self.index = index
        self.llm = llm
        self.graph_store = index.property_graph_store
        self.component_list = self._get_component_list()

    def run_retrieval_query(self, prompt: str) -> DisplayResult:
        """Runs the retrieval query and returns the results

        Args:
            prompt (str): The prompt to run

        Returns:
            DisplayResult: A DisplayResult containing the formatted results
        """
        messages = [
            ChatMessage(
                role="system",
                content="""You are an expert in Software Bill of Materials  
                Given the question below, determine if the users intent is to:
                
                * Find information about a specific component, if so return only the word COMPONENT_QUERY
                * Find information about a component and its vulnerabiltiies, if so return only the word COMPONENT_EXPLAINABILITY_QUERY
                * Find information about shared components across documents, if so return only the word  SHARED_COMPONENT_QUERY
                * If it is none of these return only the word UNKNOWN
                Do not provide any additional context or explaination.
                Component and Library are used as synonyms
                """,
            ),
            ChatMessage(role="user", content=prompt),
        ]
        resp = self.llm.chat(messages)
        logger.info(resp)
        cypher_query = ""
        response_format = DisplayResult.DisplayFormat.TABLE
        match resp.message.content:
            case "COMPONENT_QUERY":
                cypher_query = self.COMPONENT_QUERY
                response_format = DisplayResult.DisplayFormat.JSON
            case "COMPONENT_EXPLAINABILITY_QUERY":
                cypher_query = self.COMPONENT_EXPLAINABILITY_QUERY
            case "SHARED_COMPONENT_QUERY":
                cypher_query = self.SHARED_COMPONENT_QUERY
                response_format = DisplayResult.DisplayFormat.SUBGRAPH
            case _:
                return DisplayResult(
                    "The question asked is not supported by this application, please rephrase the question and try again.",
                    display_format=DisplayResult.DisplayFormat.STRING,
                    status=DisplayResult.Status.ERROR,
                )

        retriever = CypherTemplateRetriever(
            self.graph_store, self.ComponentParams, cypher_query
        )
        nodes = retriever.retrieve(prompt)
        dr = DisplayResult(
            ast.literal_eval(nodes[0].text),
            display_format=response_format,
            status=DisplayResult.Status.SUCCESS,
        )
        return dr

    def _get_component_list(self) -> List[str]:
        """Get a list of the component names

        Returns:
            List[str]: The component names
        """
        data = self.graph_store.structured_query(self.COMPONENT_LIST_QUERY)
        return [d["name"] for d in data]
