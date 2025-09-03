from strands import Agent, tool
from strands.agent import AgentResult
from strands.tools.mcp import MCPClient
from mcp import stdio_client, StdioServerParameters
from dotenv import load_dotenv
import os

load_dotenv()

# Define a specialized system prompt
from strands.tools.mcp import MCPClient
FLIGHTS_PROMPT = """
You are a specialized agent for booking flight itineraries based on data in a graph database.
Ignore any dates, airline preference, or other preferences you receive and only search for flight routes using the airport.
Generate and run a query given the information provided, always look at the schema first
Always cite your sources when possible.
"""

endpoint = os.getenv("NEPTUNE_FLIGHTS_ENDPOINT", None)
if endpoint:
    query_mcp_client = MCPClient(lambda: stdio_client(StdioServerParameters(command="uvx", 
        args=["awslabs.amazon-neptune-mcp-server@latest"],
        env={"NEPTUNE_ENDPOINT": f"{endpoint}", "FASTMCP_LOG_LEVEL": "INFO"},
        )
        )
        )


@tool
def flights(query: str) -> AgentResult:
    try:
        with query_mcp_client:
            tools = query_mcp_client.list_tools_sync()
            flight_agent = Agent(
                system_prompt=FLIGHTS_PROMPT,
                tools=tools
            )

            # Call the agent and return its response
            return flight_agent(query)
    except Exception as e:
        print(e)
        raise Exception(f"Error in flight agent: {str(e)}")
