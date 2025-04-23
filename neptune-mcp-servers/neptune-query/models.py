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
"""
Data Models Module for Neptune Graph Database

This module defines the core data structures and types used throughout the Neptune
graph database interface. It includes models for query languages, graph schema
definitions, and knowledge graph components.

The models use Python's dataclass decorator for clean, type-safe data structures
that represent both the graph structure and its contents.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List


class QueryLanguage(Enum):
    """
    Enumeration of supported query languages for Neptune database operations.

    Attributes:
        OPEN_CYPHER: OpenCypher query language for graph database operations
        GREMLIN: Gremlin query language for graph traversal and manipulation
    """
    OPEN_CYPHER = 'OPEN_CYPHER'
    GREMLIN = 'GREMLIN'


@dataclass
class Property:
    """
    Represents a property definition for nodes and relationships in the graph.

    Properties are key-value pairs that can be attached to both nodes and
    relationships, storing additional metadata about these graph elements.

    Attributes:
        name (str): The name/key of the property
        type (str): The data type of the property value
    """
    name: str
    type: str


@dataclass
class Node:
    """
    Defines a node type in the graph schema.

    Nodes represent entities in the graph database and can have labels
    and properties that describe their characteristics.

    Attributes:
        labels (str): The label(s) that categorize this node type
        properties (List[Property]): List of properties that can be assigned to this node type
    """
    labels: str
    properties: List[Property]


@dataclass
class Relationship:
    """
    Defines a relationship type in the graph schema.

    Relationships represent connections between nodes in the graph and can
    have their own properties to describe the nature of the connection.

    Attributes:
        type (str): The type/category of the relationship
        properties (List[Property]): List of properties that can be assigned to this relationship type
    """
    type: str
    properties: List[Property]


@dataclass
class RelationshipPattern:
    """
    Defines a valid relationship pattern between nodes in the graph.

    Relationship patterns describe the allowed connections between different
    types of nodes in the graph schema.

    Attributes:
        left_node (str): The label of the source/starting node
        right_node (str): The label of the target/ending node
        relation (str): The type of relationship connecting the nodes
    """
    left_node: str
    right_node: str
    relation: str


@dataclass
class GraphSchema:
    """
    Represents the complete schema definition for the graph database.

    The graph schema defines all possible node types, relationship types,
    and valid patterns of connections between nodes.

    Attributes:
        nodes (List[Node]): List of all node types defined in the schema
        relationships (List[Relationship]): List of all relationship types defined in the schema
        relationship_patterns (List[RelationshipPattern]): List of valid relationship patterns
    """
    nodes: List[Node]
    relationships: List[Relationship]
    relationship_patterns: List[RelationshipPattern]


@dataclass
class Entity:
    """
    Represents an entity (node) in the knowledge graph.

    Entities are concrete instances of nodes in the graph, representing
    real objects, concepts, or things with their associated metadata.

    Attributes:
        name (str): The unique identifier or name of the entity
        type (str): The type/category of the entity
        observations (List[str]): List of observations or facts about the entity
    """
    name: str
    type: str
    observations: List[str]


@dataclass
class Relation:
    """
    Represents a concrete relationship between two entities in the knowledge graph.

    Relations are instances of relationships that connect specific entities
    in the graph, representing actual connections between real entities.

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
    """
    Represents the complete knowledge graph structure.

    A knowledge graph contains all the actual entities and their relationships,
    forming a concrete instance of the graph schema with real data.

    Attributes:
        entities (List[Entity]): List of all entities in the knowledge graph
        relations (List[Relation]): List of all relationships between entities
    """
    entities: List[Entity]
    relations: List[Relation]


@dataclass
class Observation:
    """
    Represents an observation about an entity in the knowledge graph.

    Observations are facts or pieces of information associated with specific
    entities, providing additional context or metadata about the entity.

    Attributes:
        entityName (str): The name of the entity this observation relates to
        contents (List[str]): List of observation contents or facts about the entity
    """
    entityName: str
    contents: List[str]
