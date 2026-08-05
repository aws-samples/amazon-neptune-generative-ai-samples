"""Integration tests for agent-memory frameworks against real infrastructure.

These tests are SKIPPED by default unless the required env vars are configured.
To run integration tests:

    export MEM0_AOSS_ENDPOINT=<your-opensearch-endpoint>
    export MEM0_NEPTUNE_ENDPOINT=<your-neptune-endpoint>
    export COGNEE_ENDPOINT=<your-neptune-analytics-endpoint>
    export GRAPHITI_NEPTUNE_ENDPOINT=<your-neptune-endpoint>
    export GRAPHITI_AOSS_ENDPOINT=<your-opensearch-endpoint>
    uv run pytest tests/test_integration.py -m integration
"""

import os
import pytest

# These markers cause the tests to be skipped unless infra is configured.
# The fixtures in conftest.py clear all env vars by default (for safety),
# so integration tests must opt out of the set_test_env fixture.


pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def set_test_env():
    """Override the default fixture - integration tests need real env vars."""
    # Do NOT clear env vars for integration tests
    yield


class TestMem0Integration:
    """Integration tests for Mem0 with real Neptune + OpenSearch."""

    @pytest.fixture(autouse=True)
    def skip_without_config(self):
        if not os.getenv("MEM0_AOSS_ENDPOINT") or not os.getenv("MEM0_NEPTUNE_ENDPOINT"):
            pytest.skip("MEM0_AOSS_ENDPOINT and MEM0_NEPTUNE_ENDPOINT required")

    def test_mem0_demo_initializes(self):
        """Mem0Demo should connect to real infrastructure."""
        from frameworks.mem0_neptune import Mem0Demo
        demo = Mem0Demo("integration_test_user")
        assert demo.client is not None

    def test_mem0_add_and_search_roundtrip(self):
        """Should be able to add a memory and search for it."""
        from frameworks.mem0_neptune import Mem0Demo

        demo = Mem0Demo("integration_test_user")
        # Add a memory
        demo.client.add("I love hiking in the mountains", user_id="integration_test_user")

        # Search for it
        results = demo.client.search(
            "outdoor activities", filters={"user_id": "integration_test_user"}
        )
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_mem0_reset(self):
        """reset() should clear all memories for the user."""
        from frameworks.mem0_neptune import Mem0Demo

        demo = Mem0Demo("integration_test_reset_user")
        demo.client.add("test memory", user_id="integration_test_reset_user")
        await demo.reset()

        results = demo.client.search(
            "test memory", filters={"user_id": "integration_test_reset_user"}
        )
        assert len(results) == 0


class TestCogneeIntegration:
    """Integration tests for Cognee with real Neptune Analytics."""

    @pytest.fixture(autouse=True)
    def skip_without_config(self):
        if not os.getenv("COGNEE_ENDPOINT"):
            pytest.skip("COGNEE_ENDPOINT required")

    def test_cognee_demo_initializes(self):
        """CogneeDemo should initialize with real endpoint."""
        from frameworks.cognee_neptune import CogneeDemo
        demo = CogneeDemo("integration_test_user")
        assert demo.user_id == "integration_test_user"

    @pytest.mark.asyncio
    async def test_cognee_add_and_cognify(self):
        """Should be able to add data and run cognify."""
        from frameworks.cognee_neptune import CogneeDemo

        demo = CogneeDemo("integration_test_user")
        await demo.reset()
        await demo.add("I am planning a trip to Paris in spring")
        await demo.cognify()


class TestGraphitiIntegration:
    """Integration tests for Graphiti with real Neptune + OpenSearch."""

    @pytest.fixture(autouse=True)
    def skip_without_config(self):
        if not os.getenv("GRAPHITI_NEPTUNE_ENDPOINT") or not os.getenv("GRAPHITI_AOSS_ENDPOINT"):
            pytest.skip("GRAPHITI_NEPTUNE_ENDPOINT and GRAPHITI_AOSS_ENDPOINT required")

    def test_graphiti_demo_initializes(self):
        """GraphitiDemo should connect to real infrastructure."""
        from frameworks.graphiti_neptune import GraphitiDemo
        demo = GraphitiDemo("integration_test_group")
        assert demo.client is not None

    @pytest.mark.asyncio
    async def test_graphiti_reset_and_search(self):
        """Should be able to reset and search."""
        from frameworks.graphiti_neptune import GraphitiDemo
        from datetime import datetime
        from graphiti_core.nodes import EpisodeType

        demo = GraphitiDemo("integration_test_group")
        await demo.reset()

        await demo.client.add_episode(
            name="test_episode",
            episode_body="I prefer window seats on flights",
            source=EpisodeType.message,
            source_description="test message",
            reference_time=datetime.utcnow(),
        )

        results = await demo.client.search(
            "seat preferences", group_ids=["integration_test_group"]
        )
        assert results is not None
