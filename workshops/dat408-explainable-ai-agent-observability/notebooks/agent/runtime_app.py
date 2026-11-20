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
"""
runtime_app.py — the AgentCore Runtime entrypoint for the DAT408 underwriting agent.

This is the file that runs INSIDE Amazon Bedrock AgentCore Runtime. AgentCore
serves it over the standard /invocations + /ping HTTP contract (that is what
`app.run()` starts), and provides operational observability for free: every
invocation is traced (latency, spans, errors) into X-Ray, with metrics in CloudWatch under the
`AWS/Bedrock-AgentCore` namespace, with no instrumentation code here.

The point of DAT408 is the contrast: that built-in observability tells you the
agent RAN and how fast, but not WHY it decided what it did. So this entrypoint
also captures decision evidence — every ReAct step — into DynamoDB from inside
the runtime. Those writes flow through DynamoDB Streams -> Lambda -> Neptune to
build the queryable evidence graph the later modules investigate.

Invocation payload (JSON):
    {"application_id": "LA-2026-00148"}      # loaded from the applications table
  or
    {"application": { ...full application dict... }}   # evaluated as-is

Response (JSON): the decision dict from UnderwritingAgent.evaluate().

Packaged by lambda_build_agent_package.py: this file sits at the zip root and
the rest of the agent package ships as `agent/`, so `from agent.* import ...`
resolves. Container env vars (set by the packaging custom resource):
KB_ID, TRACES_TABLE, APPLICATIONS_TABLE, BEDROCK_MODEL_ID, AWS_REGION.
"""
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agent import init_tools, init_applications, get_application
from agent.underwriting_agent import UnderwritingAgent, SYSTEM_PROMPT
from agent.policy_ids import aggregate_updates, normalize_policy_id
from agent.bands import bands_for

# AgentCore may or may not inject AWS_REGION into the container; DAT408_REGION is
# passed explicitly by the packaging custom resource (the stack's region) so the
# runtime's boto3 clients are correct in any deploy region, not just us-east-1.
REGION = (os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
          or os.environ.get("DAT408_REGION") or "us-east-1")
KB_ID = os.environ.get("KB_ID", "")
TRACES_TABLE = os.environ.get("TRACES_TABLE", "dat408-agent-traces")
APPLICATIONS_TABLE = os.environ.get("APPLICATIONS_TABLE", "dat408-applications")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-5")
# Full tool outputs go here; the evidence item keeps a pointer and a SHA-256 hash.
EVIDENCE_BUCKET = os.environ.get("EVIDENCE_BUCKET", "")
# The Knowledge Base ingestion job that loaded the policies this runtime reads.
KB_INGESTION_JOB_ID = os.environ.get("KB_INGESTION_JOB_ID", "unknown")
# Which instructions produced a decision: a short hash of the system prompt.
PROMPT_VERSION = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:12]
# Which code produced it: a short hash of this runtime and the agent package's source.
_here = os.path.dirname(os.path.abspath(__file__))
AGENT_BUILD = hashlib.sha256(b"".join(
    open(os.path.join(root, f), "rb").read()
    for root in (_here, os.path.join(_here, "agent")) if os.path.isdir(root)
    for f in sorted(os.listdir(root)) if f.endswith(".py"))).hexdigest()[:12]

# The citation check, before a decision is recorded: a cited policy that no search in
# this evaluation returned. "annotate" records the decision and flags it; "escalate"
# records an escalation for an underwriter and keeps the original decision.
CITATION_CHECK_MODES = ("annotate", "escalate")
# Test-only: for LA-TEST- applications, the runtime can add one citation the evaluation's
# own searches didn't return, recorded as test_injection. Production builds strip it.
TEST_CITATIONS = ["12 CFR 1026.43", "HUD 4000.1 II.A.5.b", "HUD 4000.1 II.A.5.a", "12 CFR 1002.9"]

# Retention. TTL deletes; it does not retain. Regulation B (12 CFR 1002.12(b))
# requires keeping application records 25 months after notice of action taken;
# this institution keeps denials 7 years. Point-in-time recovery (enabled on the
# table) and backups are what protect the evidence until then.
RETAIN_DEFAULT_SECONDS = 25 * 31 * 86400      # Reg B minimum, rounded up
RETAIN_DENIAL_SECONDS = 7 * 365 * 86400       # institution policy: anything not approved

# Initialize the agent package once, at container start (not per invocation).
init_tools(region=REGION, knowledge_base_id=KB_ID)
init_applications(region=REGION, table_name=APPLICATIONS_TABLE)

_traces_table = boto3.resource("dynamodb", region_name=REGION).Table(TRACES_TABLE)
_ddb = boto3.client("dynamodb", region_name=REGION)
_s3 = boto3.client("s3", region_name=REGION)
_steps_written = {}   # evaluation_id -> step sort keys written (for the retention update)
_seen = {}            # evaluation_id -> {"retrieved": policy ids returned, "facts": typed values read}

app = BedrockAgentCoreApp()


def _typed_facts(action, observation):
    """Key evidence values as typed attributes, queryable without parsing JSON."""
    o = observation if isinstance(observation, dict) else {}
    facts = {
        "pull_credit_report": {"credit_score": o.get("credit_score"),
                               "derogatory_marks": o.get("derogatory_marks")},
        "verify_income": {"verified_annual_income": o.get("verified_annual_income")},
        "calculate_dti": {"back_end_dti_pct": (o.get("back_end_dti_ratio") or 0) * 100 or None,
                          "front_end_dti_pct": (o.get("front_end_dti_ratio") or 0) * 100 or None},
        "evaluate_collateral": {"ltv_pct": (o.get("ltv_ratio") or 0) * 100 or None},
    }.get(action, {})
    return {k: Decimal(str(round(v, 2))) for k, v in facts.items() if isinstance(v, (int, float))}


def _write_header(evaluation_id, application_id, now):
    """One header item per evaluation (SK = META): its status and exactly which
    model, prompt and policy ingestion produced it. Created once, IN_PROGRESS. It carries
    step_timestamp too, the sort key of prompt-index, which indexes only items that have it."""
    _traces_table.put_item(
        Item={"PK": f"EVAL#{evaluation_id}", "SK": "META", "evaluation_id": evaluation_id,
              "application_id": application_id, "status": "IN_PROGRESS", "started_at": now,
              "step_timestamp": now, "model_id": BEDROCK_MODEL_ID, "prompt_version": PROMPT_VERSION, "agent_build": AGENT_BUILD,
              "knowledge_base_id": KB_ID, "kb_ingestion_job_id": KB_INGESTION_JOB_ID},
        ConditionExpression="attribute_not_exists(PK)")


# The lineage each step records (history v3's shape): the artifact a step produced, and what it
# was built from, so live runs join the same graph walks as the history. The tools are unchanged;
# the runtime adds these ids as it records each step. Today's tools read no documents, so a live
# run's income comes from the EVOE feed.
LINEAGE = {
    "pull_credit_report": ("credit", lambda ev, day: [("feed:bureau:" + day, "FeedBatch", "DERIVED_FROM")]),
    "verify_income": ("income", lambda ev, day: [("feed:evoe:" + day, "FeedBatch", "DERIVED_FROM"),
                                                ("feed:evoe:" + day, "FeedBatch", "IDENTITY_FROM")]),
    "calculate_dti": ("ratios", lambda ev, day: [(f"art:income:{ev}", "Artifact", "DERIVED_FROM"),
                                                (f"art:credit:{ev}", "Artifact", "DERIVED_FROM")]),
    "evaluate_collateral": ("collateral", lambda ev, day: []),
}


def lineage_fields(evaluation_id, action, day):
    """The step's artifact_id and upstream ids, for the transform to project."""
    if action == "FINAL_DECISION":
        return {"used_artifacts": [f"art:{k}:{evaluation_id}" for k in ("income", "ratios", "credit", "collateral")]}
    if action not in LINEAGE:
        return {}
    kind, ups = LINEAGE[action]
    return {"artifact_id": f"art:{kind}:{evaluation_id}", "artifact_kind": kind,
            "upstream": [{"id": i, "label": l, "edge": e} for i, l, e in ups(evaluation_id, day)]}


def check_citations(decision, retrieved, mode="annotate", inject=False):
    """Compare the decision's citations with the policies its searches returned, before
    it is recorded. Changes `decision` in place and returns the fields to record."""
    fields = {}
    if inject:
        extra = next((p for p in TEST_CITATIONS if p not in retrieved), None)
        if extra:
            decision["policies_cited"] = list(decision.get("policies_cited", [])) + [extra]
            fields["test_injection"] = extra
    cited = {normalize_policy_id(p) for p in decision.get("policies_cited", [])} - {None}
    bad = sorted(cited - set(retrieved))
    fields["citation_check"] = "FAILED" if bad else "PASSED"
    if bad:
        fields["ungrounded_citations"] = bad
        fields["ungrounded_month"] = datetime.now(timezone.utc).strftime("%Y-%m")
        if mode == "escalate" and decision.get("decision") != "escalate":
            fields["original_decision"] = decision.get("decision")
            fields["escalation_reason"] = "cited a policy no retrieval returned: " + ", ".join(bad)
            decision["decision"] = "escalate"
    decision["citation_check"] = fields["citation_check"]
    if bad:
        decision["ungrounded_citations"] = bad
    return fields


def _emit_trace_event(evaluation_id, step_num, thought, action, action_input,
                      observation, application_id, settings=None):
    """Write one ReAct step to the decision-evidence table, write-once.

    Each step item is created with attribute_not_exists, so evidence can never be
    silently overwritten. The full tool output goes to S3; the item keeps its URI,
    a SHA-256 hash (tamper evidence) and typed key values. The final decision is
    written in one transaction with the header status, the retention date of every
    step, and the per-policy aggregates, so they can never disagree."""
    now = datetime.now(timezone.utc).isoformat()
    pk, sk = f"EVAL#{evaluation_id}", f"STEP#{step_num:03d}"
    if evaluation_id not in _steps_written:
        _steps_written[evaluation_id] = []
        _seen[evaluation_id] = {"retrieved": set(), "facts": {}}
        _write_header(evaluation_id, application_id, now)
    seen = _seen[evaluation_id]
    settings = settings or {}
    if action == "FINAL_DECISION" and isinstance(observation, dict):
        # The check runs before anything about the decision is written.
        check = check_citations(observation, seen["retrieved"], settings.get("mode", "annotate"),
                                settings.get("inject", False))
    obs_json = json.dumps(observation, default=str) if isinstance(observation, dict) else str(observation)
    is_decision = (action == "FINAL_DECISION")
    item = {
        "PK": pk, "SK": sk,
        "evaluation_id": evaluation_id, "application_id": application_id,
        "step_num": step_num, "step_timestamp": now,
        "thought": (thought or "")[:1000], "action": action,
        "action_input": (action_input[:1000] if isinstance(action_input, str)
                         else json.dumps(action_input, default=str)[:1000]),
        "observation_summary": obs_json[:2000], "is_decision": is_decision,
        "observation_sha256": hashlib.sha256(obs_json.encode()).hexdigest(),
        **_typed_facts(action, observation),
        **lineage_fields(evaluation_id, action, now[:10]),
    }
    if EVIDENCE_BUCKET:
        key = f"evidence/{evaluation_id}/{sk}.json"
        _s3.put_object(Bucket=EVIDENCE_BUCKET, Key=key, Body=obs_json.encode(),
                       ContentType="application/json")
        item["observation_s3_uri"] = f"s3://{EVIDENCE_BUCKET}/{key}"
    if action == "retrieve_lending_policy" and isinstance(observation, dict):
        # Ground truth for "cited but never retrieved": the policy ids the KB
        # actually returned, taken from the full observation before it is truncated.
        excerpts = [e for e in observation.get("policy_excerpts", [])
                    if e.get("policy_reference") not in (None, "", "Unknown")]
        item["retrieved_policy_ids"] = sorted({e["policy_reference"] for e in excerpts})
        # The version of each policy the agent actually read (HUD Update / eCFR date).
        item["retrieved_policy_versions"] = {e["policy_reference"]: e.get("policy_version", "unknown")
                                             for e in excerpts}
        # The exact passages the agent read (Knowledge Base chunk ids).
        item["retrieved_chunk_ids"] = sorted({e["chunk_id"] for e in observation.get("policy_excerpts", [])
                                              if e.get("chunk_id")})
        seen["retrieved"] |= {normalize_policy_id(p) for p in item["retrieved_policy_ids"]} - {None}
    seen["facts"].update({k: v for k, v in item.items()
                          if k in ("credit_score", "back_end_dti_pct", "ltv_pct")})

    if not (is_decision and isinstance(observation, dict)):
        _traces_table.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
        _steps_written[evaluation_id].append(sk)
        return

    outcome = observation.get("decision", "unknown")
    expires = int(time.time()) + (RETAIN_DEFAULT_SECONDS if outcome == "approve" else RETAIN_DENIAL_SECONDS)
    f = seen["facts"]
    item.update(bands_for(f.get("credit_score"), f.get("back_end_dti_pct"), f.get("ltv_pct")) or {})
    item.update(check)
    _seen.pop(evaluation_id, None)
    item.update({
        "outcome": outcome,
        "policies_cited": observation.get("policies_cited", []),
        "policies_violated": observation.get("policies_violated", []),
        "risk_factors": observation.get("risk_factors", []),
        "adverse_action_reasons": observation.get("adverse_action_reasons", []),
        "reasoning": observation.get("reasoning", "")[:2000],
        "ttl": expires,
    })
    from boto3.dynamodb.types import TypeSerializer
    ser = TypeSerializer()
    actions = [
        {"Put": {"TableName": TRACES_TABLE, "Item": {k: ser.serialize(v) for k, v in item.items()},
                 "ConditionExpression": "attribute_not_exists(PK)"}},
        {"Update": {"TableName": TRACES_TABLE, "Key": {"PK": {"S": pk}, "SK": {"S": "META"}},
                    "UpdateExpression": "SET #s = :done, completed_at = :now, outcome = :o, #t = :exp",
                    "ConditionExpression": "#s = :running",
                    "ExpressionAttributeNames": {"#s": "status", "#t": "ttl"},
                    "ExpressionAttributeValues": {":done": {"S": "COMPLETE"}, ":running": {"S": "IN_PROGRESS"},
                                                  ":now": {"S": now}, ":o": {"S": outcome},
                                                  ":exp": {"N": str(expires)}}}},
    ]
    # Evidence attributes are written once; only the retention date is set on each
    # earlier step, now that the outcome decides how long the evaluation is kept.
    for step_sk in _steps_written.pop(evaluation_id, []):
        actions.append({"Update": {"TableName": TRACES_TABLE, "Key": {"PK": {"S": pk}, "SK": {"S": step_sk}},
                                   "UpdateExpression": "SET #t = :exp",
                                   "ConditionExpression": "attribute_exists(PK)",
                                   "ExpressionAttributeNames": {"#t": "ttl"},
                                   "ExpressionAttributeValues": {":exp": {"N": str(expires)}}}})
    actions += aggregate_updates(TRACES_TABLE, observation, now)
    _ddb.transact_write_items(TransactItems=actions)


def _resolve_application(payload):
    """Return the application dict to evaluate: either passed inline as
    `application`, or looked up in DynamoDB by `application_id`."""
    if isinstance(payload.get("application"), dict):
        return payload["application"]
    app_id = payload.get("application_id")
    if not app_id:
        raise ValueError("payload must include 'application_id' or 'application'")
    application = get_application(app_id)
    if not application:
        raise ValueError(f"application '{app_id}' not found in {APPLICATIONS_TABLE}")
    return application


@app.entrypoint
def invoke(payload):
    """AgentCore Runtime entrypoint. Evaluate a loan application with the ReAct
    underwriting agent, capturing each step to DynamoDB, and return the decision."""
    try:
        application = _resolve_application(payload or {})
    except ValueError as e:
        return {"error": str(e)}

    capture = bool(payload.get("capture", True))
    app_id = str(application.get("application_id", ""))
    settings = {"mode": payload.get("citation_check", "annotate"),
                "inject": bool(payload.get("test_inject_citation")) and app_id.startswith("LA-TEST-")}
    if settings["mode"] not in CITATION_CHECK_MODES:
        return {"error": f"citation_check must be one of {CITATION_CHECK_MODES}"}

    # Capture the evaluation_id the agent generates so the caller can read exactly
    # this evaluation back by primary key (strongly consistent), instead of racing
    # the eventually-consistent GSI right after the write.
    holder = {"evaluation_id": None}

    def _capturing_writer(evaluation_id, step_num, thought, action, action_input,
                          observation, application_id):
        holder["evaluation_id"] = evaluation_id
        _emit_trace_event(evaluation_id, step_num, thought, action, action_input,
                          observation, application_id, settings)

    agent = UnderwritingAgent(
        trace_callback=_capturing_writer if capture else None,
        region=REGION,
        model_id=BEDROCK_MODEL_ID,
    )
    decision = agent.evaluate(application)
    return {
        "application_id": application.get("application_id", "UNKNOWN"),
        "evaluation_id": holder["evaluation_id"],
        "decision": decision,
        "captured": capture,
    }


if __name__ == "__main__":
    import sys
    if "--demo" in sys.argv:
        # Local smoke test without the AgentCore HTTP server.
        demo_id = sys.argv[sys.argv.index("--demo") + 1] if len(sys.argv) > sys.argv.index("--demo") + 1 else "LA-2026-00148"
        print(json.dumps(invoke({"application_id": demo_id}), indent=2, default=str))
    else:
        app.run()
