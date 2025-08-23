from strands.models import BedrockModel
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands import tool
from frameworks import Mem0Demo
from strands import Agent


# Define agent
system_prompt = """You are an assistant that creates helpful responses based on retrieved memories.
Use the provided memories to create a natural, conversational response to the user's question.  
If you have no memories of me then the first thing you should search the first thing you should do is load 
them using search_memory tool.  If you have no memories than do not add one, just ask me about a trip I want to take.  
Do not store any memories into the conversation history """

model = BedrockModel(
    model_id="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    max_tokens=64000,
    additional_request_fields={
        "thinking": {
            "type": "disabled",
        }
    },
)

memory = Mem0Demo("")

@tool
def search_memory(query):
    user_id = memory_agent.state.get('user_id')
    results = memory.client.search(query, user_id=user_id)
    return results

@tool
def add_memory(query):
    user_id = memory_agent.state.get('user_id')
    results = memory.client.add(query, user_id=user_id)
    return results


memory_agent = Agent(
        model=model,
        system_prompt=system_prompt,
        tools=[
            search_memory,
            add_memory
        ]
    )