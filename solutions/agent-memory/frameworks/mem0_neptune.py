"""Mem0 integration with Amazon Neptune Analytics and Amazon Bedrock.

Mem0 1.x supports both vector_store and graph_store with Neptune Analytics.
Neptune Analytics serves as both the vector store (embeddings) and graph store
(entity relationships) in a single resource.

Required environment variables:
    MEM0_NEPTUNE_ENDPOINT - Neptune Analytics endpoint (neptune-graph://<graph-id>)
    BEDROCK_MODEL_ID - Bedrock model for LLM (optional, defaults to Claude Sonnet 4)

Authentication uses the standard AWS credential chain.
"""

import os
from dotenv import load_dotenv
from mem0.memory.main import Memory

load_dotenv()

BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")


class Mem0Demo():
    def __init__(self, user_id: str):
        neptune_endpoint = os.getenv("MEM0_NEPTUNE_ENDPOINT", "")

        config = {
            "llm": {
                "provider": "aws_bedrock",
                "config": {
                    "model": BEDROCK_MODEL_ID,
                    "temperature": 0.1,
                    "max_tokens": 2000
                }
            },
            "embedder": {
                "provider": "aws_bedrock",
                "config": {
                    "model": "amazon.titan-embed-text-v2:0"
                }
            },
            "vector_store": {
                "provider": "neptune",
                "config": {
                    "collection_name": "mem0",
                    "endpoint": neptune_endpoint,
                }
            },
            "graph_store": {
                "provider": "neptune",
                "config": {
                    "endpoint": neptune_endpoint,
                }
            },
        }

        self.user_id = user_id
        self.client = Memory.from_config(config)

    async def reset(self):
        self.client.delete_all(self.user_id)
