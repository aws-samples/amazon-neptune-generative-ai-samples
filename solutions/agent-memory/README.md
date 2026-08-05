# Agent Memory

A platform for building AI agents with persistent memory using Amazon Neptune, Amazon Bedrock, and graph-based memory frameworks.

## Overview

This project provides a **generic memory-enabled agent platform** that can be configured for any use case. Agents remember user preferences, past interactions, and context across conversations using graph databases.

The platform ships with example agent configurations (like a travel assistant) to demonstrate the capabilities, but the core memory layer is domain-agnostic — you can build any kind of memory-powered agent on top of it.

## Features

- **Configurable agent personas** — Swap agent behavior via config (default generic assistant, travel planner, or your own)
- **Multi-user memory management** — Separate memory contexts per user
- **Multiple memory frameworks** — Mem0, Cognee, and Graphiti with Neptune backends
- **100% AWS-native** — All LLM, embedding, graph, and vector operations use AWS services (Bedrock, Neptune, OpenSearch). No third-party API keys required.
- **Multiple interfaces** — Streamlit web UI, Python API, kiro-cli, or Claude Code

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- AWS account with access to:
  - Amazon Bedrock (Claude Sonnet 4.6 + Titan Embed V2)
  - Amazon Neptune (Database and/or Analytics, depending on framework)
  - Amazon OpenSearch Serverless (for Graphiti only)
- AWS credentials configured (env vars, `~/.aws/credentials`, or IAM role)

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/aws-samples/amazon-neptune-generative-ai-samples.git
cd amazon-neptune-generative-ai-samples/solutions/agent-memory
```

### 2. Install dependencies

```bash
uv venv
uv sync
```

### 3. Configure environment

Copy the example environment file and fill in your infrastructure endpoints:

```bash
cp .env.example .env
```

Edit `.env` with your values. At minimum you need:

```bash
AWS_REGION = us-east-1

# For Mem0 (the default memory framework):
MEM0_NEPTUNE_ENDPOINT = neptune-graph://<your-graph-id>
```

For Cognee:
```bash
COGNEE_ENDPOINT = neptune-graph://<your-graph-id>
ENABLE_BACKEND_ACCESS_CONTROL = false
COGNEE_SKIP_CONNECTION_TEST = true
```

For Graphiti:
```bash
GRAPHITI_NEPTUNE_ENDPOINT = neptune-db://<your-cluster-endpoint>
GRAPHITI_AOSS_ENDPOINT = <your-opensearch-collection-endpoint>
```

See `.env.example` for the full list of configuration options including Cognee and Graphiti endpoints.

### AWS Authentication

All frameworks use Amazon Bedrock and Neptune, which require AWS credentials. Cognee supports multiple authentication methods (see [Cognee AWS Bedrock docs](https://docs.cognee.ai/integrations/aws-bedrock-integration)):

| Method | Setup | Best For |
|--------|-------|----------|
| **Credentials file** (recommended) | `~/.aws/credentials` with a default profile | Local development |
| **Environment variables** | Set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` | CI/CD, containers |
| **IAM instance role** | No configuration needed | EC2, ECS, Lambda |
| **AWS Profile** | Set `AWS_PROFILE` env var | Multiple accounts |

**Important for kiro-cli/MCP usage:** If you use `~/.aws/credentials`, do **not** include `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN` in the MCP server's `env` configuration — specifying them (even empty) will override the credentials file. The MCP subprocess inherits access to `~/.aws/credentials` automatically.

### 4. (Optional) Load sample data

To pre-populate all three frameworks with example conversation data for comparison:

```bash
uv run python load_all_frameworks.py
```

## Usage

The platform supports multiple agent configurations and memory backends. Set environment variables to choose:

| Variable | Options | Default |
|----------|---------|---------|
| `AGENT_CONFIG` | `default`, `travel_assistant`, or custom | `default` |
| `MEMORY_FRAMEWORK` | `mem0`, `cognee`, `graphiti` | `mem0` |

```bash
# Default generic assistant with Mem0 backend
uv run streamlit run app.py

# Travel assistant with Cognee backend
AGENT_CONFIG=travel_assistant MEMORY_FRAMEWORK=cognee uv run streamlit run app.py
```

You only need to configure the endpoints for the backend you're using (see `.env.example`).

### Option A: Streamlit Web App

```bash
uv run streamlit run app.py
```

Navigate to the displayed URL, select a user from the sidebar, and start chatting. The agent remembers context across messages.

### Option B: Python Script / CLI

The memory agent is a standalone Strands agent:

```python
from tools.memory_tool import memory_agent

memory_agent.state.set('user_id', 'Alice')
response = memory_agent("What do you remember about me?")
print(response)
```

### Option C: kiro-cli

A kiro-cli agent config is included at `.kiro/agents/memory-assistant.json`. When you run kiro-cli from this directory, the agent is automatically available:

```bash
cd solutions/agent-memory
kiro-cli chat
```

Then swap to the memory assistant:
```
/agent memory-assistant
```

The agent has `search_memory` and `add_memory` as MCP tools — it will ask for your user_id and use memory naturally throughout the conversation.

To set it as your default agent for this workspace:
```bash
kiro-cli agent set-default memory-assistant
```

### Option D: Claude Code

An `.mcp.json` config is included that exposes the memory tools to Claude Code automatically:

```bash
cd solutions/agent-memory
claude
```

Claude will have `search_memory` and `add_memory` available as tools. See `CLAUDE.md` for usage instructions that Claude reads on startup.

### Creating a Custom Agent

To create your own agent persona, add a new file in `examples/`:

```python
# examples/my_agent.py

AGENT_NAME = "My Custom Agent"
AGENT_DESCRIPTION = "An agent that does something specific."

SYSTEM_PROMPT = """\
You are a helpful assistant specialized in...
"""

EXTRA_TOOLS = []  # Add any additional @tool functions here
USERS = ["user1", "user2"]
```

Then run with:
```bash
AGENT_CONFIG=my_agent uv run streamlit run app.py
```

## Architecture

All three memory frameworks use **Amazon Bedrock** for LLM inference — no third-party API keys needed. Authentication uses the standard AWS credential chain.

### Infrastructure Per Framework

| Framework | Graph DB | Vector DB | LLM | Embeddings |
|-----------|----------|-----------|-----|-----------|
| **Mem0** | Neptune Analytics | Neptune Analytics | Bedrock (native) | Bedrock Titan Embed V2 |
| **Cognee** | Neptune Analytics | Neptune Analytics | Bedrock (native) | Bedrock Titan Embed V2 (via litellm) |
| **Graphiti** | Neptune Database | OpenSearch Serverless | Bedrock (via litellm) | Bedrock Titan Embed V2 |

### Neptune Endpoint Formats

- **Neptune Database**: `neptune-db://<cluster-endpoint>`
- **Neptune Analytics**: `neptune-graph://<graph-identifier>`

### Key Environment Variables

| Variable | Used By | Description |
|----------|---------|-------------|
| `AGENT_CONFIG` | Agent | Agent persona to load (default: `default`). See `examples/` |
| `MEMORY_FRAMEWORK` | Agent | Memory backend: `mem0`, `cognee`, or `graphiti` (default: `mem0`) |
| `AWS_REGION` | All | AWS region for Bedrock and infrastructure |
| `BEDROCK_MODEL_ID` | All | LLM model (defaults to `us.anthropic.claude-sonnet-4-6`) |
| `BEDROCK_EMBEDDING_MODEL_ID` | Graphiti | Embedding model (defaults to `amazon.titan-embed-text-v2:0`) |
| `MEM0_NEPTUNE_ENDPOINT` | Mem0 | Neptune Analytics endpoint (`neptune-graph://<id>`) |
| `COGNEE_ENDPOINT` | Cognee | Neptune Analytics endpoint (`neptune-graph://<id>`) |
| `ENABLE_BACKEND_ACCESS_CONTROL` | Cognee | Set to `false` (required for Neptune Analytics) |
| `COGNEE_SKIP_CONNECTION_TEST` | Cognee | Set to `true` (avoids Bedrock cold start timeouts) |
| `GRAPHITI_NEPTUNE_ENDPOINT` | Graphiti | Neptune Database endpoint (`neptune-db://<endpoint>`) |
| `GRAPHITI_AOSS_ENDPOINT` | Graphiti | OpenSearch Serverless endpoint |

## Project Structure

```
agent-memory/
├── .kiro/agents/            # kiro-cli agent configurations
│   └── memory-assistant.json
├── .mcp.json                # Claude Code MCP server config
├── CLAUDE.md                # Claude Code project instructions
├── examples/                # Agent configurations (personas)
│   ├── default.py           # Generic memory assistant (default)
│   └── travel_assistant.py  # Travel planning demo with weather tools
├── frameworks/              # Memory framework integrations
│   ├── memory_backend.py    # Unified backend interface (search/add)
│   ├── mem0_neptune.py      # Mem0 with Neptune Analytics + Bedrock
│   ├── cognee_neptune.py    # Cognee with Neptune Analytics + Bedrock
│   └── graphiti_neptune.py  # Graphiti with Neptune DB + AOSS + Bedrock
├── tools/                   # Agent tools and capabilities
│   ├── memory_tool.py       # Strands memory agent (for Streamlit/Python)
│   ├── weather_agent.py     # Weather lookups via NWS API
│   ├── general_assistant.py # General knowledge fallback
│   └── flights.py           # Flight booking via Neptune MCP
├── tests/                   # Unit and integration tests
├── app.py                   # Streamlit web application
├── mcp_server.py            # MCP server (for kiro-cli/Claude Code)
├── load_all_frameworks.py   # Script to load sample data into all frameworks
├── pyproject.toml           # Project dependencies and test config
└── .env.example             # Environment variable template
```

## Running Tests

```bash
# Unit tests (no infrastructure needed)
uv run pytest tests/ -m "not integration"

# Integration tests (requires configured .env with real endpoints)
uv run pytest tests/ -m integration
```

## Memory Frameworks

### Mem0
- Combines vector similarity search with graph relationships (entity extraction + relationship edges)
- Uses Neptune Analytics as a unified graph + vector store
- Supports user-specific memory contexts with per-user isolation
- Bedrock-native for both LLM and embedding operations
- Pinned to Mem0 1.x which retains `graph_store` support (removed in 2.x)

### Cognee
- Builds rich semantic knowledge graphs from conversational data (typed entities + relationship edges)
- Uses Neptune Analytics as a unified graph + vector store
- LLM-powered entity/relationship extraction during ingestion
- Native Bedrock integration for LLM (Cognee 1.4+), embeddings via Bedrock Titan through litellm
- Slower ingestion but richer graph structure for complex reasoning

### Graphiti
- Temporal knowledge graphs with evolving entity relationships
- Uses Neptune Database for graph storage and OpenSearch Serverless for fulltext search
- Bedrock LLM via litellm (native SigV4 auth, no tokens or OpenAI-compatible endpoints)
- Custom `BedrockEmbedder` for Titan Embed V2 (no OpenAI dependency)
- Indexes auto-created on first use

> **Note:** The Graphiti Neptune driver (v0.29.x) has several known bugs that this project patches at runtime:
> the `_database` attribute is uninitialized, query parameters aren't filtered for unreferenced/None values,
> and a nested `params` kwarg isn't flattened before reaching Neptune's openCypher API. Upstream fixes exist
> as open PRs ([#1568](https://github.com/getzep/graphiti/pull/1568),
> [#1539](https://github.com/getzep/graphiti/pull/1539)) but have not yet been merged.
> Additionally, vector similarity search fetches all entity embeddings from the graph and computes
> cosine similarity in Python rather than using AOSS kNN — this limits scalability to a few thousand entities.

## License

This project is part of the AWS Samples repository and follows the MIT-0 license.
