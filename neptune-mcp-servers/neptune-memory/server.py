#
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# or in the 'license' file accompanying this file. This file is distributed on an 'AS IS' BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions
# and limitations under the License.
#

from mcp.server.fastmcp import FastMCP
import os
import argparse

from neptune import NeptuneServer
import logging
from models import GraphSchema, KnowledgeGraph, Entity, Relation
from memory import KnowledgeGraphManager
from typing import List

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

endpoint = os.environ.get("NEPTUNE_ENDPOINT", None)
use_https = os.environ.get("NEPTUNE_USE_HTTPS", 'True').lower() in ('true', '1', 't')
logger.info(f"NEPTUNE_ENDPOINT: {endpoint}")
if endpoint is None:
    raise ValueError("NEPTUNE_ENDPOINT environment variable is not set")
graph = NeptuneServer(endpoint, use_https=use_https)
memory = KnowledgeGraphManager(graph, logger)


mcp = FastMCP(
    "Neptune Memory",
    instructions="""
    This provides access to a memory for an agentic workflow stored in Amazon Neptune graph.
    """,
    dependencies=[
        "langchain-aws",
        "mcp[cli]",
    ]
)

@mcp.resource(uri="amazon-neptune://status", name='GraphStatus', mime_type='application/text')
def get_status_resource() -> str:
    """Get the status of the currently configured Amazon Neptune graph"""
    return graph.status()


@mcp.resource(uri="amazon-neptune://schema", name='GraphSchema', mime_type='application/text')
def get_schema_resource() -> GraphSchema:
    """Get the schema for the graph including the vertex and edge labels as well as the
    (vertex)-[edge]->(vertex) combinations.
    """
    return graph.schema()

@mcp.tool(name="get_graph_status")
def get_status() -> str:
    """Get the status of the currently configured Amazon Neptune graph"""
    return graph.status()


@mcp.tool(name="get_graph_schema")
def get_schema() -> GraphSchema:
    """Get the schema for the graph including the vertex and edge labels as well as the
    (vertex)-[edge]->(vertex) combinations.
    """
    return graph.schema()

@mcp.tool(name="create_entities",
        description="Create multiple new entities in the knowledge graph")
def create_entities(entities: List[Entity]) -> str:
    return memory.create_entities(entities)


@mcp.tool(name="create_relations",
        description="Create multiple new relations between entities in the knowledge graph. Relations should be in active voice")
def create_relations(relations: List[Relation]) -> str:
    return memory.create_relations(relations)


@mcp.tool(name="read_graph",
        description="Read the entire knowledge graph")
def read_graph() -> KnowledgeGraph:
    return memory.read_graph()


@mcp.tool()
def search_graph(query: str) -> KnowledgeGraph:
    return memory.search_nodes(query)


def main():
    """Run the MCP server with CLI argument support."""
    parser = argparse.ArgumentParser(description='A Model Context Protocol (MCP) server')
    parser.add_argument('--sse', action='store_true', help='Use SSE transport')
    parser.add_argument('--port', type=int, default=8888, help='Port to run the server on')

    args = parser.parse_args()

    # Run server with appropriate transport
    if args.sse:
        mcp.settings.port = args.port
        mcp.run(transport='sse')
    else:
        mcp.run()


if __name__ == '__main__':
    main()