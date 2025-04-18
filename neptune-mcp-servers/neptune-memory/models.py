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

from enum import Enum
from dataclasses import dataclass
from typing import List

class QueryLanguage(Enum):
    OPEN_CYPHER = 'OPEN_CYPHER'
    GREMLIN = 'GREMLIN'

@dataclass
class Property:
    name: str
    type: str

@dataclass
class Node:
    labels: str
    properties: List[Property]

@dataclass
class Relationship:
    type: str
    properties: List[Property]


@dataclass
class RelationshipPattern:
    left_node: str
    right_node: str
    relation: str

@dataclass
class GraphSchema:
    nodes: List[Node]
    relationships: List[Relationship]
    relationship_patterns: List[RelationshipPattern]

# Models for our knowledge graph
@dataclass
class Entity():
    name: str
    type: str
    observations: List[str]

@dataclass
class Relation():
    source: str
    target: str
    relationType: str

@dataclass
class KnowledgeGraph():
    entities: List[Entity]
    relations: List[Relation]

@dataclass
class Observation():
    entityName: str
    contents: List[str]