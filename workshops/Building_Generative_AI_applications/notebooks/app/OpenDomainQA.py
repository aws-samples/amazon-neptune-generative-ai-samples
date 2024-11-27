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
    NeptuneAnalyticsPropertyGraphStore,
)
from llama_index.core import PromptTemplate

logger = logging.getLogger(__name__)


class OpenDomainQA:
    """Perform Natural Language to OC query generation using Bedrock and LlamaIndex"""

    def __init__(self, index: NeptuneAnalyticsPropertyGraphStore):
        self.index = index
        self.graph_store = index.property_graph_store
        self.graph_store.text_to_cypher_template.template = (
            self.graph_store.text_to_cypher_template.template
            + """
        Wrap all property names in backticks except for label names.\n
        Ensure that all property names are used in conjunction with the correct node or relationship alias.\n
        All comparisons with string values should be done in lowercase.\n
        Do not use RegexMatch queries, use a lowercase CONTAINS search instead.\n
        Ensure that the relationship directions are correct according to the provided schema.\n
        If you don\'t know how to write a query given the prompt return \'I don\'t know\'"""
        )
        self.template = self.graph_store.text_to_cypher_template
        # Configure the TextToCypher Retriever
        self.cypher_retriever = {}  # UPDATE CODE HERE

    def run_natural_language_query(
        self, prompt: str, summarize: bool = False
    ) -> DisplayResult:
        """This takes in the prompt and runs the natural language query against the graph store

        Args:
            prompt (str): The prompt question to answer

        Returns:
            DisplayResult: An object containing the results of the query and the query itself
        """
        self.cypher_retriever.summarize_response = summarize

        try:
            # Run the retrieve method on the TextToCypher Retriever
            resp = {}  # UPDATE CODE HERE
            if resp is None or len(resp) == 0:
                return DisplayResult(
                    "No results found",
                    display_format=DisplayResult.DisplayFormat.STRING,
                    status=DisplayResult.Status.SUCCESS,
                )
            else:
                # If we are summarizing the result then we should return it as a string, else
                # return the format as not specified since we don't know the data format
                return DisplayResult(
                    resp[0].text if summarize else resp[0].metadata["response"],
                    explanation=resp[0].metadata["query"],
                    display_format=(
                        DisplayResult.DisplayFormat.STRING
                        if summarize
                        else DisplayResult.DisplayFormat.NOTSPECIFIED
                    ),
                    status=DisplayResult.Status.SUCCESS,
                )
        except NeptuneQueryException as e:
            return DisplayResult(
                "We were not able provide a valid query result.  Please modify the question and try again.",
                explanation=e.args[0],
                display_format=DisplayResult.DisplayFormat.STRING,
                status=DisplayResult.Status.ERROR,
            )
