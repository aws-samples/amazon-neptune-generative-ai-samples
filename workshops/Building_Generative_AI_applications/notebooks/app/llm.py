"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

from llama_index.llms.bedrock_converse import BedrockConverse
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

# Fetch the configuration and set local variables
host: str = os.getenv("HOST")
# Claude Sonnet 5.5 through the US cross-region inference profile
llm_model: str = os.getenv("LLM_MODEL", "us.anthropic.claude-sonnet-5-5")
# The stored embeddings were created with Titan Text Embeddings V2 at 256 dimensions,
# so changing this model requires re-creating the embeddings in the graph and persist/
embeddings_model: str = os.getenv("EMBEDDINGS_MODEL", "amazon.titan-embed-text-v2:0")
# None lets boto3 use its normal region lookup (AWS_REGION, AWS_DEFAULT_REGION, profile)
region: str | None = os.getenv("AWS_REGION")

# Setup the llm to use the Bedrock Converse API and the provided model name
llm = BedrockConverse(model=llm_model, temperature=0, region_name=region)
Settings.llm = llm
# Setup the embedding model to use Bedrock and the provided model name
embed_model = BedrockEmbedding(
    model_name=embeddings_model,
    region_name=region,
    additional_kwargs={"dimensions": 256},
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
