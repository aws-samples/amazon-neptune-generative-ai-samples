"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

# Information
# --------------------------------
# This script automates the batch extraction of PDF files stored locally within a Jupyter notebook, or Python-enabled file system.
# It assumes Amazon Neptune Database is used as the underlying graph store, and Amazon OpenSearch Serverless Service is used as the vector store.
# Please use the following guides to create the required IAM roles:
#   - https://github.com/awslabs/graphrag-toolkit/blob/main/docs/lexical-graph/batch-extraction.md#prerequisites

import time
import json
import sys, getopt

from datetime import datetime
from collections.abc import Mapping

from pathlib import Path
from pypdf import PdfReader

from graphrag_toolkit import GraphRAGConfig
from graphrag_toolkit import set_logging_config, GraphRAGConfig, IndexingConfig, ExtractionConfig, LexicalGraphIndex
from graphrag_toolkit.storage import GraphStoreFactory
from graphrag_toolkit.storage import VectorStoreFactory
from graphrag_toolkit.storage.graph import NonRedactedGraphQueryLogFormatting
from graphrag_toolkit.indexing import sink
from graphrag_toolkit.indexing.constants import  DEFAULT_ENTITY_CLASSIFICATIONS
from graphrag_toolkit.indexing.extract import BatchConfig
from graphrag_toolkit.indexing.build import Checkpoint
from graphrag_toolkit.indexing.load import FileBasedDocs

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core import Document

import nest_asyncio
nest_asyncio.apply()

# FUNCTION DEFINITIONS
def get_files(mypath):
    # returns a list of paths of files found within the specified directory
    #  - file paths are absolute
    #  - only returns that match extension "*.pdf"
    
    pdf_dir_path = Path(mypath)
    file_paths = [
        file_path for file_path in pdf_dir_path.iterdir()
        if file_path.is_file() and file_path.match("*.pdf")
    ]
    
    return file_paths

def get_docs_from_pdf(mypath):
    # returns a list of LlamaIndex Document objects for the specified file
    #  - one Document represents a page in the PDF file
    #  - uses pypdf.PdfReader to read the file
    
    docs = []
    pdf_dir_path = Path(mypath)
    reader = PdfReader(pdf_dir_path)
    for page_num, page_content in enumerate(reader.pages):
        doc = Document(text=page_content.extract_text(), metadata={'filename': pdf_dir_path.name, 'page_num': page_num})
        docs.append(doc)
        
    return docs

def execute(source_folder,checkpoint_name,graph_endpoint,vector_endpoint,batch_config,logging="WARNING"):
    # SOURCE/CHECKPOINT DEFINITIONS
    SOURCE_FOLDER_NAME = source_folder
    CHECKPOINT = checkpoint_name

    # GRAPH/VECTOR STORE ENDPOINT DEFINITIONS
    GRAPH_ENDPOINT = graph_endpoint
    VECTOR_ENDPOINT = vector_endpoint

    # TOOLKIT-SPECIFIC GRAPH/VECTOR STORE ENDPOINT DEFINITIONS
    # This script assume Amazon Neptune Database is used as the graph store, and Amazon OpenSearch Serverless Service is used as the vector store
    GRAPH_STORE = f"neptune-db://{GRAPH_ENDPOINT}"
    VECTOR_STORE = f"aoss://{VECTOR_ENDPOINT}"

    # BATCH CONFIGURATION
    BATCH_EXTRACTION_REGION=batch_config['region'] #must be in the same region as your S3 bucket
    BATCH_EXTRACTION_BUCKET_NAME=batch_config['bucket'] 
    BATCH_EXTRACTION_KEY_PREFIX=batch_config['prefix']
    BATCH_EXTRACTION_ROLE_ARN=batch_config['role_arn']

    # TOOLKIT LOGGING CONFIGURATION
    set_logging_config(logging_level='INFO', included_modules=['graphrag_toolkit.indexing.extract', 'graphrag_toolkit.indexing.build'])

    # START OF PROGRAMME 
    print(f"Creating GraphStoreFactory: {GRAPH_STORE} ...")
    graph_store = GraphStoreFactory.for_graph_store(GRAPH_STORE,
                    log_formatting = NonRedactedGraphQueryLogFormatting())
    print("GraphStoreFactory created.")

    print(f"Creating VectorStoreFactory: {VECTOR_STORE} ...")
    vector_store = VectorStoreFactory.for_vector_store(VECTOR_STORE)
    print("VectorStoreFactory created.")

    print("Setting chunking strategy ...")
    splitter = SentenceSplitter(
        chunk_size=256,
        chunk_overlap=20
    )
    print("Chunking strategy set.")

    print("Setting batch configuration ...")
    GraphRAGConfig.extraction_batch_size = batch_config['extraction_batch_size'] #edit the batch size to pass more chunks to the LLM
    GraphRAGConfig.extraction_num_workers = 4
    GraphRAGConfig.include_domain_labels = batch_config['include_domain_labels'] #setting this to True creates domain-specific labels (fails if the PDF extraction is not good quality)
    GraphRAGConfig.build_num_workers = 4
    GraphRAGConfig.extraction_num_workers = 4
    print("Batch configuration set.")

    print("Creating BatchConfig ...")
    batch_config = BatchConfig(
        region=BATCH_EXTRACTION_REGION,
        bucket_name=BATCH_EXTRACTION_BUCKET_NAME,
        key_prefix=BATCH_EXTRACTION_KEY_PREFIX,
        role_arn=BATCH_EXTRACTION_ROLE_ARN
    )
    print("BatchConfig created.")

    print("Creating IndexingConfig ...")
    indexing_config = IndexingConfig(
        batch_config=batch_config,
        chunking=[splitter],
        extraction=ExtractionConfig(
            enable_proposition_extraction=True,
            preferred_entity_classifications=DEFAULT_ENTITY_CLASSIFICATIONS
        )
    )
    print("IndexingConfig created.")

    print("Creating LexicalGraphIndex ...")
    graph_index = LexicalGraphIndex(
        graph_store, 
        vector_store,
        indexing_config=indexing_config
    )
    print("LexicalGraphIndex created.")

    print(f"Getting file list from source folder '{SOURCE_FOLDER_NAME}' ...")
    files = get_files(SOURCE_FOLDER_NAME)
    print(f"{len(files)} file(s) found in source folder")  

    total_start = time.perf_counter()
    failed_files = []
    i = 0

    for file in files:
        success = True
        i = i + 1
        start_file_time = time.perf_counter()
        print(f"Processing file '{file}' ...")
        try:
            start_node_extraction_time = time.perf_counter()
            docs = get_docs_from_pdf(file)
            end_node_extraction_time = time.perf_counter()
            total_node_extraction_time = time.gmtime(float(end_node_extraction_time - start_node_extraction_time))
            print(f"PDF document read. {len(docs)} LlamaIndex nodes identified. Total time taken: {time.strftime('%H hours, %M minutes and %S seconds',total_node_extraction_time)}")
                    
            #------ EXTRACT STAGE ------
            
            start_graph_extraction_time = time.perf_counter()
            print(f"Starting extraction across {len(docs)} LlamaIndex nodes ...")
            
            extracted_docs = FileBasedDocs(
                docs_directory='extracted'
            )

            extraction_checkpoint_id = f"{CHECKPOINT}-{str(i)}-EXTRACTION"
            print(f"Creating checkpoint: {extraction_checkpoint_id} ...")
            extraction_checkpoint = Checkpoint(extraction_checkpoint_id, enabled=True)
            print("Checkpoint created.")
            
            print("Starting graph index extraction process ...")
            graph_index.extract(docs, handler=extracted_docs, checkpoint=extraction_checkpoint, show_progress=True)
            print("Finished graph index extraction process.")
            
            collection_id = extracted_docs.collection_id
            
            end_graph_extraction_time = time.perf_counter()
            total_graph_extraction_time = time.gmtime(float(end_graph_extraction_time - start_graph_extraction_time))
            print(f"Finished extraction process. Collection id = {collection_id}. Total time taken: {time.strftime('%H hours, %M minutes and %S seconds',total_graph_extraction_time)}")
            
            #------ BUILD STAGE ------
            
            start_graph_build_time = time.perf_counter()
            print(f"Starting build process using collection '{collection_id}' ...")
            processable_docs = FileBasedDocs(
                docs_directory='extracted',
                collection_id=collection_id
            )
            
            build_checkpoint_id = f"{CHECKPOINT}-{str(i)}-BUILD"
            print(f"Creating checkpoint: {build_checkpoint_id} ...")
            build_checkpoint = Checkpoint(build_checkpoint_id, enabled=True)
            print("Checkpoint created.")
            
            print("Starting graph index build process ...")
            graph_index.build(processable_docs, checkpoint=build_checkpoint, show_progress=True)
            print("Finished graph index build process.")
            
            end_graph_build_time = time.perf_counter()
            total_graph_build_time = time.gmtime(float(end_graph_build_time - start_graph_build_time))
            print(f"Finished building process. Time taken {time.strftime('%H hours, %M minutes and %S seconds',total_graph_build_time)}")
            
        except Exception as ex:
            print("=======================================================================\n")
            print(f"Exception raised on file '{file}': {ex}\n")
            print("=======================================================================\n")
            failed_files.append({
                "file": file,
                "reason": ex
            })
            success = False
            
        finally:
            end_file_time = time.perf_counter()
            total_file_time = time.gmtime(float(end_file_time - start_file_time))
            print(f"Finished processing file '{file}'. Status: {'Success' if success else 'Failed'}. Time taken {time.strftime('%H hours, %M minutes and %S seconds',total_file_time)}")
            
    total_end = time.perf_counter()
    total_time_obj = time.gmtime(float(total_end - total_start))

    print(f"\nProcess completed for {len(files) - len(failed_files)} file(s). Total time taken: {time.strftime('%H hours, %M minutes and %S seconds',total_time_obj)}")
    print(f"\nFiles that failed processing ({len(failed_files)}): {f' ***** File {f.file}. Cause: {f.reason}' for f in failed_files}")


def displayCLIExample():
    print("\nThe following is an example of how to call this program from the command line:\n")
    print("python batch_graphrag_terminal_script.py")
    print("\t--s /home/ec2-user/SageMaker/in_progress")
    print("\t--c my_checkpoint_name")
    print("\t--g myneptunecluster.cluster-abc1de2fghij.us-west-2.neptune.amazonaws.com")
    print("\t--v https://1abcdefgh23i45jk6lmn.us-west-2.aoss.amazonaws.com")
    print("\t--b '{\"region\":\"us-west-2\",\"bucket\":\"my_graphrag_bucket-us-west-2\",\"prefix\":\"kg-pdf-neptune\",\"role_arn\":\"arn:aws:iam::123456789012:role/MyGraphRAGBatchInferenceRole\"}'")
    print("\t--l WARNING|DEBUG|INFO")
    print("\n\n")

args = sys.argv[1:]

if args:
    if len(args) == 1 and args[0].lower() in ['--h','h','help','-h','--help']:
        displayCLIExample()
    else:
        short_options = "s:c:g:v:b:l"
        long_options = ["src=", "cp=", "ge=", "ve=", "bc=", "l="]

        try:

            options, values = getopt.getopt(args, short_options, long_options)

            source_folder = None
            checkpoint_name = None
            graph_endpoint = None
            vector_endpoint = False
            batch_config = None
            logging = "WARNING"

            for o, v in options:
                if o in ("--s", "--src"):
                    source_folder = v
                if o in ("--c", "--cp"):
                    checkpoint_name = v
                if o in ("--g", "--ge"):
                    graph_endpoint = v
                if o in ("--v", "--ve"):
                    vector_endpoint = v
                if o in ("--b", "--bc"):
                    batch_config = json.loads(v)
                if o in ("--l"):
                    logging = v

            if source_folder is None:
                print("Please specify a directory to scan. Use -s <directory>.")
                sys.exit(1)
            elif checkpoint_name is None:
                print("Please specify a checkpoint name.")
                sys.exit(1)
            elif graph_endpoint is None or vector_endpoint is None:
                print("Please specify both the graph and vector endpoints.")
                sys.exit(1)
            elif batch_config is None:
                print("Please specify a batch configuration as JSON.")
                sys.exit(1)
            
            if not batch_config is None:
                region = ""
                bucket = ""
                prefix = ""
                role_arn = ""
                extraction_batch_size = 5000
                include_domain_labels = False
                
                try:
                    region = batch_config['region']
                except:
                    print("Please specify a valid AWS region in the batch configuration")
                    sys.exit(1)
                try:
                    bucket = batch_config['bucket']
                except:
                    print("Please specify a valid S3 bucket name in the batch configuration")
                    sys.exit(1)
                try:
                    prefix = batch_config['prefix']
                except:
                    print("Please specify a valid S3 bucket prefix in the batch configuration")
                    sys.exit(1)
                try:
                    role_arn = batch_config['role_arn']
                except:
                    print("Please specify a valid IAM role arn in the batch configuration")
                    sys.exit(1)
                try:
                    extraction_batch_size = int(batch_config['extraction_batch_size'])
                except:
                    print("Please specify a valid extraction batch size. Must be numeric.")
                    sys.exit(1)
                try:
                    bool_map = {"true":True, "false":False}
                    include_domain_labels = bool_map.get(batch_config['include_domain_labels'].strip().lower, False)
                except:
                    print("Please specify a valid argument for including domain labels. Must be boolean.")
                    sys.exit(1)

                batch_config = {
                    "region": region,
                    "bucket": bucket,
                    "prefix": prefix,
                    "role_arn": role_arn,
                    "extraction_batch_size": extraction_batch_size,
                    "include_domain_labels": include_domain_labels
                }
            
            execute(source_folder,checkpoint_name,graph_endpoint,vector_endpoint,batch_config,logging)
        except Exception as e:
            print(f"Error: {e}")
else:
    displayCLIExample()