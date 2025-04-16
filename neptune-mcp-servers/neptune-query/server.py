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
from mcp.server.fastmcp.server import Context
import os
import argparse

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from neptune import NeptuneServer
import logging
from models import QueryLanguage
from typing import Dict

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

endpoint = os.environ.get("NEPTUNE_ENDPOINT", None)
use_https = os.environ.get("NEPTUNE_USE_HTTPS", 'True').lower() in ('true', '1', 't')
logger.info(f"NEPTUNE_ENDPOINT: {endpoint}")
if endpoint is None:
    raise ValueError("NEPTUNE_ENDPOINT environment variable is not set")
graph = NeptuneServer(endpoint, use_https=use_https)


mcp = FastMCP(
    "Neptune Query",
    instructions="""
    This provides access to an Amazon Neptune graph for running data queries.

    ## Usage Workflow:
    1. ALWAYS start by ensuring that the query can possibly be run
    2. Run openCypher or Gremlin queries by providing the language and query
    3. You can make multiple calls to with different queries
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
def get_schema_resource() -> str:
    """Get the schema for the graph including the vertex and edge labels as well as the
    (vertex)-[edge]->(vertex) combinations.
    """
    return graph.schema()

@mcp.tool(name="get_graph_status")
def get_status() -> str:
    """Get the status of the currently configured Amazon Neptune graph"""
    return graph.status()


@mcp.tool(name="get_graph_schema")
def get_schema() -> str:
    """Get the schema for the graph including the vertex and edge labels as well as the
    (vertex)-[edge]->(vertex) combinations.
    """
    return graph.schema()


@mcp.tool(name='run_query')
def run_query(query: str, language:QueryLanguage, parameters:Dict = None) -> Dict:
    """Executes an openCypher or Gremlin query (as specified) against the graph"""
    return graph.query(query, language, parameters)


@mcp.prompt()
def echo_prompt(message: str) -> str:
    """Create an echo prompt"""
    return f"Please process this message: {message}"


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