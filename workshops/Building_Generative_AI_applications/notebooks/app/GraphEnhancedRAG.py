"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

import logging
import os
from DisplayResult import DisplayResult
from llama_index.core import (
    PropertyGraphIndex,
    VectorStoreIndex,
    StorageContext,
    load_index_from_storage,
)

PERSIST_DIR = "app/persist"

logger = logging.getLogger(__name__)


class GraphEnhancedRAG:
    """This class shows how to run a PropertyGraphIndex query over data using LlamaIndex"""

    def __init__(
        self,
        index: PropertyGraphIndex,
    ):
        self.index = index

        self._load_pgi_index()
        self._load_vector_index()
        # self.pg_query_engine = self.pg_index.as_query_engine(
        #     include_text=True,
        # )
        self.vector_query_engine = self.vector_index.as_query_engine()
        self.vector_retriever = self.vector_index.as_retriever()

    def _load_pgi_index(self) -> None:
        """Loads and existing PropertyGraphIndex

        Returns:
            The loaded PropertyGraphIndex
        """
        # load the existing index
        logger.info("Loading PropertyGraphIndex from local")
        # UPDATE THE CODE TO CREATE THE STORAGE CONTEXT AND LOAD THE INDEX
        #         storage_context =
        #         self.pg_index =
        logger.info("Loading PropertyGraphIndex from local complete")

    def run_graphrag_answer_question(self, question: str) -> DisplayResult:
        """Runs the Graph Enhanced Q/A

        Args:
            question (str): The question being asked

        Returns:
            DisplayResult: A DisplayResult of the response
        """
        response = self.pg_query_engine.query(question)
        explanation = []
        for n in response.source_nodes:
            explanation.append(
                {
                    "score": n.score,
                    "text": n.text,
                    "file_name": n.metadata["file_name"],
                    "page_label": (
                        n.metadata["page_label"] if "page_label" in n.metadata else ""
                    ),
                }
            )
        return DisplayResult(
            response.response,
            explanation=explanation,
            display_format=DisplayResult.DisplayFormat.STRING,
        )

    def _load_vector_index(self) -> None:
        """Loads and existing VectorSearchIndex

        Returns:
            The loaded VectorSearchIndex
        """
        # load the existing index
        logger.info("Loading VectorStoreIndex from local")
        storage_context = StorageContext.from_defaults(
            persist_dir=PERSIST_DIR + "/vector",
            property_graph_store=self.index.property_graph_store,
        )
        self.vector_index = load_index_from_storage(storage_context)
        logger.info("Loading VectorStoreIndex from local complete")

    def run_vector_answer_question(self, question: str) -> DisplayResult:
        """Runs the Vector RAG Q/A

        Args:
            question (str): The question being asked

        Returns:
            DisplayResult: A DisplayResult of the response
        """
        response = self.vector_query_engine.query(question)
        explanation = []
        for n in response.source_nodes:
            explanation.append(
                {
                    "score": n.score,
                    "text": n.text,
                    "file_name": n.metadata["file_name"],
                    "page_label": (
                        n.metadata["page_label"] if "page_label" in n.metadata else ""
                    ),
                }
            )
        return DisplayResult(
            response.response,
            explanation=explanation,
            display_format=DisplayResult.DisplayFormat.STRING,
            status=DisplayResult.Status.SUCCESS,
        )
