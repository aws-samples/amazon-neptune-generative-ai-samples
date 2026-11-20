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
guardrail.py - the AnyCompany procurement agent, built on Strands Agents (given).

The agent can ACT: it drafts purchase orders and replies to supplier offers.
Those tools are deliberately clean, with no validation inside them. Policy is
enforced from outside, by a plugin on Strands' BeforeToolCallEvent hook that
runs the attendee's Neptune validation query before any consequential tool
executes (neptune_guard.py, your hook, deciding with guard_rules.py). This is the same separation
as the KGC "SHACL as a steering hook" pattern:

    draft_purchase_order / send_offer_reply   pure action, no validation logic
    NeptuneGuardPlugin                        pure policy, runs before every action
    queries/violations.cypher                 the declarative rules, in the graph

The agent has no verification tool. It never decides whether the graph is
checked; the hook does that on every gated call, whatever the model chose.

Both the notebook (Steps 1 to 4, in-process) and the deployed agent (agent.py on
AgentCore Runtime) build the agent through build_agent(), so what attendees
test is exactly what runs in production.
"""

import json
import os
import textwrap
import uuid

from strands import Agent, tool
from strands.models import BedrockModel

from verify import recommend_alternatives as _recommend_alternatives

MODEL_ID = "us.anthropic.claude-sonnet-5"
REGION = os.environ.get("AWS_REGION", "us-east-1")

SYSTEM_PROMPT = """You are AnyCompany's procurement assistant. You act on requests from the
procurement team: drafting purchase orders and replying to supplier offers.

- Use draft_purchase_order to draft a PO and send_offer_reply to answer a supplier's offer.
- Pass supplier, product, and region names exactly as they appear in the request.
- Report every tool result faithfully. If a tool call is blocked, do not retry it: explain
  why, using the reasons in the tool result, and call recommend_alternatives so the team
  has a path forward.
- Never switch to a different supplier on your own. Recommend, then ask.
- Be brief: procurement wants the outcome, the reason, and the next step."""


# ── Action tools: clean, no validation logic ─────────────────────────────────

@tool
def draft_purchase_order(supplier_name: str, product_name: str, region_name: str,
                         quantity: int) -> dict:
    """Draft a purchase order for a supplier.

    Args:
        supplier_name: Full supplier name, e.g. 'AnyCompany Supply Co'
        product_name: Product category, e.g. 'Server Hardware'
        region_name: Delivery region, e.g. 'EU-Central', 'US-East'
        quantity: Number of units
    """
    # In production this would create the PO in the ERP system.
    return {"po_number": f"PO-DRAFT-{uuid.uuid4().hex[:8].upper()}",
            "supplier": supplier_name, "product": product_name,
            "region": region_name, "quantity": quantity,
            "status": "DRAFT - not submitted"}


@tool
def send_offer_reply(supplier_name: str, product_name: str, region_name: str,
                     decision: str, message: str) -> dict:
    """Reply to a supplier's offer.

    Args:
        supplier_name: Full supplier name
        product_name: Product category the offer is for
        region_name: Delivery region the offer is for
        decision: 'accept' or 'decline'
        message: The reply text to send to the supplier
    """
    # In production this would send the email.
    return {"to": supplier_name, "decision": decision, "message": message,
            "status": "QUEUED - not sent (workshop stub)"}


# ── Read-only tool: the graph, used for recommendations ──────────────────────

@tool
def recommend_alternatives(product_name: str, region_name: str, exclude: str = "",
                           quantity: int = 1) -> dict:
    """Find suppliers that satisfy every AnyCompany rule for a product in a region and
    have the stock for the order, fastest delivery first.

    Args:
        product_name: Product category
        region_name: Delivery region
        exclude: A supplier name to leave out, e.g. the one that was just blocked
        quantity: Units needed
    """
    return _recommend_alternatives(product_name, region_name, exclude, quantity)


ACTION_TOOLS = [draft_purchase_order, send_offer_reply]


def build_agent(guard=None, extra_tools=(), extra_prompt=""):
    """The procurement agent. Pass the guard plugin to enforce the graph rules;
    pass nothing to get the same agent with no guardrail. extra_tools and extra_prompt
    build the session's comparison agents (a check tool, an instruction to call it)."""
    return Agent(
        model=BedrockModel(model_id=MODEL_ID, region_name=REGION, max_tokens=1024),
        tools=ACTION_TOOLS + [recommend_alternatives] + list(extra_tools),
        plugins=[guard] if guard else [],
        system_prompt=SYSTEM_PROMPT + extra_prompt,
        callback_handler=None,   # no streaming printout; run() returns the result
    )


# ── Running it, and seeing what happened ─────────────────────────────────────

def trace(agent):
    """Every tool call in the conversation, with its outcome:
    'ok', 'BLOCKED' (cancelled by the guard), or 'error'."""
    calls, results = [], {}
    for msg in agent.messages:
        for block in msg.get("content", []):
            if "toolUse" in block:
                calls.append(block["toolUse"])
            elif "toolResult" in block:
                tr = block["toolResult"]
                results[tr["toolUseId"]] = tr
    out = []
    for call in calls:
        tr = results.get(call["toolUseId"], {})
        text = " ".join(c.get("text", "") for c in tr.get("content", []) if "text" in c)
        if tr.get("status") == "error":
            outcome = "BLOCKED" if text.startswith("BLOCKED") else "error"
        else:
            outcome = "ok"
        out.append({"tool": call["name"], "input": call.get("input", {}),
                    "outcome": outcome, "output": text})
    return out


def run(agent, prompt):
    """Send one request to the agent. Returns {"result": text, "trace": [...]}."""
    result = agent(prompt)
    return {"result": str(result).strip(), "trace": trace(agent)}


def print_trace(steps, width=100):
    """Print a trace (from run() or from the deployed agent) one line per tool call."""
    for t in steps:
        args = ", ".join(f"{k}={v!r}" for k, v in t["input"].items() if k != "message")
        print(f"  [{t['outcome']:<7}] {t['tool']}({args})")
        if t["outcome"] != "ok":
            for line in t["output"].splitlines():
                for part in textwrap.wrap(line, width) or [""]:
                    print(f"             {part}")


def show_tool_result(result):
    """Pretty-print the ToolResult returned by a direct call like
    agent.tool.draft_purchase_order(...)."""
    text = " ".join(c.get("text", "") for c in result.get("content", []) if "text" in c)
    if result.get("status") == "error":
        print(text)
    else:
        try:
            print(json.dumps(json.loads(text), indent=2))
        except ValueError:
            print(text)
