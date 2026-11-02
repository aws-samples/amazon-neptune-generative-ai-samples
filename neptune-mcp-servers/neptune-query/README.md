# Amazon Neptune Query MCP Server (Deprecated)

> [!WARNING]
> **This server is deprecated and is no longer maintained.** Use the official
> [Amazon Neptune MCP Server](https://awslabs.github.io/mcp/servers/amazon-neptune-mcp-server/)
> ([`awslabs.amazon-neptune-mcp-server`](https://pypi.org/project/awslabs.amazon-neptune-mcp-server/))
> from the [AWS Labs MCP repository](https://github.com/awslabs/mcp/tree/main/src/amazon-neptune-mcp-server)
> instead. It provides the same capabilities as this server and is published to PyPI.
> The code here is kept for reference only and will not receive new features or fixes.

## Migrating to the official server

The official server exposes the same tools (`get_graph_status`, `get_graph_schema`,
`run_opencypher_query`, `run_gremlin_query`) and resources (`amazon-neptune://status`,
`amazon-neptune://schema`), and it uses the same endpoint formats. To migrate, change the
package and rename the environment variables:

| This server | Official server |
| --- | --- |
| `uvx <neptune_query_mcp_server wheel URL>` | `uvx awslabs.amazon-neptune-mcp-server@latest` |
| `NEPTUNE_QUERY_ENDPOINT` | `NEPTUNE_ENDPOINT` |
| `NEPTUNE_QUERY_USE_HTTPS` | `NEPTUNE_USE_HTTPS` |

```json
{
  "mcpServers": {
    "Neptune Query": {
      "command": "uvx",
      "args": ["awslabs.amazon-neptune-mcp-server@latest"],
      "env": {
        "FASTMCP_LOG_LEVEL": "INFO",
        "NEPTUNE_ENDPOINT": "<INSERT NEPTUNE ENDPOINT IN FORMAT SPECIFIED BELOW>"
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

See the [official server documentation](https://awslabs.github.io/mcp/servers/amazon-neptune-mcp-server/)
for prerequisites, IAM permissions, and Windows and Docker configuration.

## Legacy installation

If you must keep running this server for now, the published `v0.0.9` wheel needs `mcp` pinned
below 2: mcp 2.x removed `mcp.server.fastmcp`, so the server fails to start without the pin.
Lower versions of mcp 1.x have known vulnerabilities, so pin to `>=1.30.0,<2`:

```json
{
  "mcpServers": {
    "Neptune Query": {
      "command": "uvx",
      "args": [
        "--with",
        "mcp[cli]>=1.30.0,<2",
        "https://github.com/aws-samples/amazon-neptune-generative-ai-samples/releases/download/mcp-servers-v0.0.9-beta/neptune_query_mcp_server-0.0.9-py3-none-any.whl"
      ],
      "env": {
        "FASTMCP_LOG_LEVEL": "INFO",
        "NEPTUNE_QUERY_ENDPOINT": "<INSERT NEPTUNE ENDPOINT IN FORMAT SPECIFIED ABOVE>"
      }
    }
  }
}
```
