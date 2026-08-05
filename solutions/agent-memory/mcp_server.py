"""MCP Server for Agent Memory.

Exposes search_memory and add_memory as MCP tools that can be used by
any MCP-compatible client (kiro-cli, Claude Code, Cursor, etc.).

Configuration via environment variables:
    MEMORY_FRAMEWORK - Backend: mem0, cognee, graphiti (default: mem0)
    BEDROCK_MODEL_ID - Bedrock model for the memory framework's LLM
    AWS_REGION - AWS region
    + Backend-specific endpoint vars (see .env.example)

Usage:
    uv run python mcp_server.py
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("agentmemory")

# Lazy-loaded memory backend — initialized on first tool call to keep server
# startup fast (kiro-cli has a timeout for MCP server initialization).
_memory = None


def _get_memory():
    global _memory
    if _memory is None:
        from frameworks.memory_backend import get_memory_backend
        _memory = get_memory_backend()
    return _memory


@mcp.tool()
def search_memory(query: str, user_id: str):
    """Search a user's stored memories for relevant information.

    Use this to recall past conversations, preferences, facts, or context
    that has been previously stored for a user.

    Args:
        query: What to search for in the user's memories
        user_id: The user whose memories to search
    """
    memory = _get_memory()
    results = memory.search(query, user_id)
    if not results:
        return f"No memories found for user '{user_id}'. This user has no stored memories yet — use add_memory to start building their memory."
    return str(results)


@mcp.tool()
def add_memory(content: str, user_id: str):
    """Store new information in a user's memory for future recall.

    Use this to save important facts, preferences, decisions, or context
    that should be remembered across conversations.

    Args:
        content: The information to remember
        user_id: The user to store the memory for
    """
    memory = _get_memory()
    result = memory.add(content, user_id)
    return str(result)


if __name__ == "__main__":
    mcp.run()
