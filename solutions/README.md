# Sample Solutions
This folder contains a sample application built on Streamlit that shows how you can use Amazon Neptune with different Generative AI techniques to run:

## `sbom-chatbot` - Analyze Software Bill Of Materials (SBOM) using Generative AI with Amazon Neptune

This folder contains a sample application built on Streamlit that shows how you can use Amazon Neptune with different Generative AI techniques to run:

- Natural Language Queries (open world) - Using Amazon Bedrock Foundation models, your natural language question will be converted into an openCypher query, which will then be run, and results returned.
- Natural Language Queries (closed world) - Using Amazon Bedrock Foundation models, your natural language question will have the key entities extracted , which are then be run using templated queries, and results returned.
- Knowledge Graph Enhanced RAG (GraphRAG) - Using Amazon Bedrock Foundation models, your natural language question will be answered using a combination of Knowledge Graph queries and Vector similarity. This data will then be sent to the LLM for summarization and results returned.
