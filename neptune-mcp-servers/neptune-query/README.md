# Amazon Neptune Query MCP Server

Model Context Protocol (MCP) server for running queries against Amazon Neptune

This MCP server allows you to run Gremlin and openCypher queries against a Neptune Database or openCypher queries against a Neptune Analytics dataabase.

## Prerequisites

1. Install `uv` from [Astral](https://docs.astral.sh/uv/getting-started/installation/) or the [GitHub README](https://github.com/astral-sh/uv#installation)
2. Install Python using `uv python install 3.12`
## Installation

Below is an example of how to configure your MCP client, although different clients may require a different format.


```json
{
  "mcpServers": {
    "Neptune Query": {
      "command": "uvx",
      "args": [
        "https://github.com/aws-samples/amazon-neptune-generative-ai-samples/releases/download/mcp-servers-v0.0.9-beta/neptune_query_mcp_server-0.0.9-py3-none-any.whl"
       ],
      "env": {
        "FASTMCP_LOG_LEVEL": "INFO",
        "NEPTUNE_QUERY_ENDPOINT": "<INSERT NEPTUNE ENDPOINT IN FORMAT SPECIFIED BELOW>"
      }
    }
  }
}

```

When specifying the Neptune Endpoint the following formats are expected:

For Neptune Database:
`neptune-db://<Cluster Endpoint>`

For Neptune Analytics:
`neptune-graph://<graph identifier>`

## Features

The MCP Server provides the following capabilities:

1. **Run Queries**: Execute openCypher and/or Gremlin queries against the configured database
2. **Schema**: Get the schema in the configured graph as a text string
3. **Status**: Find if the graph is "Available" or "Unavailable" to your server.  This is useful in helping to ensure that the graph is connected.