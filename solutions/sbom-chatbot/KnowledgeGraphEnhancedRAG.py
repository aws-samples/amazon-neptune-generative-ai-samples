"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

import logging
import os
from DisplayResult import DisplayResult
from llama_index.core import SimpleDirectoryReader
from llama_index.readers.file import PDFReader
from llama_index.graph_stores.neptune import (
    NeptuneDatabasePropertyGraphStore,
    NeptuneDatabaseGraphStore,
)
from llama_index.llms.bedrock import Bedrock
from llama_index.embeddings.bedrock import BedrockEmbedding
from llama_index.core import (
    PropertyGraphIndex,
    KnowledgeGraphIndex,
    VectorStoreIndex,
    StorageContext,
    load_index_from_storage,
    PromptTemplate,
)

PERSIST_DIR = "persist/"

logger = logging.getLogger(__name__)


class KnowledgeGraphEnhancedRAG:
    """This class shows how to run a PropertyGraphIndex query over data using LlamaIndex"""

    def __init__(
        self,
        graph_store: NeptuneDatabasePropertyGraphStore,
        kg_graph_store: NeptuneDatabaseGraphStore,
        llm: Bedrock,
        embed_model: BedrockEmbedding,
    ):
        self.graph_store = graph_store
        self.kg_graph_store = kg_graph_store
        self.llm = llm
        self.embed_model = embed_model
        self._load_pgi_index()
        self._load_kg_index()
        self._load_vector_index()
        self.pg_query_engine = self.pg_index.as_query_engine(
            include_text=True,
            llm=llm,
        )
        self.kg_query_engine = self.kg_index.as_query_engine(
            include_text=False,
            llm=llm,
        )
        self.vector_query_engine = self.vector_index.as_query_engine(
            llm=llm,
        )
        self.vector_retriever = self.vector_index.as_retriever()
        self.pgi_retriever = self.pg_index.as_retriever()

    def _load_pgi_index(self) -> None:
        """Creates or loads the PG Index

        Returns:
            The loaded PG Index
        """
        # check if kg storage already exists
        if not os.path.exists(PERSIST_DIR + "/pgi"):
            # load the documents and create the index
            logger.info("Creating PropertyGraphIndex from documents")
            storage_context = StorageContext.from_defaults(graph_store=self.graph_store)
            parser = PDFReader()
            file_extractor = {".pdf": parser}
            reader = SimpleDirectoryReader(
                input_dir="data/kg_enhanced_rag", file_extractor=file_extractor
            )
            documents = reader.load_data()

            self.pg_index = PropertyGraphIndex.from_documents(
                documents,
                property_graph_store=self.graph_store,
                embed_kg_nodes=True,
                llm=self.llm,
                embed_model=self.embed_model,
                show_progress=True,
            )

            # persistent storage
            self.pg_index.storage_context.persist(persist_dir=PERSIST_DIR + "/pgi")

            logger.info("Creation of PropertyGraphIndex from documents complete")
        else:
            # load the existing index
            logger.info("Loading PropertyGraphIndex from local")
            storage_context = StorageContext.from_defaults(
                persist_dir=PERSIST_DIR + "/pgi",
                property_graph_store=self.graph_store,
            )
            self.pg_index = load_index_from_storage(storage_context)
            logger.info("Loading PropertyGraphIndex from local complete")

    def run_graphrag_answer_question(self, question: str) -> DisplayResult:
        """Runs the GraphRAG Q/A

        Args:
            question (str): The question being asked

        Returns:
            DisplayResult: A DisplayResult of the response
        """
        response = self.pg_query_engine.query(question)
        explaination = []
        for n in response.source_nodes:
            explaination.append(
                {
                    "score": n.score,
                    "text": n.text,
                    "file_name": n.metadata["file_name"],
                    "page_label": n.metadata["page_label"],
                }
            )
        return DisplayResult(
            response.response,
            explaination=explaination,
            display_format=DisplayResult.DisplayFormat.STRING,
            status=DisplayResult.Status.SUCCESS,
        )

    def _load_kg_index(self) -> None:
        """Creates or loads the KG Index

        Returns:
            The loaded KG Index
        """
        # check if kg storage already exists
        if not os.path.exists(PERSIST_DIR + "/kg"):
            # load the documents and create the index
            logger.info("Creating KnowledgeGraphIndex from documents")
            kg_storage_context = StorageContext.from_defaults(
                graph_store=self.kg_graph_store
            )
            parser = PDFReader()
            file_extractor = {".pdf": parser}
            reader = SimpleDirectoryReader(
                input_dir="data/kg_enhanced_rag", file_extractor=file_extractor
            )
            documents = reader.load_data()

            text = (
                "Your task is to take the text provided and extract up to the "
                "{max_knowledge_triplets} most important concepts in "
                "knowledge triplets in the form of (subject, predicate, object).\n"
                "Triplets should be focused on entities such as people, companies, locations, and events.\n"
                "All triplets should not include stopwords such as a, an, and, are, as, at, be, but, by, for, if, in, into, is, it, no, not, of, on, or, such, that, the, their, then, there, these, they, this, to, was, will and with.\n"
                "For each predicate, simplify the action into a single verb or a 2 words.\n"
                "---------------------\n"
                "Example:"
                "Text: Amazon is located in Seattle."
                "Triplets:\n(amazon, is located in, seattle)\n"
                "Text: Amazon will acquire Whole Foods Market for $42 per share.\n"
                "Triplets:\n"
                "(Amazon, acquires, Whole Foods Market)\n"
                "(whole foods market, acquired for, $42 per share)\n"
                "---------------------\n"
                "Text: {text}\n"
                "Triplets:\n"
            )
            template: PromptTemplate = PromptTemplate(text)

            self.kg_index = KnowledgeGraphIndex.from_documents(
                documents,
                storage_context=kg_storage_context,
                max_triplets_per_chunk=5,
                include_embeddings=True,
                show_progress=True,
                kg_triplet_extract_template=template,
            )

            # persistent storage
            self.kg_index.storage_context.persist(persist_dir=PERSIST_DIR + "/kg")

            logger.info("Creation of KnowledgeGraphIndex from documents complete")
        else:
            # load the existing index
            logger.info("Loading KnowledgeGraphIndex from local")
            storage_context = StorageContext.from_defaults(
                persist_dir=PERSIST_DIR + "/kg",
                graph_store=self.kg_graph_store,
            )
            self.kg_index = load_index_from_storage(storage_context)
            logger.info("Loading KnowledgeGraphIndex from local complete")

    def run_kgrag_answer_question(self, question: str) -> DisplayResult:
        """Runs the KnwoledgeGraph RAG Q/A

        Args:
            question (str): The question being asked

        Returns:
            DisplayResult: A DisplayResult of the response
        """
        response = self.kg_query_engine.query(question)
        explaination = []
        for n in response.source_nodes:
            explaination.append(
                {
                    "score": n.score,
                    "text": n.text,
                    "relevant_text": n.metadata["kg_rel_texts"],
                }
            )
        return DisplayResult(
            response.response,
            explaination=explaination,
            display_format=DisplayResult.DisplayFormat.STRING,
            status=DisplayResult.Status.SUCCESS,
        )

    def _load_vector_index(self) -> None:
        """Creates or loads the Vector Index

        Returns:
            The loaded Vector Index
        """
        # check if kg storage already exists
        if not os.path.exists(PERSIST_DIR + "/vector"):
            # load the documents and create the index
            logger.info("Creating VectorStoreIndex from documents")
            storage_context = StorageContext.from_defaults(graph_store=self.graph_store)
            parser = PDFReader()
            file_extractor = {".pdf": parser}
            reader = SimpleDirectoryReader(
                input_dir="data/kg_enhanced_rag", file_extractor=file_extractor
            )
            documents = reader.load_data()

            self.vector_index = VectorStoreIndex.from_documents(
                documents,
                llm=self.llm,
                embed_model=self.embed_model,
                show_progress=True,
            )

            # persistent storage
            self.vector_index.storage_context.persist(
                persist_dir=PERSIST_DIR + "/vector"
            )

            logger.info("Creation of VectorStoreIndex from documents complete")
        else:
            # load the existing index
            logger.info("Loading VectorStoreIndex from local")
            storage_context = StorageContext.from_defaults(
                persist_dir=PERSIST_DIR + "/vector",
                property_graph_store=self.graph_store,
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
        explaination = []
        for n in response.source_nodes:
            explaination.append(
                {
                    "score": n.score,
                    "text": n.text,
                    "file_name": n.metadata["file_name"],
                    "page_label": n.metadata["page_label"],
                }
            )
        return DisplayResult(
            response.response,
            explaination=explaination,
            display_format=DisplayResult.DisplayFormat.STRING,
            status=DisplayResult.Status.SUCCESS,
        )

    def run_hybrid_answer_question(self, question: str) -> DisplayResult:
        """Runs the Hybrid RAG Q/A

        Args:
            question (str): The question being asked

        Returns:
            DisplayResult: A DisplayResult of the response
        """
        vector_resp = self.vector_retriever.retrieve(question)
        graph_resp = self.pgi_retriever.retrieve(question)
        return None
