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
"""Neptune Memory Server Module

This module implements a Model Context Protocol (MCP) server that provides access to a memory system
stored in Amazon Neptune graph database. It enables creation, reading, and searching of entities
and relations in the knowledge graph.

The server exposes various tools through FastMCP for managing the knowledge graph operations.
"""

import argparse
import logging
import os
from mcp.server.fastmcp import FastMCP
from memory import KnowledgeGraphManager
from models import Entity, KnowledgeGraph, Relation
from neptune import NeptuneServer
from typing import List


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configure Neptune connection
endpoint = os.environ.get("NEPTUNE_MEMORY_ENDPOINT", None)
use_https = os.environ.get("NEPTUNE_MEMORY_USE_HTTPS", 'True').lower() in ('true', '1', 't')
logger.info(f"NEPTUNE_MEMORY_ENDPOINT: {endpoint}")
if endpoint is None:
    raise ValueError("NEPTUNE_MEMORY_ENDPOINT environment variable is not set")
graph = NeptuneServer(endpoint, use_https=use_https)
memory = KnowledgeGraphManager(graph, logger)


mcp = FastMCP(
    "Memory",
    instructions="""
    This provides access to a memory for an agentic workflow stored in Amazon Neptune graph.
    """,
    dependencies=[
        "langchain-aws",
        "mcp[cli]",
    ]
)

@mcp.tool(name="get_memory_server_status")
def get_status() -> str:
    """Retrieve the current status of the Amazon Neptune memory server.

    Returns:
        str: The status information of the Neptune server instance.
    """
    return graph.status()


@mcp.tool(name="create_entities",
        description="Create multiple new entities in the knowledge graph")
def create_entities(entities: List[Entity]) -> str:
    """Create multiple new entities in the knowledge graph.

    Args:
        entities (List[Entity]): A list of Entity objects to be created in the graph.

    Returns:
        str: Confirmation message indicating the result of the operation.
    """
    return memory.create_entities(entities)


@mcp.tool(name="create_relations",
        description="Create multiple new relations between entities in the knowledge graph. Relations should be in active voice")
def create_relations(relations: List[Relation]) -> str:
    """Create multiple new relations between entities in the knowledge graph.

    Args:
        relations (List[Relation]): A list of Relation objects defining connections
                                  between entities. Relations should be in active voice.

    Returns:
        str: Confirmation message indicating the result of the operation.
    """
    return memory.create_relations(relations)


@mcp.tool(name="read_memory",
        description="Read the memory knowledge graph")
def read_graph() -> KnowledgeGraph:
    """Read the entire memory knowledge graph.

    Returns:
        KnowledgeGraph: A KnowledgeGraph object containing all entities and relations
                       in the memory graph.
    """
    return memory.read_graph()


@mcp.tool(name="search_memory",
        description="Search the memory knowledge graph for a specific entity name")
def search_graph(query: str) -> KnowledgeGraph:
    """Search the memory knowledge graph for entities matching a specific name.

    Args:
        query (str): The search query string to match against entity names.

    Returns:
        KnowledgeGraph: A KnowledgeGraph object containing the matching entities
                       and their relations.
    """
    return memory.search_nodes(query)


def main():
    """Run the MCP server with CLI argument support.

    This function initializes and runs the Model Context Protocol server,
    supporting both SSE (Server-Sent Events) and default transport options.
    Command line arguments can be used to configure the server port and
    transport method.

    Command line arguments:
        --sse: Enable SSE transport
        --port: Specify the port number (default: 8888)
    """
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
