"""Unified memory backend interface.

Provides a common search/add API across Mem0, Cognee, and Graphiti.
The active backend is selected via the MEMORY_FRAMEWORK environment variable.
"""

import asyncio
import os
from abc import ABC, abstractmethod
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()


class MemoryBackend(ABC):
    """Common interface for memory operations across all frameworks."""

    @abstractmethod
    def search(self, query: str, user_id: str) -> list:
        """Search memories for a user."""
        ...

    @abstractmethod
    def add(self, content: str, user_id: str) -> dict:
        """Store a new memory for a user."""
        ...


class Mem0Backend(MemoryBackend):
    """Memory backend using Mem0 with Neptune Analytics + Bedrock.

    Mem0 1.x uses Neptune Analytics as both vector store and graph store,
    enabling entity-relationship graph construction alongside vector search.
    """

    def __init__(self):
        from frameworks.mem0_neptune import Mem0Demo
        self._demo = Mem0Demo("")

    def search(self, query: str, user_id: str) -> list:
        return self._demo.client.search(query, user_id=user_id)

    def add(self, content: str, user_id: str) -> dict:
        return self._demo.client.add(content, user_id=user_id)


class CogneeBackend(MemoryBackend):
    """Memory backend using Cognee with Neptune Analytics + Bedrock.

    Uses cognee.remember() and cognee.recall() directly. Cognee manages its own
    internal state (SQLite for metadata, Neptune Analytics for graph/vector).
    """

    def __init__(self):
        import pathlib
        from cognee import config

        # Set storage paths for Cognee's internal databases (SQLite, LanceDB, Kuzu).
        # Defaults to .data_storage/ and .cognee_system/ in the project directory.
        project_dir = pathlib.Path(__file__).parent.parent.resolve()
        data_dir = os.getenv("DATA_ROOT_DIRECTORY", str(project_dir / ".data_storage"))
        system_dir = os.getenv("SYSTEM_ROOT_DIRECTORY", str(project_dir / ".cognee_system"))
        config.data_root_directory(data_dir)
        config.system_root_directory(system_dir)

        # Configure Neptune Analytics and Bedrock
        cognee_endpoint = os.getenv("COGNEE_ENDPOINT")
        bedrock_model = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")

        if cognee_endpoint:
            config.set_graph_db_config({
                "graph_database_provider": "neptune_analytics",
                "graph_database_url": cognee_endpoint,
            })
            config.set_vector_db_config({
                "vector_db_provider": "neptune_analytics",
                "vector_db_url": cognee_endpoint,
            })

        config.set_llm_config({
            "llm_provider": "bedrock",
            "llm_model": bedrock_model,
        })

        # Configure embeddings to use Bedrock Titan via litellm.
        # The "bedrock/" prefix tells litellm to route to Bedrock.
        embedding_model = os.getenv("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
        config.set_embedding_config({
            "embedding_provider": "litellm",
            "embedding_model": f"bedrock/{embedding_model}",
            "embedding_dimensions": 1024,
        })

    def search(self, query: str, user_id: str) -> list:
        import asyncio
        import cognee

        async def _search():
            try:
                results = await cognee.recall(query, datasets=[user_id], only_context=True)
                return [str(r) for r in results] if results else []
            except Exception as e:
                if "RecallPreconditionError" in str(type(e).__name__) or "prerequisites not met" in str(e).lower():
                    return []
                raise

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, _search()).result()
        except RuntimeError:
            pass
        return asyncio.run(_search())

    def add(self, content: str, user_id: str) -> dict:
        import asyncio
        import cognee

        async def _add():
            await cognee.remember(content, dataset_name=user_id)
            return {"status": "added", "user_id": user_id}

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, _add()).result()
        except RuntimeError:
            pass
        return asyncio.run(_add())


class GraphitiBackend(MemoryBackend):
    """Memory backend using Graphiti with Neptune + OpenSearch + Bedrock."""

    def __init__(self):
        # Ensure boto3 can find the region — it reads AWS_DEFAULT_REGION,
        # but users typically set AWS_REGION. Bridge the gap.
        if not os.getenv("AWS_DEFAULT_REGION") and os.getenv("AWS_REGION"):
            os.environ["AWS_DEFAULT_REGION"] = os.getenv("AWS_REGION")

        from frameworks.graphiti_neptune import GraphitiDemo
        self._demo = GraphitiDemo("")

    def search(self, query: str, user_id: str) -> list:
        async def _search():
            try:
                results = await self._demo.client.search(query, group_ids=[user_id])
                return results
            except Exception as e:
                if "index_not_found" in str(e):
                    # First time use — create indexes
                    await self._demo.client.build_indices_and_constraints()
                    return []
                raise

        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _search()).result()
        return asyncio.run(_search())

    def add(self, content: str, user_id: str) -> dict:
        from graphiti_core.nodes import EpisodeType

        async def _add():
            await self._demo.client.add_episode(
                name=f"memory_{datetime.utcnow().isoformat()}",
                episode_body=content,
                source=EpisodeType.message,
                source_description="user_message",
                reference_time=datetime.utcnow(),
                group_id=user_id,
            )
            return {"status": "added", "user_id": user_id}

        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _add()).result()
        return asyncio.run(_add())


BACKENDS = {
    "mem0": Mem0Backend,
    "cognee": CogneeBackend,
    "graphiti": GraphitiBackend,
}


def get_memory_backend() -> MemoryBackend:
    """Create the configured memory backend.

    Set MEMORY_FRAMEWORK env var to one of: mem0, cognee, graphiti.
    Defaults to mem0.
    """
    framework = os.getenv("MEMORY_FRAMEWORK", "mem0").lower()
    if framework not in BACKENDS:
        raise ValueError(
            f"Unknown MEMORY_FRAMEWORK '{framework}'. "
            f"Valid options: {', '.join(BACKENDS.keys())}"
        )
    return BACKENDS[framework]()
