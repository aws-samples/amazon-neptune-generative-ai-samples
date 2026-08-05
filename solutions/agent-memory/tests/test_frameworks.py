"""Unit tests for framework classes - validates API compatibility after dependency upgrades."""

import inspect
import pytest
from unittest.mock import patch, MagicMock


class TestMem0DemoAPI:
    """Tests for frameworks/mem0_neptune.py API surface."""

    def test_mem0_demo_class_exists(self):
        """Mem0Demo should be importable from frameworks."""
        from frameworks.mem0_neptune import Mem0Demo
        assert Mem0Demo is not None

    def test_mem0_demo_init_signature(self):
        """Mem0Demo.__init__ should accept user_id parameter."""
        from frameworks.mem0_neptune import Mem0Demo
        sig = inspect.signature(Mem0Demo.__init__)
        params = list(sig.parameters.keys())
        assert "user_id" in params

    @patch("frameworks.mem0_neptune.Memory")
    def test_mem0_demo_creates_client(self, mock_memory):
        """Mem0Demo should create a Memory client via from_config."""
        mock_memory.from_config.return_value = MagicMock()

        from frameworks.mem0_neptune import Mem0Demo
        import importlib
        import frameworks.mem0_neptune as mod

        # Patch at module level
        mod.Memory = mock_memory
        demo = Mem0Demo("test_user")

        mock_memory.from_config.assert_called_once()
        assert demo.client is not None
        assert demo.user_id == "test_user"

    @patch("frameworks.mem0_neptune.Memory")
    def test_mem0_demo_config_uses_env_model_id(self, mock_memory, monkeypatch):
        """Mem0Demo config should use BEDROCK_MODEL_ID env var."""
        monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-5")
        mock_memory.from_config.return_value = MagicMock()

        import importlib
        import frameworks.mem0_neptune as mod
        importlib.reload(mod)
        mod.Memory = mock_memory

        mod.Mem0Demo("test_user")

        config_arg = mock_memory.from_config.call_args[0][0]
        assert config_arg["llm"]["config"]["model"] == "us.anthropic.claude-sonnet-5"

    def test_mem0_demo_has_reset_method(self):
        """Mem0Demo should have an async reset method."""
        from frameworks.mem0_neptune import Mem0Demo
        assert hasattr(Mem0Demo, "reset")
        assert inspect.iscoroutinefunction(Mem0Demo.reset)


class TestMem0SearchAPI:
    """Tests that validate the mem0 Memory.search() API contract."""

    def test_memory_search_accepts_user_id_param(self):
        """Memory.search must accept user_id as a direct parameter (1.x API)."""
        from mem0.memory.main import Memory
        sig = inspect.signature(Memory.search)
        params = list(sig.parameters.keys())
        assert "user_id" in params, (
            "Memory.search no longer accepts 'user_id' directly"
        )

    def test_memory_search_accepts_filters_param(self):
        """Memory.search should also accept a filters parameter."""
        from mem0.memory.main import Memory
        sig = inspect.signature(Memory.search)
        params = list(sig.parameters.keys())
        assert "filters" in params, (
            "Memory.search no longer accepts 'filters'"
        )

    def test_memory_add_accepts_user_id(self):
        """Memory.add should still accept user_id directly."""
        from mem0.memory.main import Memory
        sig = inspect.signature(Memory.add)
        params = list(sig.parameters.keys())
        assert "user_id" in params

    def test_memory_delete_all_accepts_user_id(self):
        """Memory.delete_all should still accept user_id directly."""
        from mem0.memory.main import Memory
        sig = inspect.signature(Memory.delete_all)
        params = list(sig.parameters.keys())
        assert "user_id" in params


class TestCogneeDemoAPI:
    """Tests for frameworks/cognee_neptune.py API surface."""

    def test_cognee_demo_class_exists(self):
        """CogneeDemo should be importable from frameworks."""
        from frameworks.cognee_neptune import CogneeDemo
        assert CogneeDemo is not None

    def test_cognee_demo_init_signature(self):
        """CogneeDemo.__init__ should accept user_id."""
        from frameworks.cognee_neptune import CogneeDemo
        sig = inspect.signature(CogneeDemo.__init__)
        params = list(sig.parameters.keys())
        assert "user_id" in params

    def test_cognee_demo_has_async_methods(self):
        """CogneeDemo should have add, cognify, reset, search as async methods."""
        from frameworks.cognee_neptune import CogneeDemo
        for method_name in ("add", "cognify", "reset", "search"):
            method = getattr(CogneeDemo, method_name, None)
            assert method is not None, f"CogneeDemo missing {method_name}"
            assert inspect.iscoroutinefunction(method), (
                f"CogneeDemo.{method_name} should be async"
            )

    def test_cognee_demo_init_without_endpoint(self, monkeypatch):
        """CogneeDemo should initialize even without COGNEE_ENDPOINT (local-only mode)."""
        monkeypatch.delenv("COGNEE_ENDPOINT", raising=False)
        from frameworks.cognee_neptune import CogneeDemo
        demo = CogneeDemo("test_user")
        assert demo.user_id == "test_user"


class TestGraphitiDemoAPI:
    """Tests for frameworks/graphiti_neptune.py API surface."""

    def test_graphiti_demo_class_exists(self):
        """GraphitiDemo should be importable from frameworks."""
        from frameworks.graphiti_neptune import GraphitiDemo
        assert GraphitiDemo is not None

    def test_graphiti_demo_init_signature(self):
        """GraphitiDemo.__init__ should accept group_id."""
        from frameworks.graphiti_neptune import GraphitiDemo
        sig = inspect.signature(GraphitiDemo.__init__)
        params = list(sig.parameters.keys())
        assert "group_id" in params

    def test_graphiti_demo_requires_endpoint(self, monkeypatch):
        """GraphitiDemo should raise ValueError if GRAPHITI_NEPTUNE_ENDPOINT not set."""
        monkeypatch.delenv("GRAPHITI_NEPTUNE_ENDPOINT", raising=False)
        monkeypatch.delenv("GRAPHITI_AOSS_ENDPOINT", raising=False)

        from frameworks.graphiti_neptune import GraphitiDemo
        with pytest.raises(ValueError, match="GRAPHITI_NEPTUNE_ENDPOINT must be set"):
            GraphitiDemo("test_group")

    def test_graphiti_demo_requires_aoss_endpoint(self, monkeypatch):
        """GraphitiDemo should raise ValueError if GRAPHITI_AOSS_ENDPOINT not set."""
        monkeypatch.setenv("GRAPHITI_NEPTUNE_ENDPOINT", "neptune-db://fake")
        monkeypatch.delenv("GRAPHITI_AOSS_ENDPOINT", raising=False)

        from frameworks.graphiti_neptune import GraphitiDemo
        with pytest.raises(ValueError, match="GRAPHITI_AOSS_ENDPOINT must be set"):
            GraphitiDemo("test_group")

    def test_graphiti_demo_has_reset_method(self):
        """GraphitiDemo should have an async reset method."""
        from frameworks.graphiti_neptune import GraphitiDemo
        assert hasattr(GraphitiDemo, "reset")
        assert inspect.iscoroutinefunction(GraphitiDemo.reset)


class TestStrandsAgentAPI:
    """Tests that validate strands-agents API compatibility."""

    def test_agent_class_importable(self):
        """Core Agent class should be importable."""
        from strands import Agent, tool
        assert Agent is not None
        assert tool is not None

    def test_bedrock_model_accepts_model_id(self):
        """BedrockModel should accept model_id as a keyword argument."""
        from strands.models import BedrockModel
        model = BedrockModel(
            model_id="us.anthropic.claude-sonnet-4-6",
            max_tokens=1000,
        )
        assert model.config["model_id"] == "us.anthropic.claude-sonnet-4-6"

    def test_bedrock_model_accepts_additional_request_fields(self):
        """BedrockModel should accept additional_request_fields."""
        from strands.models import BedrockModel
        model = BedrockModel(
            model_id="us.anthropic.claude-sonnet-4-6",
            max_tokens=1000,
            additional_request_fields={"thinking": {"type": "disabled"}},
        )
        assert model.config["additional_request_fields"] == {"thinking": {"type": "disabled"}}

    def test_agent_has_state_and_messages(self):
        """Agent instances should have .state and .messages attributes."""
        from strands import Agent
        agent = Agent(tools=[])
        assert hasattr(agent, "state")
        assert hasattr(agent, "messages")

    def test_agent_state_get_set(self):
        """Agent.state should support get/set operations."""
        from strands import Agent
        agent = Agent(tools=[])
        agent.state.set("user_id", "Alice")
        assert agent.state.get("user_id") == "Alice"

    def test_tool_decorator(self):
        """@tool decorator should produce a callable tool."""
        from strands import tool

        @tool
        def my_test_tool(query: str):
            """A test tool."""
            return f"result: {query}"

        assert callable(my_test_tool)
