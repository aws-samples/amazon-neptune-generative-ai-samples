# Amazon Neptune Memory MCP Server

Model Context Protocol (MCP) server for providing memory to agents, stored in a knowledge graph against Amazon Neptune

This MCP server allows you to have a persistent memory knowledge graph for your MCP enabled clients

## Prerequisites

1. Install `uv` from [Astral](https://docs.astral.sh/uv/getting-started/installation/) or the [GitHub README](https://github.com/astral-sh/uv#installation)
2. Install Python using `uv python install 3.12`

## Installation

To use this with MCP clients you need to 
```json
{
  "mcpServers": {
    "aws-samples.neptune-mcp-servers.neptune-memory": {
      "command": "uvx",
      "args": ["aws-samples.neptune-mcp-servers.neptune-memory"],
      "env": {
        "FASTMCP_LOG_LEVEL": "INFO",
        "NEPTUNE_MEMORY_ENDPOINT": "<INSERT NEPTUNE ENDPOINT IN FORMAT SPECIFIED BELOW>"
      }
    }
  }
}
```

When specifying the Neptune Endpoint the following formats are expected:

For Neptune Database:
`neptune-db://<Cluster Endpoint>`

For Neptune Analytics:
`neptune-analytics://<graph identifier>`

## Features

The MCP Server provides an agentic memory capability stored as a knowledge graph