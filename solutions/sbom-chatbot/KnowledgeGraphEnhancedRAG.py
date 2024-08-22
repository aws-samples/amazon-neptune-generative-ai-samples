"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""
import logging
import os
from llama_index.core import SimpleDirectoryReader
from llama_index.readers.file import PDFReader
from llama_index.graph_stores.neptune import NeptuneDatabasePropertyGraphStore
from llama_index.core import (
    PropertyGraphIndex,
    StorageContext,
    load_index_from_storage,
)
from llama_index.core import PromptTemplate

PERSIST_DIR = "persist/pgi"

logger = logging.getLogger(__name__)

class KnowledgeGraphEnhancedRAG:
    def __init__(self, graph_store, llm, embed_model):
        self.graph_store = graph_store
        self.llm = llm
        self.embed_model = embed_model
        self._load_pgi_index()
        self.query_engine = self.index.as_query_engine(
                include_text=True,
                llm=llm,
            )
        
    def _load_pgi_index(self):
        """Creates or loads the PG Index

        Args:
            graph_store: The PG Index to use in the storage context

        Returns:
            The loaded PG Index
        """
        # check if kg storage already exists
        if not os.path.exists(PERSIST_DIR):
            # load the documents and create the index
            logger.info("Creating PropertyGraphIndex from documents")
            storage_context = StorageContext.from_defaults(graph_store=self.graph_store)
            parser = PDFReader()
            file_extractor = {".pdf": parser}
            reader = SimpleDirectoryReader(input_dir="data/kg_enhanced_rag", file_extractor=file_extractor)
            documents =reader.load_data()

            self.index = PropertyGraphIndex.from_documents(
                documents,
                property_graph_store=self.graph_store,
                embed_kg_nodes=False,
                llm=self.llm,
                embed_model = self.embed_model,
                show_progress=True
            )

            # persistent storage
            self.index.storage_context.persist(persist_dir=PERSIST_DIR)
            
            logger.info("Creation of PropertyGraphIndex from documents complete")
        else:
            # load the existing index
            logger.info("Loading PropertyGraphIndex from local")
            storage_context = StorageContext.from_defaults(
                persist_dir=PERSIST_DIR, property_graph_store=self.graph_store,
            )
            self.index = load_index_from_storage(storage_context)
            logger.info("Loading PropertyGraphIndex from local complete")

    def run_graphrag_answer_question(self, question):
        response = self.query_engine.query(question)
        return response