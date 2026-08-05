"""Core memory agent — a generic memory-enabled agent with configurable persona and backend.

Configuration:
    AGENT_CONFIG - Which agent persona to use (default: "default")
    MEMORY_FRAMEWORK - Which memory backend to use: mem0, cognee, graphiti (default: "mem0")
    BEDROCK_MODEL_ID - Bedrock model for the agent LLM
"""

import os
from dotenv import load_dotenv
from strands.models import BedrockModel
from strands import tool, Agent
from frameworks.memory_backend import get_memory_backend
from examples import load_agent_config

load_dotenv()

# Load agent configuration (persona, system prompt, extra tools)
agent_config = load_agent_config()

BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")

model = BedrockModel(
    model_id=BEDROCK_MODEL_ID,
    max_tokens=64000,
    additional_request_fields={
        "thinking": {
            "type": "disabled",
        }
    },
)

# Initialize the memory backend (mem0, cognee, or graphiti)
memory = get_memory_backend()


@tool
def search_memory(query):
    """Search the user's stored memories for relevant information."""
    user_id = memory_agent.state.get('user_id')
    results = memory.search(query, user_id)
    return results


@tool
def add_memory(query):
    """Store new information in the user's memory for future recall."""
    user_id = memory_agent.state.get('user_id')
    results = memory.add(query, user_id)
    return results


# Build the tool list: core memory tools + any extras from the agent config
tools = [search_memory, add_memory] + agent_config.EXTRA_TOOLS

memory_agent = Agent(
    model=model,
    system_prompt=agent_config.SYSTEM_PROMPT,
    tools=tools,
)
