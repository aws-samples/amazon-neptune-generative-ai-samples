import os
import pathlib
from cognee import config, add, cognify, prune, search

from dotenv import load_dotenv

# load environment variables from file .env
load_dotenv()

BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")


class CogneeDemo():
    '''
    Wrapper over Cognee for graph-native memory using Amazon Neptune Analytics
    with Amazon Bedrock as the LLM provider (native support in Cognee 1.4+).

    Required environment variables:
        COGNEE_ENDPOINT - Neptune Analytics endpoint (neptune-graph://<graph-id>)
        AWS_REGION - AWS region for Bedrock calls
        BEDROCK_MODEL_ID - Bedrock model ID (optional, defaults to Claude Sonnet 4)

    Authentication uses the standard AWS credential chain:
        - AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (+ AWS_SESSION_TOKEN for temp creds)
        - AWS_PROFILE_NAME
        - IAM instance role / ECS task role / EKS IRSA (ambient)
    '''
    def __init__(self, user_id):
        current_directory = os.getcwd()

        data_directory_path = str(
            pathlib.Path(
                os.path.join(pathlib.Path(current_directory), ".data_storage")
            ).resolve()
        )
        # Set up the data directory. Cognee will store files here.
        config.data_root_directory(data_directory_path)

        cognee_directory_path = str(
            pathlib.Path(
                os.path.join(pathlib.Path(current_directory), ".cognee_system")
            ).resolve()
        )
        # Set up the Cognee system directory. Cognee will store system files and databases here.
        config.system_root_directory(cognee_directory_path)

        # Configure Neptune Analytics as the graph & vector database provider.
        # Neptune Analytics serves as both graph and vector store in a single resource.
        # Endpoint format: neptune-graph://<GRAPH_ID>
        config.set_graph_db_config(
            {
                "graph_database_provider": "neptune_analytics",
                "graph_database_url": os.getenv("COGNEE_ENDPOINT"),
            }
        )
        config.set_vector_db_config(
            {
                "vector_db_provider": "neptune_analytics",
                "vector_db_url": os.getenv("COGNEE_ENDPOINT"),
            }
        )

        # Configure Amazon Bedrock as the LLM provider (native support).
        # Uses the AWS credential chain - no API key required.
        # AWS_REGION must be set in .env or environment.
        config.set_llm_config(
            {
                "llm_provider": "bedrock",
                "llm_model": BEDROCK_MODEL_ID,
            }
        )

        self.user_id = user_id

    async def add(self, messages):
        '''
        Add a message to the knowledge graph
        '''
        await add(messages, self.user_id)

    async def cognify(self):
        '''
        Provides a wrapper of the cognify call
        '''
        await cognify(self.user_id)

    async def reset(self):
        '''
        Reset the data and system state
        '''
        await prune.prune_data()
        await prune.prune_system()

    async def search(self, query, user_id):
        '''
        Search the knowledge graph
        '''
        return await search(query, user_id)
