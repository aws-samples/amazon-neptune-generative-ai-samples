"""
Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

Unit tests for cypher_validator.CypherQueryCorrector. No AWS access is needed.

Run from the application directory:
    pip install pytest
    python -m pytest tests
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cypher_validator import CypherQueryCorrector, CypherValidationError, Schema  # noqa: E402
from llama_index.graph_stores.neptune import NeptuneQueryException  # noqa: E402

SCHEMA = [
    Schema("Document", "DESCRIBES", "Component"),
    Schema("Component", "DEPENDS_ON", "Component"),
    Schema("Vulnerability", "AFFECTS", "Component"),
    Schema("Component", "LICENSED_BY", "License"),
]


@pytest.fixture
def corrector():
    return CypherQueryCorrector(SCHEMA)


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (v:Vulnerability)-[:AFFECTS]->(c:Component) RETURN v.id",
        "MATCH (c:Component)<-[:AFFECTS]-(v:Vulnerability) RETURN v.id",
        "MATCH (c:Component)-[:AFFECTS]-(v:Vulnerability) RETURN count(*)",
        "MATCH (c:Component {name: 'python'})-[:DEPENDS_ON]->(d:Component) RETURN d.name",
        # properties and syntax are not checked
        "MATCH (v:Vulnerability)-[:AFFECTS]->(c:Component) WHERE v.madeUp > 9 RETURN v",
    ],
)
def test_valid_queries_are_unchanged(corrector, query):
    assert corrector(query) == query


def test_reversed_relationship_is_flipped(corrector):
    query = "MATCH (c:Component)-[:AFFECTS]->(v:Vulnerability) RETURN v.id"
    assert corrector(query) == "MATCH (c:Component)<-[:AFFECTS]-(v:Vulnerability) RETURN v.id"


def test_reversed_relationship_is_flipped_in_multi_hop_pattern(corrector):
    query = (
        "MATCH (c:Component)<-[:DESCRIBES]-(d:Document), "
        "(c)-[:AFFECTS]->(v:Vulnerability) RETURN d, v"
    )
    assert corrector(query) == (
        "MATCH (c:Component)<-[:DESCRIBES]-(d:Document), "
        "(c)<-[:AFFECTS]-(v:Vulnerability) RETURN d, v"
    )


def test_unknown_relationship_raises_with_explanation(corrector):
    query = "MATCH (c:Component)-[:FIXED_BY]->(v:Vulnerability) RETURN c"
    with pytest.raises(CypherValidationError) as err:
        corrector(query)
    assert "(:Component)-[:FIXED_BY]-(:Vulnerability)" in err.value.explanation
    # No relationship of that type exists, so the error lists the known types
    assert "AFFECTS, DEPENDS_ON, DESCRIBES, LICENSED_BY" in err.value.explanation
    assert err.value.query == query


def test_known_relationship_between_wrong_labels_lists_valid_patterns(corrector):
    query = "MATCH (l:License)-[:AFFECTS]->(c:Component) RETURN l"
    with pytest.raises(CypherValidationError) as err:
        corrector(query)
    assert "(:Vulnerability)-[:AFFECTS]->(:Component)" in err.value.explanation


def test_error_is_handled_like_a_malformed_neptune_query(corrector):
    """OpenDomainQA's retry loop catches NeptuneQueryException, checks details for
    MalformedQueryException, then reads the query and details from e.args[0]."""
    query = "MATCH (p:Package)-[:DEPENDS_ON]->(c:Component) RETURN p"
    with pytest.raises(NeptuneQueryException) as err:
        corrector(query)
    assert "MalformedQueryException" in err.value.details
    assert err.value.args[0]["query"] == query
    assert err.value.args[0]["details"] == err.value.details
