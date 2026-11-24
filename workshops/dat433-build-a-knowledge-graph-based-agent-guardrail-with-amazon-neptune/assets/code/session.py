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
session.py - the helpers the workshop notebooks' named cells call.

    Cell 0.1 · Connect           from session import connect;  connect(globals())

connect() runs workshop.setup(), makes sure the graph is loaded (the notebook instance
preloads it at start, see preload_graph.py) and that OFAC's 50 Percent Rule has been
computed, then adds the workshop's names to the notebook: oc, ORDER, params, the display
helpers, and the per-page helpers below. After a kernel restart, run it again.

Every rule lives in the queries under your-guard/queries and in guard_rules.py; nothing
here decides whether an order is allowed.
"""

import hashlib
import json
import os
import shutil
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# ~/SageMaker/workshop: the notebooks, your-guard/ (the files you write, and the files the deployed
# guard runs), and helpers/ (this code, given). HOME is your-guard/: every answer-file path is
# relative to it.
ROOT = os.path.join(os.path.expanduser("~"), "SageMaker", "workshop")
HOME = os.path.join(ROOT, "your-guard")
HERE = os.path.dirname(os.path.abspath(__file__))
REFERENCE = os.path.join(HERE, "reference")

# The order the unguarded agent drafts at Start: every page reads it.
ORDER = dict(supplier="AnyCompany Components", product="Server Hardware", region="US-East", quantity=40)

# The %%oc cells bind these with -qp.
def _params():
    """The parameters the %%oc cells pass with -qp params: the order, the two suppliers the session
    compares, and the rule settings from queries/rule_settings.json."""
    from verify import rule_settings
    return json.dumps({"supplier_name": ORDER["supplier"], "product_name": ORDER["product"],
                       "region_name": ORDER["region"],
                       "named_suppliers": ["AnyCompany Components", "AnyCompany Electronics"],
                       **rule_settings()})

EXPECTED_SUPPLIERS = 50000

# The files the attendee (or the reference) provides; the deploy ships them.
ANSWER_FILES = ["neptune_guard.py", "queries/ownership_50pct.cypher", "queries/violations.cypher",
                "queries/recommend.cypher", "guard_rules.py"]

_state = {"ready": False}


# ---------------------------------------------------------------------------
# Connect and resume
# ---------------------------------------------------------------------------
def _ensure_strands():
    """The notebook's python3 kernel (where graph-notebook registers %%oc) may not have
    Strands Agents, which OnCreate installs in conda_python3. Install it into this kernel."""
    import importlib
    import importlib.util
    import subprocess
    import sys
    if importlib.util.find_spec("strands") is None:
        from ui import busy
        with busy("Installing Strands Agents into this kernel (once)"):
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet",
                                   "strands-agents>=1.58,<2"])
            importlib.invalidate_caches()


# The helper modules Connect reloads when their file has changed since this kernel imported them.
_HELPERS = ["ui", "workshop", "verify", "scenarios", "guardrail", "shacl_check", "deploy_agent"]
_LOADED_AT = time.time()


def _refresh_helpers():
    """If any helper file changed after this kernel imported it (a facilitator pushed a fix during
    the event), reload it, and this module too, so that running Connect again picks the change up
    without a kernel restart. Returns True if this module was reloaded."""
    import importlib
    changed = [m for m in _HELPERS if m in sys.modules
               and os.path.getmtime(sys.modules[m].__file__) > _LOADED_AT]
    for m in changed:
        importlib.reload(sys.modules[m])
    if changed or os.path.getmtime(__file__) > _LOADED_AT:
        importlib.reload(sys.modules[__name__])
        return True
    return False


def connect(namespace, all_rules=False):
    """Cell 0.1: setup(), the graph, the 50% rule, and the session's names. The session's guard
    starts with no rules (Step 1) unless you've installed some; Go deeper and Kiro pass
    all_rules=True."""
    if _refresh_helpers():
        return sys.modules[__name__].connect(namespace, all_rules)   # the reloaded module's connect
    import workshop
    os.makedirs(os.path.join(HOME, "queries"), exist_ok=True)
    os.chdir(HOME)   # %%writefile and answer-file paths are relative to your-guard/
    if HOME not in sys.path:
        sys.path.insert(0, HOME)   # neptune_guard.py and guard_rules.py import from here
    _ensure_strands()
    # Any answer file that's missing (a notebook skipped, or not reached yet) gets the reference,
    # so every notebook runs on its own. Files you wrote are never touched.
    save_reference_answers(show=False)
    workshop.setup()
    ensure_graph()
    ensure_ownership_rule()
    from verify import ALL_RULES
    if all_rules:
        _write_rules(ALL_RULES)
    elif not os.path.exists(RULES_FILE):
        _write_rules([])
    _bind(namespace)
    _set_graph_colours()
    _state["namespace"] = namespace
    from ui import show_status
    show_status(True, "Setup complete. ORDER is the PO the unguarded agent is about to draft: "
                      f"{ORDER['quantity']} x {ORDER['product']} from {ORDER['supplier']} to {ORDER['region']}.")
    _state["ready"] = True


# Colours for `%%oc -g blocked` (Cells 2.5 and 3.3a). graph-notebook groups each vertex by its
# `blocked` value: `true` for an entity the 50% rule blocked, DEFAULT_GROUP for everything else
# (the property is absent). Orange against blue, from the Okabe-Ito palette, so the two stay
# distinct with the common forms of colour blindness.
BLOCKED_COLOURS = {
    "true": {"color": {"background": "#E66100", "border": "#993D00",
                       "highlight": {"background": "#FF8C33", "border": "#993D00"}},
             "font": {"color": "black"}},
    "DEFAULT_GROUP": {"color": {"background": "#5D9FD6", "border": "#1F5A8C",
                                "highlight": {"background": "#8CC0EB", "border": "#1F5A8C"}},
                      "font": {"color": "black"}},
}
def _string_bool_groups():
    """graph-notebook keeps a boolean property's value as the group (Python True), and the Graph
    tab's colour lookup only matches string group names. Turn True/False into "true"/"false" as
    each vertex is added, so `-g blocked` picks up BLOCKED_COLOURS. Display only."""
    from graph_notebook.network.EventfulNetwork import EventfulNetwork
    if getattr(EventfulNetwork.add_node, "_bool_groups", False):
        return   # already patched (Connect run again)
    original = EventfulNetwork.add_node

    def add_node(self, node_id, data=None):
        if data and isinstance(data.get("group"), bool):
            data = dict(data, group=str(data["group"]).lower())
        return original(self, node_id, data)
    add_node._bool_groups = True
    EventfulNetwork.add_node = add_node


def _set_graph_colours():
    """Give graph-notebook's Graph tab contrasting colours for the `blocked` groups. Display
    only: if the magic isn't available (outside the Neptune workbench), carry on."""
    try:
        _string_bool_groups()
        from IPython import get_ipython
        from graph_notebook.options import vis_options_merge
        ip = get_ipython()
        magic = ip.find_cell_magic("graph_notebook_vis_options") if ip is not None else None
        if magic is not None:
            # The settings %graph_notebook_vis_options edits, merged in directly: the magic itself
            # displays every setting when it changes them, which would fill the Connect cell.
            owner = magic.__self__
            owner.graph_notebook_vis_options = vis_options_merge(
                owner.graph_notebook_vis_options, {"groups": BLOCKED_COLOURS})
    except Exception:   # noqa: BLE001  colours are cosmetic; never fail Connect over them
        pass


def _bind(namespace):
    import importlib
    import guardrail
    import neptune_guard
    import verify
    import workshop
    from deploy_agent import invoke_deployed_agent
    from scenarios import HEADLINE
    from strands.hooks import BeforeToolCallEvent
    from strands.plugins import hook as strands_hook
    from ui import show_note, show_status
    namespace.update({k: getattr(workshop, k) for k in dir(workshop) if not k.startswith("_")})
    os.makedirs(os.path.join(HOME, "queries"), exist_ok=True)
    namespace.update({
        "time": time, "json": json, "os": os, "invoke_deployed_agent": invoke_deployed_agent,
        "ORDER": dict(ORDER), "params": _params(),
        "reload": importlib.reload, "guard_rules": importlib.import_module("guard_rules"),
        "NeptuneGuardPlugin": neptune_guard.NeptuneGuardPlugin, "build_agent": guardrail.build_agent,
        "hook": strands_hook, "BeforeToolCallEvent": BeforeToolCallEvent,
        "save_hook": save_hook, "check_hook": check_hook, "FakeRules": FakeRules,
        "HEADLINE": HEADLINE, "ask": ask, "record": record, "show_scoreboard": show_scoreboard,
        "PO": dict(supplier_name=ORDER["supplier"], product_name=ORDER["product"],
                   region_name=ORDER["region"], quantity=ORDER["quantity"]),
        "check_supplier": check_supplier_tool(), "ALWAYS_CHECK": PROMPT_RULE,
        "show_direct_call": show_direct_call, "ask_under_pressure": ask_under_pressure,
        "two_simple_checks": two_simple_checks,
        "seed_ownership_rule": verify.seed_ownership_rule, "ownership_round": ownership_round_or_stop,
        "check_ownership_rule": check_ownership_rule, "apply_ownership_rule": verify.apply_ownership_rule,
        "show_rule": show_rule, "full_report": full_report, "show_report": show_report,
        "validation_report": verify.validation_report, "run_query_file": verify.run_query_file,
        "stock_levels": verify.stock_levels, "show_stock": show_stock,
        "install_rules": install_rules, "ALL_RULES": verify.ALL_RULES,
        "run_ten_orders": run_ten_orders, "blocked_suppliers": blocked_suppliers,
        "undo_designation": undo_designation,
        "save_rule": save_rule,
        "show_note": show_note, "show_status": show_status, "move_stock": move_stock,
        "check_blocked_chain": check_blocked_chain, "show_candidate_paths": show_candidate_paths,
        "check_guard": check_guard, "check_uflpa_shape": check_uflpa_shape,
        "catch_up": catch_up, "save_reference_answers": save_reference_answers, "show_whose": show_whose,
        "deploy_guarded": deploy_guarded, "deploy_mcp": deploy_mcp,
        "mcp_server_status": mcp_server_status, "kiro_ide_link": kiro_ide_link,
    })


# ---------------------------------------------------------------------------
# The graph: preloaded at instance start, checked here
# ---------------------------------------------------------------------------
def _supplier_count():
    from workshop import oc
    return int(oc("MATCH (s:Supplier) RETURN count(s) AS n")[0]["n"])


def _loader_jobs():
    """Load ids Neptune's bulk loader knows about, newest first."""
    ep, port = os.environ["NEPTUNE_ENDPOINT"], os.environ.get("NEPTUNE_PORT", "8182")
    with urllib.request.urlopen(f"https://{ep}:{port}/loader?limit=5", timeout=30) as r:
        return json.loads(r.read()).get("payload", {}).get("loadIds", [])


def ensure_graph(timeout_seconds=1200):
    """The instance starts the bulk load when it boots (preload_graph.py). If it is still
    running, wait for it; if it never ran, load now. Prints one status line."""
    from ui import busy, show_status
    if _supplier_count() >= EXPECTED_SUPPLIERS:
        show_status(True, f"Graph loaded: {_supplier_count():,} suppliers")
        ensure_stock()
        return
    from setup_graph import load_status
    running = None
    for load_id in _loader_jobs():
        status = load_status(load_id)["payload"]["overallStatus"]["status"]
        if status in ("LOAD_IN_PROGRESS", "LOAD_IN_QUEUE", "LOAD_NOT_STARTED"):
            running = load_id
            break
    if running is None:
        from setup_graph import generate_and_upload, bulk_load_and_wait, expected_loader_records
        bucket, prefix = os.environ["DATA_BUCKET"], os.environ.get("DATA_PREFIX", "guardrail/neptune_data")
        with busy("The graph isn't loaded yet: generating the dataset and uploading it to S3"):
            uri, _ = generate_and_upload(bucket, prefix)
        bulk_load_and_wait(uri, os.environ["NEPTUNE_LOAD_ROLE_ARN"], os.environ["AWS_REGION"],
                           expected_records=expected_loader_records())
    else:
        with busy("The instance is still loading the graph (it started when the instance booted)"):
            t0 = time.time()
            while time.time() - t0 < timeout_seconds:
                status = load_status(running)["payload"]["overallStatus"]["status"]
                if status == "LOAD_COMPLETED":
                    break
                if status not in ("LOAD_IN_PROGRESS", "LOAD_IN_QUEUE", "LOAD_NOT_STARTED"):
                    raise RuntimeError(f"Bulk load {running} ended with {status}: ask a facilitator")
                time.sleep(3)
    show_status(True, f"Graph loaded: {_supplier_count():,} suppliers")
    ensure_stock()


def ensure_stock(timeout_seconds=600):
    """The stock counts live in the DynamoDB stock table, which the instance fills when it
    starts (preload_graph.py). Wait for it, or fill it now if that never ran."""
    from ui import busy, show_status
    from setup_graph import load_stock, stock_loaded
    table = os.environ["STOCK_TABLE"]
    if not stock_loaded(table):
        log = os.path.join(HERE, "preload.log")
        text = open(log).read() if os.path.exists(log) else ""
        preloading = bool(text) and "Preload complete" not in text and "Traceback" not in text
        with busy("Waiting for the instance to fill the stock table" if preloading
                  else "Filling the stock table (about a minute)"):
            t0 = time.time()
            while preloading and not stock_loaded(table) and time.time() - t0 < timeout_seconds:
                time.sleep(5)
            if not stock_loaded(table):
                _ensure_dataset_files()
                load_stock(table)
    show_status(True, f"Stock table ready: {table}")


def _ensure_dataset_files(out_dir="/tmp/neptune_data"):
    """The generator is deterministic, so regenerating gives the same counts the graph was built with."""
    from generate_dataset import STOCK_LEVELS_CSV, generate
    if not os.path.exists(os.path.join(out_dir, STOCK_LEVELS_CSV)):
        generate(out_dir, 50000, 5000, 40, 42)


def ensure_ownership_rule():
    """Page 1 and page 3 read the 50% rule's result; compute it if it has never run.
    Page 2 recomputes it with your query."""
    from workshop import oc
    if oc("MATCH (r:PolicyRun {name: 'ofac-50-percent'}) RETURN count(r) AS n")[0]["n"]:
        return
    from ui import busy
    from verify import apply_ownership_rule
    with busy("Computing OFAC's 50% rule once, so the report has a result to read"):
        apply_ownership_rule()


# ---------------------------------------------------------------------------
# Page 1 · Where the check lives
# ---------------------------------------------------------------------------
PROMPT_RULE = ("\n- Before you draft any purchase order or accept any offer, ALWAYS call "
               "check_supplier first, and do not proceed if it reports a violation.")


def _check_supplier_tool():
    from strands import tool
    from verify import verify_supplier_relationship

    @tool
    def check_supplier(supplier_name: str, product_name: str, region_name: str,
                       quantity: int = 0) -> dict:
        """Check a supplier against AnyCompany's rules (sanctions, forced labor, certifications,
        stock) for a product, delivery region and quantity.

        Args:
            supplier_name: Full supplier name
            product_name: Product category
            region_name: Delivery region
            quantity: Units being ordered
        """
        return verify_supplier_relationship(supplier_name, product_name, region_name, quantity)

    return check_supplier


def _reference_rules():
    """The reference guard_rules module (page 1 uses it; on page 4 you write your own)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("reference_guard_rules",
                                                  os.path.join(REFERENCE, "guard_rules.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_supplier_tool():
    """Option B's tool: the whole report, on demand, if the model decides to call it."""
    return _check_supplier_tool()


def show_direct_call(name, result, ran=None):
    """Cells 4.1 and 4.3: one direct tool call's outcome, and what the caller got back."""
    from ui import show_note, show_status
    text = result["content"][0]["text"]
    if result["status"] == "error" and text.startswith("BLOCKED"):
        show_status(True, f"{name}: {text.splitlines()[0][:160]}")
    else:
        try:
            po = json.loads(text).get("po_number", "")
        except ValueError:
            po = ""
        show_note(f"{name}: PO drafted {po}. Nothing checked the order.")
    if ran:
        _say_ran(ran)


def ask_under_pressure(agents, request):
    """Cell 4.2: send the same request to the three agents, in parallel, and show whether
    each one checked and whether the PO was drafted."""
    import guardrail
    from ui import busy, show_request, show_results, show_trace

    def one(item):
        name, agent = item
        guardrail.run(agent, request)
        return name, guardrail.trace(agent)

    show_request(request)
    with busy("Sending the request to agents A, B and C at once"):
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(one, agents.items()))
    rows = []
    for name, steps in results:
        hook = name.startswith("C")
        gated = any(t["tool"] == "draft_purchase_order" for t in steps)
        if hook:
            checked = "yes, before the PO tool ran" if gated else "no PO attempted"
        else:
            checked = "yes" if any(t["tool"] == "check_supplier" for t in steps) else "no"
        drafted = any(t["tool"] == "draft_purchase_order" and t["outcome"] == "ok"
                      and ORDER["supplier"] in json.dumps(t["input"]) for t in steps)
        rows.append((name, checked, "the hook" if hook else "the model",
                     "PO DRAFTED" if drafted else "not drafted"))
    show_results(rows, ["agent", "checked the graph?", "who decided to check",
                        f"{ORDER['supplier']} PO"],
                 title="The same request, three places for the check")
    for name, steps in results:
        show_trace(steps, title=f"{name}: what the agent did")


# ---------------------------------------------------------------------------
# Page 2 · Look it up or compute it
# ---------------------------------------------------------------------------
NAMED = ["AnyCompany Components", "AnyCompany Electronics"]
_options_seen = {}


SCREEN_NAME = "(s)-[:OWNED_BY]->(:Company)-[:SANCTIONED_BY]->(:SanctionsList)"


def two_simple_checks(any_listed_owner):
    """Cell 2.2: option A (screen the supplier's direct owners against the list) and option B
    (the any-depth pattern passed in) over all suppliers, with their verdicts on the two
    named suppliers."""
    from workshop import oc
    from ui import busy, show_ownership, show_results
    total = _supplier_count()
    rows = []
    with busy("Running both checks over every supplier"):
        for label, predicate in [("A · screen the name", SCREEN_NAME),
                                 ("B · any listed owner upstream", any_listed_owner)]:
            n = int(oc(f"MATCH (s:Supplier) WHERE {predicate} RETURN count(s) AS n")[0]["n"])
            hit = {r["name"] for r in oc(f"MATCH (s:Supplier) WHERE s.name IN $names AND {predicate} "
                                         "RETURN s.name AS name", names=NAMED)}
            _options_seen[label] = n
            rows.append((label, f"{n:,}", f"{100 * n / total:.1f}%",
                         *("blocked" if name in hit else "passes" for name in NAMED)))
    show_results(rows, ["option", "suppliers blocked", "of all", *NAMED],
                 title="OFAC's answer: AnyCompany Components is blocked; AnyCompany Electronics is not")
    stakes, got = _named_ownership()
    verdicts = {name: " · ".join(f"{r[0][0]}: {r[3 + i]}" for r in rows) for i, name in enumerate(NAMED)}
    show_ownership([{"title": "The two suppliers, before any rule runs", "ok": None, "stakes": stakes,
                     "nodes": {n: {"blocked": False, "listed": g["listed"]} for n, g in got.items()},
                     "notes": {n: (None, f"{verdicts[n]} · OFAC: {'blocked' if n == NAMED[0] else 'not blocked'}")
                               for n in NAMED}}],
                   title="What each option sees: the same listed owner, at 30% + 25% for one and 20% for the other",
                   native="Neptune's own view: Cell 2.1 for AnyCompany Components' chains, and Cell 2.5 for both.")


def show_rule_vs_options():
    """Cell 2.4: the rule's result beside the options from Cell 2.2."""
    from workshop import oc
    from ui import show_bars
    total = _supplier_count()
    blocked = int(oc("MATCH (s:Supplier) WHERE s.blocked = true RETURN count(s) AS n")[0]["n"])
    exposed = int(oc("MATCH (s:Supplier) WHERE coalesce(s.blocked, false) = false "
                     "AND (s)-[:OWNED_BY*1..]->(:Company)-[:SANCTIONED_BY]->(:SanctionsList) "
                     "RETURN count(s) AS n")[0]["n"])
    rows = [(label, n, f"{n:,} suppliers blocked ({100 * n / total:.1f}%)") for label, n in _options_seen.items()]
    rows.append(("C · OFAC's 50% rule", blocked, f"{blocked:,} suppliers blocked ({100 * blocked / total:.1f}%)"))
    show_bars(rows,
              title=f"{exposed:,} suppliers have a listed owner upstream but are not blocked: "
                    "a warning under OFAC's rule, a wrongful block under option B")


def catch_up(what):
    """Fallback boxes: load the reference answer and carry on.
    'ownership' (page 2) recomputes the rule with the reference query;
    'hook' (Step 1) puts the reference neptune_guard.py in place."""
    from ui import busy, show_status
    if what == "ownership":
        _copy_reference("queries/ownership_50pct.cypher")
        from verify import apply_ownership_rule
        with busy("Recomputing OFAC's 50% rule with the reference query"):
            r = apply_ownership_rule()
        show_status(True, f"Reference rule loaded: converged in {r['rounds']} rounds, "
                          f"{r['suppliers']:,} suppliers blocked. Go on to the next page.")
    elif what in ("hook", "guard"):
        _copy_reference("neptune_guard.py")
        _rebind_hook()
        show_status(True, "Reference neptune_guard.py loaded. Run Cell 1.2 to check it, then Cell 1.3.")
    else:
        show_status(False, f"No catch-up named {what!r}: use 'ownership' or 'hook'.")


def _copy_reference(path):
    target = os.path.join(HOME, path)
    if os.path.exists(target) and _sha(target) != _sha(os.path.join(REFERENCE, path)):
        shutil.copyfile(target, target + ".mine")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(os.path.join(REFERENCE, path), target)


# ---------------------------------------------------------------------------
# Run-and-read cells: the query you read is in the cell, the plumbing is here
# ---------------------------------------------------------------------------
def ownership_round_or_stop():
    """Cell 2.4: one round of your query; on an error, says so and returns None (the loop stops)."""
    from verify import ownership_round
    from ui import show_status
    try:
        return ownership_round()
    except Exception as e:
        show_status(False, f"Your query didn't run: {e}")
        return None


def check_ownership_rule(per_round):
    """Cell 2.4: the rounds your query ran, OFAC's six worked examples and AnyCompany's graph,
    then the rule beside options A and B. On a FAIL, loads the reference and recomputes."""
    from verify import apply_ownership_rule, check_ofac_examples, record_ownership_rule
    from ui import busy, show_bars, show_ownership, show_status
    from workshop import checkpoint
    ok = False
    try:
        converged = bool(per_round) and per_round[-1] == 0
        result = record_ownership_rule([n for n in per_round if n is not None])
        show_bars([(f"round {i}", n or 0, "error" if n is None else f"{n:,} newly blocked")
                   for i, n in enumerate(per_round, 1)],
                  title=(f"Converged in {result['rounds']} rounds: {result['companies']:,} companies "
                         f"and {result['suppliers']:,} suppliers blocked") if converged
                  else "Did not converge: every round blocked something (or the query failed)")
        with busy("Running your query on OFAC's worked examples"):
            examples = check_ofac_examples()
        cards, faq = [], []
        for r in examples:
            ok_ = r["blocked"] == r["expected"]
            faq.append("PASS" if ok_ else "FAIL")
            said = "blocked" if r["expected"] else "not blocked"
            got_ = (f"blocked at {r['share']}%" if r["share"] else "blocked") if r["blocked"] else "not blocked"
            title, what = OFAC_EXAMPLE_NOTES[r["example"]]
            cards.append({"title": title, "subtitle": what, "ok": ok_, "stakes": r["stakes"],
                          "nodes": {n: {"blocked": v["blocked"], "listed": n in r["listed"]}
                                    for n, v in r["nodes"].items()},
                          "notes": {r["entity"]: (ok_, f"OFAC: {said} · yours: {got_}")}})
        show_ownership(cards, title="OFAC's worked examples (FAQs 399 and 401), as your query left them",
                       native="Each example exists in Neptune only while the check runs, so it has no Neptune view.")
        stakes, got = _named_ownership()
        mine, notes = [], {}
        for n, exp, _ in OWNERSHIP_CHECKS:
            g = got.get(n, {})
            ok_ = g.get("blocked") == exp
            mine.append("PASS" if ok_ else "FAIL")
            notes[n] = (ok_, (f"blocked at {g['share']}%" if g.get("share") else "blocked")
                        if g.get("blocked") else "not blocked")
        show_ownership([{"title": "AnyCompany Components and AnyCompany Electronics", "ok": all(m == "PASS" for m in mine),
                         "stakes": stakes, "notes": notes,
                         "nodes": {n: {"blocked": g["blocked"], "listed": g["listed"]} for n, g in got.items()}}],
                       title="AnyCompany's ownership graph, as your query left it",
                       native="Neptune's own view of this graph is the Graph tab in Cell 2.5.")
        ok = converged and all(r == "PASS" for r in faq + mine)
    except Exception as e:
        show_status(False, f"The check didn't run: {e}")
    try:
        with open(os.path.join(HOME, "queries", "ownership_50pct.cypher")) as f:
            if ok and "$ofac_threshold" not in f.read():
                from ui import show_note
                show_note("Your query writes the threshold as a number. Use $ofac_threshold, so that a change "
                          "in queries/rule_settings.json reaches the rule.")
    except OSError:
        pass
    if not checkpoint(ok, "queries/ownership_50pct.cypher"):
        apply_ownership_rule()   # recompute with the reference, so the next pages read a correct result
    show_rule_vs_options()



def _named_ownership():
    """The ownership paths from AnyCompany Components and AnyCompany Electronics up to the sanctions
    list, as (owned, owner, pct) stakes, and each entity on them as {name: {blocked, listed, share}}."""
    from workshop import oc
    stakes = [(e["owned"], e["owner"], e["pct"]) for e in oc(
        "MATCH p = (s:Supplier)-[:OWNED_BY*1..]->(:Company)-[:SANCTIONED_BY]->(:SanctionsList) "
        "WHERE s.name IN $named "
        "UNWIND relationships(p) AS r WITH DISTINCT r WHERE type(r) = 'OWNED_BY' "
        "RETURN startNode(r).name AS owned, endNode(r).name AS owner, r.share_pct AS pct", named=NAMED)]
    got = {r["name"]: r for r in oc(
        "MATCH (n) WHERE n.name IN $names "
        "RETURN n.name AS name, coalesce(n.blocked, false) AS blocked, "
        "coalesce(n.listed, false) AS listed, n.blocked_share AS share",
        names=sorted({n for e in stakes for n in e[:2]}))}
    # Before the rule runs, "listed" isn't set yet: read it from the list edge instead.
    on_list = {r["name"] for r in oc("MATCH (c:Company)-[:SANCTIONED_BY]->(:SanctionsList) WHERE c.name IN $names "
                                     "RETURN c.name AS name", names=list(got))}
    for n, g in got.items():
        g["listed"] = g["listed"] or n in on_list
    return stakes, got

# What each of OFAC's worked examples shows, in plain words, for the cards in Cell 2.4. OFAC publishes
# its guidance as numbered answers to frequently asked questions: FAQ 399 says stakes held by
# different blocked owners add up, and FAQ 401 works through five ownership examples.
OFAC_EXAMPLE_NOTES = {
    "FAQ 399": ("OFAC FAQ 399", "Two listed owners hold 25% each. Their stakes add up to 50%, so A is blocked."),
    "FAQ 401 Ex 1": ("OFAC FAQ 401 · Example 1",
                     "A block passes down the chain: X's 50% blocks A, and A's 50% blocks B. "
                     "(Example 1 in the picture before Cell 2.2.)"),
    "FAQ 401 Ex 2": ("OFAC FAQ 401 · Example 2",
                     "Stakes held through blocked owners add up: 25% through A plus 25% through B. "
                     "(Example 2 in the picture.)"),
    "FAQ 401 Ex 3": ("OFAC FAQ 401 · Example 3",
                     "Direct and indirect stakes add up: X's own 10% plus blocked A's 40%."),
    "FAQ 401 Ex 4": ("OFAC FAQ 401 · Example 4",
                     "Only blocked owners count: B isn't blocked, so its 25% counts for nothing. "
                     "(Example 3 in the picture.)"),
    "FAQ 401 Ex 5": ("OFAC FAQ 401 · Example 5",
                     "Neither A nor B is blocked, so C isn't either, although X stands behind both."),
}

OWNERSHIP_CHECKS = [
    ("AnyCompany Components Holdings BV", True, "AnyCompany Group 30% + AnyCompany Capital 25% = 55%; neither alone reaches 50%"),
    ("AnyCompany Components", True, "100% owned by a blocked entity"),
    ("AnyCompany Electronics Group", False, "AnyCompany Industries holds only 20%"),
    ("AnyCompany Electronics", False, "its owner is not blocked"),
]


def blocked_suppliers():
    """Cell 3.5: how many suppliers the 50% rule's result marks blocked."""
    from workshop import oc
    return int(oc("MATCH (s:Supplier) WHERE s.blocked = true RETURN count(s) AS n")[0]["n"])


def undo_designation():
    """Cell 3.5: delist AnyCompany Partners AS again, and recompute the rule."""
    from verify import apply_ownership_rule
    from ui import busy, show_note
    from workshop import oc
    oc("MATCH (:Company {name: 'AnyCompany Partners AS'})-[e:SANCTIONED_BY]->() DELETE e")
    with busy("Undoing the designation and recomputing"):
        apply_ownership_rule()
    show_note("Undone: AnyCompany Partners AS is off the list again, and the rule is recomputed.")


def _show_supply_routes(title, supplier="AnyCompany Supply Co"):
    """Go deeper G.5: the supplier's routes to the order's region, from the graph, with each
    warehouse's live count from DynamoDB."""
    from workshop import oc
    from verify import stock_levels
    from ui import show_paths
    routes = oc("MATCH (:Supplier {name: $s})-[:HAS_WAREHOUSE]->(w:Warehouse)-[:STOCKS]->(p:Product {name: $p}), "
                "(w)-[:LOCATED_IN]->(r:Region)-[t:SHIPS_TO]->(:Region {name: $region}) "
                "RETURN id(w) AS wid, id(p) AS pid, w.name AS warehouse, r.name AS region, t.transit_days AS days "
                "ORDER BY days", s=supplier, p=ORDER["product"], region=ORDER["region"])
    units = stock_levels([(r["wid"], r["pid"]) for r in routes])
    paths = []
    for r in routes:
        n = units[(r["wid"], r["pid"])]
        enough = n >= ORDER["quantity"]
        paths.append({"tag": f"{r['days']} day{'s' if r['days'] != 1 else ''}", "tag_style": "clear" if enough else "blocked",
                      "steps": [("HAS_WAREHOUSE", {"label": r["warehouse"], "sub": f"{n} units in DynamoDB",
                                                   "style": "warn" if enough else "blocked"}),
                                ("LOCATED_IN", {"label": r["region"], "style": "clear"}),
                                (f"SHIPS_TO, {r['days']} d", {"label": ORDER["region"], "style": "clear"})]})
    show_paths({"label": supplier, "style": "supplier"}, paths, title=title,
               legend=[("warn", "a warehouse that can fill the order"), ("blocked", "one that can't")],
               native="The counts come from DynamoDB, so Neptune's graph view can't show them.")

def move_stock(key, units=0):
    """Go deeper G.5: the ranking for ORDER; then one count changes in the DynamoDB stock table, as
    the warehouse system would, and the ranking again. The graph doesn't change. Restores it."""
    import boto3
    from verify import recommend_alternatives, stock_levels
    from ui import show_code_block, show_results, show_status
    table = boto3.resource("dynamodb", region_name=os.environ["AWS_REGION"]).Table(os.environ["STOCK_TABLE"])
    cols = ["supplier", "tier", "approval_level", "available", "transit_days", "since"]

    def rank():
        return recommend_alternatives(ORDER["product"], ORDER["region"], exclude=ORDER["supplier"],
                                      quantity=ORDER["quantity"])["recommended"]
    k = (key["warehouse_id"], key["product_id"])
    before = stock_levels([k])[k]
    show_results(rank(), cols, title="Who can deliver ORDER instead")
    _show_supply_routes("AnyCompany Supply Co, before")
    try:
        table.update_item(Key=key, UpdateExpression="SET units = :u", ExpressionAttributeValues={":u": units})
        show_code_block(f"UpdateItem {key}: units {before} -> {units}", "The warehouse system updates one count")
        after = rank()
        show_results(after, cols, title="Same order, the Virginia warehouse empty")
        _show_supply_routes("AnyCompany Supply Co, after the shipment")
        gone = all(a["supplier"] != "AnyCompany Supply Co" for a in after)
        show_status(gone, "AnyCompany Supply now ships from Frankfurt (5 days) and drops out of the top five"
                    if gone else "AnyCompany Supply is still listed")
    finally:
        table.update_item(Key=key, UpdateExpression="SET units = :u", ExpressionAttributeValues={":u": before})
        show_status(True, f"Stock restored to {before} units; the graph never changed")


# ---------------------------------------------------------------------------
# Writing a piece: the cell holds only your fragment; these build the full file
# ---------------------------------------------------------------------------
def _ref(path):
    with open(os.path.join(REFERENCE, path)) as f:
        return f.read()


# What a finished answer must contain, after comments are stripped, so that saving an untouched
# starter doesn't look like success. (name: [(what the code must contain, what's missing if not)])
WRITTEN = {
    "before_tool": [("run_report(", "call self.rules.run_report(args)"),
                    ("except", "catch the exception, so the hook fails closed"),
                    ("block_message(", "call self.rules.block_message(...)"),
                    ("cancel_tool", "set event.cancel_tool")],
    "should_check": [("draft_purchase_order", "check draft_purchase_order"),
                     ("accept", "check send_offer_reply when it accepts")],
    "run_report": [("validation_report(", "call validation_report(...)")],
}
WHERE_CHECKED = {"before_tool": "Run Cell 1.2 to check it.",
                 "should_check": "The check below runs it.", "run_report": "The check below runs it."}


def _report_save(name, src, path):
    """After a save: a FAIL line naming what's still missing, or a note that says where it's checked.
    Saving is never a PASS: only a check is."""
    import re
    from ui import show_note, show_status
    code_only = "\n".join(re.sub(r"#.*", "", line) for line in src.splitlines())
    missing = [why for token, why in WRITTEN.get(name, []) if token not in code_only]
    if missing:
        show_status(False, f"Saved, but {name} isn't written yet: it doesn't "
                           f"{', or '.join(missing)}. Fill in the ✏️ lines and run this cell again.")
    else:
        show_note(f"Saved {name} to {os.path.basename(path)} (fingerprint {_sha(path)[:12]}). "
                  f"{WHERE_CHECKED.get(name, '')}")


def save_rule(fn):
    """Cells G.1, G.2: save one function you wrote into your-guard/guard_rules.py,
    replacing the version there (the file starts as the reference)."""
    import ast
    import inspect
    import textwrap
    path = os.path.join(HOME, "guard_rules.py")
    if not os.path.exists(path):
        shutil.copyfile(os.path.join(REFERENCE, "guard_rules.py"), path)
    src = open(path).read()
    lines = src.splitlines(keepends=True)
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == fn.__name__)
    new = textwrap.dedent(inspect.getsource(fn)).rstrip() + "\n"
    out = "".join(lines[:node.lineno - 1]) + new + "".join(lines[node.end_lineno:])
    with open(path, "w") as f:
        f.write(out)
    _report_save(fn.__name__, new, path)


GUARD_CASES = [  # label, expected, tool, arguments
    ("ORDER (4 violations)", "BLOCKED", "draft_purchase_order",
     dict(supplier_name="AnyCompany Components", product_name="Server Hardware", region_name="US-East", quantity=40)),
    ("AnyCompany Supply PO", "ok", "draft_purchase_order",
     dict(supplier_name="AnyCompany Supply Co", product_name="Server Hardware", region_name="US-East", quantity=40)),
    ("AnyCompany Electronics PO (warning only)", "ok", "draft_purchase_order",
     dict(supplier_name="AnyCompany Electronics", product_name="Server Hardware", region_name="EU-Central", quantity=10)),
    ("AnyCompany Hardware: accept offer", "BLOCKED", "send_offer_reply",
     dict(supplier_name="AnyCompany Hardware Inc", product_name="Server Hardware", region_name="US-East",
          decision="accept", message="Deal.")),
    ("AnyCompany Hardware: decline offer", "ok", "send_offer_reply",
     dict(supplier_name="AnyCompany Hardware Inc", product_name="Server Hardware", region_name="US-East",
          decision="decline", message="We'll pass.")),
    ("Unknown supplier", "BLOCKED", "draft_purchase_order",
     dict(supplier_name="Nonexistent Supplier Ltd", product_name="Server Hardware", region_name="EU-Central", quantity=1)),
]


def check_guard():
    """Checks G.1 and G.2: the guard, with your guard_rules.py, called directly with no
    model. The last case makes Neptune unreachable. Loads the reference on a FAIL."""
    import importlib
    import guard_rules
    import neptune_guard
    from guardrail import build_agent
    from ui import busy, show_code_block, show_results
    from workshop import checkpoint
    importlib.reload(guard_rules)
    importlib.reload(neptune_guard)
    agent = build_agent(guard=neptune_guard.NeptuneGuardPlugin(rules=guard_rules))

    def direct(tool, kw):
        res = getattr(agent.tool, tool)(record_direct_tool_call=False, **kw)
        text = res["content"][0]["text"]
        if res["status"] == "error" and text.startswith("BLOCKED"):
            return "BLOCKED", text
        return ("ok" if res["status"] == "success" else "error"), text

    rows = []
    with busy("Calling the tools directly, with no model involved"):
        for label, expected, tool, kw in GUARD_CASES:
            got = direct(tool, kw)[0]
            rows.append(("PASS" if got == expected else "FAIL", label, tool, expected, got))
        real = guard_rules.validation_report

        def unreachable(*a, **k):
            raise ConnectionError("simulated: Neptune endpoint unreachable")
        guard_rules.validation_report = unreachable
        try:
            got = direct("draft_purchase_order", GUARD_CASES[1][3])[0]
        finally:
            guard_rules.validation_report = real
        rows.append(("PASS" if got == "BLOCKED" else "FAIL", "AnyCompany Supply PO, Neptune unreachable",
                     "draft_purchase_order", "BLOCKED", got))
    show_results(rows, ["result", "case", "tool", "expected", "got"])
    show_code_block(direct(GUARD_CASES[0][2], GUARD_CASES[0][3])[1], "What the model reads when ORDER is blocked")
    checkpoint(all(r[0] == "PASS" for r in rows), "guard_rules.py")


TEN_ORDERS = [  # supplier, product, region, quantity, expected violations, expected warnings
    ("AnyCompany Components", "Server Hardware", "US-East", 40, {"sanctions", "uflpa", "certification", "inventory"}, set()),
    ("AnyCompany Components", "Server Hardware", "EU-Central", 0, {"sanctions"}, set()),
    ("AnyCompany Hardware Inc", "Server Hardware", "US-East", 0, {"status", "approval", "certification"}, set()),
    ("AnyCompany Cloud Ltd", "Storage Arrays", "EU-Central", 0, {"approval", "region", "certification"}, set()),
    ("AnyCompany Systems", "Server Hardware", "EU-Central", 0, {"certification"}, set()),
    ("AnyCompany Supply Co", "Server Hardware", "EU-Central", 50, set(), set()),
    ("AnyCompany Electronics", "Server Hardware", "EU-Central", 10, set(), {"sanctions-exposure"}),
    ("Nonexistent Supplier Ltd", "Server Hardware", "EU-Central", 0, {"existence"}, set()),
    ("AnyCompany Devices", "Server Hardware", "US-East", 0, {"uflpa"}, set()),
    ("AnyCompany Devices", "Server Hardware", "EU-Central", 0, set(), set()),
]


def run_ten_orders():
    """Ten orders, each breaking a different combination of rules.
    Returns True if every one matches."""
    from verify import ALL_RULES as ALL, validation_report
    from ui import busy, show_results
    rows = []
    with busy("Running the report for ten orders"):
        for supplier, product, region, qty, exp_v, exp_w in TEN_ORDERS:
            report = validation_report(supplier, product, region, qty, rules=ALL)
            got_v = {v["rule"] for v in report if v["severity"] == "violation"}
            got_w = {v["rule"] for v in report if v["severity"] == "warning"}
            rows.append(("PASS" if (got_v, got_w) == (exp_v, exp_w) else "FAIL", f"{supplier} -> {region}",
                         ", ".join(sorted(got_v)) or "none", ", ".join(sorted(got_w)) or "none",
                         ", ".join(sorted(exp_v)) or "none"))
    show_results(rows, ["result", "order", "violations", "warnings", "expected violations"])
    return all(r[0] == "PASS" for r in rows)


# ---------------------------------------------------------------------------
# Whose answer ran: the reference, or yours from Go deeper
# ---------------------------------------------------------------------------
FRAGMENTS = {  # piece: (file, start marker, end marker, where you write it)
    "blocked_chain": ("queries/violations.cypher", "// Rule: not blocked under OFAC's 50% rule.",
                      "// Rule (warning):", "Go deeper G.3"),
}
FUNCTIONS = {"should_check": "Go deeper G.1", "run_report": "Go deeper G.2"}
PIECE_NAMES = {"blocked_chain": "blocked chain (the sanctions evidence)",
               "should_check": "which-calls-to-check rule", "run_report": "fail-closed report call"}


def _block(text, start, end):
    i = text.index(start)
    return text[i:text.index(end, i)]


def _function_source(path, name):
    import ast
    src = open(path).read()
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return "\n".join(src.splitlines()[node.lineno - 1:node.end_lineno])


def whose(piece):
    """'yours' or 'the reference', for one piece of the guard."""
    norm = lambda t: " ".join(t.split())
    if piece in FRAGMENTS:
        path, start, end, _ = FRAGMENTS[piece]
        mine, ref = (_block(open(p).read(), start, end) for p in (os.path.join(HOME, path), os.path.join(REFERENCE, path)))
    else:
        mine, ref = (_function_source(p, piece) for p in (os.path.join(HOME, "guard_rules.py"),
                                                         os.path.join(REFERENCE, "guard_rules.py")))
    return "the reference" if norm(mine) == norm(ref) else "yours"


def _say_ran(piece):
    from ui import show_note
    where = FRAGMENTS[piece][3] if piece in FRAGMENTS else FUNCTIONS[piece]
    if whose(piece) == "yours":
        show_note(f"Ran your {PIECE_NAMES[piece]} ({where}).")
    else:
        show_note(f"Ran the reference {PIECE_NAMES[piece]}; you write it in {where}.")


def _scoreboard(text):
    from ui import show_code_block
    show_code_block(text, "The order: 40 x Server Hardware from AnyCompany Components to US-East")


# ---------------------------------------------------------------------------
# Your guard: the rules it runs, and the order sent through it
# ---------------------------------------------------------------------------
RULES_FILE = os.path.join(HOME, "queries", "installed_rules.json")
RULE_NAMES = {"basics": "status, approval and region", "sanctions": "sanctions (your 50% rule's result)",
              "uflpa": "forced labour (UFLPA)", "certification": "certification", "inventory": "stock"}


def _write_rules(rules):
    os.makedirs(os.path.dirname(RULES_FILE), exist_ok=True)
    with open(RULES_FILE, "w") as f:
        json.dump(list(rules), f)


def install_rules(rules):
    """Cells 1.3, 2.6, 3.3: the rules your guard runs from now on (queries/installed_rules.json;
    validation_report reads it). An unknown supplier is always blocked."""
    from ui import show_note
    _write_rules(rules)
    show_note("Your guard now checks: " + (", ".join(RULE_NAMES[r] for r in rules) if rules
                                           else "nothing yet (only that the supplier exists)"))


SCOREBOARD_FILE = os.path.join(HOME, ".scoreboard.json")
START_LINE = "Start    the unguarded agent drafted the PO"


def _load_sent():
    """The order's outcome after each step, kept in a file so it carries across the notebooks."""
    try:
        with open(SCOREBOARD_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def show_scoreboard():
    """Cells 2.0, 3.0, 4.0: where the order stands, from the notebooks before this one."""
    from ui import show_note
    sent = _load_sent()
    if sent:
        _scoreboard(START_LINE + "\n" + "\n".join(sent))
    else:
        show_note("No order sent through your guard yet: the earlier notebooks' steps fill this in.")


def ask(agent, request, title="Your guarded agent"):
    """Cells 1.3, 2.6, 3.4: send one request to an in-notebook agent; show what it did and said."""
    import guardrail
    from ui import busy, show_reply, show_request, show_trace
    show_request(request)
    with busy("Sending the request to the agent"):
        reply = guardrail.run(agent, request)
    show_trace(reply["trace"], "What the agent did")
    show_reply(reply["result"], title)
    return reply


def record(step, reply):
    """Cells 1.3, 2.6, 3.4: what happened to ORDER's PO, from the agent's trace, added to the
    scoreboard. The reasons are the rules your block message lists."""
    import re
    po = [t for t in reply["trace"] if t["tool"] == "draft_purchase_order"
          and t["input"].get("supplier_name") == ORDER["supplier"]]
    if not po:
        outcome = "didn't try to draft the PO"
    elif any(t["outcome"] == "ok" for t in po):
        outcome = "drafted the PO"
    else:
        reasons = re.findall(r"^- ([\w-]+):", po[-1]["output"], re.M)
        outcome = (f"BLOCKED: {len(reasons)} of 4 problems caught ({', '.join(reasons)})" if reasons
                   else "BLOCKED: the check couldn't run")
    sent = sorted([line for line in _load_sent() if not line.startswith(step)] + [f"{step:<8} {outcome}"])
    os.makedirs(HOME, exist_ok=True)
    with open(SCOREBOARD_FILE, "w") as f:
        json.dump(sent, f)
    _scoreboard(START_LINE + "\n" + "\n".join(sent))
    if step == "Step 1":
        _say_ran("should_check")


# ---------------------------------------------------------------------------
# Re-checking the order, page by page
# ---------------------------------------------------------------------------
def _order_dict(order):
    if isinstance(order, dict):
        return order
    keys = ["supplier", "product", "region", "quantity"]
    return dict(zip(keys, order))


def _split(name):
    """'X (detail)' as the evidence lists write it: ('X', 'detail')."""
    if name.endswith(")") and " (" in name:
        head, _, detail = name[:-1].partition(" (")
        return head, detail
    return name, None


def _evidence_paths(report, order):
    """The report's evidence as paths from the supplier, one per finding, for show_paths."""
    from workshop import oc
    paths = []
    for v in report:
        ev = v.get("evidence") or []
        if v["rule"] == "sanctions" and ev:
            steps = []
            for name in ev:
                label, detail = _split(name)
                style = ("list" if not detail and name == ev[-1] else
                         "listed" if detail == "listed" else "blocked")
                edge = "SANCTIONED_BY" if style == "list" else "OWNED_BY"
                steps.append((edge, {"label": label, "sub": detail, "style": style}))
            paths.append({"tag": "sanctions", "steps": steps})
        elif v["rule"] == "sanctions-exposure" and ev:
            steps = [("OWNED_BY", {"label": n, "style": "listed" if n == ev[-1] else "clear"}) for n in ev[1:]]
            paths.append({"tag": "exposure", "tag_style": "warn", "steps": steps})
        elif v["rule"] == "uflpa" and ev:
            steps = [("SOURCES_FROM", {"label": n, "style": "clear"}) for n in ev[1:-1]]
            steps[-1][1]["style"] = "blocked"
            steps[-1][1]["sub"] = f"{v.get('hops') or len(ev) - 2} tiers down"
            steps.append(("ON_LIST", {"label": ev[-1], "style": "list"}))
            paths.append({"tag": "uflpa", "steps": steps})
        elif v["rule"] == "inventory":
            for w in ev:
                name, _, units = w.rpartition(": ")
                paths.append({"tag": "inventory", "tag_style": "warn",
                              "steps": [("HAS_WAREHOUSE", {"label": name, "sub": f"{units} in DynamoDB",
                                                           "style": "warn"}),
                                        ("STOCKS", {"label": order["product"], "sub": f"order: {order['quantity']}",
                                                    "style": "clear"})]})
        elif v["rule"] == "certification":
            held = {r["code"]: r["status"] for r in oc(
                "MATCH (s:Supplier {name: $s})-[h:HOLDS_CERT]->(c:Certification) WHERE c.code IN $codes "
                "RETURN c.code AS code, h.cert_status AS status", s=order["supplier"], codes=ev)}
            for code in ev:
                status = held.get(code)
                paths.append({"tag": "certification", "steps": [
                    ("HOLDS_CERT" if status else "no HOLDS_CERT",
                     {"label": code, "sub": f"held: {status}" if status else "not held", "style": "blocked"}),
                    ("<- REQUIRES_CERT", {"label": order["region"], "sub": "requires it", "style": "clear"})]})
    return paths


_EVIDENCE_LEGEND = [("supplier", "the supplier on the order"), ("blocked", "what breaks the rule"),
                    ("listed", "on the sanctions list"), ("list", "a list"), ("warn", "stock"),
                    ("clear", "on the path")]


def show_candidate_paths(name, rows):
    """Go deeper G.3a: each candidate path from the supplier to the sanctions list, one row each,
    blocked entities in red."""
    from ui import show_paths
    paths = []
    for r in rows:
        steps = []
        for k, (n, blocked, pct) in enumerate(zip(r["names"][1:], r["blocked"][1:], r["stakes"])):
            last = k == len(r["stakes"]) - 1
            steps.append(("SANCTIONED_BY" if last else f"{pct}%",
                          {"label": n, "style": "list" if last else "blocked" if blocked else "clear"}))
        every = all(r["blocked"][:-1])
        paths.append({"tag": "all blocked" if every else "a gap",
                      "tag_style": "blocked" if every else "clear", "steps": steps})
    blocked = bool(rows) and rows[0]["blocked"][0]
    show_paths({"label": name, "sub": "blocked" if blocked else "not blocked",
                "style": "blocked" if blocked else "clear"}, paths,
               title=f"{name}: {len(paths)} path(s) to the sanctions list",
               legend=[("blocked", "blocked by the 50% rule"), ("clear", "not blocked"), ("list", "the list")],
               native="Neptune's own view of these paths is the Graph tab in Cell 2.5, in notebook 1.2.")

def show_rule(query, orders):
    """Cell 3.1: run one rule's query, shown in the cell, for each order. A row means the rule
    is broken, and its evidence is drawn as a path; no row means it holds."""
    from workshop import oc
    from ui import show_note, show_paths
    from verify import rule_settings
    for order in orders:
        rows = oc(query, supplier_name=order["supplier"], region_name=order["region"],
                  product_name=order["product"], **rule_settings())
        title = f"{order['supplier']} to {order['region']}"
        if rows:
            for r in rows:
                show_note(f"{title}: {r['rule']} {r['severity']}. {r['message']}")
            show_paths({"label": order["supplier"], "style": "supplier"}, _evidence_paths(rows, order),
                       title="The row's evidence, as a path in the graph", legend=_EVIDENCE_LEGEND,
                       native="Neptune's own view of this path is the Graph tab in Cell 2.1.")
        else:
            show_note(f"{title}: no row, so the rule holds.")


def show_report(report, title=None, order=None, native=None):
    """Cells 3.3, 3.5 and G.6: the report's rows, then each finding's evidence drawn as a path from
    the supplier."""
    from ui import show_paths, show_results
    show_results([(v["severity"], v["rule"], "" if v["hops"] is None else v["hops"], v["message"]) for v in report]
                 or [("", "conforms", "", "no rule is broken")],
                 ["severity", "rule", "hops", "message"], title=title or f"{len(report)} findings, in one call")
    if order is not None:
        order = _order_dict(order)
        paths = _evidence_paths(report, order)
        if paths:
            show_paths({"label": order["supplier"], "sub": f"to {order['region']}", "style": "supplier"}, paths,
                       title="The evidence, as paths in the graph", legend=_EVIDENCE_LEGEND, native=native)
    if any(v["rule"] == "sanctions" for v in report):
        _say_ran("blocked_chain")


def full_report(order):
    """Go deeper G.6: the full report for an order."""
    from verify import validation_report
    show_report(validation_report(order["supplier"], order["product"], order["region"], order["quantity"]),
                order=order, native="To see these paths in Neptune's Graph tab, run Cell 3.3a in notebook 1.3 "
                                    "with this order's names in params.")


def show_stock(locations, units, order):
    """Cell 3.2: the two halves of the stock check. The graph gives the path to each warehouse that
    carries the product, and its key; DynamoDB gives the count for that key."""
    from ui import show_note, show_paths
    show_paths({"label": order["supplier"], "style": "supplier"},
               [{"tag": "stock", "tag_style": "warn", "steps": [
                   ("HAS_WAREHOUSE", {"label": l["warehouse"], "style": "warn",
                                      "sub": f"key {l['warehouse_id']}: {units[(l['warehouse_id'], l['product_id'])]} units"}),
                   ("STOCKS", {"label": order["product"], "style": "clear"})]} for l in locations],
               title=f"{order['supplier']}: the graph's path to each warehouse, and DynamoDB's count for its key",
               legend=[("supplier", "the supplier"), ("warn", "a warehouse, with its DynamoDB count"),
                       ("clear", "the product")],
               native="The counts come from DynamoDB, so Neptune's graph view can't show them.")
    available = sum(units.values())
    show_note(f"{available} units available against {order['quantity']} ordered"
              + ("" if available >= order["quantity"] else ": not enough for this order"))


# ---------------------------------------------------------------------------
# Page 3 and page 4 checks (no model involved)
# ---------------------------------------------------------------------------
def _direct_agent():
    import importlib
    import guard_rules
    import neptune_guard
    from guardrail import build_agent
    importlib.reload(guard_rules)
    importlib.reload(neptune_guard)
    agent = build_agent(guard=neptune_guard.NeptuneGuardPlugin(rules=guard_rules))

    def direct(tool, kw):
        res = getattr(agent.tool, tool)(record_direct_tool_call=False, **kw)
        text = res["content"][0]["text"]
        if res["status"] == "error" and text.startswith("BLOCKED"):
            return "BLOCKED", text
        return ("ok" if res["status"] == "success" else "error"), text
    return guard_rules, direct


def save_hook(fn):
    """Cell 1.1: save the before_tool you wrote into your-guard/neptune_guard.py, in place of
    the method there (the file starts as the reference), and load it."""
    import ast
    import inspect
    import textwrap
    path = os.path.join(HOME, "neptune_guard.py")
    if not os.path.exists(path):
        shutil.copyfile(os.path.join(REFERENCE, "neptune_guard.py"), path)
    src = open(path).read()
    lines = src.splitlines(keepends=True)
    cls = next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == "NeptuneGuardPlugin")
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "before_tool")
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    new = textwrap.indent(textwrap.dedent(inspect.getsource(fn)).rstrip() + "\n", "    ")
    with open(path, "w") as f:
        f.write("".join(lines[:start - 1]) + new + "".join(lines[node.end_lineno:]))
    _rebind_hook()
    _report_save("before_tool", inspect.getsource(fn), path)


def _rebind_hook():
    """Reload neptune_guard.py, so NeptuneGuardPlugin in the notebook is the hook on disk."""
    import importlib
    import neptune_guard
    importlib.reload(neptune_guard)
    if "namespace" in _state:
        _state["namespace"]["NeptuneGuardPlugin"] = neptune_guard.NeptuneGuardPlugin


class FakeRules:
    """Cell 1.2: stand-in guard rules, so the hook can be tested with no graph and no model.
    Checks every PO; run_report returns the report you give it, or raises the error you give
    it; block_message is the given one from guard_rules.py."""

    def __init__(self, report=(), error=None):
        self.report, self.error, self.report_ran = list(report), error, False

    def should_check(self, tool, args):
        return tool == "draft_purchase_order"

    def run_report(self, args):
        self.report_ran = True
        if self.error:
            raise self.error
        return self.report

    def block_message(self, supplier, product, region, report):
        import guard_rules
        return guard_rules.block_message(supplier, product, region, report)


VIOLATION = [{"rule": "sanctions", "severity": "violation", "message": "Blocked under the OFAC 50 Percent Rule",
              "evidence": [], "hops": 3}]
PO_ARGS = dict(supplier_name="AnyCompany Components", product_name="Server Hardware",
               region_name="US-East", quantity=40)


def check_hook():
    """Cell 1.2: your hook in a real agent, called directly with FakeRules: a violation, an
    empty report, a report that can't run, and a call that needs no check. Loads the reference
    on a FAIL."""
    import guardrail
    import neptune_guard
    from ui import show_code_block, show_results
    from workshop import checkpoint
    _rebind_hook()
    cases = [("a report with a violation", FakeRules(VIOLATION), "draft_purchase_order", PO_ARGS, "BLOCKED"),
             ("an empty report", FakeRules([]), "draft_purchase_order", PO_ARGS, "runs"),
             ("the report can't run", FakeRules(error=ConnectionError("Neptune unreachable")),
              "draft_purchase_order", PO_ARGS, "BLOCKED"),
             ("a call that needs no check", FakeRules(VIOLATION), "send_offer_reply",
              dict(PO_ARGS, decision="decline", message="We'll pass."), "runs, no report")]
    rows, blocked_text = [], None
    for label, rules, tool, kw, want in cases:
        try:
            agent = guardrail.build_agent(guard=neptune_guard.NeptuneGuardPlugin(rules=rules))
            res = getattr(agent.tool, tool)(record_direct_tool_call=False, **kw)
            text = res["content"][0]["text"]
            blocked = res["status"] == "error" and text.startswith("BLOCKED")
            got = "BLOCKED" if blocked else ("runs, no report" if not rules.report_ran else "runs")
            if label == "a report with a violation" and blocked:
                blocked_text = text
        except Exception as e:
            got = f"error: {type(e).__name__}: {e}"[:60]
        ok = got == want
        rows.append(("PASS" if ok else "FAIL", label, want, got))
    show_results(rows, ["result", "case", "expected", "got"], title="Your hook, called directly, no model")
    if blocked_text:
        show_code_block(blocked_text, "What the model reads instead of the PO")
    if not checkpoint(all(r[0] == "PASS" for r in rows), "neptune_guard.py"):
        _rebind_hook()


# ---------------------------------------------------------------------------
# Go deeper: your fragment replaces the reference in queries/violations.cypher
# ---------------------------------------------------------------------------
def _splice(piece, body):
    path, start, end, where = FRAGMENTS[piece]
    target = os.path.join(HOME, path)
    text = open(target).read()
    block = _block(text, start, end)
    indented = "\n".join("  " + l if l.strip() else l for l in body.strip().splitlines())
    new = f"{start} (yours: {where})\nCALL {{\n  WITH s\n{indented}\n}}\n\n"
    with open(target, "w") as f:
        f.write(text.replace(block, new, 1))


def _reference_body(piece):
    path, start, end, _ = FRAGMENTS[piece]
    block = _block(open(os.path.join(REFERENCE, path)).read(), start, end)
    body = block.split("WITH s\n", 1)[1].rsplit("}", 1)[0]
    return "\n".join(l[2:] if l.startswith("  ") else l for l in body.strip("\n").splitlines())


def _check_fragment(piece, body, wrapper, cases, column):
    """Run your subquery alone on each case and compare with the reference; on a pass, put
    it into queries/violations.cypher and run the ten orders."""
    from verify import run_open_cypher
    from ui import show_results, show_status
    from workshop import checkpoint
    rows, ok = [], True
    try:
        for label, params in cases:
            mine = (run_open_cypher(wrapper % body, **params) or [{}])[0].get(column) or []
            want = (run_open_cypher(wrapper % _reference_body(piece), **params) or [{}])[0].get(column) or []
            ok &= mine == want
            rows.append(("PASS" if mine == want else "FAIL", label, " -> ".join(mine) or "none",
                         " -> ".join(want) or "none"))
        show_results(rows, ["result", "case", "yours", "expected"], title="Your subquery, on its own")
    except Exception as e:
        ok = False
        show_status(False, f"Your subquery didn't run: {e}")
    if ok:
        _splice(piece, body)
        show_status(True, "Put into queries/violations.cypher, in place of the reference")
        ok = run_ten_orders()
    checkpoint(ok, FRAGMENTS[piece][0])


def check_blocked_chain(body):
    """Check G.3: your blocked-chain subquery against the reference, for the named suppliers
    and three blocked suppliers from the registry."""
    from workshop import oc
    names = ["AnyCompany Components", "AnyCompany Electronics", "AnyCompany Supply Co"] + [
        r["n"] for r in oc("MATCH (s:Supplier) WHERE s.blocked = true AND NOT s.name STARTS WITH 'AnyCompany' "
                           "RETURN s.name AS n ORDER BY n LIMIT 3")]
    wrapper = ("OPTIONAL MATCH (s:Supplier {name: $supplier_name})\nCALL {\n  WITH s\n%s\n}\n"
               "RETURN CASE WHEN chain IS NULL THEN [] ELSE [n IN nodes(chain) | n.name] END AS chain")
    _check_fragment("blocked_chain", body, wrapper, [(n, {"supplier_name": n}) for n in names], "chain")


def check_uflpa_shape(shape_path="queries/uflpa_shape.ttl"):
    """Check G.4: your SHACL shape on four orders' supply chains, beside the report's UFLPA row."""
    from verify import validation_report
    from shacl_check import ensure_pyshacl, shacl_validate, supply_chain_rdf
    from ui import show_results, show_status
    ensure_pyshacl()
    orders = [("AnyCompany Components", "US-East"), ("AnyCompany Devices", "US-East"),
              ("AnyCompany Devices", "EU-Central"), ("AnyCompany Supply Co", "US-East")]
    rows, ok = [], True
    for supplier, region in orders:
        _, results = shacl_validate(supply_chain_rdf(supplier, region), shape_path)
        shacl = [r for r in results if r["severity"] == "Violation"]
        report = [v for v in validation_report(supplier, "Server Hardware", region) if v["rule"] == "uflpa"]
        same = bool(shacl) == bool(report)
        ok &= same
        rows.append(("PASS" if same else "FAIL", f"{supplier} -> {region}",
                     shacl[0]["message"] if shacl else "conforms", "uflpa violation" if report else "no uflpa row"))
    show_results(rows, ["result", "order", "your SHACL shape", "the report"],
                 title="The UFLPA rule as a SHACL shape, beside the openCypher report")
    show_status(ok, "Same verdicts as the report" if ok else "Your shape and the report disagree")


# ---------------------------------------------------------------------------
# Deploy: the guarded agent and the MCP server, from the same files
# ---------------------------------------------------------------------------
def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


WHERE_YOU_WRITE = {"neptune_guard.py": "Cell 1.1 (the hook)", "queries/ownership_50pct.cypher": "Cell 2.3 (the 50% rule)",
                   "guard_rules.py": "Go deeper G.1 and G.2 (the hook's decisions)",
                   "queries/violations.cypher": "Go deeper G.3 (the sanctions evidence)",
                   "queries/recommend.cypher": "given (the fulfilment ranking)"}


def show_whose(title):
    """Go deeper G.0 and G.9: every file the deployed guard runs, and whether it's yours yet."""
    from ui import show_results
    rows = save_reference_answers(show=False)
    show_results([(path, who, WHERE_YOU_WRITE.get(path, ""), sha) for path, who, sha in rows],
                 ["file", "whose", "you write it in", "fingerprint"], title=title)


def save_reference_answers(show=True):
    """Any answer file that is missing gets the reference. Shows each file, whose it is,
    and its fingerprint (the first 12 characters of its SHA-256)."""
    from ui import show_results
    rows = []
    for path in ANSWER_FILES:
        target, ref = os.path.join(HOME, path), os.path.join(REFERENCE, path)
        if not os.path.exists(target):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(ref, target)
        rows.append((path, "the reference" if _sha(target) == _sha(ref) else "yours",
                     _sha(target)[:12]))
    if show:
        show_results(rows, ["file", "whose", "fingerprint"], title="The files the deploy ships")
    return rows


def _common():
    from deploy_agent import select_supported_subnets
    subnets = select_supported_subnets(os.environ.get("AGENTCORE_CANDIDATE_SUBNET_IDS", "").split(","),
                                       os.environ["AWS_REGION"])
    return dict(code_dir=ROOT, bucket=os.environ["DATA_BUCKET"],
                role_arn=os.environ["AGENTCORE_ROLE_ARN"],
                security_group_id=os.environ["AGENTCORE_SECURITY_GROUP_ID"], subnet_ids=subnets,
                environment_variables={"NEPTUNE_ENDPOINT": os.environ["NEPTUNE_ENDPOINT"],
                                       "NEPTUNE_PORT": os.environ.get("NEPTUNE_PORT", "8182"),
                                       "AWS_REGION": os.environ["AWS_REGION"],
                                       "STOCK_TABLE": os.environ["STOCK_TABLE"]})


# Paths under ~/SageMaker/workshop; deploy_agent strips the folder name, so the package has
# agent.py, neptune_guard.py and guard_rules.py at its root, with queries/ beside them.
YOUR_FILES = ["your-guard/neptune_guard.py", "your-guard/guard_rules.py",
              "your-guard/queries/violations.cypher", "your-guard/queries/recommend.cypher"]
GIVEN_FILES = ["helpers/guardrail.py", "helpers/verify.py", "your-guard/queries/stock_locations.cypher",
               "your-guard/queries/rule_settings.json"]


def deploy_mcp(wait=True):
    """Cell K.2: deploy ProcurementMCP, your files served as an MCP server."""
    from deploy_agent import deploy_agent
    return deploy_agent(runtime_name="ProcurementMCP", entry_file="mcp_server.py",
                        code_files=["helpers/mcp_server.py"] + GIVEN_FILES + YOUR_FILES,
                        protocol="MCP", wait=wait, **_common())


def deploy_guarded():
    """Cell 4.4: deploy the guarded agent from your files. (The MCP server deploys in
    3 - Run it from Kiro (optional).ipynb, Cell K.2.) Returns its runtime ARN."""
    from deploy_agent import deploy_agent
    from ui import busy, show_status
    save_reference_answers()
    with busy("Deploying the guarded agent to AgentCore Runtime (a few minutes)"):
        arn = deploy_agent(runtime_name="ProcurementGuardedAgent", entry_file="agent.py",
                           code_files=["helpers/agent.py"] + GIVEN_FILES + YOUR_FILES, **_common())
    show_status(True, "Guarded agent ProcurementGuardedAgent is live")
    return arn


def mcp_server_status():
    """Cell K.3: the server's status, its endpoint, and the tools Kiro's model will see."""
    import ast
    import boto3
    from deploy_agent import mcp_endpoint_url
    from ui import show_code_block, show_results, show_status
    control = boto3.client("bedrock-agentcore-control", region_name=os.environ["AWS_REGION"])
    rt = next((r for p in control.get_paginator("list_agent_runtimes").paginate()
               for r in p["agentRuntimes"] if r["agentRuntimeName"] == "ProcurementMCP"), None)
    if rt is None:
        show_status(False, "No MCP server yet: run Cell K.2.")
        return
    show_status(rt["status"] == "READY", f"ProcurementMCP is {rt['status']}")
    show_code_block(mcp_endpoint_url(rt["agentRuntimeArn"]), "Its endpoint (connect.sh finds it for you)")
    # Read the tools from the deployed source without importing it: the server's MCP
    # library ships with the deployment, not in this kernel.
    src = ast.parse(open(os.path.join(HERE, "mcp_server.py")).read())
    tools = [f for f in src.body if isinstance(f, ast.FunctionDef)
             and any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool" for d in f.decorator_list)]
    show_results([(f.name, ", ".join(a.arg for a in f.args.args),
                   " ".join(ast.get_docstring(f).split()).split(". ")[0] + ".") for f in tools],
                 ["MCP tool", "arguments", "what Kiro's model is told"],
                 title=f"{len(tools)} tools on ProcurementMCP")


def kiro_ide_link():
    """Cell K.4: the Kiro IDE's URL, from the Kiro stack's outputs."""
    import boto3
    from IPython.display import HTML, display
    from ui import show_status
    cfn = boto3.client("cloudformation", region_name=os.environ["AWS_REGION"])
    url = None
    try:
        for page in cfn.get_paginator("describe_stacks").paginate():
            for st in page["Stacks"]:
                for o in st.get("Outputs", []):
                    v = o["OutputValue"]
                    if o["OutputKey"].upper() == "URL" and v.startswith("https://") and "tkn=" in v:
                        url = v
    except Exception as e:
        print(f"(This notebook can't look up the Kiro stack: {type(e).__name__}: {e})")
    if url:
        display(HTML(f'<p style="font-size:1.1em"><a href="{url}" target="_blank" rel="noopener">'
                     f'<b>Open your Kiro IDE</b></a> (opens in a new tab)</p>'))
    else:
        show_status(False, "No Kiro link found from here: use the URL output under Event Outputs "
                           "on the workshop page.")
