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
"""transform.py — the reference stream transform: option B, what decisions share.

Deployed by Cell 0.1 (deploy_reference_transform) as the dat408-stream-processor Lambda's
index.py; Go deeper's G.4 is this file with three TODOs. Each DynamoDB Stream record is one
STEP# item. The transform projects it onto the decision it belongs to:

  (:Application)-[:HAS_DECISION]->(:Decision)
  (:Decision)-[:RETRIEVED_POLICY {issued, version}]->(:Policy)   each search's policies and edition
  (:Decision)-[:READ]->(:Chunk)                                  the exact passages it was given
  (:Decision)-[:USED_TOOL]->(:Tool)
  (:Decision)-[:CITED_POLICY {reference}]->(:Policy)             what it said it relied on
  (:Decision)-[:VIOLATED]->(:Policy)                             what it said the application failed
  (:Decision)-[:IN_BAND]->(:Band)                                its credit, DTI and LTV bands

Steps stay in DynamoDB: one Query on EVAL#<id> returns them in order. Every node is MERGEd
on an id taken from the record, so a replay, or records arriving out of order, add nothing.
"""
import json
import os
import re

import boto3

neptune_client = boto3.client("neptune-graph")
GRAPH_ID = os.environ["GRAPH_ID"]

# Canonical policy ids: every citation form ("HUD 4000.1 II.A.5.d viii", "12 CFR § 1002.9(a)(2)")
# lands on the same Policy node as the search that returned it.
HUD_RE = re.compile(r"(?:HUD\s*)?4000\.1\s+([IVX]+\.[A-Z]\.\d+\.[a-z])")
CFR_RE = re.compile(r"12\s*C\.?F\.?R\.?\s*(?:§\s*)?(\d{4}\.\d+)")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
ISSUED_RE = re.compile(r"issued (\d{4}-\d{2}-\d{2})")


def normalize_policy_id(raw):
    text = str(raw or "")
    m = HUD_RE.search(text)
    if m:
        return f"HUD 4000.1 {m.group(1)}"
    m = CFR_RE.search(text)
    if m:
        return f"12 CFR {m.group(1)}"
    return None


def _day_short(day):
    """'2026-10-22' as 'Oct 22', the label the lineage view shows on a decision."""
    import datetime
    try:
        d = datetime.date.fromisoformat(day)
        return f"{d:%b} {d.day}"
    except ValueError:
        return day


def strings(image, field):
    return [v.get("S", "") for v in image.get(field, {}).get("L", [])]


def execute_query(query, parameters=None):
    response = neptune_client.execute_query(graphIdentifier=GRAPH_ID, queryString=query,
                                            language="OPEN_CYPHER", parameters=parameters or {})
    return json.loads(response["payload"].read())


def retrieved_policies(image):
    """[{id, issued, version}] for each policy a search returned. `issued` is the edition's
    issue date ("Update 18, issued 2026-08-12; ..."), or the date a regulation's text is as of."""
    versions = {normalize_policy_id(k): v.get("S", "unknown")
                for k, v in image.get("retrieved_policy_versions", {}).get("M", {}).items()}
    out = []
    for pid in sorted({normalize_policy_id(p) for p in strings(image, "retrieved_policy_ids")} - {None}):
        version = versions.get(pid, "unknown")
        # The edition's issue date, not a section's effective date ("...; section effective ...").
        m = ISSUED_RE.search(version) or DATE_RE.search(version)
        out.append({"id": pid, "issued": m.group(1) if m else "", "version": version})
    return out


def remove_step(keys):
    """TTL expired a step in DynamoDB. When its decision step expires, the decision goes from
    the graph too; the graph never keeps evidence the record has dropped."""
    evaluation_id = keys["PK"]["S"].replace("EVAL#", "")
    execute_query("""
        MATCH (d:Decision {`~id`: $dec_gid})
        WHERE d.historical IS NULL AND d.decision_step = $sk
        DETACH DELETE d
    """, {"dec_gid": f"decision:{evaluation_id}_decision", "sk": keys["SK"]["S"]})


def project_lineage(image, dec_gid, day, evaluation_id):
    """The artifact a step produced and what it was built from (history v3's labels and edges),
    and on the decision step, the artifacts the decision used. Runs from before the runtime
    recorded lineage carry none of these fields, and are skipped."""
    art = image.get("artifact_id", {}).get("S")
    if art:
        ups = [{k: v["S"] for k, v in u["M"].items()} for u in image.get("upstream", {}).get("L", [])]
        execute_query("""
            MERGE (x:Artifact {`~id`: $art})
            ON CREATE SET x.kind = $kind, x.day = $day, x.run = $run
        """, {"art": art, "kind": image.get("artifact_kind", {}).get("S", ""), "day": day, "run": evaluation_id})
        for edge in ("DERIVED_FROM", "IDENTITY_FROM"):
            for label in ("Artifact", "FeedBatch"):
                ids = [u["id"] for u in ups if u["edge"] == edge and u["label"] == label]
                if ids:
                    execute_query(f"""
                        MATCH (x:Artifact {{`~id`: $art}})
                        UNWIND $ids AS uid
                        MERGE (u:{label} {{`~id`: uid}})
                        MERGE (x)-[:{edge}]->(u)
                    """, {"art": art, "ids": ids})
    used = strings(image, "used_artifacts")
    if used:
        execute_query("""
            MATCH (d:Decision {`~id`: $dec_gid})
            UNWIND $ids AS aid
            MERGE (a:Artifact {`~id`: aid})
            MERGE (d)-[:USED]->(a)
        """, {"dec_gid": dec_gid, "ids": used})


def project_step(image):
    """Project one step onto its decision."""
    evaluation_id = image["PK"]["S"].replace("EVAL#", "")
    application_id = image["application_id"]["S"]
    action = image.get("action", {}).get("S", "")
    timestamp = image.get("step_timestamp", {}).get("S", "")
    is_decision = image.get("is_decision", {}).get("BOOL", False)
    decision_id = f"{evaluation_id}_decision"

    # The hub: the application and its decision. Every step MERGEs it, so steps can arrive
    # in any order, or twice.
    execute_query("""
        MERGE (a:Application {`~id`: $app_gid})
        ON CREATE SET a.id = $app_id, a.application_id = $app_id
        MERGE (d:Decision {`~id`: $dec_gid})
        ON CREATE SET d.id = $dec_id, d.application_id = $app_id, d.evaluation_id = $eval_id
        MERGE (a)-[:HAS_DECISION]->(d)
    """, {"app_gid": f"app:{application_id}", "app_id": application_id, "dec_gid": f"decision:{decision_id}",
          "dec_id": decision_id, "eval_id": evaluation_id})

    project_lineage(image, f"decision:{decision_id}", timestamp[:10], evaluation_id)

    if not is_decision:
        # What this step used: its tool, and for a search, each policy with its edition and
        # the passages it returned.
        execute_query("""
            MATCH (d:Decision {`~id`: $dec_gid})
            MATCH (t:Tool {`~id`: "tool:" + $tool})
            MERGE (d)-[:USED_TOOL]->(t)
            WITH d
            UNWIND $policies AS pol
            MERGE (p:Policy {`~id`: "policy:" + pol.id}) ON CREATE SET p.id = pol.id
            MERGE (d)-[r:RETRIEVED_POLICY {issued: pol.issued}]->(p)
            SET r.version = pol.version
        """, {"dec_gid": f"decision:{decision_id}", "tool": action, "policies": retrieved_policies(image)})
        chunks = strings(image, "retrieved_chunk_ids")
        if chunks:
            execute_query("""
                MATCH (d:Decision {`~id`: $dec_gid})
                UNWIND $chunks AS cid
                MATCH (c:Chunk) WHERE id(c) = cid
                MERGE (d)-[:READ]->(c)
            """, {"dec_gid": f"decision:{decision_id}", "chunks": chunks})
        return

    # The decision step: what it said, what it failed, and its bands.
    execute_query("""
        MATCH (d:Decision {`~id`: $dec_gid})
        SET d.outcome = $outcome, d.day = $day, d.day_short = $day_short, d.reasoning = $reasoning,
            d.decision_step = $sk,
            d.citation_check = $check
    """, {"dec_gid": f"decision:{decision_id}", "outcome": image.get("outcome", {}).get("S", "unknown"),
          "day": timestamp[:10], "day_short": _day_short(timestamp[:10]), "reasoning": image.get("reasoning", {}).get("S", "")[:1000],
          "sk": image["SK"]["S"], "check": image.get("citation_check", {}).get("S", "")})
    cited = [{"id": normalize_policy_id(r), "ref": r} for r in strings(image, "policies_cited")]
    violated = sorted({normalize_policy_id(r) for r in strings(image, "policies_violated")} - {None})
    bands = [image[b]["S"] for b in ("credit_band", "dti_band", "ltv_band") if b in image]
    execute_query("""
        MATCH (d:Decision {`~id`: $dec_gid})
        UNWIND $cited AS c
        MERGE (p:Policy {`~id`: "policy:" + c.id}) ON CREATE SET p.id = c.id
        MERGE (d)-[:CITED_POLICY {reference: c.ref}]->(p)
    """, {"dec_gid": f"decision:{decision_id}", "cited": [c for c in cited if c["id"]]})
    execute_query("""
        MATCH (d:Decision {`~id`: $dec_gid})
        UNWIND $violated AS pid
        MERGE (p:Policy {`~id`: "policy:" + pid}) ON CREATE SET p.id = pid
        MERGE (d)-[:VIOLATED]->(p)
    """, {"dec_gid": f"decision:{decision_id}", "violated": violated})
    execute_query("""
        MATCH (d:Decision {`~id`: $dec_gid})
        UNWIND $bands AS bid
        MATCH (b:Band {`~id`: "band:" + bid})
        MERGE (d)-[:IN_BAND]->(b)
    """, {"dec_gid": f"decision:{decision_id}", "bands": bands})


def handler(event, context):
    """Each record on its own; report only the ones that fail, so one bad record doesn't
    block the stream (failed records are retried, then sent to the dead-letter queue)."""
    failures = []
    for record in event.get("Records", []):
        try:
            if record.get("eventName") == "REMOVE":
                remove_step(record["dynamodb"]["Keys"])
            else:
                project_step(record["dynamodb"]["NewImage"])
        except Exception as e:
            print(f"failed {record.get('dynamodb', {}).get('SequenceNumber')}: {e}")
            failures.append({"itemIdentifier": record["dynamodb"]["SequenceNumber"]})
    return {"batchItemFailures": failures}
