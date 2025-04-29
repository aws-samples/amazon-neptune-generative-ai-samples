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
"""Knowledge Graph Management Module for Neptune Memory System

This module provides a comprehensive interface for managing a knowledge graph in Amazon Neptune.
It handles all graph operations including creating, reading, updating, and deleting entities,
relations, and observations in the knowledge graph.

The KnowledgeGraphManager class serves as the main interface for all graph operations,
providing methods to manipulate and query the graph structure while maintaining data consistency.
"""

import json
import logging
from dataclasses import asdict
from models import Entity, KnowledgeGraph, Observation, QueryLanguage, Relation
from neptune import NeptuneServer
from typing import Any, Dict, List


class KnowledgeGraphManager:
    """Manages operations on a knowledge graph stored in Amazon Neptune.

    This class provides methods for creating, reading, updating, and deleting
    entities, relations, and observations in the knowledge graph. It handles
    all interactions with the Neptune database through a provided client.

    Attributes:
        client (NeptuneServer): Instance of NeptuneServer for database operations
        logger (logging.Logger): Logger instance for tracking operations
    """

    def __init__(self, client: NeptuneServer, logger: logging.Logger):
        """Initialize the KnowledgeGraphManager.

        Args:
            client (NeptuneServer): Neptune database client instance
            logger (logging.Logger): Logger instance for operation tracking
        """
        self.client = client
        self.logger = logger

    def load_graph(self, filter_query=None) -> KnowledgeGraph:
        """Load the knowledge graph with optional filtering.

        Retrieves entities and their relationships from the Neptune database.
        Can filter entities based on a provided query string.

        Args:
            filter_query (str, optional): Query string to filter entities by name

        Returns:
            KnowledgeGraph: Object containing filtered entities and their relations
        """
        if filter_query:
            query = "MATCH (entity) WHERE toLower(entity.name) CONTAINS toLower($filter) "
        else:
            query = ""
        query = (
            query
            + """
                OPTIONAL MATCH p=(entity:Memory)-[r]-(other)
                WITH nodes(p) as n
                UNWIND n as node
                WITH collect(DISTINCT node) as nodes
            UNWIND nodes as node
            RETURN  {
                name: node.name,
                type: node.type,
                observations: node.observations
            } as node
        """
        )
        resp = self.client.query(query, parameters={"filter": filter_query}, language=QueryLanguage.OPEN_CYPHER)
        result = json.loads(resp)["results"]

        entities = []
        for node in result:
            if "name" in node["node"]:
                entities.append(
                    Entity(
                        name=node["node"]["name"],
                        type=node["node"]["type"],
                        observations=node["node"]["observations"].split("|"),
                    )
                )

        if filter_query:
            query = "MATCH (entity) WHERE toLower(entity.name) CONTAINS toLower($filter) "
        else:
            query = ""
        query = (
            query
            + """
            OPTIONAL MATCH p=(entity:Memory)-[r]-(other)
            RETURN  {
                            source: id(startNode(r)),
                            target: id(endNode(r)),
                            relationType: r.type
                        } as rel
        """
        )
        resp = self.client.query(query, parameters={"filter": filter_query}, language=QueryLanguage.OPEN_CYPHER)

        result = json.loads(resp)["results"]
        rels = []
        for rel in result:
            if "relationType" in rel["rel"]:
                rels.append(
                    Relation(
                        source=rel["rel"]["source"],
                        target=rel["rel"]["target"],
                        relationType=rel["rel"]["relationType"]
                    )
                )

        self.logger.debug(f"Loaded entities: {entities}")
        self.logger.debug(f"Loaded relations: {rels}")
        return KnowledgeGraph(entities=entities, relations=rels)

    def create_entities(self, entities: List[Entity]) -> List[Entity]:
        """Create new entities in the knowledge graph.

        Args:
            entities (List[Entity]): List of entities to create

        Returns:
            List[Entity]: The created entities
        """
        query = """
        UNWIND $entities as entity
        MERGE (e:Memory { name: entity.name })
        SET e.type = entity.type
        SET e.observations = join(entity.observations, '|')
        """
        entities_data = [asdict(entity) for entity in entities]
        self.client.query(query, parameters={"entities": entities_data}, language=QueryLanguage.OPEN_CYPHER)
        return entities

    def create_relations(self, relations: List[Relation]) -> List[Relation]:
        """Create new relations between entities in the knowledge graph.

        Args:
            relations (List[Relation]): List of relations to create

        Returns:
            List[Relation]: The created relations
        """
        for relation in relations:
            query = """
            UNWIND $relations as relation
            MATCH (from:Memory),(to:Memory)
            WHERE from.name = relation.source
            AND  to.name = relation.target
            MERGE (from)-[r:related_to]->(to)
            SET r.type = relation.relationType
            """

            self.client.query(
                query, parameters={"relations": [asdict(relation) for relation in relations]}, language=QueryLanguage.OPEN_CYPHER
            )

        return relations

    def add_observations(self, observations: List[Observation]) -> List[Dict[str, Any]]:
        """Add new observations to existing entities.

        Args:
            observations (List[Observation]): List of observations to add

        Returns:
            List[Dict[str, Any]]: Results of the operation, including added observations
        """
        query = """
        UNWIND $observations as obs
        MATCH (e:Memory { name: obs.entityName })
        WITH e, [o in obs.contents WHERE NOT o IN e.observations] as new
        SET e.observations = coalesce(e.observations,[]) + new
        RETURN e.name as name, new
        """

        result = self.client.query(
            query, parameters={"observations": [asdict(obs) for obs in observations]}, language=QueryLanguage.OPEN_CYPHER
        )

        results = [
            {"entityName": record.get("name"), "addedObservations": record.get("new")}
            for record in result.records
        ]
        return results

    def read_graph(self) -> KnowledgeGraph:
        """Read the entire knowledge graph.

        Returns:
            KnowledgeGraph: Complete graph with all entities and relations
        """
        return self.load_graph()

    def search_nodes(self, query: str) -> KnowledgeGraph:
        """Search for nodes in the knowledge graph.

        Args:
            query (str): Search query string

        Returns:
            KnowledgeGraph: Graph containing matching nodes and their relations
        """
        return self.load_graph(query)

    def find_nodes(self, names: List[str]) -> KnowledgeGraph:
        """Find specific nodes by their names.

        Args:
            names (List[str]): List of node names to find

        Returns:
            KnowledgeGraph: Graph containing the specified nodes and their relations
        """
        return self.load_graph("name: (" + " ".join(names) + ")")
