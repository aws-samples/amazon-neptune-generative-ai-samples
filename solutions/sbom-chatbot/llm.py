"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: Apache-2.0
"""

from llama_index.llms.bedrock import Bedrock
from llama_index.embeddings.bedrock import BedrockEmbedding
from llama_index.graph_stores.neptune import (
    NeptuneDatabasePropertyGraphStore,
    NeptuneQueryException,
)
from llama_index.graph_stores.neptune.neptune import NeptuneQueryException
from llama_index.core.indices.property_graph import TextToCypherRetriever
from llama_index.core import PropertyGraphIndex
import boto3
from enum import Enum
import os
import streamlit as st
from dotenv import load_dotenv

from langchain_community.chains.graph_qa.cypher_utils import CypherQueryCorrector
from langchain_community.chains.graph_qa.cypher_utils import Schema

load_dotenv()

vulnerability_list = None
QUERY_TYPES = Enum("QUERY_TYPES", ["Templated", "Explainability", "Unknown"])

VULNERABILITY_TEMPLATED_QUERY = """
    MATCH (n:Vulnerability {id: $id})
    CALL neptune.algo.vectors.topKByNode(n)
    YIELD node, score
    RETURN node.id as id, node.description as description, score
    ORDER BY score ASC
"""

VULNERABILITY_EXPLAINABILITY_QUERY_NODES = """
    MATCH (n:Vulnerability {id: $id})
    CALL neptune.algo.vectors.topKByNode(n)
    YIELD node, score
    WITH n, node ORDER BY score ASC
    MATCH p=(n)-[:AFFECTS]-(c:Component)-[:AFFECTS]-(noe:Vulnerability)
    WITH nodes(p) as nodes
    UNWIND nodes as n
    RETURN collect(distinct n) as nodes
"""

VULNERABILITY_EXPLAINABILITY_QUERY_EDGES = """
    MATCH (n:Vulnerability {id: $id})
    CALL neptune.algo.vectors.topKByNode(n)
    YIELD node, score
    WITH n, node ORDER BY score ASC
    MATCH p=(n)-[:AFFECTS]-(c:Component)-[:AFFECTS]-(noe:Vulnerability)
    WITH relationships(p) as edges
    UNWIND edges as e
    RETURN collect(distinct e) as edges
"""

VULNERABILITY_LIST_QUERY = """
    MATCH (n:Vulnerability)
    RETURN n.id AS id ORDER BY id
"""


def get_langchain_schema():
    edge_schema = []
    for i in graph_store.get_schema()["triples"]:
        i = (
            i.replace("(:`", "")
            .replace("`)", "")
            .replace("[:`", "")
            .replace("`]", "")
            .replace(">", "")
        )
        parts = i.split("-")
        if len(parts) == 3:
            edge_schema.append(
                Schema(left_node=parts[0], relation=parts[1], right_node=parts[2])
            )

    return edge_schema


host = os.getenv("GRAPH_ENDPOINT")
port = os.getenv("PORT", 8182)
use_https = os.getenv("USE_HTTPS", "true").lower() in ("true", "1")
if use_https:
    host_url = f"https://{host}:{str(port)}"
else:
    host_url = f"http://{host}:{str(port)}"

llm = Bedrock(
    model=os.getenv("LLM_MODEL"),
    model_kwargs={"temperature": 0},
)


embed_model = BedrockEmbedding(model="amazon.titan-embed-text-v1")

graph_store = NeptuneDatabasePropertyGraphStore(host=host, use_https=use_https)

cypher_query_corrector = CypherQueryCorrector(get_langchain_schema())

neptune_client = boto3.client("neptunedata", endpoint_url=host_url)

index = PropertyGraphIndex.from_existing(
    property_graph_store=graph_store,
    embed_model=embed_model,
    llm=llm,
)

DEFAULT_RESPONSE_TEMPLATE = "Query:\n{query}\n\nResponse:\n{response}"
DEFAULT_TEXT_TO_CYPHER_TEMPLATE = (index.property_graph_store.text_to_cypher_template,)

graph_store.text_to_cypher_template.template += """Wrap all property names in backticks except for label names.
Ensure that all property names are used in conjunction with the correct node or relationship alias. 
Example don't use "toLower(`ratings.severity`)" as this must be "toLower(v.`ratings.severity`)"
All comparisons with string values should be done in lowercase.
Do not use RegexMatch queries, use a lowercase CONTAINS search instead.
Ensure that the relationship directions are correct according to the provided schema.
If you don't know how to write a query given the prompt return 'I don't know' """
# print(graph_store.text_to_cypher_template)
cypher_retriever = TextToCypherRetriever(
    index.property_graph_store,
    llm=llm,
    response_template=DEFAULT_RESPONSE_TEMPLATE,
    cypher_validator=cypher_query_corrector.correct_query,
)

graph_store.text_to_cypher_template.template += """Wrap all property names in backticks except for label names.
Ensure that all property names are used in conjunction with the correct node or relationship alias. 
Example don't use "toLower(`ratings.severity`)" as this must be "toLower(v.`ratings.severity`)"
All comparisons with string values should be done in lowercase.
Do not use RegexMatch queries, use a lowercase CONTAINS search instead.
Ensure that the relationship directions are correct according to the provided schema.
If you don't know how to write a query given the prompt return 'I don't know' """

cypher_retriever = TextToCypherRetriever(
    index.property_graph_store,
    llm=llm,
    response_template=DEFAULT_RESPONSE_TEMPLATE,
    cypher_validator=cypher_query_corrector.correct_query,
)


def determine_query_information(prompt, query_type):
    template = f"""
    You are an expert in Software Bill Of Materials.  Given the question below:
    {prompt}
    Tell me if the user wants to know about a Document, Component, License, Vulnerability, or Reference element 
    and what value they would like to find out about.  
    The answer must be two lines, with the first line being the element type name and the second line being the id.  Do not add any additional words in the answer
                """
    response = chat.invoke(template)
    lines = response.content.split("\n")
    if len(lines) == 2:
        node_labels = graph._get_labels()
        label = None
        if lines[0] in node_labels[0]:
            label = lines[0]
        value_id = lines[1]

        match label:
            case "Vulnerability":
                if query_type == QUERY_TYPES.Templated:
                    resp = run_graph_query(
                        VULNERABILITY_TEMPLATED_QUERY, {"id": value_id}
                    )
                elif query_type == QUERY_TYPES.Explainability:
                    resp = {"subgraph": {}}
                    res = run_graph_query(
                        VULNERABILITY_EXPLAINABILITY_QUERY_NODES, {"id": value_id}
                    )
                    resp["subgraph"]["nodes"] = res[0]["nodes"]
                    res = run_graph_query(
                        VULNERABILITY_EXPLAINABILITY_QUERY_EDGES, {"id": value_id}
                    )
                    resp["subgraph"]["edges"] = res[0]["edges"]

                else:
                    resp = "The information you requested is not currently supported by this application.  Please try again."
            case _:
                resp = "The information you requested is not currently supported by this application.  Please try again."
        return resp


def run_natural_language_query(prompt):
    try:
        resp = cypher_retriever.retrieve(prompt)
    except NeptuneQueryException as e:
        print(e)
        raise e
    results = resp[0].text.split("\n\n")
    results[0].split("\n")

    return {
        "results": results[1].replace("Response:\n", ""),
        "query": results[0].replace("Query:\n", ""),
    }


@st.cache_data
def get_vulnerability_list():
    data = run_graph_query(VULNERABILITY_LIST_QUERY)
    return [d["id"] for d in data]


def run_templated_query(query, type):
    resp = determine_query_information(query, type)
    return resp


def run_graphrag_query(query):
    resp = determine_query_information(query, QUERY_TYPES.GraphRAG)
    return resp


def run_graph_query(query, parameters={}):
    resp = neptune_client.execute_open_cypher_query(
        openCypherQuery=query, parameters=str(parameters)
    )
    return resp["results"]


def run_graphrag_answer_question(question):
    raise NotImplementedError("GraphRAG is not implemented yet.")
