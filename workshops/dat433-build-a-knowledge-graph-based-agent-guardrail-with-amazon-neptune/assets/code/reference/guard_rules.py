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

"""guard_rules.py - the guard's three decisions (reference answers).

neptune_guard.NeptuneGuardPlugin (your hook, Cell 1.1) calls these before every tool call.
block_message is given; you write should_check and run_report in Go deeper Cells G.1 and G.2.
"""

from verify import validation_report


def should_check(tool, args):
    """Which calls commit AnyCompany to a supplier: every PO, and an offer reply only when it accepts."""
    return (tool == "draft_purchase_order"
            or (tool == "send_offer_reply" and args.get("decision") == "accept"))


def run_report(args):
    """The validation report for the call's order. Any exception blocks the call (fail closed),
    so a missing argument blocks too. quantity defaults to 0 for offer replies."""
    return validation_report(args["supplier_name"], args["product_name"],
                             args["region_name"], args.get("quantity", 0))


def block_message(supplier, product, region, report):
    """The message that cancels the call, or None to let it run. Only 'violation' rows block."""
    violations = [v for v in report if v.get("severity") == "violation"]
    if not violations:
        return None
    reasons = "\n".join(
        f"- {v['rule']}: {v['message']}"
        + (f" [{' -> '.join(v['evidence'])}]" if v.get("evidence") else "")
        for v in violations)
    return (f"BLOCKED by the supplier knowledge graph: {supplier} violates {len(violations)} "
            f"rule(s) for {product} in {region}:\n{reasons}\n"
            "Do not retry this action. Explain the violations and offer qualified alternatives "
            "with recommend_alternatives.")
