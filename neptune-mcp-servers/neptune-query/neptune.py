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
import re
from models import QueryLanguage


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
        self.graph = None

    def status(self) -> str:
        if self._engine_type == EngineType.UNKNOWN:
            raise AttributeError("Engine type is unknown so we cannot fetch the schema")
        try:
            self.query("RETURN 1", QueryLanguage.OPENCYPHER)
            return "Available"
        except Exception:
            return "Unavailabe"

    def schema(self) -> str:
        if self._engine_type == EngineType.UNKNOWN:
            raise AttributeError("Engine type is unknown so we cannot fetch the schema")

        return self.graph.schema

    def query(self, query: str, language: QueryLanguage, parameters: map = None) -> str:
        if self._engine_type == EngineType.DATABASE:
            return self._query_database(query, language, parameters)
        elif self._engine_type == EngineType.ANALYTICS:
            if language != QueryLanguage.OPEN_CYPHER:
                raise ValueError("Only openCypher is supported for analytics queries")
            return self._query_analytics(query, parameters)
        else:
            raise AttributeError("Engine type is unknown so we cannot query")


    def _query_analytics(self, query:str, parameters:dict = None):
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
                    resp = self.graph.client.execute_open_cypher_query(openCypherQuery=query)
            elif language == QueryLanguage.GREMLIN:
                resp = self.graph.client.execute_gremlin_query(gremlinQuery=query, serializer="application/vnd.gremlin-v3.0+json;types=false")
            else:
                raise ValueError("Unsupported language")
            if resp["ResponseMetadata"]["HTTPStatusCode"] == 200:
                return resp["result"] if "result" in resp else resp["results"]
        except Exception as e:
            self._logger.debug(e)
            raise e
