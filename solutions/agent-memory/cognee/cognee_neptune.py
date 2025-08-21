import os
import pathlib
from cognee import config, add, cognify, search, SearchType, prune, visualize_graph
from dotenv import load_dotenv
import asyncio

# load environment variables from file .env
load_dotenv()

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
config.set_graph_db_config(
    {
        "graph_database_provider": "neptune_analytics",  # Specify Neptune Analytics as provider
        "graph_database_url": os.getenv('COGNEE_ENDPOINT'),  # Neptune Analytics endpoint with the format neptune-graph://<GRAPH_ID>
    }
)
config.set_vector_db_config(
    {
        "vector_db_provider": "neptune_analytics",  # Specify Neptune Analytics as provider
        "vector_db_url": os.getenv('COGNEE_ENDPOINT'),  # Neptune Analytics endpoint with the format neptune-graph://<GRAPH_ID>
    }
)

async def main():
    # Add sample text to the dataset
    sample_text_1 = """Neptune Analytics is a memory-optimized graph database engine for analytics. With Neptune
        Analytics, you can get insights and find trends by processing large amounts of graph data in seconds. To analyze
        graph data quickly and easily, Neptune Analytics stores large graph datasets in memory. It supports a library of
        optimized graph analytic algorithms, low-latency graph queries, and vector search capabilities within graph
        traversals.
        """

    sample_text_2 = """Neptune Analytics is an ideal choice for investigatory, exploratory, or data-science workloads
        that require fast iteration for data, analytical and algorithmic processing, or vector search on graph data. It
        complements Amazon Neptune Database, a popular managed graph database. To perform intensive analysis, you can load
        the data from a Neptune Database graph or snapshot into Neptune Analytics. You can also load graph data that's
        stored in Amazon S3.
        """

    # Create a dataset
    dataset_name = "neptune_descriptions"

    # Add the text data to Cognee.
    await add([sample_text_1, sample_text_2], dataset_name)

    # Cognify the text data.
    await cognify([dataset_name])

asyncio.run(main())