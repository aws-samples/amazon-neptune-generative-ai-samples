
import asyncio
from datetime import datetime
from graphiti_core.nodes import EpisodeType
from frameworks import *
import logging
import threading

logger = logging.getLogger(__name__)


messages = [
    {"role": "user", "content": "I'm planning a 5-day trip to Japan with a $3000 budget. I'm really interested in cultural activities. Can you help me plan this?"},
    {"role": "user", "content": "I'm thinking Tokyo and Kyoto in April. I've heard cherry blossom season is amazing for cultural experiences."},
]



async def main():
    user_id = 'Alice'
    mem0 = await load_mem0(user_id)
    graphiti = await load_graphiti(user_id)
    cognee = await load_cognee(user_id)

    print("********************* Mem0 Search *********************")
    resp = mem0.client.search("What information do you know about me?", user_id=user_id)
    print(resp)

    print("********************* Graphiti Search *********************")
    resp = graphiti.client.search("What information do you know about me?", group_ids=[user_id])
    print(resp)

    print("********************* Cognee Search *********************")
    resp = cognee.search("What information do you know about me?", user_id=user_id)
    print(resp)

    logger.info("Data Load Complete")

async def load_cognee(user_id):
    logger.info("Starting Cognee data load")
    cognee = CogneeDemo(user_id)
    await cognee.reset()
    logger.info("Cognee reset complete")
    data = []
    for msg in messages:
        data = msg['content']        
    await cognee.add(data)
    await cognee.cognify()
    logger.info("Cognee load complete")
    return cognee

async def load_graphiti(user_id):
    logger.info("Starting Graphiti data load")
    graphiti = GraphitiDemo(user_id)
    await graphiti.reset()
    logger.info("Graphiti reset complete")
    for index, msg in enumerate(messages):
        resp = await graphiti.client.add_episode(
                name=f'Msg_{index}_{msg["role"]}',
                episode_body=msg['content'],
                source=EpisodeType.message,
                source_description=f'Msg_{index}_{msg["role"]}',
                reference_time=datetime.utcnow(),
        )
    await graphiti.client.build_communities()
    logger.info("Graphiti load complete")
    return graphiti

async def load_mem0(user_id):
    logger.info("Starting Mem0 data load")
    mem0 = Mem0Demo(user_id)
    await mem0.reset()
    logger.info("Mem0 reset complete")
    mem0.client.add(messages=messages, user_id=mem0.user_id)
    logger.info("Mem0 load complete")
    return mem0


if __name__ == "__main__":
    asyncio.run(main())
