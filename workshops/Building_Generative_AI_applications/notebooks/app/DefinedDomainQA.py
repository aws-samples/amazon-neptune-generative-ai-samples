"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

from DisplayResult import DisplayResult
import logging
import ast
from pydantic import BaseModel, Field
from llama_index.core.indices.property_graph import CypherTemplateRetriever
from llama_index.core import PropertyGraphIndex, Settings
from llama_index.core.prompts import PromptTemplate

logger = logging.getLogger(__name__)


class DefinedDomainQA:
    """This demonstrates how to run Defined domain queries queries using
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
        MATCH (c:Component)
        WHERE toLower(c.name) = toLower($component_name)
        RETURN c as component
    """

    COMPONENT_NEIGHBORHOOD_QUERY: str = """

    """  # UPDATE WITH THE QUERY FROM THE NOTEBOOK

    SHARED_COMPONENT_QUERY: str = """

    """  # This needs updated if you choose to do the optional section

    INTENT_TEMPLATE = PromptTemplate(
        """
        
        """  # UPDATE WITH THE PROMPT FROM THE NOTEBOOK
    )

    def __init__(self, index: PropertyGraphIndex):
        self.index = index
        self.graph_store = index.property_graph_store

    def run_retrieval_query(self, prompt: str) -> DisplayResult:
        """Runs the retrieval query and returns the results

        Args:
            prompt (str): The prompt to run

        Returns:
            DisplayResult: A DisplayResult containing the formatted results
        """
        resp = Settings.llm.predict(
            self.INTENT_TEMPLATE,
            question=prompt,
        )
        logger.info(resp)
        cypher_query = ""
        response_format = DisplayResult.DisplayFormat.TABLE
        match resp:
            case "COMPONENT_QUERY":
                cypher_query = self.COMPONENT_QUERY
                response_format = DisplayResult.DisplayFormat.JSON
            case "COMPONENT_NEIGHBORHOOD_QUERY":
                cypher_query = self.COMPONENT_NEIGHBORHOOD_QUERY
            case "SHARED_COMPONENT_QUERY":
                cypher_query = self.SHARED_COMPONENT_QUERY
                response_format = DisplayResult.DisplayFormat.JSON
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
