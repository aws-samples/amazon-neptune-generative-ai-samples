# MIT No Attribution
#
# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this
# software and associated documentation files (the "Software"), to deal in the Software
# without restriction, including without limitation the rights to use, copy, modify,
# merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
# PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# SPDX-License-Identifier: MIT-0
"""reference.py — the reference answers: what the main path runs, and what Go deeper's
exercises are checked against. When an exercise passes, its answer is saved to solution/
and the MCP server runs that file instead of this one."""
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer

from agent.policy_ids import aggregate_updates

ser = TypeSerializer()


def _ctx():
    from agent.session import _state
    return _state["ctx"]


# G.1 · the evidence Query
def get_evidence(evaluation_id):
    ctx = _ctx()
    return ctx.dynamodb.Table(ctx.TRACES_TABLE).query(
        KeyConditionExpression=Key("PK").eq(f"EVAL#{evaluation_id}"), ConsistentRead=True)["Items"]


# G.2 · one decision, one transaction
def record_decision(evaluation_id, decision, now):
    ctx = _ctx()
    pk = f"EVAL#{evaluation_id}"
    actions = [
        {"Put": {"TableName": ctx.TRACES_TABLE,
                 "Item": {k: ser.serialize(v) for k, v in decision.items()},
                 "ConditionExpression": "attribute_not_exists(PK)"}},
        {"Update": {"TableName": ctx.TRACES_TABLE,
                    "Key": {"PK": {"S": pk}, "SK": {"S": "META"}},
                    "UpdateExpression": "SET #s = :done, completed_at = :now",
                    "ConditionExpression": "#s = :running",
                    "ExpressionAttributeNames": {"#s": "status"},
                    "ExpressionAttributeValues": {":done": {"S": "COMPLETE"},
                                                  ":running": {"S": "IN_PROGRESS"},
                                                  ":now": {"S": now}}}},
    ]
    actions += aggregate_updates(ctx.TRACES_TABLE, decision, now)
    ctx.dynamodb_client.transact_write_items(TransactItems=actions)


# G.3 · the monthly counts
def policy_months(policy):
    ctx = _ctx()
    return ctx.dynamodb.Table(ctx.TRACES_TABLE).query(
        KeyConditionExpression=Key("PK").eq(f"POLICY#{policy}") & Key("SK").begins_with("MONTH#"),
        ReturnConsumedCapacity="TOTAL")


# G.6 · WHERE NOT: denials that failed II.A.5.d and cite a policy no search returned
UNGROUNDED = """
MATCH (:Policy {`~id`: $ratio_rule})<-[:VIOLATED]-(d:Decision {outcome: 'deny'})
MATCH (d)-[c:CITED_POLICY]->(p:Policy)
WHERE NOT (d)-[:RETRIEVED_POLICY]->(p)
RETURN d.application_id AS application, p.id AS policy, c.reference AS cited_as
"""

# G.9 · the edition query (option B: one hop, the edition on the edge)
EDITIONS = """
MATCH (p:Policy {`~id`: $policy})<-[r:RETRIEVED_POLICY]-(d:Decision {outcome: 'deny'})
WHERE r.issued < $current
RETURN r.issued AS edition_issued, count(DISTINCT d) AS denials
ORDER BY edition_issued
"""

# Page 3 · the lineage walk from a model version
WALK = """
MATCH (v:Version {`~id`: $source})
CALL neptune.algo.bfs.levels(v, {traversalDirection: 'inbound',
     edgeLabels: ['PRODUCED_BY', 'DERIVED_FROM', 'IDENTITY_FROM', 'USED', 'RESTS_ON']})
YIELD node, level
WHERE 'Decision' IN labels(node) OR 'Notice' IN labels(node)
RETURN head(labels(node)) AS kind, node.outcome AS outcome,
       node.day > $fixed AS after_fix, count(node) AS found, max(level) AS deepest
"""

# G.7 · a paragraph-level check: of the passages a decision read from a cited policy, the
# ones that contain the cited paragraph's heading (a hint, not proof: passages don't line up
# with paragraphs)
PARAGRAPH = """
MATCH (d:Decision {`~id`: $decision})-[c:CITED_POLICY]->(p:Policy {`~id`: $policy})
MATCH (d)-[:READ]->(ch:Chunk)
WHERE ch.`metadata_x-amz-bedrock-kb-source-uri` CONTAINS replace(p.id, ' ', '-')
RETURN c.reference AS cited_as, count(ch) AS passages_read,
       sum(CASE WHEN ch.text CONTAINS $paragraph THEN 1 ELSE 0 END) AS with_heading
"""

# G.8 · the nearest passages, from each passage a decision read (its stored embedding)
NEAREST = """
MATCH (d:Decision {`~id`: $decision})-[:READ]->(c:Chunk)
CALL neptune.algo.vectors.topK.byNode(c, {topK: 4})
YIELD node, score
WITH c, node, score WHERE id(node) <> id(c)
RETURN id(c) AS passage_read, id(node) AS nearest, score
ORDER BY passage_read, score
"""

# G.11 · what needs a graph: decisions that read the same passages as this one
SAME_PASSAGES = """
MATCH (m:Decision {`~id`: $decision})-[:READ]->(c:Chunk)<-[:READ]-(other:Decision)
WHERE id(other) <> id(m)
RETURN other.application_id AS application, other.outcome AS outcome,
       count(DISTINCT c) AS shared_passages
ORDER BY shared_passages DESC, application
"""

# G.12 · Carlos's past peers that cite a policy never retrieved
PEERS_UNGROUNDED = """
MATCH (d:Decision)-[:IN_BAND]->(:Band {`~id`: $credit})
MATCH (d)-[:IN_BAND]->(:Band {`~id`: $dti})
MATCH (d)-[:IN_BAND]->(:Band {`~id`: $ltv})
MATCH (d)-[:CITED_POLICY]->(p:Policy)
WHERE d.historical = true AND NOT (d)-[:RETRIEVED_POLICY]->(p)
RETURN p.id AS cited_never_retrieved, count(DISTINCT d) AS decisions
ORDER BY decisions DESC
"""


# The answer files the MCP server runs, as the exercises save them. 03 Kiro.ipynb's K.2 saves
# the reference for any you didn't write (save_reference_answers); yours are never replaced.
SOURCES = {
    "get_evidence.py": '''def get_evidence(evaluation_id):
    return trace_table.query(
        KeyConditionExpression=Key("PK").eq(f"EVAL#{evaluation_id}"),
        ConsistentRead=True,
    )["Items"]
''',
    "policy_months.py": '''def policy_months(policy):
    return trace_table.query(
        KeyConditionExpression=Key("PK").eq(f"POLICY#{policy}") & Key("SK").begins_with("MONTH#"),
        ReturnConsumedCapacity="TOTAL",
    )
''',
    "ungrounded_citations.cypher": UNGROUNDED,
    "lineage_walk.cypher": WALK,
}
