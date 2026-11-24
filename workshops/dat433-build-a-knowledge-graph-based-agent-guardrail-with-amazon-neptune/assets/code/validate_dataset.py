#!/usr/bin/env python3
"""
validate_dataset.py

Proves the generated CSVs encode the workshop scenarios, with no Neptune cluster
required. It is also the reference implementation, in plain Python, of what the
workshop's openCypher computes:

  * OFAC's 50 Percent Rule (FAQs 398, 399, 401): an entity is blocked if it is
    listed, or if blocked owners together hold 50% or more of it. Computed by
    propagation, exactly like the Module 2 step query run until nothing changes.
  * The validation report (queries/violations.cypher): one row per rule, with a
    severity of 'violation' or 'warning'.

It also checks the rule against every worked example OFAC publishes, and prints
how much of the registry is blocked or exposed, as a realism check.

Usage:
    python3 generate_dataset.py --out /tmp/nd
    python3 validate_dataset.py --data /tmp/nd
"""

import argparse
import csv
import os
import sys
from collections import defaultdict



def load(data_dir):
    def rows(fn):
        with open(os.path.join(data_dir, fn), newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    g = {}
    g["supplier"] = {r["~id"]: r for r in rows("v_supplier.csv")}
    g["company"] = {r["~id"]: r for r in rows("v_company.csv")}
    g["product"] = {r["~id"]: r for r in rows("v_product.csv")}
    g["region"] = {r["~id"]: r for r in rows("v_region.csv")}
    g["cert"] = {r["~id"]: r for r in rows("v_certification.csv")}
    g["list"] = {r["~id"]: r for r in rows("v_sanctions_list.csv")}

    g["approved"] = defaultdict(list)
    for r in rows("e_approved_for.csv"):
        g["approved"][r["~from"]].append(r)
    g["operates"] = defaultdict(set)
    for r in rows("e_operates_in.csv"):
        g["operates"][r["~from"]].add(r["~to"])
    g["owners"] = defaultdict(list)               # owned -> [(owner, share_pct)]
    for r in rows("e_owned_by.csv"):
        g["owners"][r["~from"]].append((r["~to"], int(r["share_pct:Int"])))
    g["listed"] = {}                              # company -> list name
    for r in rows("e_sanctioned_by.csv"):
        g["listed"][r["~from"]] = g["list"][r["~to"]]["name:String"]
    g["requires"] = defaultdict(set)
    for r in rows("e_requires_cert.csv"):
        g["requires"][r["~from"]].add(r["~to"])
    g["holds"] = defaultdict(dict)
    for r in rows("e_holds_cert.csv"):
        g["holds"][r["~from"]][r["~to"]] = r
    g["warehouses"] = defaultdict(list)           # supplier -> [warehouse]
    for r in rows("e_has_warehouse.csv"):
        g["warehouses"][r["~from"]].append(r["~to"])
    g["wh_region"] = {r["~from"]: r["~to"] for r in rows("e_located_in.csv")}
    g["stock"] = defaultdict(dict)                # warehouse -> {product: units}
    for r in rows("stock_levels.csv"):           # the DynamoDB stock table's contents
        g["stock"][r["warehouse_id"]][r["product_id"]] = int(r["units"])
    g["transit"] = {(r["~from"], r["~to"]): int(r["transit_days:Int"]) for r in rows("e_ships_to.csv")}
    g["sources"] = defaultdict(list)              # buyer -> [maker]
    for r in rows("e_sources_from.csv"):
        g["sources"][r["~from"]].append(r["~to"])
    g["uflpa"] = {r["~from"] for r in rows("e_on_list.csv")}
    g["by_name"] = {r["name:String"]: i for i, r in g["supplier"].items()}
    g["prod_by_name"] = {r["name:String"]: i for i, r in g["product"].items()}
    g["reg_by_name"] = {r["name:String"]: i for i, r in g["region"].items()}
    return g


def propagate(listed, owners):
    """OFAC 50% rule by propagation. listed: set of ids; owners: owned -> [(owner, pct)].
    Returns (blocked set, blocked_share dict, rounds)."""
    blocked, share, rounds = set(listed), {}, 0
    while True:
        rounds += 1
        totals = defaultdict(int)
        for owned, os_ in owners.items():
            for owner, pct in os_:
                if owner in blocked:
                    totals[owned] += pct
        new = {e: s for e, s in totals.items() if s >= 50 and e not in blocked}
        if not new:
            return blocked, share, rounds
        blocked |= set(new)
        share.update(new)


def name(g, n):
    return (g["supplier"].get(n) or g["company"].get(n) or {}).get("name:String", n)


def _nearest(g, start, ok_node, target):
    """Shortest upward OWNED_BY path from start to a node satisfying target,
    passing only through nodes satisfying ok_node. Returns the node list or None."""
    frontier, seen = [[start]], {start}
    while frontier:
        nxt = []
        for path in frontier:
            for owner, _ in g["owners"].get(path[-1], []):
                if owner in seen or not ok_node(owner):
                    continue
                p = path + [owner]
                if target(owner):
                    return p
                seen.add(owner)
                nxt.append(p)
        frontier = nxt
    return None


def uflpa_chain(g, sid):
    """Shortest SOURCES_FROM chain from a supplier to a maker on the UFLPA Entity
    List, at any tier, or None."""
    frontier, seen = [[sid]], {sid}
    while frontier:
        nxt = []
        for path in frontier:
            for m in g["sources"].get(path[-1], []):
                if m in seen:
                    continue
                p = path + [m]
                if m in g["uflpa"]:
                    return p
                seen.add(m); nxt.append(p)
        frontier = nxt
    return None


def available(g, sid, pid):
    return sum(g["stock"][w].get(pid, 0) for w in g["warehouses"].get(sid, []))


def report(g, blocked, share, supplier, product, region, quantity=0):
    """The validation report for one supplier: [(rule, severity, detail)]."""
    sid = g["by_name"].get(supplier)
    if sid is None:
        return [("existence", "violation", "not in registry")]
    out, s = [], g["supplier"][sid]
    if s["status:String"] != "active":
        out.append(("status", "violation", s["status:String"]))
    pid, rid = g["prod_by_name"].get(product), g["reg_by_name"].get(region)
    if not any(e["~to"] == pid and e["approval_status:String"] == "active" for e in g["approved"][sid]):
        out.append(("approval", "violation", product))
    if rid not in g["operates"][sid]:
        out.append(("region", "violation", region))
    if sid in blocked:
        chain = _nearest(g, sid, lambda n: n in blocked, lambda n: n in g["listed"])
        out.append(("sanctions", "violation", " -> ".join(name(g, n) for n in chain)
                    + f" ({len(chain) - 1} hops)" if chain else "blocked"))
    else:
        chain = _nearest(g, sid, lambda n: True, lambda n: n in blocked)
        if chain:
            pct = dict(g["owners"][chain[-2]])[chain[-1]]
            out.append(("sanctions-exposure", "warning",
                        f"{name(g, chain[-1])} holds {pct}% of {name(g, chain[-2])}"))
    if rid and g["region"][rid].get("country:String") == "US":
        chain = uflpa_chain(g, sid)
        if chain:
            out.append(("uflpa", "violation", " -> ".join(name(g, n) for n in chain)
                        + f" ({len(chain) - 1} tiers)"))
    if quantity > 0 and available(g, sid, pid) < quantity:
        out.append(("inventory", "violation", f"{available(g, sid, pid)} available, {quantity} needed"))
    req = {g["cert"][c]["code:String"] for n in (pid, rid) if n for c in g["requires"].get(n, set())}
    held = {g["cert"][c]["code:String"] for c, e in g["holds"][sid].items() if e["cert_status:String"] == "active"}
    if req - held:
        out.append(("certification", "violation", ", ".join(sorted(req - held))))
    return out


# supplier, product, region, expected {(rule, severity)}[, quantity]
EXPECTED = [
    # The headline order: one request, four violations at four depths.
    ("AnyCompany Components",      "Server Hardware", "US-East",
     {("sanctions", "violation"), ("uflpa", "violation"), ("certification", "violation"),
      ("inventory", "violation")}, 40),
    ("AnyCompany Components",      "Server Hardware", "EU-Central", {("sanctions", "violation")}),
    ("AnyCompany Hardware Inc",       "Server Hardware", "US-East",
     {("status", "violation"), ("approval", "violation"), ("certification", "violation")}),
    ("AnyCompany Cloud Ltd",      "Storage Arrays",  "EU-Central",
     {("approval", "violation"), ("region", "violation"), ("certification", "violation")}),
    ("AnyCompany Systems",            "Server Hardware", "EU-Central", {("certification", "violation")}),
    ("AnyCompany Supply Co",            "Server Hardware", "EU-Central", set()),
    ("AnyCompany Electronics",     "Server Hardware", "EU-Central", {("sanctions-exposure", "warning")}),
    ("Nonexistent Supplier Ltd", "Server Hardware", "EU-Central", {("existence", "violation")}),
    ("AnyCompany Devices",       "Server Hardware", "US-East",    {("uflpa", "violation")}),
    ("AnyCompany Devices",       "Server Hardware", "EU-Central", set()),
]

# OFAC's own worked examples: FAQ 399, and FAQ 401 Examples 1-5.
OFAC_EXAMPLES = [
    ("FAQ 399: X 25% of A, Y 25% of A", {"X", "Y"}, [("A", "X", 25), ("A", "Y", 25)], "A", True),
    ("FAQ 401 Ex 1", {"X"}, [("A", "X", 50), ("B", "A", 50)], "B", True),
    ("FAQ 401 Ex 2", {"X"}, [("A", "X", 50), ("B", "X", 50), ("C", "A", 25), ("C", "B", 25)], "C", True),
    ("FAQ 401 Ex 3", {"X"}, [("A", "X", 50), ("B", "X", 10), ("B", "A", 40)], "B", True),
    ("FAQ 401 Ex 4", {"X"}, [("A", "X", 50), ("B", "X", 25), ("C", "A", 25), ("C", "B", 25)], "C", False),
    ("FAQ 401 Ex 5", {"X"}, [("A", "X", 25), ("B", "X", 25), ("C", "A", 50), ("C", "B", 50)], "C", False),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="./neptune_data")
    a = ap.parse_args()
    failures = 0

    print("OFAC worked examples")
    for label, listed, edges, target, expect in OFAC_EXAMPLES:
        owners = defaultdict(list)
        for owned, owner, pct in edges:
            owners[owned].append((owner, pct))
        got = target in propagate(listed, owners)[0]
        failures += got != expect
        print(f"  [{'PASS' if got == expect else 'FAIL'}] {label}: {target} blocked={got} (OFAC: {expect})")

    g = load(a.data)
    blocked, share, rounds = propagate(set(g["listed"]), g["owners"])
    print(f"\nLoaded {len(g['supplier']):,} suppliers, {len(g['company']):,} companies; "
          f"{len(g['listed'])} listed; propagation finished in {rounds} rounds\n")

    for supplier, product, region, expected, *qty in EXPECTED:
        rows = report(g, blocked, share, supplier, product, region, *qty)
        got = {(r, sev) for r, sev, _ in rows}
        ok = got == expected
        failures += not ok
        print(f"[{'PASS' if ok else 'FAIL'}] {supplier:<25} " +
              ("; ".join(f"{r}/{sev}: {d}" for r, sev, d in rows) or "conforms"))
        if not ok:
            print(f"       expected {sorted(expected)}")

    print()
    for label, sup, prod, reg, qty, expect in [
            ("AnyCompany Supply 50 Server Hardware (in stock)", "AnyCompany Supply Co", "Server Hardware", "EU-Central", 50, False),
            ("AnyCompany Supply 5,000 Server Hardware (more than stocked)", "AnyCompany Supply Co", "Server Hardware", "EU-Central", 5000, True),
            ("AnyCompany Electronics 10 Server Hardware (in stock)", "AnyCompany Electronics", "Server Hardware", "EU-Central", 10, False)]:
        got = any(r == "inventory" for r, _, _ in report(g, blocked, share, sup, prod, reg, qty))
        failures += got != expect
        print(f"[{'PASS' if got == expect else 'FAIL'}] {label}: inventory violation={got}")
    mh = "co-ac-components-holdings"
    print(f"\nAnyCompany Components Holdings BV: blocked owners hold {share.get(mh, 0)}% "
          f"(AnyCompany Group SA 30% + AnyCompany Capital LP 25%)")
    if share.get(mh) != 55:
        failures += 1
        print("  FAIL: expected 55%")

    # The workshop's walks are unbounded (*1..), which is safe because the chains are this shallow.
    # In production, a bound chosen from these depths keeps a walk's cost predictable.
    def deepest(adj):
        memo = {}
        def depth(n, seen=frozenset()):
            if n not in memo:
                memo[n] = max((1 + depth(m, seen | {n}) for m in adj.get(n, []) if m not in seen), default=0)
            return memo[n]
        return max((depth(n) for n in list(adj)), default=0)
    print(f"\nDeepest chains: {deepest({k: [o for o, _ in v] for k, v in g['owners'].items()})} OWNED_BY hops, "
          f"{deepest(g['sources'])} SOURCES_FROM hops")

    sup = list(g["supplier"])
    n_blocked = sum(1 for s in sup if s in blocked)
    n_warn = sum(1 for s in sup if s not in blocked and
                 _nearest(g, s, lambda n: True, lambda n: n in blocked))
    n_any = sum(1 for s in sup if _nearest(g, s, lambda n: True, lambda n: n in g["listed"]))
    print(f"\nRealism: {n_blocked:,} suppliers blocked ({n_blocked / len(sup):.1%}), "
          f"{n_warn:,} with a minority exposure warning ({n_warn / len(sup):.1%})")
    print(f"A naive 'any sanctioned company anywhere upstream' rule would block {n_any:,} "
          f"({n_any / len(sup):.1%}), {n_any - n_blocked:,} of them wrongly under OFAC's rule")
    exposed = [s for s in sup if uflpa_chain(g, s)]
    depth = defaultdict(int)
    for s in exposed:
        depth[len(uflpa_chain(g, s)) - 1] += 1
    print(f"UFLPA: {len(exposed):,} suppliers ({len(exposed) / len(sup):.1%}) source, at some tier, "
          f"from an entity on the list; by tier: {dict(sorted(depth.items()))}")

    print("\nRESULT:", "ALL SCENARIOS CORRECT" if failures == 0 else f"{failures} PROBLEM(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
