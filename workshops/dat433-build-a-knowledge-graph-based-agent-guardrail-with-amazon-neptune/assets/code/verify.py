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
verify.py - Neptune-backed supplier verification guardrail (given harness).

This is the harness between the agent and the graph. The graph QUERIES it runs
are the workshop deliverable: attendees write them as openCypher files under
queries/ (the session notebooks and Go deeper). This file only loads those files and runs them
against Neptune through the neptunedata data API; every rule lives in the
queries, none here.

  queries/ownership_50pct.cypher   one round of OFAC's 50 Percent Rule (Cell 2.3)
  queries/violations.cypher        the validation report (its sanctions evidence: Go deeper G.3)
  queries/recommend.cypher         qualified candidates, nearest first (given)
  queries/stock_locations.cypher   which warehouses carry a product for one supplier
  queries/rule_settings.json       the rules' settings (OFAC threshold, UFLPA list and country)

Stock counts are not in the graph: they live in the DynamoDB stock table (STOCK_TABLE),
keyed by warehouse and product. The graph says which warehouses carry a product and how far
they are; this harness reads the counts for exactly those keys.

The guard hook (neptune_guard.py, Cell 1.1) calls validation_report() before
any consequential tool runs; guardrail.py exposes recommend_alternatives() as an
agent tool. deploy_agent.py ships this file plus the queries/ folder to
AgentCore Runtime, so the deployed agent runs exactly the queries the attendee
wrote.
"""

import json
import os

import boto3


def _query_dir():
    """Where the queries/*.cypher files live. On the notebook instance the helper
    modules and the queries/ folder sit in different directories, so the lifecycle
    sets QUERIES_DIR. In the deployed AgentCore container verify.py and queries/
    ship together, so we fall back to a path relative to this file."""
    return os.environ.get("QUERIES_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "queries")


def _client():
    endpoint = os.environ.get("NEPTUNE_ENDPOINT")
    if not endpoint:
        raise RuntimeError("NEPTUNE_ENDPOINT is not set in the environment.")
    port = os.environ.get("NEPTUNE_PORT", "8182")
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("neptunedata",
                        endpoint_url=f"https://{endpoint}:{port}",
                        region_name=region)


def run_open_cypher(open_cypher, **params):
    """Run an openCypher query string with parameters; return the result rows
    as a list of dicts keyed by the query's RETURN aliases."""
    resp = _client().execute_open_cypher_query(
        openCypherQuery=open_cypher,
        parameters=json.dumps(params))
    return resp.get("results") or []


def rule_settings():
    """The settings the rules read, from queries/rule_settings.json: the OFAC threshold, and the
    UFLPA list's name and country. They ship with the queries, so a change is a reviewed config
    change rather than a query edit. A missing file raises, so the guard fails closed."""
    with open(os.path.join(_query_dir(), "rule_settings.json")) as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def run_query_file(name, **params):
    """Run the openCypher in queries/<name> with the rule settings and the given parameters."""
    with open(os.path.join(_query_dir(), name)) as f:
        return run_open_cypher(f.read(), **{**rule_settings(), **params})


# ── OFAC 50 Percent Rule: computed by propagation ─────────────────────────────
# An entity is blocked if it is listed, or if blocked owners together hold 50% or
# more of it (OFAC FAQs 399, 401). The definition refers to itself, so it cannot be
# evaluated by one query per supplier: it is computed over the whole ownership graph
# whenever lists or ownership change, and read at action time by violations.cypher.

POLICY_RUN = "ofac-50-percent"


def seed_ownership_rule():
    """Clear the last run's results, and mark every company on the sanctions list blocked
    (and listed, so the report can tell later whether the list has changed)."""
    run_open_cypher("MATCH (r:PolicyRun {name: $name}) DELETE r", name=POLICY_RUN)
    run_open_cypher("MATCH (n) WHERE n.blocked = true REMOVE n.blocked, n.blocked_share, n.listed")
    run_open_cypher("MATCH (c:Company)-[:SANCTIONED_BY]->(:SanctionsList) "
                    "SET c.blocked = true, c.listed = true")


def ownership_round():
    """One round of queries/ownership_50pct.cypher. Returns how many entities it newly blocked."""
    rows = run_query_file("ownership_50pct.cypher")
    return int(rows[0]["newly_blocked"]) if rows else 0


def record_ownership_rule(per_round):
    """Record the run (a PolicyRun marker that violations.cypher requires), and count what's
    blocked. Returns {"rounds", "per_round", "companies", "suppliers"}."""
    import datetime
    counts = {r["label"]: r["n"] for r in run_open_cypher(
        "MATCH (n) WHERE n.blocked = true RETURN head(labels(n)) AS label, count(n) AS n")}
    # The seed step marked every company listed at this moment with listed = true.
    # violations.cypher compares those marks with the list as it is now: a listed
    # company without the mark is a new designation, a marked company no longer on
    # the list is a delisting. Either makes every earlier result untrustworthy.
    run_open_cypher("MERGE (r:PolicyRun {name: $name}) SET r.completed_at = $ts, r.rounds = $rounds",
                    name=POLICY_RUN, ts=datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    rounds=len(per_round))
    return {"rounds": len(per_round), "per_round": list(per_round),
            "companies": counts.get("Company", 0), "suppliers": counts.get("Supplier", 0)}


def apply_ownership_rule(max_rounds=25):
    """Compute OFAC's 50 Percent Rule over the graph: seed, run queries/ownership_50pct.cypher
    until it blocks nothing new, then record the run."""
    seed_ownership_rule()
    per_round = []
    for _ in range(max_rounds):
        per_round.append(ownership_round())
        if per_round[-1] == 0:
            break
    else:
        raise RuntimeError(f"OFAC 50% rule did not converge in {max_rounds} rounds; "
                           "check queries/ownership_50pct.cypher")
    return record_ownership_rule(per_round)


# OFAC's own worked examples (FAQ 399, and FAQ 401 Examples 1-5), the same six that
# validate_dataset.py checks offline: (example, listed persons, stakes as
# (owned, owner, share_pct), entity to check, whether OFAC says it is blocked).
OFAC_EXAMPLES = [
    ("FAQ 399", {"X", "Y"}, [("A", "X", 25), ("A", "Y", 25)], "A", True),
    ("FAQ 401 Ex 1", {"X"}, [("A", "X", 50), ("B", "A", 50)], "B", True),
    ("FAQ 401 Ex 2", {"X"}, [("A", "X", 50), ("B", "X", 50), ("C", "A", 25), ("C", "B", 25)], "C", True),
    ("FAQ 401 Ex 3", {"X"}, [("A", "X", 50), ("B", "X", 10), ("B", "A", 40)], "B", True),
    ("FAQ 401 Ex 4", {"X"}, [("A", "X", 50), ("B", "X", 25), ("C", "A", 25), ("C", "B", 25)], "C", False),
    ("FAQ 401 Ex 5", {"X"}, [("A", "X", 25), ("B", "X", 25), ("C", "A", 50), ("C", "B", 50)], "C", False),
]


def check_ofac_examples(max_rounds=10):
    """Run queries/ownership_50pct.cypher on OFAC's worked examples. Each example is
    built as its own small graph (label OfacExample, connected to nothing else), its
    listed persons are seeded as blocked, the query runs until it returns 0, and the
    examples are always deleted again. Call it after apply_ownership_rule(), so the
    real graph has converged and only the examples change. Returns one dict per
    example: {example, entity, expected, blocked, share, listed, stakes, nodes}."""
    nodes, listed, edges = set(), [], []
    for i, (_, persons, stakes, _, _) in enumerate(OFAC_EXAMPLES):
        for owned, owner, pct in stakes:
            nodes.update({f"ofac-{i}-{owned}", f"ofac-{i}-{owner}"})
            edges.append({"owned": f"ofac-{i}-{owned}", "owner": f"ofac-{i}-{owner}", "pct": pct})
        listed += [f"ofac-{i}-{p}" for p in persons]
    targets = [f"ofac-{i}-{ex[3]}" for i, ex in enumerate(OFAC_EXAMPLES)]
    try:
        run_open_cypher("UNWIND $ids AS id CREATE (:OfacExample {id: id})", ids=sorted(nodes))
        run_open_cypher("MATCH (n:OfacExample) WHERE n.id IN $ids SET n.blocked = true", ids=listed)
        run_open_cypher("UNWIND $edges AS e "
                        "MATCH (a:OfacExample {id: e.owned}), (b:OfacExample {id: e.owner}) "
                        "CREATE (a)-[:OWNED_BY {share_pct: e.pct}]->(b)", edges=edges)
        for _ in range(max_rounds):
            rows = run_query_file("ownership_50pct.cypher")
            if not rows or int(rows[0]["newly_blocked"]) == 0:
                break
        got = {r["id"]: r for r in run_open_cypher(
            "MATCH (n:OfacExample) "
            "RETURN n.id AS id, coalesce(n.blocked, false) AS blocked, n.blocked_share AS share")}
    finally:
        run_open_cypher("MATCH (n:OfacExample) DETACH DELETE n")
    # "nodes" is every entity in the example as the query left it, for drawing the example.
    return [{"example": name, "entity": entity, "expected": expected,
             "blocked": got.get(target, {}).get("blocked"),
             "share": got.get(target, {}).get("share"),
             "listed": sorted(persons), "stakes": stakes,
             "nodes": {k[len(f"ofac-{i}-"):]: v for k, v in got.items() if k.startswith(f"ofac-{i}-")}}
            for i, (target, (name, persons, stakes, entity, expected)) in enumerate(zip(targets, OFAC_EXAMPLES))]


def stock_levels(keys):
    """Live units for (warehouse_id, product_id) pairs, from the DynamoDB stock table, read
    strongly consistent with BatchGetItem (100 keys a call). Missing items count as 0.
    Any failure raises, so the guard fails closed."""
    import time
    keys = list(dict.fromkeys(keys))
    if not keys:
        return {}
    table = os.environ.get("STOCK_TABLE")
    if not table:
        raise RuntimeError("STOCK_TABLE is not set in the environment.")
    client = boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    levels = {}
    for i in range(0, len(keys), 100):
        request = {table: {"Keys": [{"warehouse_id": {"S": w}, "product_id": {"S": p}} for w, p in keys[i:i + 100]],
                           "ProjectionExpression": "warehouse_id, product_id, units", "ConsistentRead": True}}
        for attempt in range(8):
            resp = client.batch_get_item(RequestItems=request)
            for item in resp["Responses"].get(table, []):
                levels[(item["warehouse_id"]["S"], item["product_id"]["S"])] = int(item["units"]["N"])
            request = resp.get("UnprocessedKeys") or {}
            if not request:
                break
            time.sleep(0.05 * 2 ** attempt)
        else:
            raise RuntimeError("DynamoDB left stock keys unprocessed after retries")
    return {k: levels.get(k, 0) for k in keys}


# The rules the guard can run. The session installs them step by step (session.install_rules);
# with no queries/installed_rules.json, as in a deployed agent built after the session, all run.
ALL_RULES = ["basics", "sanctions", "uflpa", "certification", "inventory"]


def installed_rules():
    """The rules installed in queries/installed_rules.json, or all of them if there's no list."""
    path = os.path.join(_query_dir(), "installed_rules.json")
    if not os.path.exists(path):
        return list(ALL_RULES)
    with open(path) as f:
        return json.load(f)


def validation_report(supplier_name, product_name, region_name, quantity=0, rules=None):
    """The validation report: one row per failing rule, each with rule, severity
    ('violation' or 'warning'), message, evidence, and hops. No violation rows means the
    supplier conforms. This is the call the guard hook makes before any action runs.

    `rules` (default: the installed rules) picks which rules run; an unknown supplier is always
    a violation. The rules that live in the graph come from queries/violations.cypher, in one query.
    With quantity > 0 it also checks stock: queries/stock_locations.cypher finds the
    supplier's warehouses that carry the product, and the stock table gives their counts."""
    rules = installed_rules() if rules is None else list(rules)
    rows = run_query_file("violations.cypher", supplier_name=supplier_name,
                          product_name=product_name, region_name=region_name,
                          quantity=int(quantity or 0), rules=rules)
    quantity = int(quantity or 0)
    if "inventory" in rules and quantity > 0 and not any(v["rule"] == "existence" for v in rows):
        locations = run_query_file("stock_locations.cypher", supplier_name=supplier_name,
                                   product_name=product_name)
        levels = stock_levels([(l["warehouse_id"], l["product_id"]) for l in locations])
        available = sum(levels.values())
        if available < quantity:
            row = {"rule": "inventory", "severity": "violation",
                   "message": (f"Only {available} units of {product_name} in stock across its "
                               f"warehouses; the order needs {quantity}"),
                   "evidence": [f"{l['warehouse']}: {levels[(l['warehouse_id'], l['product_id'])]} units"
                                for l in locations],
                   "hops": None}
            # Keep the report's order: inventory comes before certification.
            at = next((k for k, v in enumerate(rows) if v["rule"] == "certification"), len(rows))
            rows.insert(at, row)
    return rows


def verify_supplier_relationship(supplier_name, product_name, region_name, quantity=0):
    """Summarize the validation report as a verdict:
    {verified, failed_stage, reason, violations, warnings, source}. failed_stage
    is the first violated rule (None when the supplier conforms). Warnings do not
    affect the verdict."""
    report = validation_report(supplier_name, product_name, region_name, quantity)
    violations = [v for v in report if v.get("severity") == "violation"]
    warnings = [v for v in report if v.get("severity") == "warning"]
    if not violations:
        return {"verified": True, "failed_stage": None, "source": "neptune",
                "reason": (f"'{supplier_name}' satisfies every rule for '{product_name}' "
                           f"in '{region_name}'."),
                "violations": [], "warnings": warnings}
    return {"verified": False, "failed_stage": violations[0]["rule"], "source": "neptune",
            "reason": "; ".join(v["message"] for v in violations),
            "violations": violations, "warnings": warnings}


_TIER = {"preferred": 0, "standard": 1}
_APPROVAL = {"gold": 0, "silver": 1}


def _rank(c, transit_days):
    """Fastest delivery first, then tier, approval level, longest relationship, name."""
    return (transit_days, _TIER.get(c["tier"], 2), _APPROVAL.get(c["approval_level"], 2),
            c["since"], c["supplier"])


def recommend_alternatives(product_name, region_name, exclude=None, quantity=1, top=5, batch=100):
    """Suppliers that satisfy every rule for this product in this region AND can fulfil
    `quantity` today, fastest delivery first.

    queries/recommend.cypher returns every compliant candidate, nearest possible delivery
    first, with the warehouses that carry the product. Only the stock table knows which
    of them have stock, so this reads the counts in batches, in that order, and stops as
    soon as no later candidate can beat the top `top` (a candidate's delivery time with
    stock is never shorter than its nearest possible one)."""
    quantity = max(1, int(quantity or 1))
    candidates = run_query_file("recommend.cypher", product_name=product_name,
                                region_name=region_name, exclude=exclude or "", quantity=quantity)
    found, i, reads = [], 0, 0
    while i < len(candidates):
        chunk, keys = [], []
        while i < len(candidates) and (not chunk or len(keys) + len(candidates[i]["warehouses"]) <= batch):
            c = candidates[i]
            chunk.append(c)
            keys += [(w["warehouse_id"], c["product_id"]) for w in c["warehouses"]]
            i += 1
        levels = stock_levels(keys)
        reads += len(set(keys))
        for c in chunk:
            stocked = [w for w in c["warehouses"] if levels[(w["warehouse_id"], c["product_id"])] > 0]
            available = sum(levels[(w["warehouse_id"], c["product_id"])] for w in stocked)
            if available >= quantity:
                transit = min(w["transit_days"] for w in stocked)
                found.append((_rank(c, transit), {
                    "supplier": c["supplier"], "tier": c["tier"], "approval_level": c["approval_level"],
                    "available": available, "transit_days": transit, "since": c["since"]}))
        found.sort(key=lambda f: f[0])
        if len(found) >= top and i < len(candidates) and \
                found[top - 1][0] <= _rank(candidates[i], candidates[i]["best_transit"]):
            break
    return {"product": product_name, "region": region_name, "quantity": quantity,
            "recommended": [f[1] for f in found[:top]], "source": "neptune + dynamodb",
            "candidates": len(candidates), "stock_reads": reads}
