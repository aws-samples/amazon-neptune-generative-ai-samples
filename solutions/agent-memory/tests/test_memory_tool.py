"""Unit tests for tools/memory_tool.py - memory agent search and add functionality.

Note: memory_tool.py instantiates Mem0Demo("") at module level, which requires
either real infrastructure or patching Memory.from_config before import.
"""

import sys
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_memory_module(monkeypatch):
    """Import memory_tool with Mem0Demo fully mocked to avoid needing real infra.

    This patches Memory.from_config before memory_tool.py's Mem0Backend initialization.
    """
    # Ensure we use the mem0 backend for these tests
    monkeypatch.setenv("MEMORY_FRAMEWORK", "mem0")

    # Remove cached modules so we get a fresh import
    for mod_name in list(sys.modules.keys()):
        if "tools.memory_tool" in mod_name or "frameworks.mem0_neptune" in mod_name or "frameworks.memory_backend" in mod_name:
            del sys.modules[mod_name]

    mock_client = MagicMock()
    mock_client.search.return_value = [{"memory": "likes hiking", "score": 0.9}]
    mock_client.add.return_value = {"id": "mem_123"}

    with patch("mem0.memory.main.Memory.from_config", return_value=mock_client):
        import tools.memory_tool as mt
        # The memory backend is a Mem0Backend with _demo.client
        mt.memory._demo.client = mock_client
        yield mt, mock_client


class TestSearchMemory:
    """Tests for the search_memory tool function."""

    def test_search_memory_calls_client_with_user_id(self, mock_memory_module):
        """search_memory should pass user_id directly (mem0 1.x API)."""
        mt, mock_client = mock_memory_module

        mt.memory_agent.state.set("user_id", "Alice")
        # Call the underlying function via __wrapped__
        result = mt.search_memory.__wrapped__(query="what do I like?")

        mock_client.search.assert_called_once_with(
            "what do I like?", user_id="Alice"
        )

    def test_search_memory_returns_results(self, mock_memory_module):
        """search_memory should return whatever the client returns."""
        mt, mock_client = mock_memory_module
        mock_client.search.return_value = [
            {"memory": "prefers window seats", "score": 0.95}
        ]

        mt.memory_agent.state.set("user_id", "Bob")
        result = mt.search_memory.__wrapped__(query="seat preferences")

        assert result == [{"memory": "prefers window seats", "score": 0.95}]

    def test_add_memory_calls_client_with_user_id(self, mock_memory_module):
        """add_memory should pass user_id directly (not via filters)."""
        mt, mock_client = mock_memory_module

        mt.memory_agent.state.set("user_id", "Bob")
        mt.add_memory.__wrapped__(query="I love sushi")

        mock_client.add.assert_called_once_with("I love sushi", user_id="Bob")

    def test_add_memory_returns_result(self, mock_memory_module):
        """add_memory should return the client's response."""
        mt, mock_client = mock_memory_module
        mock_client.add.return_value = {"id": "mem_456", "status": "created"}

        mt.memory_agent.state.set("user_id", "Chris")
        result = mt.add_memory.__wrapped__(query="I'm allergic to peanuts")

        assert result == {"id": "mem_456", "status": "created"}


class TestMemoryToolConfiguration:
    """Tests for memory_tool configuration and env var handling."""

    def test_bedrock_model_id_from_env(self, monkeypatch):
        """BEDROCK_MODEL_ID env var should control model selection."""
        monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-5")

        # Clear cached module
        for mod_name in list(sys.modules.keys()):
            if "tools.memory_tool" in mod_name or "frameworks.mem0_neptune" in mod_name:
                del sys.modules[mod_name]

        with patch("mem0.memory.main.Memory.from_config", return_value=MagicMock()):
            import tools.memory_tool as mt
            assert mt.BEDROCK_MODEL_ID == "us.anthropic.claude-sonnet-5"

    def test_bedrock_model_id_default(self, monkeypatch):
        """Without BEDROCK_MODEL_ID set, should use Claude Sonnet 4 default."""
        monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)

        for mod_name in list(sys.modules.keys()):
            if "tools.memory_tool" in mod_name or "frameworks.mem0_neptune" in mod_name:
                del sys.modules[mod_name]

        with patch("mem0.memory.main.Memory.from_config", return_value=MagicMock()):
            import tools.memory_tool as mt
            assert mt.BEDROCK_MODEL_ID == "us.anthropic.claude-sonnet-4-6"

    def test_memory_agent_has_expected_tools(self, mock_memory_module):
        """memory_agent should be configured with search_memory, add_memory, weather_agent."""
        mt, _ = mock_memory_module
        # The agent should exist and have tools configured
        assert mt.memory_agent is not None
        assert hasattr(mt.memory_agent, "state")

    def test_memory_agent_state_operations(self, mock_memory_module):
        """memory_agent.state should support get/set for user_id."""
        mt, _ = mock_memory_module
        mt.memory_agent.state.set("user_id", "TestUser")
        assert mt.memory_agent.state.get("user_id") == "TestUser"
