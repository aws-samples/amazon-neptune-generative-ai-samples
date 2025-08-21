import boto3
from dotenv import load_dotenv
import os
from opensearchpy import RequestsHttpConnection, AWSV4SignerAuth
from mem0.memory.main import Memory

load_dotenv()

region = 'us-west-2'
service = 'aoss'
credentials = boto3.Session().get_credentials()
auth = AWSV4SignerAuth(credentials, region, service)

config = {
    "embedder": {
        "provider": "aws_bedrock",
        "config": {
            "model": "amazon.titan-embed-text-v2:0"
        }
    },
    "llm": {
        "provider": "aws_bedrock",
        "config": {
            "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            "temperature": 0.1,
            "max_tokens": 2000
        }
    },
    "vector_store": {
        "provider": "opensearch",
        "config": {
            "collection_name": "mem0",
            "host": os.getenv("MEM0_AOSS_ENDPOINT"),
            "port": 443,
            "http_auth": auth,
            "connection_class": RequestsHttpConnection,
            "pool_maxsize": 20,
            "use_ssl": True,
            "verify_certs": True,
            "embedding_model_dims": 1024,
        }
    },
    "graph_store": {
        "provider": "neptune",
        "config": {
            "endpoint": os.getenv("MEM0_NEPTUNE_ENDPOINT")
        },
    },
}

# Initialize the memory system
m = Memory.from_config(config)

messages = [
    {"role": "user", "content": "I'm planning to watch a movie tonight. Any recommendations?"},
    {"role": "assistant", "content": "How about a thriller movies? They can be quite engaging."},
    {"role": "user", "content": "I'm not a big fan of thriller movies but I love sci-fi movies."},
    {"role": "assistant", "content": "Got it! I'll avoid thriller recommendations and suggest sci-fi movies in the future."}
]

# Store inferred memories (default behavior)
result = m.add(messages, user_id='foo')