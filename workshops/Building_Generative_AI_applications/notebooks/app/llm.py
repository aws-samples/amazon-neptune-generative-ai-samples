"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

from llama_index.llms.bedrock import Bedrock
from llama_index.embeddings.bedrock import BedrockEmbedding
from llama_index.graph_stores.neptune import NeptuneAnalyticsPropertyGraphStore
from llama_index.core import PropertyGraphIndex, Settings
import logging
import os
import streamlit as st
from dotenv import load_dotenv
from OpenDomainQA import OpenDomainQA
from GraphEnhancedRAG import GraphEnhancedRAG
from DefinedDomainQA import DefinedDomainQA


# load the environment variables from .env file
load_dotenv()

# Fetch configuration issues and set local variables to pass to the
host: str = os.getenv("HOST")

# Setup the llm to use Bedrock and the provided model name
llm = Bedrock(
    model="anthropic.claude-3-sonnet-20240229-v1:0", temperature=0, context_size=200000
)
Settings.llm = llm
# Setup the embedding model to use Bedrock and the provided model name
embed_model = BedrockEmbedding(
    model_name="amazon.titan-embed-text-v2:0", additional_kwargs={"dimensions": 256}
)
Settings.embed_model = embed_model

# Create the the PropertyGraphStore and KG Graph Store to use the provided Neptune Database
graph_store = NeptuneAnalyticsPropertyGraphStore(
    graph_identifier=host,
)


# Create the PropertyGraphIndex for the provided graph store, llm, and embedding model
def get_pgi_from_existing():
    return PropertyGraphIndex.from_existing(
        property_graph_store=graph_store,
        embed_model=embed_model,
        llm=llm,
    )


@st.cache_resource(show_spinner=False)
def get_open_domain_qa():
    return OpenDomainQA(index)


@st.cache_resource(show_spinner=False)
def get_defined_domain_qa():
    return DefinedDomainQA(index)


@st.cache_resource(show_spinner=False)
def get_graph_enhanced_rag():
    return GraphEnhancedRAG(index)


index = get_pgi_from_existing()
open_domain_qa = get_open_domain_qa()
defined_domain_qa = get_defined_domain_qa()
graph_enhanced_rag = get_graph_enhanced_rag()
