"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0
"""

from enum import Enum

VULNERABILITY_TEMPLATED_QUERY: str = """
    MATCH (n:Vulnerability {id: $id})
    CALL neptune.algo.vectors.topKByNode(n)
    YIELD node, score
    RETURN node.id as id, node.description as description, score
    ORDER BY score ASC
"""

VULNERABILITY_EXPLAINABILITY_QUERY_NODES: str = """
    MATCH (n:Vulnerability {id: $id})
    CALL neptune.algo.vectors.topKByNode(n)
    YIELD node, score
    WITH n, node ORDER BY score ASC
    MATCH p=(n)-[:AFFECTS]-(c:Component)-[:AFFECTS]-(noe:Vulnerability)
    WITH nodes(p) as nodes
    UNWIND nodes as n
    RETURN collect(distinct n) as nodes
"""

VULNERABILITY_EXPLAINABILITY_QUERY_EDGES: str = """
    MATCH (n:Vulnerability {id: $id})
    CALL neptune.algo.vectors.topKByNode(n)
    YIELD node, score
    WITH n, node ORDER BY score ASC
    MATCH p=(n)-[:AFFECTS]-(c:Component)-[:AFFECTS]-(noe:Vulnerability)
    WITH relationships(p) as edges
    UNWIND edges as e
    RETURN collect(distinct e) as edges
"""

VULNERABILITY_LIST_QUERY: str = """
    MATCH (n:Vulnerability)
    RETURN n.id AS id ORDER BY id
"""
QUERY_TYPES = Enum("QUERY_TYPES", ["Templated", "Explainability", "Unknown"])
