#!/usr/bin/env python3
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
mcp_server.py — your DAT408 solution as an MCP server (given).

It adds no queries and no rules of its own. Every evidence tool runs an answer you
wrote in the notebook, from the exact file your exercise cell saved, through the
same code the notebook used (agent.evidence):

    get_decision_evidence   solution/get_evidence.py          Go deeper G.1 (DynamoDB)
    reasoning_chain         solution/get_evidence.py          Go deeper G.1 (DynamoDB)
    policy_denial_stats     solution/policy_months.py         Go deeper G.3 (DynamoDB)
    ungrounded_citations    solution/ungrounded_citations.cypher  Go deeper G.6 (Neptune)
    your own tool           solution/extra_tool.py, running       Kiro K.4
                            solution/lineage_walk.cypher          (DAT408, Cell 3.2)

evaluate_application re-runs one of the three sample applications through the
hosted underwriting agent, whose evidence then flows through your Lambda transform
into the graph. solution_source returns the files themselves. Every result carries
the sha256 of the answer it ran: compare it with the one your notebook printed.

Deployed to Amazon Bedrock AgentCore Runtime with the MCP protocol by
the Kiro notebook's Cell K.2. AgentCore expects a stateless
streamable-HTTP server on 0.0.0.0:8000 at /mcp and authenticates callers with IAM
(SigV4), so a client such as Kiro CLI connects through mcp-proxy-for-aws. The
runtime's role can read the evidence and invoke the underwriting agent; it cannot
write evidence.
"""
import functools
import json
import os
import time
from decimal import Decimal
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key
from mcp.server.fastmcp import FastMCP

from agent.evidence import ALL_ANSWERS, load_function, read_answers, run_cypher, sha256

REGION = os.environ.get("DAT408_REGION") or os.environ.get("AWS_REGION", "us-east-1")
GRAPH_ID = os.environ["GRAPH_ID"]
AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
GRAPH_WAIT_SECONDS = 45   # projection normally takes seconds; the agent run itself ~40 s
SAMPLE_APPLICATIONS = os.environ.get(
    "SAMPLE_APPLICATIONS", "LA-2026-00147,LA-2026-00148,LA-2026-00149").split(",")

neptune = boto3.client("neptune-graph", region_name=REGION)
agentcore = boto3.client("bedrock-agentcore", region_name=REGION)
trace_table = boto3.resource("dynamodb", region_name=REGION).Table(os.environ["TRACES_TABLE"])

# Your answers, exactly as your exercise cells saved them.
ANSWER_TEXT = read_answers(Path(__file__).parent / "solution")
FINGERPRINTS = {name: sha256(text) for name, text in ANSWER_TEXT.items()}
# Your two DynamoDB functions, defined from their source with the same globals
# the notebook cells had.
_names = {"trace_table": trace_table, "Key": Key}
get_evidence = load_function(ANSWER_TEXT["get_evidence"], "get_evidence", _names)
policy_months = load_function(ANSWER_TEXT["policy_months"], "policy_months", _names)

mcp = FastMCP("dat408-evidence", host="0.0.0.0", port=8000, stateless_http=True)


def _ran(name):
    """Which of your answers produced a result, and its fingerprint."""
    return {"file": f"solution/{ALL_ANSWERS[name][0]}", "sha256": FINGERPRINTS[name]}


# For results that come from given code rather than one of your answers.
_GIVEN = {"file": None, "sha256": None,
          "note": "given code (the hosted underwriting agent), not one of the workshop's answer files"}


def _plain(value):
    """DynamoDB items carry Decimals; make them JSON-friendly."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    return value


def _cypher(name, params=None):
    return run_cypher(neptune, GRAPH_ID, ANSWER_TEXT[name], params).get("results", [])


@mcp.tool()
def evaluate_application(application_id: str) -> dict:
    """Run one of the three sample loan applications through the hosted underwriting
    agent again. The agent records every step as decision evidence in DynamoDB, which
    streams through the workshop's Lambda into the Neptune graph; this tool returns once
    the new evaluation is in the graph (in_graph), so every other tool sees it as the
    most recent. Returns the decision and the evaluation_id to investigate.

    Args:
        application_id: One of LA-2026-00147, LA-2026-00148, LA-2026-00149
    """
    if application_id not in SAMPLE_APPLICATIONS:
        return {"error": f"Only the sample applications can be evaluated: {', '.join(SAMPLE_APPLICATIONS)}"}
    resp = agentcore.invoke_agent_runtime(
        agentRuntimeArn=AGENT_RUNTIME_ARN,
        payload=json.dumps({"capture": True, "application_id": application_id}).encode(),
        contentType="application/json", accept="application/json")
    body = json.loads(resp["response"].read())
    decision = body.get("decision") or {}
    # Wait (bounded) for the stream and Lambda to project the new evaluation, so the graph
    # tools answer about this evaluation rather than the previous one.
    in_graph, deadline = False, time.time() + GRAPH_WAIT_SECONDS
    while body.get("evaluation_id") and not in_graph and time.time() < deadline:
        in_graph = bool(run_cypher(neptune, GRAPH_ID,
                                   "MATCH (d:Decision {`~id`: $d}) WHERE d.outcome IS NOT NULL RETURN count(d) AS n",
                                   {"d": f"decision:{body.get('evaluation_id')}_decision"}).get("results", [{}])[0].get("n"))
        if not in_graph:
            time.sleep(2)
    return {"application_id": application_id, "evaluation_id": body.get("evaluation_id"),
            "in_graph": in_graph,
            "decision": decision.get("decision"), "policies_cited": decision.get("policies_cited", []),
            "policies_violated": decision.get("policies_violated", []),
            "adverse_action_reasons": decision.get("adverse_action_reasons", []),
            "ran": _GIVEN}


@mcp.tool()
def get_decision_evidence(evaluation_id: str) -> dict:
    """Read back the decision evidence one evaluation recorded in DynamoDB: its header
    (model, prompt version, status) and every step, in order, with what each tool
    returned to the agent and the final decision record.

    Args:
        evaluation_id: The evaluation to read, as returned by evaluate_application
    """
    items = _plain(get_evidence(evaluation_id))
    header = next((i for i in items if i.get("SK") == "META"), {})
    steps = sorted((i for i in items if str(i.get("SK", "")).startswith("STEP#")), key=lambda i: i["SK"])
    keep = ("step_num", "action", "thought", "observation_summary", "outcome", "policies_cited",
            "policies_violated", "risk_factors", "adverse_action_reasons", "retrieved_policy_ids")
    return {"evaluation_id": evaluation_id,
            "header": {k: header.get(k) for k in ("status", "model_id", "prompt_version", "application_id")},
            "steps": [{k: s[k] for k in keep if k in s} for s in steps],
            "ran": _ran("get_evidence")}


@mcp.tool()
def policy_denial_stats(policy: str) -> dict:
    """How often a policy was cited and failed across every recorded decision, from
    its precomputed monthly aggregates in DynamoDB (one query).

    Args:
        policy: Canonical policy id, e.g. 'HUD 4000.1 II.A.5.d' or '12 CFR 1002.9'
    """
    resp = policy_months(policy)
    months = _plain(resp["Items"])
    return {"policy": policy, "months": len(months),
            "decisions_citing": sum(m.get("decisions_citing", 0) for m in months),
            "decisions_failing": sum(m.get("decisions_failing", 0) for m in months),
            "read_units": _plain((resp.get("ConsumedCapacity") or {}).get("CapacityUnits")),
            "ran": _ran("policy_months")}


@mcp.tool()
def reasoning_chain(application_id: str) -> dict:
    """The agent's reasoning steps, in order, for the most recent evaluation of an
    application: the steps it recorded in DynamoDB, read back by key in sort-key order.

    Args:
        application_id: e.g. 'LA-2026-00148'
    """
    keys = trace_table.query(IndexName="application-index", ScanIndexForward=False,
                             KeyConditionExpression=Key("application_id").eq(application_id))["Items"]
    evaluations = list(dict.fromkeys(k["PK"].replace("EVAL#", "") for k in keys))
    if not evaluations:
        return {"application_id": application_id, "evaluations_found": 0, "ran": _ran("get_evidence")}
    latest = evaluations[0]
    steps = sorted((i for i in _plain(get_evidence(latest)) if str(i.get("SK", "")).startswith("STEP#")),
                   key=lambda i: i["SK"])
    return {"application_id": application_id, "evaluation_id": latest,
            "steps_in_order": [f"{s.get('step_num')}. {s.get('action')}" for s in steps],
            "earlier_evaluations": len(evaluations) - 1, "ran": _ran("get_evidence")}


@mcp.tool()
def ungrounded_citations(application_id: str = "") -> dict:
    """The examiner's question: denials that failed the qualifying-ratio rule and cite
    a policy the agent never retrieved in that evaluation. Searches every recorded
    decision (a few seconds). Optionally narrow the result to one application.

    Args:
        application_id: Leave empty for all decisions, or e.g. 'LA-AUDIT-TEST'
    """
    rows = _cypher("ungrounded_citations", {"ratio_rule": "policy:HUD 4000.1 II.A.5.d"})
    if application_id:
        rows = [r for r in rows if r.get("application") == application_id]
    by_policy = {}
    for r in rows:
        by_policy.setdefault(r.get("policy"), set()).add(r.get("application"))
    return {"denials_with_ungrounded_citations": len({r.get("application") for r in rows}),
            "by_policy": {p: len(a) for p, a in sorted(by_policy.items(), key=lambda kv: -len(kv[1]))},
            "examples": rows[:10], "ran": _ran("ungrounded_citations")}


@mcp.tool()
def solution_source() -> dict:
    """The answers this server runs, exactly as the workshop's exercise cells saved
    them, with the sha256 of each. (This tool itself is given code.)"""
    return {name: {"file": f"solution/{ALL_ANSWERS[name][0]}", "sha256": FINGERPRINTS[name],
                   "source": ANSWER_TEXT[name]} for name in ANSWER_TEXT}


def run_answer(name, params=None):
    """Run one of your saved openCypher answers: the same contract the notebook's
    run_answer() gives the tool you write in Cell K.4."""
    return _cypher(name, params)


# K.4: the tool you wrote, registered as written. Its name, arguments and
# docstring are what Kiro's model sees; its results also report the fingerprints of
# the tool and of the query it ran.
if "extra_tool" in ANSWER_TEXT:
    _tool = load_function(ANSWER_TEXT["extra_tool"], "decisions_resting_on", {"run_answer": run_answer})

    @functools.wraps(_tool)
    def _your_tool(*args, **kwargs):
        result = _tool(*args, **kwargs)
        result = result if isinstance(result, dict) else {"result": result}
        result["ran"] = [_ran("extra_tool"), _ran("lineage_walk")]
        return result

    mcp.add_tool(_your_tool)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
