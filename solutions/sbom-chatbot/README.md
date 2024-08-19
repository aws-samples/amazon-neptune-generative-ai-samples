# Analyze Software Bill Of Materials (SBOM) using Generative AI with Amazon Neptune

This repo contains a sample application built on Streamlit that shows how you can use Amazon Neptune with different Generative AI techniques to run:

- Natural Language Queries - Using Amazon Bedrock Foundation models, your natural language
  question will be converted into an openCypher query, which will then be run, and results returned.
- Templated Query Extraction - Using Amazon Bedrock Foundation models, your natural language question will have the key entities extracted ,
  which are then be run using templated queries, and results returned.
- Knowledge Graph Enhanced RAG queries - Using Amazon Bedrock Foundation models, your natural language question will be answered using a combination of
  Knowledge Graph queries and Vector similarity. This data will then be sent to the LLM for summarization and
  results returned.

This is a Proof Of Concept application using an SBOM based dataset created using the notebook [here](https://github.com/aws/graph-notebook/blob/main/src/graph_notebook/notebooks/02-Neptune-Analytics/03-Sample-Use-Cases/03-Software-Bill-Of-Materials/02-SBOM-Vulnerability-Analysis.ipynb) with an embedding dimension of 1536.

## Dataset

In this project we used [Nodestream](https://nodestream-proj.github.io/docs/) and the [Nodestream SBOM plugin](https://github.com/nodestream-proj/nodestream-plugin-sbom) to load several SPDX files which were sourced from Github using its SBOM feature, detailed [here](https://docs.github.com/en/rest/dependency-graph/sboms).

Nodestream is a framework for dealing with semantically modeling data as a graph. It is designed to be flexible and extensible, allowing you to define how data is collected and modeled as a graph. It uses a pipeline-based approach to define how data is collected and processed, and it provides a way to define how the graph should be updated when the schema changes. All of this is done using a simple, human-readable configuration file in yaml format.

The included files for this notebook are:

- AWS CLI - version 2.0.6
- Gremlin Console - version 3.7.1
- Gremlin Server - version 3.7.1

## Running the Application

Setup your virtual environment

```
python -m venv ./venv
source ./venv/bin/activate
``

Install the requirements
```

pip install -r requirements.txt

```

To run the application:
```

streamlit run Home.py

```

```
