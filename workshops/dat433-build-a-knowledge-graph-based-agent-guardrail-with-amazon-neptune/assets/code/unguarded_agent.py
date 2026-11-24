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
unguarded_agent.py

The "before" state: the AnyCompany procurement agent as it ran before this
project started. Same Strands agent, same model, same action tools as the
guarded agent (guardrail.py), and NO guard plugin: nothing checks a supplier
against the registry before the agent acts.

It is deployed by the workshop CloudFormation stack (the AgentPackageBuild
custom resource), not by attendees, so Module 1 can invoke it the moment the
session opens. That custom resource downloads ONLY this file, so it is
self-contained: the two action tools are repeated here rather than imported
from guardrail.py. Keep them identical.

The headline case is AnyCompany Components: every direct fact about it is
favourable, so this agent drafts the PO. The disqualifying fact lives three
ownership hops away, on a company the agent was never told about and has no
way to find.

Local usage (exercises the same logic without AgentCore Runtime):
    python3 unguarded_agent.py --demo

Hosted usage (the stack's entryPoint=["unguarded_agent.py"], run with no
arguments, so app.run() is the default):
    python3 unguarded_agent.py
"""

import os
import sys
import uuid

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from strands.models import BedrockModel

MODEL_ID = "us.anthropic.claude-sonnet-5"
REGION = os.environ.get("AWS_REGION", "us-east-1")

app = BedrockAgentCoreApp()

SYSTEM_PROMPT = """You are AnyCompany's procurement assistant. You act on requests from the
procurement team: drafting purchase orders and replying to supplier offers.

- Use draft_purchase_order to draft a PO and send_offer_reply to answer a supplier's offer.
- Pass supplier, product, and region names exactly as they appear in the request.
- Report every tool result faithfully.
- Be brief: procurement wants the outcome, the reason, and the next step."""


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
    return {"to": supplier_name, "decision": decision, "message": message,
            "status": "QUEUED - not sent (workshop stub)"}


def _trace(agent):
    calls, results = [], {}
    for msg in agent.messages:
        for block in msg.get("content", []):
            if "toolUse" in block:
                calls.append(block["toolUse"])
            elif "toolResult" in block:
                results[block["toolResult"]["toolUseId"]] = block["toolResult"]
    out = []
    for call in calls:
        tr = results.get(call["toolUseId"], {})
        text = " ".join(c.get("text", "") for c in tr.get("content", []) if "text" in c)
        out.append({"tool": call["name"], "input": call.get("input", {}),
                    "outcome": "ok" if tr.get("status") != "error" else "error",
                    "output": text})
    return out


def ask(prompt):
    """No guard: whatever the model decides to do, it does."""
    agent = Agent(
        model=BedrockModel(model_id=MODEL_ID, region_name=REGION, max_tokens=1024),
        tools=[draft_purchase_order, send_offer_reply],
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,
    )
    result = agent(prompt)
    return {"result": str(result).strip(), "trace": _trace(agent)}


# ── The AgentCore Runtime entrypoint ──────────────────────────────────────────
@app.entrypoint
def invoke(payload):
    """AgentCore Runtime entrypoint. Returns {"result": ..., "trace": [...]}."""
    prompt = payload.get("prompt", "")
    if not prompt:
        return {"error": "payload must include a 'prompt' field"}
    return ask(prompt)


if __name__ == "__main__":
    if "--demo" in sys.argv:
        prompt = ("Hey, can you put together a PO for 40 units of Server Hardware from "
                  "AnyCompany Components for the Frankfurt build-out (EU-Central)? They're one "
                  "of our preferred vendors and Sarah in sourcing already gave the nod, so "
                  "this should be quick.")
        print("UN-GUARDED AGENT\n\n" + prompt + "\n")
        out = ask(prompt)
        for t in out["trace"]:
            print(f"  [{t['outcome']}] {t['tool']}({t['input']})")
        print("\n" + out["result"])
        print("\nNothing checked AnyCompany Components' ownership chain (AnyCompany Components Holdings BV -> "
              "AnyCompany Group SA -> AnyCompany Industries OAO, OFAC SDN).")
    else:
        app.run()
