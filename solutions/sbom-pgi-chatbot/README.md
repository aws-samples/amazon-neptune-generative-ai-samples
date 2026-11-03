# Analyze Software Bill Of Materials (SBOM) using Generative AI with Amazon Neptune

This repo contains a sample application built on Streamlit that shows how you can use Amazon Neptune with different Generative AI techniques to run:

- Natural Language Queries (open world) - Using Amazon Bedrock Foundation models, your natural language question will be converted into an openCypher query, which will then be run, and results returned.
- Natural Language Queries (closed world) - Using Amazon Bedrock Foundation models, your natural language question will have the key entities extracted , which are then be run using templated queries, and results returned.
- Graph Enhanced RAG (GraphRAG) - Using Amazon Bedrock Foundation models, your natural language question will be answered using a combination of Knowledge Graph queries and Vector similarity. This data will then be sent to the LLM for summarization and results returned.


The SBOM data for this application was created using the SBOM based dataset created using the notebook [here](https://github.com/aws/graph-notebook/blob/main/src/graph_notebook/notebooks/02-Neptune-Analytics/03-Sample-Use-Cases/03-Software-Bill-Of-Materials/02-SBOM-Vulnerability-Analysis.ipynb).

## Dataset

The dataset used for the natural language querying portions of this sample were created using the [Nodestream](https://nodestream-proj.github.io/docs/) and the [Nodestream SBOM plugin](https://github.com/nodestream-proj/nodestream-plugin-sbom) to load several SPDX files which were sourced from Github using its SBOM feature, detailed [here](https://docs.github.com/en/rest/dependency-graph/sboms).

Nodestream is a framework for dealing with semantically modeling data as a graph. It is designed to be flexible and extensible, allowing you to define how data is collected and modeled as a graph. It uses a pipeline-based approach to define how data is collected and processed, and it provides a way to define how the graph should be updated when the schema changes. All of this is done using a simple, human-readable configuration file in yaml format.

The included files for this notebook are:

- AWS CLI - version 2.0.6
- Gremlin Console - version 3.7.1
- Gremlin Server - version 3.7.1

After the data was loaded into the graph it was exported into a Gremlin CSV format that was capable of being loaded into Neptune.

The documents used for the graph enhanced RAG portions of this example are either available from the [United States Cybersecurity & Infrastructure Security Agency (CISA) SBOM Resource Library](https://www.cisa.gov/topics/cyber-threats-and-advisories/sbom/sbomresourceslibrary):

* [SBOM FAQ 2024](https://cisa.gov/resources-tools/resources/sbom-faq)
* [SBOM Sharing Primer](https://www.cisa.gov/resources-tools/resources/sbom-sharing-primer)
* [Software Transparency in a SaaS Environment](https://www.cisa.gov/resources-tools/resources/software-transparency-saas-environments-0)

or was synthetically generated (Example Corp Software Bill of Material.docx) to represent non-public internal documentation and policies.

### Loading the Data
The quickest way to run this application is the workshop in [`workshops/Building_Generative_AI_applications`](../../workshops/Building_Generative_AI_applications), whose `make deploy` creates the graph, loads the data, and runs this application on the notebook instance.

To run it yourself, you need a single Neptune Analytics graph with at least 32 m-NCUs and vector search enabled with a dimension of 256, which matches the stored Titan Text Embeddings V2 embeddings.

The data for the graph is in [`workshops/Building_Generative_AI_applications/assets/sbom_data`](../../workshops/Building_Generative_AI_applications/assets/sbom_data). It contains both the SBOM data and the entities and chunks, with their embeddings, used by the Graph Enhanced RAG page. Copy the folder to an S3 bucket in the same Region as the graph, then load it with openCypher (see [Batch load](https://docs.aws.amazon.com/neptune-analytics/latest/userguide/batch-load.html)):

```
CALL neptune.load({format: 'csv', source: 's3://<bucket>/<prefix>/sbom_data/'})
YIELD totalRecords
RETURN totalRecords
```

The `persist/` folder holds the saved LlamaIndex indexes that match this data, so the application doesn't need to rebuild them.

## Security

This application requires the ability to perform queries on the databases.

For the SBOM cluster/Natural Language querying we suggest that you only allow [`ReadDataViaQuery`](https://docs.aws.amazon.com/neptune/latest/userguide/iam-dp-actions.html#readdataviaquery) permissions in order to prevent unintended consequences, such as data mutation/deletion.

For the GraphRAG cluster the user will need both [`ReadDataViaQuery`](https://docs.aws.amazon.com/neptune/latest/userguide/iam-dp-actions.html#readdataviaquery) and [`WriteDataViaQuery`](https://docs.aws.amazon.com/neptune/latest/userguide/iam-dp-actions.html#writedataviaquery) to write the data during indexing and read the results during retrieval.

The application will also need IAM permissions to invoke the Bedrock API with the [`bedrock:InvokeModel`](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html) policy.

Note: Within the library the `botocore` library is used to fetch the credentials used for the application.  If you are using an EC2 role this means that you will need to setup default region, and example of how this can be done is [here](https://stackoverflow.com/questions/40377662/boto3-client-noregionerror-you-must-specify-a-region-error-only-sometimes).


## Setup

This application uses [dotenv](https://pypi.org/project/python-dotenv/) to manage the configuration.  To use this you will need to create a `.env` file and put in the information below

```
# The graph identifier of the Neptune Analytics graph
HOST="your-sbom-neptune-analytics-graph-identifier"
# The Region of the graph and of the Bedrock calls
AWS_REGION="us-east-1"

# Optional. The Bedrock model or inference profile used for query generation and answers.
# Defaults to Claude Sonnet 5.5 through the US cross-region inference profile.
LLM_MODEL="us.anthropic.claude-sonnet-5-5"
# Optional. The embedding model. The stored embeddings were created with Titan Text
# Embeddings V2 at 256 dimensions, so changing this requires re-creating them.
EMBEDDINGS_MODEL="amazon.titan-embed-text-v2:0"
```

## Running the Application

The application requires Python 3.11 or later. Setup your virtual environment

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

To run the unit tests for the query validator in `cypher_validator.py`, which don't need AWS access:
```
pip install pytest
python -m pytest tests
```

Once you run the application the terminal will give you the IP and port that you can use to connect to the UI.
