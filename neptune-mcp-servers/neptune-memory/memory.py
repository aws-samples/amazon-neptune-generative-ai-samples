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

from models import KnowledgeGraph, Entity, Relation, Observation, QueryLanguage
import json
from typing import List, Dict, Any
from dataclasses import asdict
from neptune import NeptuneServer
import logging


class KnowledgeGraphManager():    
    def __init__(self, client:NeptuneServer, logger:logging.Logger):
        self.client = client
        self.logger = logger

    def load_graph(self, filter_query=None):
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
        result = json.loads(resp)[
            "results"
        ]

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
        query = """
        UNWIND $entities as entity
        MERGE (e:Memory { name: entity.name })
        SET e.type = entity.type
        SET e.observations = join(entity.observations, '|')
        """
        entities_data = [asdict(entity) for entity in entities]
        self.client.query(query, parameters = {"entities": entities_data}, language=QueryLanguage.OPEN_CYPHER)
        return entities

    def create_relations(self, relations: List[Relation]) -> List[Relation]:
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
                query, parameters = {"relations": [asdict(relation) for relation in relations]}, language=QueryLanguage.OPEN_CYPHER
            )

        return relations

    def add_observations(
        self, observations: List[Observation]
    ) -> List[Dict[str, Any]]:
        query = """
        UNWIND $observations as obs  
        MATCH (e:Memory { name: obs.entityName })
        WITH e, [o in obs.contents WHERE NOT o IN e.observations] as new
        SET e.observations = coalesce(e.observations,[]) + new
        RETURN e.name as name, new
        """

        result = self.client.query(
            query, parameters = {"observations": [asdict(obs) for obs in observations]}, language=QueryLanguage.OPEN_CYPHER
        )

        results = [
            {"entityName": record.get("name"), "addedObservations": record.get("new")}
            for record in result.records
        ]
        return results

    def delete_entities(self, entity_names: List[str]) -> None:
        query = """
        UNWIND $entities as name
        MATCH (e:Memory { name: name })
        DETACH DELETE e
        """

        self.client.query(query, parameters = {"entities": entity_names}, language=QueryLanguage.OPEN_CYPHER)

    def delete_observations(self, deletions: List[Observation]) -> None:
        query = """
        UNWIND $deletions as d  
        MATCH (e:Memory { name: d.entityName })
        SET e.observations = [o in coalesce(e.observations,[]) WHERE NOT o IN d.observations]
        """
        self.client.query(
            query, parameters={"deletions": [asdict(deletion) for deletion in deletions]}, language=QueryLanguage.OPEN_CYPHER
        )

    def delete_relations(self, relations: List[Relation]) -> None:
        query = """
        UNWIND $relations as relation
        MATCH (source:Memory)-[r:$(relation.relationType)]->(target:Memory)
        WHERE source.name = relation.source
        AND target.name = relation.target
        DELETE r
        """
        self.client.query(
            query, parameters={"relations": [asdict(relation) for relation in relations]}, language=QueryLanguage.OPEN_CYPHER
        )

    def read_graph(self) -> KnowledgeGraph:
        return self.load_graph()

    def search_nodes(self, query: str) -> KnowledgeGraph:
        return self.load_graph(query)

    def find_nodes(self, names: List[str]) -> KnowledgeGraph:
        return self.load_graph("name: (" + " ".join(names) + ")")
