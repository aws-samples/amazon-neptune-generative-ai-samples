"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
"""

from llama_index.llms.bedrock import Bedrock
from llama_index.embeddings.bedrock import BedrockEmbedding
from llama_index.graph_stores.neptune import (
    NeptuneDatabasePropertyGraphStore,
)
from llama_index.core import PropertyGraphIndex
import boto3
import os
from dotenv import load_dotenv
from NaturalLanguageQuerying import NaturalLanguageQuerying

# load the environment variables from .env file
load_dotenv()

vulnerability_list = None

# Fetch configuration issues and set local variables
host: str = os.getenv("GRAPH_ENDPOINT")
port: int = int(os.getenv("PORT", 8182))
use_https = os.getenv("USE_HTTPS", "true").lower() in ("true", "1")
if use_https:
    host_url = f"https://{host}:{str(port)}"
else:
    host_url = f"http://{host}:{str(port)}"

# Setup the llm to use Bedrock and the provided model name
llm = Bedrock(
    model=os.getenv("LLM_MODEL"),
    model_kwargs={"temperature": 0},
)

# Setup the embedding model to use Bedrock and the provided model name
embed_model = BedrockEmbedding(model="amazon.titan-embed-text-v1")

# Create the the PropertyGraphStore to use the provided Neptune Database
graph_store = NeptuneDatabasePropertyGraphStore(host=host, use_https=use_https)

# Create the Neptune Database Boto3 client
neptune_client = boto3.client("neptunedata", endpoint_url=host_url)

# Create the PropertyGraphIndex for the provided graph store, llm, and embedding model
index = PropertyGraphIndex.from_existing(
    property_graph_store=graph_store,
    embed_model=embed_model,
    llm=llm,
)

natural_language_querying = NaturalLanguageQuerying(index, llm)


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


def run_graphrag_answer_question(question):
    raise NotImplementedError("GraphRAG is not implemented yet.")
