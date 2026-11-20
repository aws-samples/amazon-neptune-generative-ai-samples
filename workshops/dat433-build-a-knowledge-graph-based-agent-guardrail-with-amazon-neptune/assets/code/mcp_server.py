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
mcp_server.py - the procurement solution as an MCP server (given).

Kiro CLI calls this (3 - Run it from Kiro (optional).ipynb, and the Finished early? page). It adds no rules and no logic of its own: every
tool maps onto code you already ran in the notebook, unchanged.

    validation_report        verify.validation_report   -> queries/violations.cypher, reading your 50% rule (Cell 2.3)
    recommend_alternatives   verify.recommend_alternatives -> queries/recommend.cypher (given)
    draft_purchase_order     guardrail.draft_purchase_order, behind NeptuneGuardPlugin and your guard_rules.py
    send_offer_reply         guardrail.send_offer_reply, behind NeptuneGuardPlugin and your guard_rules.py
    ask_procurement_agent    the whole guarded agent (guardrail.build_agent + your plugin)

The action tools run as direct tool calls on the guarded Strands agent, the same
mechanism as Checkpoint 4, so your BeforeToolCallEvent hook validates every one
against Neptune before it executes, whichever agent asked for it.

Deployed to Amazon Bedrock AgentCore Runtime with the MCP protocol by
deploy_agent(..., protocol="MCP") from Cell K.2. AgentCore expects a stateless
streamable-HTTP server on 0.0.0.0:8000 at /mcp, and authenticates callers with IAM
(SigV4), so a client such as Kiro CLI connects through mcp-proxy-for-aws.
"""

import importlib
import json
import threading

from mcp.server.fastmcp import FastMCP

import verify
from guardrail import build_agent, run
from neptune_guard import NeptuneGuardPlugin

mcp = FastMCP("procurement", host="0.0.0.0", port=8000, stateless_http=True)

# One guarded agent for the direct action calls. Strands runs one invocation per agent
# at a time, so calls on it are serialised; the workshop's traffic is one attendee.
class _RecordingRules:
    """guard_rules.py, passed through unchanged, noting whether the hook asked for a report
    and what it got. The hook is yours and keeps no record, so the server keeps its own."""

    def __init__(self, rules):
        self.rules, self.checked, self.report = rules, False, None

    def should_check(self, tool, args):
        return self.rules.should_check(tool, args)

    def run_report(self, args):
        self.checked = True
        self.report = self.rules.run_report(args)
        return self.report

    def block_message(self, supplier, product, region, report):
        return self.rules.block_message(supplier, product, region, report)


_rules = _RecordingRules(importlib.import_module("guard_rules"))
_guard = NeptuneGuardPlugin(rules=_rules)
_agent = build_agent(guard=_guard)
_lock = threading.Lock()


def _guarded_call(tool_name, **kwargs):
    """Call one action tool through the guarded agent, with no model involved. Returns
    the tool's result plus what the guard decided, so the caller can see the check."""
    with _lock:
        _rules.checked, _rules.report = False, None
        res = getattr(_agent.tool, tool_name)(record_direct_tool_call=False, **kwargs)
        checked, report = _rules.checked, _rules.report or []
    text = " ".join(c.get("text", "") for c in res.get("content", []) if "text" in c)
    if res.get("status") != "success":
        return {"status": "BLOCKED" if text.startswith("BLOCKED") else "error", "message": text}
    try:
        result = json.loads(text)
    except ValueError:
        result = {"result": text}
    result["guardrail"] = {
        "checked": checked,
        "violations": 0,
        "warnings": [w["message"] for w in report if w.get("severity") == "warning"],
        "source": "your hook (neptune_guard.py) with guard_rules.py, running queries/violations.cypher on Neptune",
    }
    return result


@mcp.tool()
def validation_report(supplier_name: str, product_name: str, region_name: str,
                      quantity: int = 0) -> dict:
    """Check one order against every AnyCompany procurement rule in the supplier knowledge
    graph (sanctions under OFAC's 50 Percent Rule, UFLPA sourcing, certifications, stock,
    approval, status, region). Returns one row per failing rule with its severity and
    evidence; an empty list of violations means the order may proceed.

    Args:
        supplier_name: Full supplier name, e.g. 'AnyCompany Supply Co'
        product_name: Product category, e.g. 'Server Hardware'
        region_name: Delivery region, e.g. 'US-East', 'EU-Central'
        quantity: Units in the order (0 skips the stock check)
    """
    rows = verify.validation_report(supplier_name, product_name, region_name, quantity)
    return {"supplier": supplier_name, "product": product_name, "region": region_name,
            "quantity": quantity,
            "violations": [r for r in rows if r.get("severity") == "violation"],
            "warnings": [r for r in rows if r.get("severity") == "warning"]}


@mcp.tool()
def recommend_alternatives(product_name: str, region_name: str, quantity: int = 1,
                           exclude: str = "") -> dict:
    """Find the suppliers that satisfy every AnyCompany rule for a product in a delivery
    region AND have the stock to fill the order, fastest delivery first. Use this to
    choose a supplier before drafting a purchase order.

    Args:
        product_name: Product category, e.g. 'Server Hardware'
        region_name: Delivery region, e.g. 'US-East'
        quantity: Units needed
        exclude: A supplier name to leave out, if any
    """
    return verify.recommend_alternatives(product_name, region_name, exclude, quantity)


@mcp.tool()
def draft_purchase_order(supplier_name: str, product_name: str, region_name: str,
                         quantity: int) -> dict:
    """Draft a purchase order. The AnyCompany guardrail validates it against the supplier
    knowledge graph first: an order that breaks a rule is blocked with the reasons.

    Args:
        supplier_name: Full supplier name, e.g. 'AnyCompany Supply Co'
        product_name: Product category, e.g. 'Server Hardware'
        region_name: Delivery region, e.g. 'US-East'
        quantity: Number of units
    """
    return _guarded_call("draft_purchase_order", supplier_name=supplier_name,
                         product_name=product_name, region_name=region_name,
                         quantity=int(quantity))


@mcp.tool()
def send_offer_reply(supplier_name: str, product_name: str, region_name: str,
                     decision: str, message: str) -> dict:
    """Reply to a supplier's offer ('accept' or 'decline'). Accepting is validated by the
    AnyCompany guardrail against the supplier knowledge graph first.

    Args:
        supplier_name: Full supplier name
        product_name: Product category the offer is for
        region_name: Delivery region the offer is for
        decision: 'accept' or 'decline'
        message: The reply text to send to the supplier
    """
    return _guarded_call("send_offer_reply", supplier_name=supplier_name,
                         product_name=product_name, region_name=region_name,
                         decision=decision, message=message)


@mcp.tool()
def ask_procurement_agent(request: str) -> dict:
    """Send a request in plain language to AnyCompany's guarded procurement agent (the
    agent built in the workshop) and get its reply and the tool calls it made.

    Args:
        request: What procurement wants, e.g. 'Draft a PO for 40 units of Server
            Hardware from AnyCompany Supply Co for US-East.'
    """
    out = run(build_agent(guard=NeptuneGuardPlugin()), request)
    return {"reply": out["result"],
            "tool_calls": [{"tool": t["tool"], "input": t["input"], "outcome": t["outcome"]}
                           for t in out["trace"]]}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
