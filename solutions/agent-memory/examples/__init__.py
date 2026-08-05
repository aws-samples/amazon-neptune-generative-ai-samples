"""Example agent configurations for the memory-enabled agent platform.

Each example module defines:
    AGENT_NAME (str): Display name for the agent
    AGENT_DESCRIPTION (str): One-line description
    SYSTEM_PROMPT (str): The agent's system prompt
    EXTRA_TOOLS (list): Additional tools beyond search_memory and add_memory
    USERS (list[str]): Preset user IDs for the Streamlit demo

To create a custom agent, copy any example and modify the constants.
"""

import importlib
import os

AVAILABLE_AGENTS = {
    "default": "examples.default",
    "travel_assistant": "examples.travel_assistant",
}


def load_agent_config(name: str = None):
    """Load an agent configuration by name.

    Args:
        name: Agent config name (key from AVAILABLE_AGENTS) or a dotted module path.
              Defaults to AGENT_CONFIG env var, or "default" if not set.

    Returns:
        The imported module containing AGENT_NAME, SYSTEM_PROMPT, EXTRA_TOOLS, USERS.
    """
    name = name or os.getenv("AGENT_CONFIG", "default")

    if name in AVAILABLE_AGENTS:
        module_path = AVAILABLE_AGENTS[name]
    else:
        module_path = name

    return importlib.import_module(module_path)
