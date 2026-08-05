# Agent Memory - Claude Code Instructions

You have access to persistent memory tools via the `agent-memory` MCP server.

## Available Tools

- `search_memory(query, user_id)` — Search a user's stored memories
- `add_memory(content, user_id)` — Store new information for a user

## Usage Pattern

1. At the start of a conversation, ask the user for their `user_id` (or use a default like "default")
2. Search memory for any existing context about them
3. Store important new information they share

## Example

```
search_memory(query="preferences", user_id="Alice")
add_memory(content="Alice prefers window seats on flights", user_id="Alice")
```
