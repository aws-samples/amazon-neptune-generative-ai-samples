import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from logging import INFO

from dotenv import load_dotenv

from graphiti_core import Graphiti
from graphiti_core.driver.neptune_driver import NeptuneDriver

load_dotenv()


class GraphitiDemo():   
    def __init__(self, group_id: str):
        # Initialize Graphiti with Neptune connection
        neptune_uri = os.environ.get('GRAPHITI_NEPTUNE_ENDPOINT')
        aoss_host = os.environ.get('GRAPHITI_AOSS_ENDPOINT')

        if not neptune_uri:
            raise ValueError('GRAPHITI_NEPTUNE_ENDPOINT must be set')

        if not aoss_host:
            raise ValueError('GRAPHITI_AOSS_ENDPOINT must be set')
        
        self.driver = NeptuneDriver(
            host=neptune_uri,
            port=int(os.environ.get('GRAPHITI_NEPTUNE_PORT', 8182)),
            aoss_host=aoss_host,
        )
        self.client = Graphiti(graph_driver=self.driver)
        self.group_id = group_id

    
    async def reset(self):
        await self.driver.delete_aoss_indices()
        await self.driver._delete_all_data()
        await self.client.build_indices_and_constraints()