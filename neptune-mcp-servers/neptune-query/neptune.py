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

from langchain_aws.graphs import NeptuneGraph, NeptuneAnalyticsGraph
from enum import Enum
import logging
import json
from dataclasses import asdict
from models import (
    Relationship,
    QueryLanguage,
    GraphSchema,
    RelationshipPattern,
    Property,
    Node,
)


class EngineType(Enum):
    ANALYTICS = "analytics"
    DATABASE = "database"
    UNKNOWN = "unknown"


class NeptuneServer:
    _logger: logging.Logger = logging.getLogger()
    _engine_type: EngineType = EngineType.UNKNOWN
    graph = None

    def __init__(
        self, endpoint: str, use_https: bool = True, port: int = 8182, *args, **kwargs
    ):
        """The init function"""
        # Parse out the graphId from the hostname
        if endpoint:
            self._logger.debug("NeptuneServer host: %s", endpoint)
            if endpoint.startswith("neptune-db://"):
                # This is a Neptune Database Cluster
                endpoint = endpoint.replace("neptune-db://", "")
                self.graph = NeptuneGraph(endpoint, port, use_https=use_https)
                self._engine_type = EngineType.DATABASE
                self._logger.debug("Creating Neptune Database session for %s", endpoint)
            elif endpoint.startswith("neptune-graph://"):
                # This is a Neptune Analytics Graph
                graphId = endpoint.replace("neptune-graph://", "")
                self.graph = NeptuneAnalyticsGraph(graphId)
                self._engine_type = EngineType.ANALYTICS
                self._logger.debug("Creating Neptune Graph session for %s", endpoint)
            else:
                raise ValueError(
                    "You must provide an endpoint to create a NeptuneServer as either neptune-db://<endpoint> or neptune-graph://<graphid>"
                )
        else:
            raise ValueError("You must provide an endpoint to create a NeptuneServer")

    def close(self):
        self.graph = None

    def status(self) -> str:
        if self._engine_type == EngineType.UNKNOWN:
            raise AttributeError("Engine type is unknown so we cannot fetch the schema")
        try:
            self.query("RETURN 1", QueryLanguage.OPEN_CYPHER)
            return "Available"
        except Exception:
            return "Unavailabe"

    def schema(self) -> GraphSchema:
        match self._engine_type:
            case EngineType.DATABASE:
                return self._schema_database()
            case EngineType.ANALYTICS:
                return self._schema_analytics()
            case __:
                raise AttributeError(
                    "Engine type is unknown so we cannot fetch the schema"
                )

    def query(self, query: str, language: QueryLanguage, parameters: map = None) -> str:
        if self._engine_type == EngineType.DATABASE:
            return self._query_database(query, language, parameters)
        elif self._engine_type == EngineType.ANALYTICS:
            if language != QueryLanguage.OPEN_CYPHER:
                raise ValueError("Only openCypher is supported for analytics queries")
            return self._query_analytics(query, parameters)
        else:
            raise AttributeError("Engine type is unknown so we cannot query")

    def _query_analytics(self, query: str, parameters: dict = None):
        try:
            # Run Neptune Analytics queries
            self._logger.debug("Querying graph %s", self.graph.graph_identifier)
            if parameters:
                resp = self.graph.client.execute_query(
                    graphIdentifier=self.graph.graph_identifier,
                    queryString=query,
                    parameters=parameters,
                    language="OPEN_CYPHER",
                )
            else:
                resp = self.graph.client.execute_query(
                    graphIdentifier=self.graph.graph_identifier,
                    queryString=query,
                    language="OPEN_CYPHER",
                )
            if resp["ResponseMetadata"]["HTTPStatusCode"] == 200:
                return resp["payload"].read().decode("UTF-8")
            else:
                self._logger.debug(resp)
                raise Exception
        except Exception as e:
            self._logger.debug(e)
            raise e

    # amazonq-ignore-next-line
    def _query_database(
        self, query: str, language: QueryLanguage, parameters: dict = None
    ):
        try:
            if language == QueryLanguage.OPEN_CYPHER:
                if parameters:
                    resp = self.graph.client.execute_open_cypher_query(
                        openCypherQuery=query,
                        parameters=json.dumps(parameters),
                    )
                else:
                    resp = self.graph.client.execute_open_cypher_query(
                        openCypherQuery=query
                    )
            elif language == QueryLanguage.GREMLIN:
                resp = self.graph.client.execute_gremlin_query(
                    gremlinQuery=query,
                    serializer="application/vnd.gremlin-v3.0+json;types=false",
                )
            else:
                raise ValueError("Unsupported language")
            if resp["ResponseMetadata"]["HTTPStatusCode"] == 200:
                return resp["result"] if "result" in resp else resp["results"]
        except Exception as e:
            self._logger.debug(e)
            raise e

    def _schema_analytics(self) -> GraphSchema:
        """
        Retrives the Neptune graph schema information and returns a GraphSchema object.
        """
        pg_schema_query = """
        CALL neptune.graph.pg_schema() 
        YIELD schema
        RETURN schema
        """

        data = json.loads(
            self.query(pg_schema_query, language=QueryLanguage.OPEN_CYPHER)
        )
        raw_schema = data["results"][0]["schema"]
        graph = GraphSchema(nodes=[], relationships=[], relationship_patterns=[])
        for i in raw_schema["labelTriples"]:
            graph.relationship_patterns.append(
                RelationshipPattern(
                    left_node=i["~from"], relation=i["~type"], right_node=i["~to"]
                )
            )

        for label in raw_schema["nodeLabels"]:
            details = raw_schema["nodeLabelDetails"][label]
            props = []
            for p in details["properties"]:
                props.append(
                    Property(name=p, type=details["properties"][p]["datatypes"])
                )
            graph.nodes.append(Node(labels=label, properties=props))

        for label in raw_schema["edgeLabels"]:
            details = raw_schema["edgeLabelDetails"][label]
            props = []
            for p in details["properties"]:
                props.append(
                    Property(name=p, type=details["properties"][p]["datatypes"])
                )
            graph.relationships.append(Relationship(type=label, properties=props))

        return asdict(graph)

    def _schema_database(self) -> GraphSchema:
        """
        Retrives the Neptune database schema information and returns a GraphSchema object.
        """
        types = {
            "str": "STRING",
            "float": "DOUBLE",
            "int": "INTEGER",
            "list": "LIST",
            "dict": "MAP",
            "bool": "BOOLEAN",
        }

        n_labels, e_labels = self.graph._get_labels()
        triple_schema = self.graph._get_triples(e_labels)
        node_properties = self.graph._get_node_properties(n_labels, types)
        edge_properties = self.graph._get_edge_properties(e_labels, types)

        graph = GraphSchema(nodes=[], relationships=[], relationship_patterns=[])
        for i in triple_schema:
            i = (
                i.replace("(:`", "")
                .replace("`)", "")
                .replace("[:`", "")
                .replace("`]", "")
                .replace(">", "")
            )
            parts = i.split("-")
            graph.relationship_patterns.append(
                RelationshipPattern(
                    left_node=parts[0], relation=parts[1], right_node=parts[2]
                )
            )

        for i in node_properties:
            props = []
            for p in i["properties"]:
                props.append(Property(name=p["property"], type=p["type"]))
            graph.nodes.append(Node(labels=i["labels"], properties=props))

        for i in edge_properties:
            props = []
            for p in i["properties"]:
                props.append(Property(name=p["property"], type=p["type"]))
            graph.relationships.append(Relationship(type=i["type"], properties=props))

        return asdict(graph)
