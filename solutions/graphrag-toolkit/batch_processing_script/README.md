# Batch Graph and Vector store extraction and build using the GraphRAG Toolkit and Amazon Neptune

This repositories contains sample script that can be run from any Python 3.11 enabled command-line (CLI) environment to create a knowledge graph using [Amazon Neptune](https://www.amazonaws.com/neptune) and the [GraphRAG Toolkit](https://github.com/awslabs/graphrag-toolkit/tree/main) from PDF files stored on the file system.

## How the script works

The sample script performs the [extraction](https://github.com/awslabs/graphrag-toolkit/blob/main/docs/lexical-graph/indexing.md#extract) and [build](https://github.com/awslabs/graphrag-toolkit/blob/main/docs/lexical-graph/indexing.md#build) stages [separately](https://github.com/awslabs/graphrag-toolkit/blob/main/docs/lexical-graph/indexing.md#run-the-extract-and-build-stages-separately) in order to store the generated embedding files for auditing or use in different environments. 

It utilises [batch extraction and inference](https://github.com/awslabs/graphrag-toolkit/blob/main/docs/lexical-graph/batch-extraction.md) in order to improve throughput and reduce document processing time. Each document is chunked and sent to an Amazon S3 bucket. An Amazon Bedrock batch inference job is created by the toolkit to perform the inference across all the chunks in one go, as opposed to infering each chunk one-by-one.

## Prerequisites

The sample script assumes the graph store will be an [Amazon Neptune Database cluster](https://docs.aws.amazon.com/neptune/latest/userguide/get-started-cfn-create.html) and the vector store will be an [Amazon OpenSearch Serverless collection](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-getting-started.html). The quick-start tutorial guides will help you get these set-up prior to running the script.

In addition, the role configured to run this script will need to have the required IAM permissions to write to the Neptune cluster and OpenSearch Serverless collection, as well as create and execute batch inference. For batch inference, follow the [prerequisite guide](https://github.com/awslabs/graphrag-toolkit/blob/main/docs/lexical-graph/batch-extraction.md) on the GraphRAG toolkit.

To avoid reprocessing chunks that have been successfully processed during the `extract` and `build` stages, the script implements [checkpointing](https://github.com/awslabs/graphrag-toolkit/blob/main/docs/lexical-graph/batch-extraction.md#checkpoints) using the name provided by the `--c` argument. For each stage it creates a different Checkpoint as follows:

Extract stage:
```
extraction_checkpoint_id = f"{CHECKPOINT}-{str(i)}-EXTRACTION"
extraction_checkpoint = Checkpoint(extraction_checkpoint_id, enabled=True)
```

Build stage:
```
build_checkpoint_id = f"{CHECKPOINT}-{str(i)}-BUILD"
build_checkpoint = Checkpoint(build_checkpoint_id, enabled=True)
```

For debugging purposes, the `extraction_checkpoint_id` and `build_checkpoint_id` are both printed to screen.

## Running the Script

Setup your virtual environment

```
python -m venv ./venv
source ./venv/bin/activate
```

Install the requirements
```
pip install -r requirements.txt
```

The script requires the following command-line arguments:

- `--s` - the path to a local folder
- `--c` - the checkpoint name. See the [GraphRAG checkpointing](https://github.com/awslabs/graphrag-toolkit/blob/main/docs/lexical-graph/batch-extraction.md#checkpoints) section for more information.
- `--g` - the Neptune cluster endpoint
- `--v` - the OpenSearch Serverless collection endpoint
- `--b` - a JSON map representing the batch processing configuration (see below)

### Batch Configuration options

The `--b` parameter accepts a JSON map object containing the following keys:

- `region` - the AWS region running, e.g. US-WEST-2
- `bucket` - the name of an S3 bucket deployed in the same region to store batch extraction results
- `prefix` - an S3 bucket prefix
- `role_arn` - the ARN of the IAM role used for batch inference. See the [GraphRAG toolkit document](https://github.com/awslabs/graphrag-toolkit/blob/main/docs/lexical-graph/batch-extraction.md#custom-service-role) for more information.
- `extraction_batch_size` - the size of each extraction batch. `Default: 5000`
- `include_domain_labels` - whether or not to extract and create domain-specific labels in the graph. `Default: False`

The following is an example of calling the script with the required parameters:

```
python batch_graphrag_terminal_script.py 
   --s /home/my_pdf_files \
   --c checkpoint-neptune-aoss-kg \
   --g my-neptune-cluster.cluster-abc1de2fghij.us-west-2.neptune.amazonaws.com \
   --v https://1abcdefgh23i45jk6lmn.us-west-2.aoss.amazonaws.com \
   --b '{"region":"us-west-2","bucket":"s3-batch-extract-bucket-us-west-2","prefix":"neptune-aoss-kg" "role_arn":"arn:aws:iam::123456789012:role/MyGraphRAGBatchInferenceRole","extraction_batch_size":5000,"include_domain_labels":True}'
```

## Debugging

By default, the script will print all setup information such as when it's setting the chunking strategy, or when it's starting either `extract` or `build` stages. In addition, it also sets the GraphRAG toolkit logging configuration to print all `INFO` logs to screen for the `extract` and `build` stages using the following command:

```
set_logging_config(logging_level='INFO', included_modules=['graphrag_toolkit.indexing.extract', 'graphrag_toolkit.indexing.build'])
```

To configure this for different logging levels, see the [Logging configuration](https://github.com/awslabs/graphrag-toolkit/blob/60bb025f79ee125f83eefdbcd1fcb04730e81eb7/docs/lexical-graph/configuration.md#logging-configuration) section on the GraphRAG toolkit repository for more information.