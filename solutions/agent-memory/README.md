# Agent Memory Demo

A demonstration of AI agents with persistent memory capabilities using Amazon Neptune and various memory frameworks.

## Overview

This project showcases how to build conversational AI agents that can remember user preferences and past interactions using graph databases. The demo includes a travel assistant that maintains memory across conversations for different users.

## Features

- **Multi-user memory management** - Separate memory contexts for different users (Alice, Bob, Chris)
- **Multiple memory frameworks** - Support for Mem0, Cognee, and Graphiti
- **Amazon Neptune integration** - Graph database backend for persistent memory storage
- **Weather integration** - Real-time weather information for travel planning
- **Streamlit web interface** - Interactive chat interface for testing

## Architecture

The project integrates three memory frameworks with Amazon Neptune:

- **Mem0** - Vector and graph-based memory with OpenSearch and Neptune
- **Cognee** - Knowledge graph construction with Neptune Analytics
- **Graphiti** - Graph-based memory management

## Prerequisites

- Python 3.12+
- AWS account with access to:
  - Amazon Neptune
  - Amazon Bedrock (Claude 3.7 Sonnet)
  - Amazon OpenSearch Serverless
- AWS credentials configured

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   uv venv
   uv sync
   ```

3. Configure environment variables in `.env`, use the `.env.example` as a template

When specifying the Neptune Endpoint the following formats are expected:

For Neptune Database: neptune-db://<Cluster Endpoint>

For Neptune Analytics: neptune-graph://<graph identifier>

## Usage

Run the Streamlit application:
```bash
streamlit run app.py
```

Navigate to the web interface and:
1. Select a user (Alice, Bob, or Chris)
2. Start chatting with the travel assistant
3. The agent will remember your preferences and past conversations

## Project Structure

```
agent-memory/
├── frameworks/          # Memory framework integrations
│   ├── cognee_neptune.py
│   ├── mem0_neptune.py
│   └── graphiti_neptune.py
├── tools/              # Agent tools and capabilities
│   ├── memory_tool.py
│   ├── weather_agent.py
│   └── general_assistant.py
├── app.py             # Streamlit web application
└── pyproject.toml     # Project dependencies
```

## Memory Frameworks

### Mem0
- Combines vector similarity search with graph relationships
- Uses OpenSearch for embeddings and Neptune for graph storage
- Supports user-specific memory contexts

### Cognee
- Builds knowledge graphs from conversational data
- Integrates with Neptune Analytics
- Provides semantic search capabilities

### Graphiti
- Graph-based memory management
- Maintains temporal relationships between memories
- Optimized for conversational AI applications

## License

This project is part of the AWS Samples repository and follows the MIT-0 license.