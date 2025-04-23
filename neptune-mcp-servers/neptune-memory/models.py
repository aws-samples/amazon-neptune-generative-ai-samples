#
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may not use this file except in compliance
# with the License. A copy of the License is located at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# or in the 'license' file accompanying this file. This file is distributed on an 'AS IS' BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions
# and limitations under the License.
#
"""Data Models Module for Neptune Memory System

This module defines the data structures used in the Neptune memory system, including
graph schema definitions and knowledge graph representations. It uses dataclasses
for clean and type-safe data modeling.

The module contains two main groups of models:
1. Graph Schema Models: For defining the structure of the graph database
2. Knowledge Graph Models: For representing the actual data within the graph
"""

from dataclasses import dataclass
from enum import Enum
from typing import List


class QueryLanguage(Enum):
    """Enumeration of supported query languages for the Neptune database.

    Attributes:
        OPEN_CYPHER: OpenCypher query language
        GREMLIN: Gremlin query language
    """
    OPEN_CYPHER = 'OPEN_CYPHER'
    GREMLIN = 'GREMLIN'


@dataclass
class Property:
    """Represents a property definition for nodes and relationships in the graph.

    Attributes:
        name (str): The name of the property
        type (str): The data type of the property
    """
    name: str
    type: str


@dataclass
class Node:
    """Defines a node type in the graph schema.

    Attributes:
        labels (str): The label(s) associated with the node
        properties (List[Property]): List of properties that can be assigned to this node type
    """
    labels: str
    properties: List[Property]


@dataclass
class Relationship:
    """Defines a relationship type in the graph schema.

    Attributes:
        type (str): The type of relationship
        properties (List[Property]): List of properties that can be assigned to this relationship type
    """
    type: str
    properties: List[Property]


@dataclass
class RelationshipPattern:
    """Defines a valid relationship pattern between nodes in the graph.

    Attributes:
        left_node (str): The label of the source node
        right_node (str): The label of the target node
        relation (str): The type of relationship between the nodes
    """
    left_node: str
    right_node: str
    relation: str


@dataclass
class GraphSchema:
    """Represents the complete schema definition for the graph database.

    Attributes:
        nodes (List[Node]): List of all node types in the schema
        relationships (List[Relationship]): List of all relationship types in the schema
        relationship_patterns (List[RelationshipPattern]): List of valid relationship patterns
    """
    nodes: List[Node]
    relationships: List[Relationship]
    relationship_patterns: List[RelationshipPattern]


@dataclass
class Entity:
    """Represents an entity in the knowledge graph.

    An entity is a node in the graph that represents a distinct concept or object
    with associated observations.

    Attributes:
        name (str): The unique identifier or name of the entity
        type (str): The type or category of the entity
        observations (List[str]): List of observations or facts about the entity
    """
    name: str
    type: str
    observations: List[str]


@dataclass
class Relation:
    """Represents a relationship between two entities in the knowledge graph.

    Attributes:
        source (str): The name/identifier of the source entity
        target (str): The name/identifier of the target entity
        relationType (str): The type of relationship between the entities
    """
    source: str
    target: str
    relationType: str


@dataclass
class KnowledgeGraph:
    """Represents the complete knowledge graph structure.

    This class serves as a container for all entities and their relationships
    in the knowledge graph.

    Attributes:
        entities (List[Entity]): List of all entities in the knowledge graph
        relations (List[Relation]): List of all relationships between entities
    """
    entities: List[Entity]
    relations: List[Relation]


@dataclass
class Observation:
    """Represents an observation about an entity in the knowledge graph.

    Observations are facts or pieces of information associated with a specific entity.

    Attributes:
        entityName (str): The name of the entity this observation relates to
        contents (List[str]): List of observation contents or facts
    """
    entityName: str
    contents: List[str]
