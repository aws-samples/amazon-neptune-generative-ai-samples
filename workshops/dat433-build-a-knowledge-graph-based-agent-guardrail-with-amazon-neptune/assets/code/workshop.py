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
workshop.py

One-line setup for the workshop notebooks. Each notebook starts with:

    from workshop import *
    setup()

That single import pulls in the shared configuration, the Bedrock client, the
model id, and a small openCypher helper, so the notebook cells stay focused on
the workshop content (the graph queries, the guardrail, the agent) instead of
plumbing.

The graph work in this workshop is openCypher run through Amazon Neptune's data
API (the boto3 `neptunedata` client). Interactive queries in the notebook use
the `%%oc` magic; the deployed agent runs the same style of query from verify.py.
"""

import json
import os
import shutil

import boto3

# Display helpers (spinner, styled tables, agent traces), re-exported so every
# notebook gets them from the one `from workshop import *`.
from ui import (busy, banner, pill, show_code_block, show_explain, show_reply,
                show_request, show_results, show_status, show_trace)

MODEL_ID = "us.anthropic.claude-sonnet-5"


def _load_config():
    """Load workshop_config.txt (written by the SageMaker lifecycle at startup)
    into os.environ. Existing environment values win, so nothing is clobbered."""
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workshop_config.txt")
    if os.path.exists(cfg_path):
        for line in open(cfg_path):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)


_load_config()

# ── Configuration (resolved from the environment / workshop_config.txt) ───────
NEPTUNE_ENDPOINT = os.environ.get("NEPTUNE_ENDPOINT")
NEPTUNE_PORT     = os.environ.get("NEPTUNE_PORT", "8182")
DATA_BUCKET      = os.environ.get("DATA_BUCKET")
DATA_PREFIX      = os.environ.get("DATA_PREFIX", "guardrail/neptune_data")
LOAD_ROLE_ARN    = os.environ.get("NEPTUNE_LOAD_ROLE_ARN")
AWS_REGION       = os.environ.get("AWS_REGION", "us-east-1")

# Deployment target for the guarded agent (Cell 4.4).
AGENTCORE_ROLE_ARN             = os.environ.get("AGENTCORE_ROLE_ARN")
AGENTCORE_SECURITY_GROUP_ID    = os.environ.get("AGENTCORE_SECURITY_GROUP_ID")
AGENTCORE_CANDIDATE_SUBNET_IDS = os.environ.get("AGENTCORE_CANDIDATE_SUBNET_IDS", "").split(",")

# Shared clients.
bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)


def _neptune_data():
    return boto3.client("neptunedata",
                        endpoint_url=f"https://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}",
                        region_name=AWS_REGION)


def oc(query, **params):
    """Run an openCypher query from Python and return its result rows.
    (For interactive, visualized queries use the %%oc cell magic instead.)"""
    resp = _neptune_data().execute_open_cypher_query(
        openCypherQuery=query, parameters=json.dumps(params))
    return resp.get("results") or []


def oc_explain(query, mode="static", **params):
    """Neptune's query plan for an openCypher query, as text. mode is 'static'
    (plan only), 'dynamic' (runs the query and reports per-operator row counts),
    or 'details'."""
    resp = _neptune_data().execute_open_cypher_explain_query(
        openCypherQuery=query, explainMode=mode, parameters=json.dumps(params))
    body = resp["results"]
    return (body.read() if hasattr(body, "read") else body).decode("utf-8")


def checkpoint(ok, path):
    """End-of-step check. On a pass, say so. On a fail, keep the attendee's file as
    <path>.mine and load the reference answer from helpers/reference/, so a stuck
    attendee can carry on with the next step. path is relative to
    ~/SageMaker/workshop/your-guard, e.g. 'queries/violations.cypher' or 'neptune_guard.py'."""
    if ok:
        show_status(True, f"Checkpoint passed: {path} is ready for the next step.")
        return True
    home = os.path.join(os.path.expanduser("~"), "SageMaker", "workshop", "your-guard")
    target = os.path.join(home, path)
    reference = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference", path)
    if not os.path.exists(reference):
        show_status(False, f"Checkpoint failed, and no reference answer was found at {reference}.")
        return False
    if os.path.exists(target):
        shutil.copyfile(target, target + ".mine")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(reference, target)
    show_status(False, f"Checkpoint failed. Your version is saved as {path}.mine and the reference "
                       f"answer is now in {path}. Re-run this cell to confirm, then carry on.")
    return False


def setup():
    """Confirm Bedrock responds and show the workshop configuration. Neptune
    itself is checked with the %status magic in the notebook."""
    with busy(f"Checking Amazon Bedrock ({MODEL_ID})"):
        resp = bedrock.invoke_model(modelId=MODEL_ID, body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31", "max_tokens": 20,
            "messages": [{"role": "user", "content": "Reply exactly: Bedrock OK"}]}))
        verdict = json.loads(resp["body"].read())["content"][0]["text"].strip()
    show_results([
        ("Bedrock", "ok" if "OK" in verdict else verdict, MODEL_ID),
        ("Neptune", "ok" if NEPTUNE_ENDPOINT else "missing", NEPTUNE_ENDPOINT or "not set"),
        ("Dataset", "ok" if DATA_BUCKET else "missing", f"s3://{DATA_BUCKET}/{DATA_PREFIX}"),
        ("Region", "ok", AWS_REGION),
    ], ["", "status", "value"])
