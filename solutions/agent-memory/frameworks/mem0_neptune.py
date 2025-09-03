import boto3
from dotenv import load_dotenv
import os
from opensearchpy import RequestsHttpConnection, AWSV4SignerAuth
from mem0.memory.main import Memory

load_dotenv()


class Mem0Demo():
    def __init__(self, user_id: str):
        region = boto3.Session().region_name
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
        self.user_id = user_id
        # Initialize the memory system
        self.client = Memory.from_config(config)

    async def reset(self):
        self.client.delete_all(self.user_id)

