"""Shared test fixtures for agent-memory tests."""

import os
import pytest


@pytest.fixture(autouse=True)
def set_test_env(monkeypatch):
    """Ensure tests don't accidentally use real infrastructure."""
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
    monkeypatch.delenv("MEM0_AOSS_ENDPOINT", raising=False)
    monkeypatch.delenv("MEM0_NEPTUNE_ENDPOINT", raising=False)
    monkeypatch.delenv("COGNEE_ENDPOINT", raising=False)
    monkeypatch.delenv("GRAPHITI_NEPTUNE_ENDPOINT", raising=False)
    monkeypatch.delenv("GRAPHITI_AOSS_ENDPOINT", raising=False)


def has_mem0_config():
    """Check if Mem0 infrastructure is configured."""
    return bool(os.getenv("MEM0_AOSS_ENDPOINT")) and bool(os.getenv("MEM0_NEPTUNE_ENDPOINT"))


def has_cognee_config():
    """Check if Cognee infrastructure is configured."""
    return bool(os.getenv("COGNEE_ENDPOINT"))


def has_graphiti_config():
    """Check if Graphiti infrastructure is configured."""
    return bool(os.getenv("GRAPHITI_NEPTUNE_ENDPOINT")) and bool(os.getenv("GRAPHITI_AOSS_ENDPOINT"))


requires_mem0 = pytest.mark.skipif(
    not has_mem0_config(),
    reason="MEM0_AOSS_ENDPOINT and MEM0_NEPTUNE_ENDPOINT not configured"
)

requires_cognee = pytest.mark.skipif(
    not has_cognee_config(),
    reason="COGNEE_ENDPOINT not configured"
)

requires_graphiti = pytest.mark.skipif(
    not has_graphiti_config(),
    reason="GRAPHITI_NEPTUNE_ENDPOINT and GRAPHITI_AOSS_ENDPOINT not configured"
)
