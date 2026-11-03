# Building Generative AI applications using knowledge graphs in Amazon Neptune

In this workshop, you'll learn how to leverage generative AI and graphs to create an application that queries your domain-specific, differentiated, and highly related datasets using natural language. Amazon Neptune will store your knowledge graph, ensuring that the data is up-to-date and accessible. The application will use natural language processing and vector search techniques to retrieve relevant information from your knowledge graph. 

To participate, bring a laptop. This workshop is for development teams, software engineers, architects, system administrators, data engineers, and data scientists who want to build knowledge systems using AI and graphs. The workshop will last approximately 2 hours, although with the optional content it may take longer.

Throughout this workshop we will be playing the part of a builder on an internal security team where you are assigned to work on a high priority project to provide tooling to provide improve your security posture through exposing software dependencies and vulnerabilities using Software Bill of Materials (SBOMs).

As a builder, you need to develop a tool that enables both power and standard users to access the information in the database through a chatbot interface. This information consists of data as well as documents.

You have decided that a graph database is the right tool to store your SBOM data and that you would like to use a generative AI application to query the documents.

The application you are building has the following requirements

* As a power user I want to be able to ask a natural language question over any data in the system
* As a user I want to be able to ask natural language question and have the system query based on a set of allowable actions
* As a user I want to be able to be able to ask a natural language question about data in documents


To meet these goals, you will use several techniques that leverage Generative AI, specifically open and defined domain question answering and graph enhanced RAG, along with services and tools such as Amazon Neptune, Amazon Bedrock, LlamaIndex, and Streamlit to build out a chatbot application. 

Throughout this workshop you will work through building the pieces required for each of the requirements above. At the end of each step, we will apply the techniques learned to an "incomplete" version of the chatbot application.

## Our Notebooks for this workshop

Each notebook is purpose-built to guide you through one of the key concepts required to build the application.

* 1-Introduction - This notebook provides an introductory overview to the application we are building as well as some introduction to graph concepts you will need to know to successfully complete this application.  
* 2-Open-Domain-Question-Answering - This notebook covers the ability to generate and execute graph queries from natural language questions.  Given the open nature of the questions allowed by this technique the user may ask any question of the system, providing a highly flexible, yet less secure, mechanism for accessing data.  e.g. Find me the number of vulnerabilities?
* 3-Defined-Domain-Question-Answering - This notebook covers to the process to take a natural language question, map it to one of a set of predefined actions, extract any key entities/identifiers from the question, and then use those as input to a pre-configured query.  This technique can be thought of as sort of a phone tree, where the user can make any request they would like but only a small set of actions are allowed.  Given the defined nature of the actions allowed, this technique allows the user ask any question but only perform a set of actions allowed by the developers, providing a secure and optimized experience for the end user.  e.g. Find me information about openldap?
* 4-Graph-Enhanced-RAG - This notebook covers how you can enhance vector-based retrieval in a RAG application through the addition of a graph.  We will show how you can leverage graphs to provide more complete and explainable responses to questions that require facts from multiple documents to answer questions or to summarize collections of documents.  e.g My vendor isn't giving me an SBOM, what do I do now?
* 5-Glossary - This notebook provides an in-depth overview of some of the key concepts and terms used throughout this workshop, to enable you to dive further into concepts that are unfamiliar or interesting.  e.g. What is a knowledge graph?

Notebooks 2, 3, and 4 contain both a walkthrough section as well as an optional section, which you can feel free to complete as time and interest allow.  The optional sections are not required to complete the workshop but do go into more depth on different configurations, optimizations, and features of these techniques.


## Prerequisites

- An AWS account, and AWS CLI v2 credentials with permission to create the resources below and an S3 bucket.
- A Region where Amazon Neptune Analytics and Amazon Bedrock are available. The sample application uses Claude Sonnet 5.5 through the US cross-region inference profile (`us.anthropic.claude-sonnet-5-5`), so use a US Region, or set `LLM_MODEL` to a model or inference profile that is available in your Region.
- Access to these Amazon Bedrock models. Bedrock enables most models on first use; for Anthropic models, a first-time use case form may need to be submitted for the account. See [Access Amazon Bedrock foundation models](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html).
  - Anthropic Claude Sonnet 5.5
  - Amazon Titan Text Embeddings V2
- On the machine you deploy from: GNU Make 3.81 or later (included with macOS and most Linux distributions), `rsync` and `tar`. `cfn-lint` (or `uv`, to run it) is optional and used by `make lint`.

## What gets deployed

The [CloudFormation template](./cloudformation/workshop.yaml) creates:

- Two Neptune Analytics graphs with 32 m-NCUs each: one that the notebooks use, and one that holds the data for the finished sample application.
- An `ml.t3.medium` SageMaker notebook instance running Amazon Linux 2023 and JupyterLab 4, with the Neptune graph notebook installed.
- An IAM role for the notebook instance that can query the two graphs, invoke Bedrock models, and read the workshop assets.

When the notebook instance first starts, it copies the workshop notebooks into `Neptune/00-Workshop-Start-HERE`, loads the demo graph, and starts the finished application from its own Python 3.12 environment. This takes a few minutes after the stack finishes.

These resources are billed while they exist, mainly the two graphs. Delete the stack when you're done (see [Cleaning up](#cleaning-up)).

## Getting Started

The [`GNUmakefile`](./GNUmakefile) in this folder builds and deploys everything from this repository:

```bash
cd workshops/Building_Generative_AI_applications
make deploy
```

`make deploy` runs these steps in order:

1. `bucket` - creates an S3 bucket for the workshop assets in your account, named `neptune-genai-workshop-<account>-<region>`, if it doesn't exist. Neptune Analytics loads data only from buckets in the graph's Region, so the bucket is in the same Region as the stack.
2. `package` - stages the notebooks, the data in [`assets/`](./assets), and the finished application from [`solutions/sbom-pgi-chatbot`](../../solutions/sbom-pgi-chatbot) into `build/stage`.
3. `upload` - syncs `build/stage` to `s3://<bucket>/<stack name>/`.
4. Deploys the stack with `aws cloudformation deploy`, then prints its outputs.

When it finishes, open the `NotebookUrl` output and go to `Neptune/00-Workshop-Start-HERE`, starting with `1-Introduction.ipynb`. Run `make outputs` to show the URLs again.

Settings can be changed on the command line:

| Variable | Default | Description |
| --- | --- | --- |
| `AWS_PROFILE` | the default credential chain | AWS CLI profile |
| `AWS_REGION` | the profile's Region | Region for the stack and the assets bucket |
| `STACK_NAME` | `genai-workshop` | Stack name. The notebook instance is named `aws-neptune-<STACK_NAME>`. |
| `LLM_MODEL` | `us.anthropic.claude-sonnet-5-5` | Bedrock model or inference profile for the sample application |
| `NOTEBOOK_INSTANCE_TYPE` | `ml.t3.medium` | Notebook instance type |
| `BUCKET` | `neptune-genai-workshop-<account>-<region>` | Assets bucket |
| `PREFIX` | `<STACK_NAME>/` | Key prefix for the assets in the bucket |

For example: `make deploy AWS_PROFILE=workshop AWS_REGION=us-west-2 STACK_NAME=my-workshop`. Run `make help` to list all targets.

The notebook instance copies the notebooks only on its first start, so that changes you make to them are kept when the instance restarts. To give an existing instance updated notebooks, delete the stack and deploy it again.

### Using Workshop Studio

The template takes the location of the assets as the `AssetsBucketName` and `AssetsBucketPrefix` parameters, so it can also be run from Workshop Studio. Run `make package`, upload the contents of `build/stage` to the event's assets location, and pass that bucket and prefix to the template.

## Troubleshooting

On the notebook instance, open a terminal and check:

- `~/SageMaker/.workshop/setup.log` - the background setup: copying the notebooks, loading the demo graph, and installing and starting the finished application.
- `~/SageMaker/.workshop/streamlit.log` - the finished application on port 8080.

The notebook cells that open the application read `~/SageMaker/.workshop/config.json`, which the setup writes when it finishes. If those cells report that the file doesn't exist, wait for the setup to finish and run the cell again.

## Cleaning up

```bash
make delete          # deletes the stack, including both graphs and the notebook instance
make delete-assets   # deletes this stack's assets from the bucket
make delete-bucket   # deletes the bucket, once it is empty
```

Each command asks for confirmation; add `CONFIRM=yes` to skip it. Use the same `AWS_PROFILE`, `AWS_REGION` and `STACK_NAME` values that you deployed with.