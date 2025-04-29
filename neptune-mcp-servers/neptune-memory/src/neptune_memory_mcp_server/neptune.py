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
"""Neptune Database Interface Module

This module provides a high-level interface for interacting with Amazon Neptune databases,
supporting both Neptune Analytics and Neptune Database instances. It handles connection
management, query execution, and schema operations for both graph database types.

The module supports multiple query languages (OpenCypher and Gremlin) and provides
a unified interface for different Neptune deployment types through the NeptuneServer class.
"""

import json
import logging
from dataclasses import asdict
from enum import Enum
from langchain_aws.graphs import NeptuneAnalyticsGraph, NeptuneGraph
from .models import (
    GraphSchema,
    Node,
    Property,
    QueryLanguage,
    Relationship,
    RelationshipPattern,
)


class EngineType(Enum):
    """Enumeration of supported Neptune engine types.

    Attributes:
        ANALYTICS: Neptune Analytics instance
        DATABASE: Neptune Database instance
        UNKNOWN: Unidentified engine type
    """
    ANALYTICS = "analytics"
    DATABASE = "database"
    UNKNOWN = "unknown"


class NeptuneServer:
    """A unified interface for interacting with Amazon Neptune instances.

    This class provides methods for connecting to and querying both Neptune Analytics
    and Neptune Database instances. It handles connection management, query execution,
    and schema operations.

    Attributes:
        _logger (logging.Logger): Logger instance for operation tracking
        _engine_type (EngineType): Type of Neptune engine being used
        graph: Connection to the Neptune instance (NeptuneGraph or NeptuneAnalyticsGraph)
    """

    _logger: logging.Logger = logging.getLogger()
    _engine_type: EngineType = EngineType.UNKNOWN
    graph = None

    def __init__(
        self, endpoint: str, use_https: bool = True, port: int = 8182, *args, **kwargs
    ):
        """Initialize a connection to a Neptune instance.

        Args:
            endpoint (str): Neptune endpoint URL (neptune-db:// or neptune-graph://)
            use_https (bool, optional): Whether to use HTTPS connection. Defaults to True.
            port (int, optional): Port number for connection. Defaults to 8182.
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.

        Raises:
            ValueError: If endpoint is not provided or has invalid format
        """
        if endpoint:
            self._logger.debug("NeptuneServer host: %s", endpoint)
            if endpoint.startswith("neptune-db://"):
                # This is a Neptune Database Cluster
                endpoint = endpoint.replace(
                    "neptune-db://", ""
                )
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
        """Close the connection to the Neptune instance."""
        self.graph = None

    def status(self) -> str:
        """Check the current status of the Neptune instance.

        Returns:
            str: Current status of the Neptune instance ("Available" or "Unavailable")

        Raises:
            AttributeError: If engine type is unknown
        """
        if self._engine_type == EngineType.UNKNOWN:
            raise AttributeError("Engine type is unknown so we cannot fetch the schema")
        try:
            self.query("RETURN 1", QueryLanguage.OPEN_CYPHER)
            return "Available"
        except Exception:
            return "Unavailable"

    def schema(self) -> GraphSchema:
        """Retrieve the schema information from the Neptune instance.

        Returns:
            GraphSchema: Complete schema information for the graph

        Raises:
            AttributeError: If engine type is unknown
        """
        match self._engine_type:
            case EngineType.DATABASE:
                return self._schema_database()
            case EngineType.ANALYTICS:
                return self._schema_analytics()
            case __:
                raise AttributeError("Engine type is unknown so we cannot fetch the schema")

    def query(self, query: str, language: QueryLanguage, parameters: map = None) -> str:
        """Execute a query against the Neptune instance.

        Args:
            query (str): Query string to execute
            language (QueryLanguage): Query language to use (OpenCypher or Gremlin)
            parameters (map, optional): Query parameters. Defaults to None.

        Returns:
            str: Query results

        Raises:
            ValueError: If using unsupported query language for analytics
            AttributeError: If engine type is unknown
        """
        if self._engine_type == EngineType.DATABASE:
            return self._query_database(query, language, parameters)
        elif self._engine_type == EngineType.ANALYTICS:
            if language != QueryLanguage.OPEN_CYPHER:
                raise ValueError("Only openCypher is supported for analytics queries")
            return self._query_analytics(query, parameters)
        else:
            raise AttributeError("Engine type is unknown so we cannot query")

    def _query_analytics(self, query: str, parameters: dict = None):
        """Execute a query against a Neptune Analytics instance.

        Args:
            query (str): Query string to execute
            parameters (dict, optional): Query parameters. Defaults to None.

        Returns:
            str: Query results in UTF-8 encoded string format

        Raises:
            Exception: If query execution fails
        """
        try:
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

    def _query_database(
        self, query: str, language: QueryLanguage, parameters: dict = None
    ):
        """Execute a query against a Neptune Database instance.

        Args:
            query (str): Query string to execute
            language (QueryLanguage): Query language to use
            parameters (dict, optional): Query parameters. Defaults to None.

        Returns:
            dict: Query results

        Raises:
            ValueError: If using unsupported query language
            Exception: If query execution fails
        """
        try:
            if language == QueryLanguage.OPEN_CYPHER:
                if parameters:
                    resp = self.graph.client.execute_open_cypher_query(
                        openCypherQuery=query,
                        parameters=json.dumps(parameters),
                    )
                else:
                    resp = self.graph.client.execute_open_cypher_query(openCypherQuery=query)
            elif language == QueryLanguage.GREMLIN:
                resp = self.graph.client.execute_gremlin_query(
                    gremlinQuery=query,
                    serializer="application/vnd.gremlin-v3.0+json;types=false"
                )
            else:
                raise ValueError("Unsupported language")
            if resp["ResponseMetadata"]["HTTPStatusCode"] == 200:
                return resp["result"] if "result" in resp else resp["results"]
        except Exception as e:
            self._logger.debug(e)
            raise e

    def _schema_analytics(self) -> GraphSchema:
        """Retrieve schema information from a Neptune Analytics instance.

        Returns:
            GraphSchema: Complete schema information for the analytics graph
        """
        pg_schema_query = """
        CALL neptune.graph.pg_schema()
        YIELD schema
        RETURN schema
        """

        data = json.loads(self.query(pg_schema_query, language=QueryLanguage.OPEN_CYPHER))
        raw_schema = data['results'][0]["schema"]
        graph = GraphSchema(nodes=[], relationships=[], relationship_patterns=[])

        for i in raw_schema["labelTriples"]:
            graph.relationship_patterns.append(
                RelationshipPattern(
                    left_node=i['~from'],
                    relation=i['~type'],
                    right_node=i['~to']
                )
            )

        for l in raw_schema["nodeLabels"]:
            details = raw_schema["nodeLabelDetails"][l]
            props = []
            for p in details["properties"]:
                props.append(
                    Property(
                        name=p,
                        type=details["properties"][p]['datatypes']
                    )
                )
            graph.nodes.append(Node(labels=l, properties=props))

        for l in raw_schema["edgeLabels"]:
            details = raw_schema["edgeLabelDetails"][l]
            props = []
            for p in details["properties"]:
                props.append(
                    Property(
                        name=p,
                        type=details["properties"][p]['datatypes']
                    )
                )
            graph.relationships.append(Relationship(type=l, properties=props))

        return asdict(graph)

    def _schema_database(self) -> GraphSchema:
        """Retrieve schema information from a Neptune Database instance.

        Returns:
            GraphSchema: Complete schema information for the database graph
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
                    left_node=parts[0],
                    relation=parts[1],
                    right_node=parts[2]
                )
            )

        for i in node_properties:
            props = []
            for p in i["properties"]:
                props.append(Property(name=p['property'], type=p['type']))
            graph.nodes.append(Node(labels=i['labels'], properties=props))

        for i in edge_properties:
            props = []
            for p in i["properties"]:
                props.append(Property(name=p['property'], type=p['type']))
            graph.relationships.append(Relationship(type=i['type'], properties=props))

        return asdict(graph)

