"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

from llama_index.llms.bedrock import Bedrock
from llama_index.embeddings.bedrock import BedrockEmbedding
from llama_index.graph_stores.neptune import (
    NeptuneDatabasePropertyGraphStore,
    NeptuneDatabaseGraphStore,
)
from llama_index.core import PropertyGraphIndex, Settings
import logging
import os
import streamlit as st
from dotenv import load_dotenv
from NaturalLanguageQuerying import NaturalLanguageQuerying
from KnowledgeGraphEnhancedRAG import KnowledgeGraphEnhancedRAG
from KnowledgeGraphRetrieval import KnowledgeGraphRetriever

# load the environment variables from .env file
load_dotenv()

vulnerability_list = None

logging.basicConfig(level=logging.INFO)

# Fetch configuration issues and set local variables to pass to the
# The Cluster Endpoint for the SBOM natural language querying cluster
kg_host: str = os.getenv("GRAPH_ENDPOINT")
# The Cluster port for these clusters
port: int = int(os.getenv("PORT", 8182))
# The Cluster transport protocol for these clusters
use_https = os.getenv("USE_HTTPS", "true").lower() in ("true", "1")
# The Cluster Endpoint for the GraphRAG cluster
kgrag_host: str = os.getenv("KGRAG_ENDPOINT")
# The max number of triples extracted per chunk for the GraphRAG KG Index
max_triplets_per_chunk = os.getenv("MAX_TRIPLETS_PER_CHUNK", 5)

# Setup the llm to use Bedrock and the provided model name
llm = Bedrock(
    model=os.getenv("LLM_MODEL"),
    model_kwargs={"temperature": 0},
)
Settings.llm = llm
# Setup the embedding model to use Bedrock and the provided model name
embed_model = BedrockEmbedding(model="amazon.titan-embed-text-v1")
Settings.embed_model = embed_model

# Create the the PropertyGraphStore and KG Graph Store to use the provided Neptune Database
graph_store = NeptuneDatabasePropertyGraphStore(
    host=kg_host, use_https=use_https, port=port
)
kg_graph_store = NeptuneDatabaseGraphStore(
    host=kgrag_host, use_https=use_https, port=port
)
graphrag_store = NeptuneDatabasePropertyGraphStore(
    host=graphrag_host, use_https=use_https, port=port
)


# Create the PropertyGraphIndex for the provided graph store, llm, and embedding model
def get_pgi_from_existing():
    return PropertyGraphIndex.from_existing(
        property_graph_store=graph_store,
        embed_model=embed_model,
        llm=llm,
    )


@st.cache_resource(show_spinner=False)
def get_natural_language_querying():
    return NaturalLanguageQuerying(index, llm)


@st.cache_resource(show_spinner=False)
def get_knowledge_graph_retriever():
    return KnowledgeGraphRetriever(index, llm)


@st.cache_resource(show_spinner=False)
def get_knowledge_graph_rag():
    return KnowledgeGraphEnhancedRAG(
        graphrag_store,
        kg_graph_store,
        llm,
        embed_model,
        max_triplets_per_chunk=max_triplets_per_chunk,
    )


index = get_pgi_from_existing()
natural_language_querying = get_natural_language_querying()
knowledge_graph_retreiver = get_knowledge_graph_retriever()
knowledge_graph_enhanced_rag = get_knowledge_graph_rag()
