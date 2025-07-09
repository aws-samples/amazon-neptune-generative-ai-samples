# Sample Solutions
This folder contains a sample solutions using Generative AI tools and techniques that you can run in your own environment. 

## `sbom-chatbot` - Analyze Software Bill Of Materials (SBOM) using Generative AI with Amazon Neptune

This folder contains a sample application built on Streamlit that shows how you can use Amazon Neptune with different Generative AI techniques to run:

- Natural Language Queries (open world) - Using Amazon Bedrock Foundation models, your natural language question will be converted into an openCypher query, which will then be run, and results returned.
- Natural Language Queries (closed world) - Using Amazon Bedrock Foundation models, your natural language question will have the key entities extracted , which are then be run using templated queries, and results returned.
- Knowledge Graph Enhanced RAG (GraphRAG) - Using Amazon Bedrock Foundation models, your natural language question will be answered using a combination of Knowledge Graph queries and Vector similarity. This data will then be sent to the LLM for summarization and results returned.

## `graphrag-toolkit` - Use the GraphRAG toolkit to create a knowledge graph in Amazon Neptune

This folder contains sample code relating to implementing solutions using the [GraphRAG Toolkit](https://github.com/awslabs/graphrag-toolkit/tree/main).

This folder contains two folders;
- `(batch_processing_script)[/graphrag-toolkit/batch_processing_script]` - a sample script that can be run from any Python 3.11 enabled command-line (CLI) environment to create a knowledge graph using [Amazon Neptune](https://www.amazonaws.com/neptune) and the GraphRAG toolkit from PDF files stored on the file system.toolkit
- `(notebooks)[/graphrag-toolkit/notebooks]` - sample Jupyter notebooks that provide examples of using the GraphRAG toolkit with Amazon Neptune and Amazon OpenSearch Serverless.

## `mcp` - Use the Neptune MCP server for 'Conversational Graph Analytics' with Amazon Neptune

The folder contains sample code relating to implementing solutions using the [Amazon MCP Server](https://github.com/awslabs/mcp/tree/main/src/amazon-neptune-mcp-server).

- `(notebooks)[/mcp/notebooks]` - sample Jupyter notebooks that provide examples of using the Neptune MCP server with Amazon Neptune to help build your knowledge graph and ask natural language questions of the generated graph.
