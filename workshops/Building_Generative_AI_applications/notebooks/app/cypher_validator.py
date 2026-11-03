"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0 AND MIT

Relationship validation for generated openCypher queries.

``CypherQueryCorrector`` is used as the ``cypher_validator`` of LlamaIndex's
``TextToCypherRetriever``. It checks the relationships in a generated query against
the graph schema (a list of ``Schema(left_node, relation, right_node)`` triples):

* a relationship written in the wrong direction is rewritten to the right direction
* a relationship that does not exist between those labels in either direction is
  rejected with a ``CypherValidationError`` that explains the problem

Properties, syntax and other parts of the query are not checked.

The detection and correction logic is adapted from LangChain's ``CypherQueryCorrector``
(``langchain-community``, now deprecated and being sunset), which is itself taken from the
winning submission to https://github.com/sakusaku-rich/cypher-direction-competition.
That code is licensed under the MIT License:

    MIT License

    Copyright (c) 2024 LangChain

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

Changes from the LangChain version:

* removed the dependency on LangChain and its deprecation decorator
* a query that cannot be matched to the schema raises ``CypherValidationError``
  instead of returning an empty string, so that the retry logic can pass the
  explanation back to the LLM
"""

import re
from collections import namedtuple
from typing import Any, Dict, List, Optional, Tuple

from llama_index.graph_stores.neptune import NeptuneQueryException

Schema = namedtuple("Schema", ["left_node", "relation", "right_node"])


class CypherValidationError(NeptuneQueryException):
    """A generated query uses a relationship that is not in the graph schema.

    This is a ``NeptuneQueryException`` so that code which already handles query errors
    from the graph store also handles this one. The details are reported as a
    ``MalformedQueryException`` so that a retry loop looking for that error passes the
    explanation back to the LLM to correct the query.
    """

    def __init__(self, explanation: str, query: str):
        payload = {
            "message": explanation,
            "details": f"MalformedQueryException: {explanation}",
            "query": query,
        }
        super().__init__(payload)
        # Code that handles NeptuneQueryException reads e.args[0]["query"] and e.args[0]["details"]
        self.args = (payload,)
        self.query = query
        self.explanation = explanation


class CypherQueryCorrector:
    """
    Used to correct relationship direction in generated Cypher statements.
    This code is copied from the winner's submission to the Cypher competition:
    https://github.com/sakusaku-rich/cypher-direction-competition
    """

    property_pattern = re.compile(r"\{.+?\}")
    node_pattern = re.compile(r"\(.+?\)")
    path_pattern = re.compile(
        r"(\([^\,\(\)]*?(\{.+\})?[^\,\(\)]*?\))(<?-)(\[.*?\])?(->?)(\([^\,\(\)]*?(\{.+\})?[^\,\(\)]*?\))"
    )
    node_relation_node_pattern = re.compile(
        r"(\()+(?P<left_node>[^()]*?)\)(?P<relation>.*?)\((?P<right_node>[^()]*?)(\))+"
    )
    relation_type_pattern = re.compile(r":(?P<relation_type>.+?)?(\{.+\})?]")

    def __init__(self, schemas: List[Schema]):
        """
        Args:
            schemas: list of schemas
        """
        self.schemas = schemas

    def clean_node(self, node: str) -> str:
        """
        Args:
            node: node in string format

        """
        node = re.sub(self.property_pattern, "", node)
        node = node.replace("(", "")
        node = node.replace(")", "")
        node = node.strip()
        return node

    def detect_node_variables(self, query: str) -> Dict[str, List[str]]:
        """
        Args:
            query: cypher query
        """
        nodes = re.findall(self.node_pattern, query)
        nodes = [self.clean_node(node) for node in nodes]
        res: Dict[str, Any] = {}
        for node in nodes:
            parts = node.split(":")
            if parts == "":
                continue
            variable = parts[0]
            if variable not in res:
                res[variable] = []
            res[variable] += parts[1:]
        return res

    def extract_paths(self, query: str) -> "List[str]":
        """
        Args:
            query: cypher query
        """
        paths = []
        idx = 0
        while matched := self.path_pattern.findall(query[idx:]):
            matched = matched[0]
            matched = [
                m for i, m in enumerate(matched) if i not in [1, len(matched) - 1]
            ]
            path = "".join(matched)
            idx = query.find(path) + len(path) - len(matched[-1])
            paths.append(path)
        return paths

    def judge_direction(self, relation: str) -> str:
        """
        Args:
            relation: relation in string format
        """
        direction = "BIDIRECTIONAL"
        if relation[0] == "<":
            direction = "INCOMING"
        if relation[-1] == ">":
            direction = "OUTGOING"
        return direction

    def extract_node_variable(self, part: str) -> Optional[str]:
        """
        Args:
            part: node in string format
        """
        part = part.lstrip("(").rstrip(")")
        idx = part.find(":")
        if idx != -1:
            part = part[:idx]
        return None if part == "" else part

    def detect_labels(
        self, str_node: str, node_variable_dict: Dict[str, Any]
    ) -> List[str]:
        """
        Args:
            str_node: node in string format
            node_variable_dict: dictionary of node variables
        """
        splitted_node = str_node.split(":")
        variable = splitted_node[0]
        labels = []
        if variable in node_variable_dict:
            labels = node_variable_dict[variable]
        elif variable == "" and len(splitted_node) > 1:
            labels = splitted_node[1:]
        return labels

    def verify_schema(
        self,
        from_node_labels: List[str],
        relation_types: List[str],
        to_node_labels: List[str],
    ) -> bool:
        """
        Args:
            from_node_labels: labels of the from node
            relation_type: type of the relation
            to_node_labels: labels of the to node
        """
        valid_schemas = self.schemas
        if from_node_labels != []:
            from_node_labels = [label.strip("`") for label in from_node_labels]
            valid_schemas = [
                schema for schema in valid_schemas if schema[0] in from_node_labels
            ]
        if to_node_labels != []:
            to_node_labels = [label.strip("`") for label in to_node_labels]
            valid_schemas = [
                schema for schema in valid_schemas if schema[2] in to_node_labels
            ]
        if relation_types != []:
            relation_types = [type.strip("`") for type in relation_types]
            valid_schemas = [
                schema for schema in valid_schemas if schema[1] in relation_types
            ]
        return valid_schemas != []

    def detect_relation_types(self, str_relation: str) -> Tuple[str, List[str]]:
        """
        Args:
            str_relation: relation in string format
        """
        relation_direction = self.judge_direction(str_relation)
        relation_type = self.relation_type_pattern.search(str_relation)
        if relation_type is None or relation_type.group("relation_type") is None:
            return relation_direction, []
        relation_types = [
            t.strip().strip("!")
            for t in relation_type.group("relation_type").split("|")
        ]
        return relation_direction, relation_types

    def correct_query(self, query: str) -> str:
        """
        Args:
            query: cypher query
        """
        original_query = query
        node_variable_dict = self.detect_node_variables(query)
        paths = self.extract_paths(query)
        for path in paths:
            original_path = path
            start_idx = 0
            while start_idx < len(path):
                match_res = re.match(self.node_relation_node_pattern, path[start_idx:])
                if match_res is None:
                    break
                start_idx += match_res.start()
                match_dict = match_res.groupdict()
                left_node_labels = self.detect_labels(
                    match_dict["left_node"], node_variable_dict
                )
                right_node_labels = self.detect_labels(
                    match_dict["right_node"], node_variable_dict
                )
                end_idx = (
                    start_idx
                    + 4
                    + len(match_dict["left_node"])
                    + len(match_dict["relation"])
                    + len(match_dict["right_node"])
                )
                original_partial_path = original_path[start_idx : end_idx + 1]
                relation_direction, relation_types = self.detect_relation_types(
                    match_dict["relation"]
                )

                if relation_types != [] and "".join(relation_types).find("*") != -1:
                    start_idx += (
                        len(match_dict["left_node"]) + len(match_dict["relation"]) + 2
                    )
                    continue

                if relation_direction == "OUTGOING":
                    is_legal = self.verify_schema(
                        left_node_labels, relation_types, right_node_labels
                    )
                    if not is_legal:
                        is_legal = self.verify_schema(
                            right_node_labels, relation_types, left_node_labels
                        )
                        if is_legal:
                            corrected_relation = "<" + match_dict["relation"][:-1]
                            corrected_partial_path = original_partial_path.replace(
                                match_dict["relation"], corrected_relation
                            )
                            query = query.replace(
                                original_partial_path, corrected_partial_path
                            )
                        else:
                            raise self._reject(
                                original_query,
                                left_node_labels,
                                relation_types,
                                right_node_labels,
                            )
                elif relation_direction == "INCOMING":
                    is_legal = self.verify_schema(
                        right_node_labels, relation_types, left_node_labels
                    )
                    if not is_legal:
                        is_legal = self.verify_schema(
                            left_node_labels, relation_types, right_node_labels
                        )
                        if is_legal:
                            corrected_relation = match_dict["relation"][1:] + ">"
                            corrected_partial_path = original_partial_path.replace(
                                match_dict["relation"], corrected_relation
                            )
                            query = query.replace(
                                original_partial_path, corrected_partial_path
                            )
                        else:
                            raise self._reject(
                                original_query,
                                left_node_labels,
                                relation_types,
                                right_node_labels,
                            )
                else:
                    is_legal = self.verify_schema(
                        left_node_labels, relation_types, right_node_labels
                    )
                    is_legal |= self.verify_schema(
                        right_node_labels, relation_types, left_node_labels
                    )
                    if not is_legal:
                        raise self._reject(
                            original_query,
                            left_node_labels,
                            relation_types,
                            right_node_labels,
                        )

                start_idx += (
                    len(match_dict["left_node"]) + len(match_dict["relation"]) + 2
                )
        return query

    def _reject(
        self,
        query: str,
        left_node_labels: List[str],
        relation_types: List[str],
        right_node_labels: List[str],
    ) -> CypherValidationError:
        """Build the error for a relationship that is not in the schema.

        Args:
            query: the query that was being validated
            left_node_labels: labels of the node on the left of the relationship
            relation_types: relationship types in the query
            right_node_labels: labels of the node on the right of the relationship
        """

        def clean(names: List[str]) -> List[str]:
            return [name.strip("`") for name in names]

        left = ":".join(clean(left_node_labels)) or "any label"
        right = ":".join(clean(right_node_labels)) or "any label"
        types = "|".join(clean(relation_types)) or "any type"
        explanation = (
            f"The relationship (:{left})-[:{types}]-(:{right}) does not exist in the "
            "graph schema in either direction."
        )
        # Point at what does exist: the same relationship types if there are any,
        # otherwise every relationship type in the schema
        same_type = [s for s in self.schemas if s.relation in clean(relation_types)]
        if same_type:
            options = "; ".join(
                f"(:{s.left_node})-[:{s.relation}]->(:{s.right_node})"
                for s in same_type
            )
            explanation += f" The schema has: {options}."
        else:
            known = ", ".join(sorted({s.relation for s in self.schemas}))
            explanation += f" The relationship types in the schema are: {known}."
        return CypherValidationError(explanation, query)

    def __call__(self, query: str) -> str:
        """Correct the relationship directions in a query.

        Args:
            query: cypher query

        Returns:
            The query, with any relationship written in the wrong direction flipped

        Raises:
            CypherValidationError: a relationship is not in the schema in either direction
        """
        return self.correct_query(query)
