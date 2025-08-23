import os
import pathlib
from cognee import config, add, cognify, prune, search
from cognee.modules.users.models import User

from dotenv import load_dotenv

# load environment variables from file .env
load_dotenv()

class CogneeDemo():
    '''
    This is a class that provides a wrapper over Cognee to allow for
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

        # Configure Neptune Analytics as the graph & vector database provider
        # Specify Neptune Analytics as provider
        # Neptune Analytics endpoint with the format neptune-graph://<GRAPH_ID>
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
        Reset the data and system state
        '''
        await search(query, user_id)
