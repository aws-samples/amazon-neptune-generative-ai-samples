# Analyze Software Bill Of Materials (SBOM) using Generative AI with Amazon Neptune

This sample application was used as part of an [AWS On-Air segment](https://www.twitch.tv/videos/2237168636?filter=all&sort=time), it is recommended that you watch this recording to understand the features and functionality being demonstrated by this application.

This repo contains a sample application built on Streamlit that shows how you can use Amazon Neptune with different Generative AI techniques to run:

- Natural Language Queries (open world) - Using Amazon Bedrock Foundation models, your natural language question will be converted into an openCypher query, which will then be run, and results returned.
- Natural Language Queries (closed world) - Using Amazon Bedrock Foundation models, your natural language question will have the key entities extracted , which are then be run using templated queries, and results returned.
- Knowledge Graph Enhanced RAG (GraphRAG) - Using Amazon Bedrock Foundation models, your natural language question will be answered using a combination of Knowledge Graph queries and Vector similarity. This data will then be sent to the LLM for summarization and results returned.


This iSBOM data for this application was created using the SBOM based dataset created using the notebook [here](https://github.com/aws/graph-notebook/blob/main/src/graph_notebook/notebooks/02-Neptune-Analytics/03-Sample-Use-Cases/03-Software-Bill-Of-Materials/02-SBOM-Vulnerability-Analysis.ipynb).

## Dataset

In this project we used [Nodestream](https://nodestream-proj.github.io/docs/) and the [Nodestream SBOM plugin](https://github.com/nodestream-proj/nodestream-plugin-sbom) to load several SPDX files which were sourced from Github using its SBOM feature, detailed [here](https://docs.github.com/en/rest/dependency-graph/sboms).

Nodestream is a framework for dealing with semantically modeling data as a graph. It is designed to be flexible and extensible, allowing you to define how data is collected and modeled as a graph. It uses a pipeline-based approach to define how data is collected and processed, and it provides a way to define how the graph should be updated when the schema changes. All of this is done using a simple, human-readable configuration file in yaml format.

The included files for this notebook are:

- AWS CLI - version 2.0.6
- Gremlin Console - version 3.7.1
- Gremlin Server - version 3.7.1

### Loading the Data
To use this application you will need to setup 2 Neptune Database clusters, one for the natural language querying portions and a second for the GraphRAG demo.

Once you have created the clusters you will need to load the data locations in `/data/sbom` into the SBOM cluster using the Neptune Bulk loader.  
Instructions for using the bulk loader are available here: (Neptune Bulk Loader)[https://docs.aws.amazon.com/neptune/latest/userguide/bulk-load.html]

The data for the RAG and GraphRAG workflows will be created and stored into the cluster on the first run using the PDF files located in `/data/kg_enhanced_rag`.

## Security

This application requires the ability to perform queries on the databases.

For the SBOM cluster/Natural Language querying we suggest that you only allow [`ReadDataViaQuery`](https://docs.aws.amazon.com/neptune/latest/userguide/iam-dp-actions.html#readdataviaquery) permissions in order to prevent unintended consequences, such as data mutation/deletion.

For the GraphRAG cluster the user will need both [`ReadDataViaQuery`](https://docs.aws.amazon.com/neptune/latest/userguide/iam-dp-actions.html#readdataviaquery) and [`WriteDataViaQuery`](https://docs.aws.amazon.com/neptune/latest/userguide/iam-dp-actions.html#writedataviaquery) to write the data during indexing and read the results during retrieval.

The application will also need IAM permissions to invoke the Bedrock API with the [`bedrock:InvokeModel`](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html) policy.

Note: Within the library the `botocore` library is used to fetch the credentials used for the application.  If you are using an EC2 role this means that you will need to setup default region, and example of how this can be done is [here](https://stackoverflow.com/questions/40377662/boto3-client-noregionerror-you-must-specify-a-region-error-only-sometimes).


## Setup

This application uses [dotenv](https://pypi.org/project/python-dotenv/) to manage the configuration.  To use this you will need to create a `.env` file and put in the information below

```
# The Cluster Endpoint for the SBOM cluster
GRAPH_ENDPOINT="your-sbom-neptune-endpoint"
# The Cluster Endpoint for the GraphRAG cluster
KGRAG_ENDPOINT="your-graphrag-neptune-endpoint"
USE_HTTPS = true
PORT = 8182

# The LLM used to perform extraction.
LLM_MODEL="anthropic.claude-3-sonnet-20240229-v1:0"
# The LLM used to compute embeddings and perform vector search.
EMBEDDINGS_MODEL="amazon.titan-embed-text-v1"

# Max number of triplets per chunk for the Knowledge Graph Index
MAX_TRIPLETS_PER_CHUNK = 5
```

## Running the Application

Setup your virtual environment

```
python -m venv ./venv
source ./venv/bin/activate
```

Install the requirements
```
pip install -r requirements.txt
```

To run the application:
```
streamlit run Home.py
```

Once you run the application the terminal will give you the IP and port that you can use to connect to the UI.