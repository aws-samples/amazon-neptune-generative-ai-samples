"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

from enum import Enum
import logging
# NOTE: current v1 is needed
from pydantic.v1 import BaseModel, Field
from llama_index.core.indices.property_graph import CypherTemplateRetriever
from llama_index.core.llms import ChatMessage

# create a pydantic class to represent the params for our query
# the class fields are directly used as params for running the cypher query
class ComponentParams(BaseModel):
    """Template params for a cypher query."""

    component_name: str = Field(
        description="The component name to use for a start location of a query"
    )

COMPONENT_QUERY: str = """
    MATCH (c:Component {name: $component_name})
    RETURN c as component
"""

COMPONENT_EXPLAINABILITY_QUERY_EDGES: str = """
    MATCH p=(n)-[]-(c:Component {name: $component_name})-[]-(noe:Vulnerability)
    WITH relationships(p) as edges
    UNWIND edges as e
    RETURN collect(distinct e) as edges
"""

SHARED_COMPONENT_QUERY_EDGES: str = """
    MATCH p=(n)-[]-(c:Component {name: $component_name})-[]-(:Vulnerability)-[]-(:Component)
    WITH relationships(p) as edges
    UNWIND edges as e
    RETURN collect(distinct e) as edges
"""


COMPONENT_LIST_QUERY: str = """
    MATCH (c:Component) WHERE exists(c.name) RETURN c.name as name ORDER BY c.name
"""
QUERY_TYPES = Enum("QUERY_TYPES", ["Fetch Component", "Explainability", "Unknown"])

logger = logging.getLogger(__name__)

class KnowledgeGraphRetriever:
    def __init__(self, index, llm):
        self.index = index
        self.llm = llm
        self.graph_store = index.property_graph_store
        self.component_list = self._get_component_list()
    
    def run_retrieval_query(self, prompt):
        messages = [
            ChatMessage(
                role="system", content="""You are an expert in Software Bill of Materials  
                Given the question below, determine if the users intent is to:
                
                * Find information about a specific component, if so return only the word COMPONENT_QUERY
                * Find information about a component and its vulnerabiltiies, if so return only the word COMPONENT_EXPLAINABILITY_QUERY_EDGES
                * Find information about shared components across documents, if so return only the word  SHARED_COMPONENT_QUERY_EDGES
                * If it is none of these return only the word UNKNOWN
                Do not provide any additional context or explaination.
                """
            ),
            ChatMessage(role="user", content=prompt),
        ]
        resp = self.llm.chat(messages)
        logger.info(resp)
        cypher_query = ""
        match resp.message.content:
            case "COMPONENT_QUERY":
                cypher_query = COMPONENT_QUERY
            case "COMPONENT_EXPLAINABILITY_QUERY_EDGES":
                cypher_query = COMPONENT_EXPLAINABILITY_QUERY_EDGES                
            case "SHARED_COMPONENT_QUERY_EDGES":
                cypher_query = SHARED_COMPONENT_QUERY_EDGES                
            case _:
                return "The question asked is not supported by this application, please rephrase the question and try again."
            
        retriever = CypherTemplateRetriever(
            self.graph_store, ComponentParams, cypher_query
        )
        nodes = retriever.retrieve(prompt)
        return nodes[0].text
        
    def _get_component_list(self):
        data = self.graph_store.structured_query(COMPONENT_LIST_QUERY)
        return [d["name"] for d in data]
