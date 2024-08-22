"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
"""

from llama_index.llms.bedrock import Bedrock
from llama_index.embeddings.bedrock import BedrockEmbedding
from llama_index.graph_stores.neptune import (
    NeptuneDatabasePropertyGraphStore,
)
from llama_index.core import PropertyGraphIndex, Settings
import boto3
import os
from dotenv import load_dotenv
from NaturalLanguageQuerying import NaturalLanguageQuerying
from KnowledgeGraphEnhancedRAG import KnowledgeGraphEnhancedRAG

# load the environment variables from .env file
load_dotenv()

vulnerability_list = None

# Fetch configuration issues and set local variables
kg_host: str = os.getenv("GRAPH_ENDPOINT")
graphrag_host: str = os.getenv("GRAPHRAG_ENDPOINT")
port: int = int(os.getenv("PORT", 8182))
use_https = os.getenv("USE_HTTPS", "true").lower() in ("true", "1")
# if use_https:
#     kg_host_url = f"https://{kg_host}:{str(port)}"
# else:
#     kg_host_url = f"http://{kg_host}:{str(port)}"

# Setup the llm to use Bedrock and the provided model name
llm = Bedrock(
    model=os.getenv("LLM_MODEL"),
    model_kwargs={"temperature": 0},
)
Settings.llm = llm
# Setup the embedding model to use Bedrock and the provided model name
embed_model = BedrockEmbedding(model="amazon.titan-embed-text-v1")
Settings.embed_model = embed_model

# Create the the PropertyGraphStore to use the provided Neptune Database
graph_store = NeptuneDatabasePropertyGraphStore(host=kg_host, use_https=use_https, port=port)

# Create the the PropertyGraphStore to use the provided Neptune Database
graphrag_store = NeptuneDatabasePropertyGraphStore(host=graphrag_host, use_https=use_https, port=port)

# # Create the Neptune Database Boto3 client
# neptune_client = boto3.client("neptunedata", endpoint_url=host_url)

# Create the PropertyGraphIndex for the provided graph store, llm, and embedding model
index = PropertyGraphIndex.from_existing(
    property_graph_store=graph_store,
    embed_model=embed_model,
    llm=llm,
)

natural_language_querying = NaturalLanguageQuerying(index, llm)
knowledge_graph_enhanced_rag = KnowledgeGraphEnhancedRAG(graphrag_store, llm, embed_model)


def determine_query_information(prompt, query_type):
    raise NotImplementedError("This function is not implemented yet.")


# @st.cache_data
# def get_vulnerability_list():
#     data = run_graph_query(VULNERABILITY_LIST_QUERY)
#     return [d["id"] for d in data]


# def run_templated_query(query, type):
#     resp = determine_query_information(query, type)
#     return resp


# def run_graphrag_query(query):
#     resp = determine_query_information(query, QUERY_TYPES.GraphRAG)
#     return resp


# def run_graph_query(query, parameters={}):
#     resp = neptune_client.execute_open_cypher_query(
#         openCypherQuery=query, parameters=str(parameters)
#     )
#     return resp["results"]



