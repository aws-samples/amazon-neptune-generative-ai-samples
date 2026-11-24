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
"""session.py — the helpers 01 DAT408.ipynb's cells call (spec v3).

    from agent.session import connect
    connect(globals(), graph=True)

connect() runs workshop.setup() and bind(), then adds the names below to the notebook. Each
After a kernel restart, Cell 0.1 again: connect() finds your latest Carlos evaluation and sets
CARLOS and params. Go deeper's G.0 calls resume(globals()), which is instant unless the kernel restarted.
Every number a cell prints comes from the stack it runs on, or from a file under agent/recorded/
that says where it was recorded.
"""
import base64
import hashlib
import io
import json
import os
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from agent import workshop as ws

CARLOS_APP, SAANVI_APP, JANE_APP = "LA-2026-00148", "LA-2026-00149", "LA-2026-00147"
P_RATIOS = "HUD 4000.1 II.A.5.d"
RRU_PRICE = 0.125 / 1_000_000          # on-demand read request unit, us-east-1 (AWS Price List)
HERE = os.path.dirname(os.path.abspath(__file__))
_state = {"ctx": None}


# ---------------------------------------------------------------------------
# Connect, resume, catch up
# ---------------------------------------------------------------------------
def connect(namespace, graph=False):
    """setup() and bind(), the session's helpers, and (graph=True) the %%oc graph view."""
    ctx = ws.setup()
    ws.bind(ctx, namespace)
    outputs = {o["OutputKey"]: o["OutputValue"] for o in ctx.cfn_outputs} if hasattr(ctx, "cfn_outputs") else {}
    ctx.HISTORY_BUCKET = outputs.get("HistoryBucketName") or _output(ctx, "HistoryBucketName")
    ctx.EVIDENCE_BUCKET = _output(ctx, "S3BucketName")
    ctx.s3 = __import__("boto3").client("s3", region_name=ctx.region)
    # agent.transform reads these at import, as the Lambda does (Go deeper runs it in the notebook).
    os.environ.setdefault("GRAPH_ID", ctx.GRAPH_ID)
    os.environ.setdefault("AWS_DEFAULT_REGION", ctx.region)
    _state["ctx"], _state["ns"] = ctx, namespace
    if graph:
        ws.enable_graph_notebook(ctx)
    namespace.update(helpers(ctx))
    if "show_agentcore_observability" in namespace:
        _source(ws.show_agentcore_observability, namespace["show_agentcore_observability"])
    if graph and not namespace.get("CARLOS"):
        # After a kernel restart, Cell 0.1 puts back the Carlos evaluation the later cells read.
        carlos = _latest_carlos(ctx)
        if carlos:
            _set_carlos(namespace, carlos)
            print(f"Found your earlier Carlos evaluation: CARLOS = {carlos} (LA-2026-00148, deny).")
    return ctx


def _set_carlos(namespace, carlos):
    """Set CARLOS, and the params the %%oc cells pass with -qp params (merged, not replaced:
    Cell 3.3 adds its lineage sample)."""
    namespace["CARLOS"] = carlos
    namespace.setdefault("params", {}).update(graph_params(carlos))


def _output(ctx, key):
    import boto3
    stack = boto3.client("cloudformation", region_name=ctx.region).describe_stacks(StackName=ctx.stack_name)
    return {o["OutputKey"]: o["OutputValue"] for o in stack["Stacks"][0]["Outputs"]}.get(key)


def connect_deeper(namespace):
    """Go deeper's G.0: connect, plus the checks and the transform's helpers its exercises use."""
    ctx = connect(namespace, graph=True)
    from agent import deeper, transform
    namespace.update({
        "check_query": deeper.check_query, "check_get_evidence": deeper.check_get_evidence,
        "check_policy_months": deeper.check_policy_months, "test_transform": deeper.test_transform,
        "prove_replay_safe": deeper.prove_replay_safe,
        "execute_query": transform.execute_query, "retrieved_policies": transform.retrieved_policies,
        "strings": transform.strings, "normalize_policy_id": transform.normalize_policy_id,
        "Key": __import__("boto3.dynamodb.conditions", fromlist=["Key"]).Key,
        "ser": __import__("boto3.dynamodb.types", fromlist=["TypeSerializer"]).TypeSerializer(),
        "aggregate_updates": __import__("agent.policy_ids", fromlist=["aggregate_updates"]).aggregate_updates,
        "show_decision": lambda eval_id: show_decision(ctx, eval_id) and None,
    })
    return ctx


def show_decision(ctx, eval_id):
    """G.13: the decision's steps from DynamoDB, in sort-key order (G.13a draws its links in the graph)."""
    import pandas as pd
    from IPython.display import display
    items = [i for i in sorted(_evaluation_items(ctx, eval_id), key=lambda i: i["SK"]) if i["SK"].startswith("STEP#")]
    print(f"Steps of evaluation {eval_id}, from one Query on EVAL#, in sort-key order (no sorting in code):")
    display(ws.styled_table(pd.DataFrame([{"step": int(i["step_num"]), "tool": i["action"],
                                           "typed result": ws.summarize_evidence(i)} for i in items])))
    print("Its links in the graph are in Cell G.13a, next.")
    return True


def save_reference_answers(ctx):
    """K.2: save the reference answer for every file you didn't write; yours stay."""
    from pathlib import Path
    from agent import reference
    from agent.evidence import sha256
    out = Path(ws.SOLUTION_DIR)
    out.mkdir(exist_ok=True)
    for name, text in reference.SOURCES.items():
        path = out / name
        if path.exists() and path.read_text().strip():
            print(f"   solution/{name:<28} yours, sha256 {sha256(path.read_text())[:12]}")
        else:
            path.write_text(text)
            print(f"   solution/{name:<28} the reference, sha256 {sha256(text)[:12]}")
    return True


def check_extra_tool(ctx, tool):
    """K.4: run your tool the way the MCP server will (defined from its source, with run_answer
    as its only helper), compare it with the walk's expected answer, and save it."""
    import inspect
    from agent.evidence import load_function
    doc = inspect.getdoc(tool) or ""
    if len(doc) < 60 or doc.upper().startswith("TODO"):
        print("❌ Write the docstring: it is the only description Kiro's model gets of what this tool "
              "answers and what each argument means.")
        return False
    as_deployed = load_function(inspect.getsource(tool), tool.__name__,
                                {"run_answer": lambda name, params=None: ws.run_answer(ctx, name, params)})
    result = as_deployed("version:doc-extract:2.3.1", "2026-05-24")
    want = _expected(ctx)["walks"]["both"]["decisions"]
    if not isinstance(result, dict) or want not in [v for v in result.values() if isinstance(v, int)]:
        print(f"❌ The result should be a dict that includes the number of decisions ({want:,}); it returned {result!r}.")
        return False
    print(f"✅ As the MCP server will run it: {tool.__name__}('version:doc-extract:2.3.1', '2026-05-24') -> "
          f"{want:,} decisions.")
    print("   What Kiro's model will see:")
    print(f"   {tool.__name__}{inspect.signature(tool)}")
    print("   " + doc.replace("\n", "\n   "))
    ws.save_answer("extra_tool", tool)
    return True


def _source(fn, call):
    """Point a notebook helper at the function it calls, so `name??` in a cell shows that
    function's source, not this file's lambda."""
    call.__wrapped__, call.__doc__, call.__name__ = fn, fn.__doc__, fn.__name__
    return call


def helpers(ctx):
    bound = {
        "save_reference_answers": lambda: save_reference_answers(ctx) and None,
        "check_extra_tool": lambda fn: check_extra_tool(ctx, fn) and None,
        "deploy_reference_transform": lambda: deploy_reference_transform(ctx) and None,
        "run_evaluations": lambda ids: run_evaluations(ctx, ids),
        "show_recorded_runs": lambda app_id: show_recorded_runs(ctx, app_id) and None,
        "choose_carlos": choose_carlos,
        "summarize_decision": lambda eval_id, runs=2: summarize_decision(ctx, eval_id, runs),
        "show_evidence": lambda eval_id: show_evidence(ctx, eval_id) and None,
        "check_sort": lambda answers: check_sort(answers) and None,
        "run_questions": lambda eval_id: run_questions(ctx, eval_id) and None,
        "show_peers": lambda app_id, query=None: show_peers(ctx, app_id, query) and None,
        "band_keys": lambda app_id: _band_keys(ctx, app_id) or (None, None, None),
        "reference_answer": reference_answer,
        "check_decision_transaction": lambda fn, label=None: ws.check_decision_transaction(ctx, fn) and None,
        "show_lineage": lambda walk, **kw: show_lineage(ctx, walk, **kw) and None,
        "draw_lineage": lambda **kw: draw_lineage(ctx, **kw) and None,
        "show_from_source": lambda query: show_from_source(query) and None,
        "LINEAGE_SAMPLE": "408:v3:view",
        "test_copy": lambda app_id, new_id: test_copy(ctx, app_id, new_id),
        "run_with_check": lambda app, plant=True: run_with_check(ctx, app, plant),
        "show_ungrounded": lambda query, params=None: show_ungrounded(ctx, query, params) and None,
        "planted_case": lambda: planted_case(ctx),
        "embed": lambda text: embed(ctx, text),
        "inline": inline,
        "show_closest": lambda rows, reason: show_closest(rows, reason) and None,
        "catch_up": lambda what: catch_up(ctx, what),
        "pd": __import__("pandas"),
        "display": __import__("IPython.display", fromlist=["display"]).display,
    }
    # `name??` in a cell shows the function each lambda calls.
    for name, call in bound.items():
        fn = globals().get(name) or globals().get("_" + name) or getattr(ws, name, None)
        if getattr(call, "__name__", "") == "<lambda>" and callable(fn):
            _source(fn, call)
    return bound


def resume(namespace):
    """Go deeper's G.0: reconnect after a kernel restart, deploy the transform if
    it isn't, and find the Carlos evaluation the pages read (running him once if none)."""
    if namespace.get("CARLOS") and _state["ctx"] is not None:
        print(f"CARLOS = {namespace['CARLOS']} (already set).")
        namespace.setdefault("params", {}).update(graph_params(namespace["CARLOS"]))
        return namespace["CARLOS"]
    ctx = _state["ctx"] or connect(namespace, graph=True)
    if not _transform_deployed(ctx):
        deploy_reference_transform(ctx)
    carlos = _latest_carlos(ctx)
    if not carlos:
        print("No evaluation of LA-2026-00148 yet: running Carlos once (about 45 seconds).")
        runs = run_evaluations(ctx, [CARLOS_APP])
        carlos = choose_carlos(runs)
    print(f"CARLOS = {carlos} (LA-2026-00148, deny): the next pages read this evaluation.")
    _set_carlos(namespace, carlos)
    return carlos


def graph_params(carlos):
    """The parameters the %%oc cells pass with -qp params."""
    return {"decision": f"decision:{carlos}_decision", "ratio_rule": "policy:HUD 4000.1 II.A.5.d",
            "planted": "LA-AUDIT-TEST", "source": "version:doc-extract:2.3.1",
            # Go deeper's graph views: Update 18's issue date, Saanvi, and Carlos's three bands
            "current": "2026-08-12", "saanvi": "LA-2026-00149",
            "credit": "band:credit:580-619", "dti": "band:dti:50-100", "ltv": "band:ltv:96.5-200"}


def _latest_carlos(ctx):
    from boto3.dynamodb.conditions import Key
    t = ctx.dynamodb.Table(ctx.TRACES_TABLE)
    keys = t.query(IndexName="application-index", KeyConditionExpression=Key("application_id").eq(CARLOS_APP),
                   ScanIndexForward=False)["Items"]
    for pk in dict.fromkeys(k["PK"] for k in keys):
        meta = t.get_item(Key={"PK": pk, "SK": "META"}).get("Item", {})
        if meta.get("status") == "COMPLETE" and meta.get("outcome") == "deny":
            return pk.replace("EVAL#", "")
    return None


def _write_recorded(ctx, items, eval_id):
    """Write a recorded evaluation's items under a fixed id, as INSERTs, so the stream projects
    it like a live run. Deletes an earlier copy first; returns the id."""
    from decimal import Decimal
    old = items[0]["PK"].replace("EVAL#", "")
    t = ctx.dynamodb.Table(ctx.TRACES_TABLE)
    for it in items:
        t.delete_item(Key={"PK": f"EVAL#{eval_id}", "SK": it["SK"]})
    for it in items:
        it = json.loads(json.dumps(it).replace(old, eval_id), parse_float=Decimal)
        if it["SK"] == "META" and "started_at" in it:
            it.setdefault("step_timestamp", it["started_at"])    # so prompt-index holds it
        t.put_item(Item=it)
    return eval_id


def catch_up(ctx, what):
    """Load a recorded run when a live one fails or runs long (the guide's fallback boxes):
    "carlos", "summaries", "check" or "plant"."""
    path = os.path.join(HERE, "recorded", f"catch_up_{what}.json")
    if what == "plant":
        ws.plant_unsupported_citation(ctx)
        return None
    if not os.path.exists(path):
        print(f"No recorded '{what}' run in this build: ask a facilitator.")
        return None
    data = json.load(open(path))
    if what == "carlos":
        eid = _write_recorded(ctx, data["items"], "recorded-carlos-0001")
        _set_carlos(_state["ns"], eid)
        print(f"Loaded a recorded Carlos evaluation ({data['recorded']}).\nCARLOS = {eid}: the next pages read it.")
        return eid
    if what == "summaries":
        for n, sm in enumerate(data["summaries"], 1):
            print(f"Summary {n}, recorded ({data['recorded']}):")
            for r in sm.get("reasons", []):
                print(f"  - {r.get('reason')} (step {r.get('step')})")
        return data["summaries"]
    if what == "check":
        for mode, items in data["runs"].items():
            eid = _write_recorded(ctx, items, f"recorded-check-{mode}")
            dec = next(i for i in items if i.get("is_decision"))
            print(f"Loaded the recorded {mode} run as {eid}: outcome {dec['outcome']}, "
                  f"citation_check {dec.get('citation_check')}, ungrounded {dec.get('ungrounded_citations')}.")
        ws.plant_unsupported_citation(ctx)
        return None
    return data


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------
def _transform_zip():
    """The reference transform as the Lambda's index.py, zipped deterministically, so the
    deployed code's SHA-256 tells whether it is the reference."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("index.py", date_time=(2026, 1, 1, 0, 0, 0))
        info.external_attr = 0o644 << 16
        zf.writestr(info, open(os.path.join(HERE, "transform.py")).read())
    return buf.getvalue()


def _transform_deployed(ctx):
    sha = base64.b64encode(hashlib.sha256(_transform_zip()).digest()).decode()
    return ctx.lambda_.get_function_configuration(FunctionName=ctx.STREAM_PROCESSOR)["CodeSha256"] == sha


def deploy_reference_transform(ctx):
    """Cell 0.1: the stream transform, option B, deployed to dat408-stream-processor."""
    body = _transform_zip()

    def deploy():
        r = ctx.lambda_.update_function_code(FunctionName=ctx.STREAM_PROCESSOR, ZipFile=body)
        ctx.lambda_.get_waiter("function_updated").wait(FunctionName=ctx.STREAM_PROCESSOR)
        return r
    r = ws._run_with_spinner(deploy, "deploying the stream transform")
    print(f"✅ Deployed transform to {r['FunctionName']} ({r['CodeSize']} bytes)")
    for m in ctx.lambda_.list_event_source_mappings(FunctionName=ctx.STREAM_PROCESSOR)["EventSourceMappings"]:
        dest = m.get("DestinationConfig", {}).get("OnFailure", {}).get("Destination", "n/a").rsplit(":", 1)[-1]
        print(f"   Stream trigger: {m['State']}, batch size {m.get('BatchSize')}, failed records go to {dest}")
    return True


def run_evaluations(ctx, application_ids, payload=None):
    """Cell 0.2: run the agent once per id, all in parallel (an id can repeat). Returns one
    dict per run: application, run number, evaluation id, decision, seconds."""
    def one(app_id):
        t0 = time.time()
        body = ws._invoke_once(ctx, {"capture": True, "application_id": app_id, **(payload or {})})
        return {"application": app_id, "evaluation_id": body.get("evaluation_id"),
                "decision": (body.get("decision") or {}).get("decision", "?"),
                "response": body, "seconds": round(time.time() - t0)}

    def run_all():
        with ThreadPoolExecutor(max_workers=len(application_ids) or 1) as pool:
            return list(pool.map(one, application_ids))
    runs = ws._run_with_spinner(run_all, f"the agent evaluating {len(application_ids)} applications in parallel")
    seen, rows = {}, []
    for r in runs:
        seen[r["application"]] = seen.get(r["application"], 0) + 1
        r["run"] = seen[r["application"]]
        items = _evaluation_items(ctx, r["evaluation_id"]) if r["evaluation_id"] else []
        facts = {k: v for i in items for k, v in i.items() if k in ("ltv_pct", "back_end_dti_pct")}
        app = ctx.get_application(r["application"]) or {}
        rows.append({"application": r["application"], "applicant": (app.get("applicant") or {}).get("name", ""),
                     "run": r["run"], "decision": r["decision"],
                     "LTV": f"{float(facts['ltv_pct']):.1f}%" if "ltv_pct" in facts else "",
                     "back-end DTI": f"{float(facts['back_end_dti_pct']):.2f}%" if "back_end_dti_pct" in facts else "",
                     "steps recorded": sum(1 for i in items if i["SK"].startswith("STEP#")),
                     "seconds": r["seconds"]})
    import pandas as pd
    from IPython.display import display
    display(ws.styled_table(pd.DataFrame(rows), caption="Your runs, each recorded as it ran"))
    meta = next((m for m in (_meta(ctx, r["evaluation_id"]) for r in runs if r["evaluation_id"]) if m), {})
    print(f"Each header records model {meta.get('model_id', '?')} and prompt {meta.get('prompt_version', '?')}.")
    saanvi = [r for r in runs if r["application"] == SAANVI_APP]
    if saanvi:
        print("Saanvi's runs, the start of each reasoning:")
        for r in saanvi:
            reasoning = ((r["response"].get("decision") or {}).get("reasoning") or "")[:90]
            print(f"  {r['run']}  \"{reasoning}...\"")
    done = [r for r in saanvi if r["evaluation_id"]]
    if len(done) == 2:
        # What each run read: the passages its policy searches returned, from the record.
        read = []
        for r in done:
            items = _evaluation_items(ctx, r["evaluation_id"])
            read.append(({c for i in items for c in (i.get("retrieved_chunk_ids") or [])},
                         sum(1 for i in items if i["SK"].startswith("STEP#")), r["decision"]))
        (a1, s1, d1), (a2, s2, d2) = read
        same = "both " + d1 if d1 == d2 else f"{d1} and {d2}"
        print(f"\nYour two runs of Saanvi: {same}; {s1} and {s2} steps; they read {len(a1)} and {len(a2)} passages, "
              f"{len(a1 & a2)} of them in common." + (" Same outcome, different evidence." if d1 == d2 and a1 != a2 else ""))
    return runs


def _evaluation_items(ctx, eval_id, consistent=True):
    from boto3.dynamodb.conditions import Key
    return ctx.dynamodb.Table(ctx.TRACES_TABLE).query(
        KeyConditionExpression=Key("PK").eq(f"EVAL#{eval_id}"), ConsistentRead=consistent)["Items"]


def _meta(ctx, eval_id):
    return ctx.dynamodb.Table(ctx.TRACES_TABLE).get_item(Key={"PK": f"EVAL#{eval_id}", "SK": "META"}).get("Item")


def show_recorded_runs(ctx, app_id):
    """Cell 0.2: the recorded runs of an application under each build, if this build has them."""
    path = os.path.join(HERE, "recorded", f"runs_{app_id}.json")
    if not os.path.exists(path):
        print(f"Recorded runs of {app_id}: not in this build yet. They're recorded on a test event "
              "before the session ships (20 under the earlier build, 20 under this one).")
        return True
    import pandas as pd
    from IPython.display import display
    data = json.load(open(path))
    df = pd.DataFrame(data["by_build"])
    display(ws.styled_table(df, caption=f"{app_id}: recorded runs by build ({data.get('recorded', '')})"))
    runs = data.get("runs", [])
    if runs:
        outcomes = sorted({r["outcome"] for r in runs})
        sets = len({tuple(sorted(r.get("passages_read") or [])) for r in runs})
        print(f"Of the {len(runs)} recorded runs: " + ("all " + outcomes[0] if len(outcomes) == 1 else
              ", ".join(outcomes)) + f", reading {sets} different sets of passages.")
    return True


def choose_carlos(runs):
    """The Carlos run the next pages read: his denial (the latest, if there are several)."""
    carlos = [r for r in runs if r["application"] == CARLOS_APP and r["decision"] == "deny"]
    if not carlos:
        print("Carlos wasn't denied in this run: run Cell 0.2 again, or catch_up(\"carlos\") to load a recorded run.")
        return None
    eid = carlos[-1]["evaluation_id"]
    print(f"CARLOS = {eid} (LA-2026-00148, deny): the next pages read this evaluation.")
    if _state.get("ns") is not None:
        _set_carlos(_state["ns"], eid)
    return eid


# ---------------------------------------------------------------------------
# 1 · What to record
# ---------------------------------------------------------------------------
SUMMARY_SYSTEM = ("You are a compliance analyst. From this agent transcript, state the specific reasons for "
                  "denial, the information relied on, and the policies applied. For each reason, name the step "
                  "that supports it. Answer as JSON: {\"reasons\": [{\"reason\": str, \"step\": int or null}], "
                  "\"information\": [str], \"policies\": [str]}.")
# A fixed checker, not a model: the facts a reason can state, and the record fields that hold them.
FACT_FIELDS = {
    "loan-to-value": ["ltv_pct"], "ltv": ["ltv_pct"], "debt-to-income": ["back_end_dti_pct"],
    "dti": ["back_end_dti_pct"], "debt": ["back_end_dti_pct"], "credit score": ["credit_score"],
    "derogatory": ["derogatory_marks"], "income": ["verified_annual_income"],
    "reserves": [], "savings": [], "assets": [], "down payment": [], "employment gap": [],
}


def _check_reason(text, record, risk_factors, said_text):
    """⚠️ a reason that states a fact the record doesn't hold: no field holds it, and the
    decision's own recorded words (its reasoning, risk factors and adverse action reasons)
    don't state it. ℹ️ a risk factor given as a reason."""
    low, said = text.lower(), (said_text or "").lower()
    for fact, fields in FACT_FIELDS.items():
        if fact in low and not any(f in record for f in fields) and fact not in said:
            return "⚠️", fact
    if any(r.lower() in low or low in r.lower() for r in risk_factors) and not any(
            k in low for k in ("ltv", "loan-to-value", "dti", "debt-to-income")):
        return "ℹ️", None
    return "", None


REASON_FACTORS = [   # (row, keywords, what in the record answers it); first fixed list, no model
    ("Loan-to-value above 96.5%", ("loan-to-value", "ltv"), "II.A.2.b"),
    ("Front-end ratio (PTI) above 40%", ("front-end", "pti", "payment-to-income", "housing ratio"), "II.A.5.d"),
    ("Back-end DTI above 50%", ("back-end", "debt-to-income", "dti"), "II.A.5.d"),
    ("No compensating factors cure the ratios", ("compensating factor",), "II.A.5.d"),
    ("Income too low for the debts", ("insufficient", "qualifying income", "income relative", "disposable income",
                                      "residual income"), None),
    ("Income below stated", ("stated income", "discrepan", "below stated"), None),
    ("Credit score and derogatory marks", ("credit score", "fico", "618", "derogatory", "payment history"), None),
    ("Credit utilization", ("utilization",), None),
    ("Hard inquiries", ("inquir",), None),
    ("Short employment history", ("employ", "tenure"), None),
    ("Cash reserves", ("reserve",), None),
    ("Property condition", ("property condition",), None),
]


def _reason_factors(text):
    """The rows a reason covers. Parentheticals are usually examples or asides, so they count only
    when nothing outside them matches ("Elevated credit risk (618 credit score, ...)")."""
    stripped = _factor_hits(re.sub(r"\([^)]*\)", " ", text.lower()))
    return stripped or _factor_hits(text.lower())


def _factor_hits(low):
    hits = []
    for name, keys, _ in REASON_FACTORS:
        if any(k in low for k in keys):
            if name == "Back-end DTI above 50%" and "back-end" not in low and "front-end" in low and low.count("dti") <= 1:
                continue   # "front-end DTI" alone is the front-end row
            hits.append(name)
    return hits


def _record_says(row, violated, risk):
    pol = next((p for f, _, p in REASON_FACTORS if f == row), None)
    if pol:
        hit = [v for v in violated if pol in v]
        return f"failed {hit[0]}" if hit else "not a failed policy"
    keys = next((k for f, k, _ in REASON_FACTORS if f == row), None)
    if keys and any(any(k in r.lower() for k in keys) for r in risk):
        return "a risk factor"
    return "not in the record" if keys else ""


def summarize_decision(ctx, eval_id, runs=2):
    """Cell 1.2, option B: rebuild the fullest transcript a log could hold (each step's full
    output from S3, hash-checked), and ask the agent's own model to explain the denial, twice."""
    items = sorted(_evaluation_items(ctx, eval_id), key=lambda i: i["SK"])
    steps = [i for i in items if i["SK"].startswith("STEP#")]
    ok, transcript = 0, []
    for i in steps:
        body = i.get("observation_summary", "")
        if i.get("observation_s3_uri"):
            b, k = i["observation_s3_uri"].replace("s3://", "").split("/", 1)
            body = ctx.s3.get_object(Bucket=b, Key=k)["Body"].read().decode()
            ok += hashlib.sha256(body.encode()).hexdigest() == i.get("observation_sha256")
        transcript.append(f"Step {i['step_num']}: {i['action']}\nThought: {i.get('thought', '')}\nOutput: {body}")
    prompt = "\n\n".join(transcript)

    def ask(_):
        r = ctx.bedrock_runtime.converse(modelId=ctx.BEDROCK_MODEL_ID, system=[{"text": SUMMARY_SYSTEM}],
                                         messages=[{"role": "user", "content": [{"text": prompt}]}])
        # Sonnet 5 can return a reasoning block before its answer: take the text blocks.
        text = "".join(c["text"] for c in r["output"]["message"]["content"] if "text" in c)
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else {"reasons": [{"reason": text[:300], "step": None}]}
    out = ws._run_with_spinner(lambda: list(ThreadPoolExecutor(runs).map(ask, range(runs))),
                               f"asking {ctx.BEDROCK_MODEL_ID} for {runs} summaries")
    dec = next(i for i in steps if i.get("is_decision"))
    record = {k: v for i in steps for k, v in i.items()}
    risk = [str(x) for x in dec.get("risk_factors", [])]
    said = " ".join([str(dec.get("reasoning", ""))] + risk + [str(x) for x in dec.get("adverse_action_reasons", [])])
    print(f"Rebuilt the transcript of evaluation {eval_id} from {len(steps)} recorded steps, each read in full "
          f"from S3 ({ok} of {sum(1 for i in steps if i.get('observation_s3_uri'))} match the SHA-256 on their "
          f"items). Sent it {runs} times to {ctx.BEDROCK_MODEL_ID}.")
    import pandas as pd
    from IPython.display import HTML, display
    violated = [str(p) for p in dec.get("policies_violated", [])]
    marks, grid, unmatched = [], {}, {}
    for n, s in enumerate(out, 1):
        for r in s.get("reasons", []):
            text = str(r.get("reason", ""))
            mark, fact = _check_reason(text, record, risk, said)
            if mark:
                marks.append((n, text, mark, fact))
            hit = _reason_factors(text)
            if not hit:   # nothing on the list: the reason gets a row of its own
                hit = [unmatched.setdefault(text.lower()[:60], text[:70] + ("..." if len(text) > 70 else ""))]
            for f in hit:
                grid.setdefault(f, {})[n] = grid.get(f, {}).get(n, "") or ("✓ " + mark).strip()
    rows = []
    for f in [f for f, _, _ in REASON_FACTORS if f in grid] + [f for f in grid if f not in {x for x, _, _ in REASON_FACTORS}]:
        rows.append({"reason for denial": f, **{f"summary {n}": grid[f].get(n, "") for n in range(1, len(out) + 1)},
                     "the record": _record_says(f, violated, risk)})
    display(ws.styled_table(pd.DataFrame(rows), caption="What each summary gave as a reason, beside the record"))
    named = [{f for f, by in grid.items() if n in by} for n in range(1, len(out) + 1)]
    if len(named) == 2:
        print(f"Summary 1 names {len(named[0])} of these and summary 2 names {len(named[1])}; they agree on "
              f"{len(named[0] & named[1])}. The record holds one answer: failed {', '.join(violated) or 'none'}.")
    print("Information relied on: " + "; ".join(f"summary {n} lists {len(s.get('information', []))} items and "
                                             f"{len(s.get('policies', []))} policies" for n, s in enumerate(out, 1)) + ".")
    import html as _h
    full = "".join(f"<p><b>Summary {n}</b></p><ol>" + "".join(
        f"<li>{_h.escape(str(r.get('reason', '')))}" + (f" <i>(step {r['step']})</i>" if r.get("step") is not None else "")
        + "</li>" for r in s.get("reasons", [])) + "</ol>" for n, s in enumerate(out, 1))
    display(HTML(ws.plain_html(f"<details><summary>Show the two summaries in full</summary>{full}</details>")))
    for n, reason, mark, fact in marks:
        print(f"{mark} Summary {n}: \"{reason}\"" + (f": the record holds no {fact}, and the decision never stated it." if fact
                                                    else ": the record lists it as a risk factor, not a failed policy."))
    if not any(m == "⚠️" for _, _, m, _ in marks):
        print("Neither of your summaries states a fact no field holds.")
    path = os.path.join(HERE, "recorded", "summaries_carlos.json")
    if os.path.exists(path):
        data = json.load(open(path))
        print(f"Of {data['n']} recorded summaries of one Carlos evaluation ({data['recorded']}): "
              f"{data['distinct_reason_sets']} different sets of reasons, {data['states_unrecorded_fact']} stating a "
              "fact the record doesn't hold.")
    return out


def show_evidence(ctx, eval_id):
    """Cell 1.3, option C: the evidence by key, twice, strongly consistent, hash-checked."""
    from boto3.dynamodb.conditions import Key
    t = ctx.dynamodb.Table(ctx.TRACES_TABLE)
    t0 = time.time()
    r = t.query(KeyConditionExpression=Key("PK").eq(f"EVAL#{eval_id}"), ConsistentRead=True,
                ReturnConsumedCapacity="TOTAL")
    ms = (time.time() - t0) * 1000
    items = sorted(r["Items"], key=lambda i: i["SK"])
    meta = next((i for i in items if i["SK"] == "META"), {})
    steps = [i for i in items if i["SK"].startswith("STEP#")]
    dec = next((i for i in steps if i.get("is_decision")), {})
    print(f"Query  KeyConditionExpression: PK = EVAL#{eval_id}  ConsistentRead: True\n"
          f"       -> {len(items)} items, {ms:.0f} ms, {r['ConsumedCapacity']['CapacityUnits']} read units")
    print(f"Header (META): {meta.get('status')} | model {meta.get('model_id')} | prompt {meta.get('prompt_version')}")
    print(f"  agent build {meta.get('agent_build', '?')} | ingestion job {meta.get('kb_ingestion_job_id')}")
    import pandas as pd
    from IPython.display import display
    rows = []
    for i in steps:
        if i.get("is_decision"):
            what = f"decision recorded: {str(i.get('outcome', '')).upper()}"
        elif i["action"] == "retrieve_lending_policy":
            q = (json.loads(i["action_input"]).get("query") if i.get("action_input", "").startswith("{") else i.get("action_input"))
            what = f"searched \"{q}\" -> {', '.join(i.get('retrieved_policy_ids', []))}"
        else:
            what = ws.summarize_evidence(i)
        rows.append({"step": int(i["step_num"]), "tool": i["action"], "what it read": what})
    display(ws.styled_table(pd.DataFrame(rows), caption="What the agent read (tool outputs, in step order)"))
    eds = {p: v for i in steps for p, v in (i.get("retrieved_policy_versions") or {}).items()}
    print("Editions read: " + "; ".join(f"{p} \"{v}\"" for p, v in sorted(eds.items())))
    print(f"\nDECISION: {str(dec.get('outcome', '')).upper()}\n{dec.get('reasoning', '')[:400]}")
    for field, cap in (("policies_cited", "Policies cited"), ("policies_violated", "Policies the application failed"),
                       ("risk_factors", "Risk factors"), ("adverse_action_reasons", "Adverse action reasons")):
        if dec.get(field):
            display(ws.styled_table(pd.DataFrame({cap.lower(): dec[field]}), caption=cap))
    if dec.get("citation_check"):
        print(f"Citation check: {dec['citation_check']}" + (f" ({', '.join(dec.get('ungrounded_citations', []))})"
                                                             if dec.get("ungrounded_citations") else ""))
    good = 0
    for i in steps:
        if i.get("observation_s3_uri"):
            b, k = i["observation_s3_uri"].replace("s3://", "").split("/", 1)
            body = ctx.s3.get_object(Bucket=b, Key=k)["Body"].read().decode()
            good += hashlib.sha256(body.encode()).hexdigest() == i.get("observation_sha256")
    n = sum(1 for i in steps if i.get("observation_s3_uri"))
    print(f"{'✅' if good == n else '❌'} {good} of {n} recorded outputs match the SHA-256 on their items (full copies in S3).")
    again = t.query(KeyConditionExpression=Key("PK").eq(f"EVAL#{eval_id}"), ConsistentRead=True)["Items"]
    same = sorted((i["SK"], i.get("observation_sha256")) for i in again) == sorted(
        (i["SK"], i.get("observation_sha256")) for i in items)
    print(f"{'✅' if same else '❌'} Read twice, strongly consistent: the same {len(items)} items both times.")
    return True


# ---------------------------------------------------------------------------
# 2 · How to key it
# ---------------------------------------------------------------------------
SORT_ANSWERS = {1: "key", 2: "index", 3: "count", 4: "index", 5: "later"}
SORT_WHY = {
    1: "one Query on the table's own key, PK = EVAL#<id>, in step order",
    2: "application-index finds the evaluations; each header (META) names the model and prompt",
    3: "the POLICY#/MONTH# items, kept current in the decision's own transaction",
    4: "band-index: every decision item holds its three bands, so one Query on all three finds the peers",
    5: "no item holds the answer: it compares what one item retrieved with what another cited. "
       "A Scan plus join code now; a graph, or an export, later",
}


def check_sort(answers):
    """Cell 2.1: accept any answer, and explain each one."""
    norm = {k: str(v).strip().lower() for k, v in answers.items()}
    if not any(norm.values()):
        print('Set each answer to "key", "index", "count", or "later", then run this cell again.')
        return True
    right = 0
    for q in sorted(SORT_ANSWERS):
        got, want = norm.get(q, ""), SORT_ANSWERS[q]
        right += got == want
        print(f"{'✅' if got == want else '❌'} {q}: you chose {got or '(nothing)'}; the design: {want}. {SORT_WHY[q]}.")
    print(f"\n{right} of 5 as the design has it. Cell 2.2 answers each one that way, with its cost.")
    return True


def run_questions(ctx, eval_id):
    """Cell 2.2: each of the five questions answered the way the design answers it, beside your
    sort from Cell 2.1, with what each one cost in read units."""
    from boto3.dynamodb.conditions import Key
    import pandas as pd
    from IPython.display import display
    t = ctx.dynamodb.Table(ctx.TRACES_TABLE)

    def q(**kw):
        items, ru, kw = [], 0.0, {**kw, "ReturnConsumedCapacity": "TOTAL"}
        while True:
            r = t.query(**kw)
            items += r["Items"]
            ru += r["ConsumedCapacity"]["CapacityUnits"]
            if "LastEvaluatedKey" not in r:
                return items, ru
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    rows = []   # (question number, question, how the design answers it, read units, short answer)
    sent = []   # the request behind each answer, printed above the table
    sent.append(f"1  Query  PK = EVAL#{eval_id}  ConsistentRead: True")
    items, ru = q(KeyConditionExpression=Key("PK").eq(f"EVAL#{eval_id}"), ConsistentRead=True)
    rows.append((1, "What did the agent do for Carlos, step by step?", "a Query on the table's key", ru,
                 f"{len(items)} items, in step order"))
    sent.append(f"2  Query  application-index: application_id = {CARLOS_APP}, then GetItem SK = META per evaluation")
    keys, ru = q(IndexName="application-index", KeyConditionExpression=Key("application_id").eq(CARLOS_APP))
    evals = sorted({k["PK"] for k in keys})
    metas = [t.get_item(Key={"PK": pk, "SK": "META"}, ReturnConsumedCapacity="TOTAL") for pk in evals]
    ru += sum(m["ConsumedCapacity"]["CapacityUnits"] for m in metas)
    models = {(m["Item"].get("model_id"), m["Item"].get("prompt_version")) for m in metas if "Item" in m}
    rows.append((2, "Which evaluations ran for LA-2026-00148, under which model and prompt?",
                 "application-index, then each header", ru,
                 f"{len(evals)} evaluations, {len(models)} model and prompt" + ("s" if len(models) > 1 else "")))
    sent.append(f"3  Query  PK = POLICY#{P_RATIOS}  (one item per month: SK = MONTH#yyyy-mm)")
    months, ru = q(KeyConditionExpression=Key("PK").eq(f"POLICY#{P_RATIOS}"))
    this = datetime.now(timezone.utc).strftime("%Y-%m")
    past = [m for m in months if m["SK"] < f"MONTH#{this}"]
    rows.append((3, "How many decisions failed II.A.5.d each month?", "the monthly count items", ru,
                 f"{len(past)} months, {sum(int(m['decisions_failing']) for m in past):,} failures"))
    dec = next(i for i in items if i.get("is_decision"))
    bands = {b: dec.get(b) for b in ("credit_band", "dti_band", "ltv_band")}
    if all(bands.values()):
        sent.append("4  Query  band-index, on Carlos's three bands (you'll write this one in Cell 2.2a)")
        peers, ru = q(IndexName="band-index", KeyConditionExpression=Key("credit_band").eq(bands["credit_band"])
                      & Key("dti_band").eq(bands["dti_band"]) & Key("ltv_band").eq(bands["ltv_band"]))
        past_p = [p for p in peers if p["PK"].startswith("EVAL#hist-")]
        by = {}
        for p in past_p:
            by[p["outcome"]] = by.get(p["outcome"], 0) + 1
        verdict = ("all " + _done(next(iter(by)))) if len(by) == 1 else ", ".join(f"{v:,} {_done(k)}" for k, v in by.items())
        rows.append((4, "Were applicants like Carlos decided the same way?", "band-index on his three bands", ru,
                     f"{len(past_p):,} past peers, {verdict}"))
    scan_ru = _scan_estimate(ctx)
    sent.append("5  Scan   the whole table (not run: priced from a 2,000-item sample)")
    rows.append((5, "Which past denials cite a policy the agent never retrieved?", "no key, so a full Scan for now", scan_ru,
                 f"not run: about ${scan_ru * RRU_PRICE:.3f}, plus join code"))
    print("The request behind each answer:\n" + "\n".join(f"  {r}" for r in sent) + "\n")
    mine = {k: str(v).strip().lower() for k, v in ((_state.get("ns") or {}).get("ANSWERS") or {}).items()}
    table = []
    for n, question, how, cost, answer in rows:
        row = {"question": f"{n} · {question}"}
        if any(mine.values()):
            row["you chose"] = (mine.get(n) or "(nothing)") + (" ✅" if mine.get(n) == SORT_ANSWERS[n] else " ❌")
        row.update({"the design": f"{SORT_ANSWERS[n]}: {how}",
                    "read units": f"{float(cost):,.1f}" if float(cost) < 10 else f"{float(cost):,.0f}",
                    "answer": answer})
        table.append(row)
    display(ws.styled_table(pd.DataFrame(table),
                            caption=f"Your five questions, answered against {ctx.HISTORICAL_DECISIONS:,} past decisions"))
    ws.bar_chart([f"question {n}" for n, *_ in rows], [max(float(r[3]), 0.5) for r in rows],
                 "Read units for one answer (log scale)", log=True,
                 colors=[ws.OUTCOME["deny"] if n == 5 else ws.SERIES[0] for n, *_ in rows],
                 legend={ws.SERIES[0]: "a key, an index, or a count", ws.OUTCOME["deny"]: "no key: a full Scan"})
    keyed = [float(r[3]) for r in rows if r[0] != 5]
    print(f"Questions 1 to 4 cost {min(keyed):,.1f} to {max(keyed):,.0f} read units each. Question 5 has no key: "
          f"one answer would cost about {scan_ru:,} read units. For new decisions, the runtime writes "
          f"ungrounded_month when a citation check fails, so the sparse ungrounded-index finds them by key.")
    return True


def _done(outcome):
    return {"deny": "denied", "escalate": "escalated", "approve": "approved"}.get(outcome, outcome)


def show_peers(ctx, app_id, query=None):
    """Cell 2.2a: question 4 for another applicant. Runs your band-index Query (the kwargs in
    `query`), checks it against the reference, and shows past peers by how many compensating
    factors each documented, and the outcome. A blank or wrong Query runs the reference instead."""
    from boto3.dynamodb.conditions import Key
    from botocore.exceptions import ClientError
    import pandas as pd
    from IPython.display import display
    app = ctx.get_application(app_id) or {}
    name = (app.get("applicant") or {}).get("name", app_id).split(" ")[0]
    t = ctx.dynamodb.Table(ctx.TRACES_TABLE)
    keys = _band_keys(ctx, app_id)
    if not keys:
        print(f"No recorded decision for {app_id} yet: run Cell 0.2 first.")
        return True

    def run(kw):
        items, ru, kw = [], 0.0, {**kw, "ReturnConsumedCapacity": "TOTAL"}
        while True:
            r = t.query(**kw)
            items += r["Items"]; ru += r["ConsumedCapacity"]["CapacityUnits"]
            if "LastEvaluatedKey" not in r:
                return items, ru
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    ref = {"IndexName": "band-index", "KeyConditionExpression": Key("credit_band").eq(keys[0])
           & Key("dti_band").eq(keys[1]) & Key("ltv_band").eq(keys[2])}
    want, want_ru = run(ref)
    items, ru, yours = want, want_ru, False
    query = query or {}
    if query.get("KeyConditionExpression") is None:
        print("Fill in the line marked ✏️, then run this cell again. Showing the reference Query's answer for now.")
    elif query.get("IndexName") != "band-index":
        print("❌ Not yet: query IndexName=\"band-index\". Showing the reference Query's answer for now.")
    else:
        try:
            got, got_ru = run(query)
            if sorted(i["PK"] for i in got) == sorted(i["PK"] for i in want):
                print(f"✅ Your Query matches the reference: {len(got):,} decisions in {name}'s three bands.")
                items, ru, yours = got, got_ru, True
            else:
                print(f"❌ Not yet: your Query found {len(got):,} decisions; the reference finds {len(want):,}. "
                      "Showing the reference Query's answer for now.")
        except ClientError as e:
            print(f"❌ DynamoDB rejected the Query: {e.response['Error']['Message']}")
            print("   band-index's partition key is all three bands, so the condition needs an equality on "
                  "credit_band, dti_band and ltv_band. Showing the reference Query's answer for now.")
    piv = pd.DataFrame([{"compensating factors": int(p.get("compensating_factors", 0)), "outcome": _done(p["outcome"])}
                        for p in items if p["PK"].startswith("EVAL#hist-")])
    tab = piv.pivot_table(index="compensating factors", columns="outcome", aggfunc="size", fill_value=0).reset_index()
    whose = "Your" if yours else "The reference"
    display(ws.styled_table(tab, caption=f"{name}'s {len(piv):,} past peers ({', '.join(keys)}): outcome by how many "
                                         f"compensating factors each file documented. {whose} band-index Query, "
                                         f"{ru:.1f} read units."))
    none = piv[piv["compensating factors"] == 0]["outcome"].value_counts()
    if len(none) > 1:
        print(f"Look at the row with no compensating factor: " + " and ".join(f"{v:,} {k}" for k, v in none.items())
              + ". Similar files, decided two ways: the inconsistency the examiner's fourth ask is looking for.")
    return True


def _band_keys(ctx, app_id):
    """An application's three bands, from its latest recorded decision."""
    from boto3.dynamodb.conditions import Key
    t = ctx.dynamodb.Table(ctx.TRACES_TABLE)
    keys = t.query(IndexName="application-index", KeyConditionExpression=Key("application_id").eq(app_id))["Items"]
    for pk in sorted({k["PK"] for k in keys}, reverse=True):
        for i in _evaluation_items(ctx, pk.replace("EVAL#", "")):
            if i.get("is_decision") and all(i.get(b) for b in ("credit_band", "dti_band", "ltv_band")):
                return (i["credit_band"], i["dti_band"], i["ltv_band"])
    return None


# ---------------------------------------------------------------------------
# Reference answers (the Go deeper solutions the main path runs)
# ---------------------------------------------------------------------------
def reference_answer(name):
    from agent import reference
    return getattr(reference, name)


# ---------------------------------------------------------------------------
# 3 · What goes in the graph: the lineage walk
# ---------------------------------------------------------------------------
WALK_LABELS = {
    "identities": ["PRODUCED_BY", "IDENTITY_FROM", "USED", "RESTS_ON"],
    "amounts": ["PRODUCED_BY", "DERIVED_FROM", "USED", "RESTS_ON"],
    "both": ["PRODUCED_BY", "DERIVED_FROM", "IDENTITY_FROM", "USED", "RESTS_ON"],
}


def _expected(ctx):
    key = "history/fixtures/lineage-expected.json"
    return json.loads(ctx.s3.get_object(Bucket=ctx.HISTORY_BUCKET, Key=key)["Body"].read())


def show_lineage(ctx, walk, source, fixed, recent):
    """Cell 3.2: your walk, checked against the walk over both routes, beside the same walk over
    amounts only and identities only, a date filter, one hop, and recursive SQL's expected answer."""
    import pandas as pd
    from IPython.display import display
    exp = _expected(ctx)
    v = exp["versions"][source.replace("version:", "")]
    start, end = v["live"]
    print(f"doc-extract 2.3.1 read income documents from {start} to {end}; 2.3.2 replaced it on {exp['fixed_on']}.")

    def run(q):
        t0 = time.time()
        rows = ctx.neptune_query(q, {"source": source, "fixed": fixed, "recent": recent})["results"]
        decs = [r for r in rows if r["kind"] == "Decision"]
        return {"decisions": sum(r["found"] for r in decs),
                "after_fix": sum(r["found"] for r in decs if r["after_fix"]),
                "notices": sum(r["found"] for r in rows if r["kind"] == "Notice"),
                "deepest": max((r["deepest"] for r in rows), default=0)}, time.time() - t0

    def labelled(labels):
        return re.sub(r"edgeLabels: \[[^\]]*\]", "edgeLabels: [" + ", ".join(f"'{x}'" for x in labels) + "]", walk)
    res, secs = {}, 0.0
    for name, labels in WALK_LABELS.items():
        res[name], s = run(labelled(labels))
        secs += s
    # Your walk, as written, checked against the walk over both routes.
    m = re.search(r"edgeLabels: \[([^\]]*)\]", walk)
    yours_labels = re.findall(r"'(\w+)'", m.group(1)) if m else []
    try:
        yours, _ = run(walk)
    except Exception as e:
        yours = None
        print(f"❌ The walk failed: {str(e)[:300]}")
    want = res["both"]
    if yours and (yours["decisions"], yours["after_fix"]) == (want["decisions"], want["after_fix"]):
        print(f"✅ Your walk follows both routes: {yours['decisions']:,} decisions, the same as recursive SQL.")
    elif yours and set(yours_labels) == set(WALK_LABELS["identities"]):
        print(f"❌ Not yet: your walk follows employer identities only, and finds {yours['decisions']:,} decisions; "
              f"recursive SQL finds {want['decisions']:,}. Add the edge that follows amounts to edgeLabels "
              "(see the graph model above), then run the cell again.")
    elif yours:
        print(f"❌ Not yet: your walk finds {yours['decisions']:,} decisions; recursive SQL finds "
              f"{want['decisions']:,}. Its edgeLabels: {', '.join(yours_labels) or '(none found)'}.")
    if not yours or (yours["decisions"], yours["after_fix"]) != (want["decisions"], want["after_fix"]):
        print("   The rows below include the walk over both routes, so the rest of the page still works.\n")
    date_n, used = exp["date_filter"]["decisions"], exp["date_filter"]["decisions"] - exp["date_filter"]["never_used_it"]
    table = pd.DataFrame([
        ["Date filter: decided May 4 to 24", date_n, date_n - used, 0],
        ["One hop: runs that called 2.3.1", exp["one_hop"], 0, 0],
        ["Walk over amounts it read", res["amounts"]["decisions"], 0, res["amounts"]["after_fix"]],
        ["Walk over identities it read", res["identities"]["decisions"], 0, res["identities"]["after_fix"]],
        *([["Your walk", yours["decisions"], 0, yours["after_fix"]]] if yours else []),
        ["Walk over both", res["both"]["decisions"], 0, res["both"]["after_fix"]],
        ["C: recursive SQL, expected", exp["walks"]["both"]["decisions"], 0, exp["walks"]["both"]["after_fix"]],
    ], columns=["Method", "Decisions", "Don't rest on it", "After the fix"])
    display(ws.styled_table(table, bar_cols=["Decisions"], caption="Which decisions rest on what 2.3.1 read?"))
    print(f"Date filter: {date_n - used:,} of its {date_n:,} never used 2.3.1: their income came from the EVOE feed.")
    print("One hop: what a GSI on the model version would return. C: SQLite's WITH RECURSIVE over the same lineage "
          "files (computed at deploy).")
    print(f"Each walk in about {secs / 3:.1f} s. The walk over both reaches {res['both']['deepest']} hops; recursive SQL in "
          "Athena stops at 10.")
    match = all(res[w]["decisions"] == exp["walks"][w]["decisions"] and res[w]["after_fix"] == exp["walks"][w]["after_fix"]
                for w in WALK_LABELS)
    b = res["both"]
    print(f"{'✅' if match else '❌'} {b['decisions']:,} decisions rest on doc-extract 2.3.1, over both; "
          f"{b['after_fix']:,} came after the fix: {res['identities']['after_fix']:,} through identities, "
          f"{res['amounts']['after_fix']:,} through amounts. {b['notices']:,} notices rest on it.")
    live = ctx.neptune_query("""MATCH (d:Decision)-[:USED]->(a:Artifact) WHERE d.historical IS NULL
        RETURN count(DISTINCT d) AS n""")["results"][0]["n"]
    if live:
        print(f"Your {live} live runs joined the lineage too, through the EVOE and bureau feeds. None read a "
              "document, so none rest on 2.3.1.")
    hops = exp["walks"]["both"]["decisions_by_hop"]
    ws.bar_chart([f"{h} hops" for h in hops], list(hops.values()), "Decisions by hop, over both", unit="decisions")
    return True


def _lineage_sample(ctx, source, fixed, seed):
    """A fixed-seed sample of the walk's decisions in five groups, the same in every account:
    the busiest employer record's decisions after and before the fix (and the decision whose
    document built it), wage earners whose own documents 2.3.1 read, re-applications after the
    fix that reused a document it read (with their earlier applications), and self-employed
    applicants. Returns ({group: [decision ids]}, the busiest record's root extraction)."""
    import random
    rng = random.Random(seed)
    q = lambda text, **p: ctx.neptune_query(text, {"source": source, "fixed": fixed, **p})["results"]
    exp = _expected(ctx)
    root = exp.get("busiest_identity", {}).get("built_from")
    groups = {}
    if root:
        hub = q("""MATCH (x:Artifact {`~id`: $root})<-[:IDENTITY_FROM*1..6]-(:Artifact {kind: 'employer_record'})
                   <-[:IDENTITY_FROM]-(:Artifact {kind: 'income'})<-[:USED]-(d:Decision)
                   RETURN DISTINCT id(d) AS id, d.day > $fixed AS after""", root=root)
        after = sorted(r["id"] for r in hub if r["after"])
        before = sorted(r["id"] for r in hub if not r["after"])
        groups["the busiest employer record, after the fix"] = rng.sample(after, min(7, len(after)))
        builder = f"decision:{root.split(':')[2]}_decision"
        groups["the busiest employer record, before the fix"] = rng.sample(
            [i for i in before if i != builder], min(3, max(0, len(before) - 1))) + [builder]
    direct = sorted(r["id"] for r in q("""MATCH (v:Version {`~id`: $source})<-[:PRODUCED_BY]-(x:Artifact)
            <-[:DERIVED_FROM]-(:Artifact {kind: 'income'})<-[:USED]-(d:Decision)
            WHERE x.doc IN ['paystubs', 'w2s', 'wvoe'] AND d.id = x.run + '_decision'
            RETURN DISTINCT id(d) AS id LIMIT 2000"""))
    groups["wage earners whose own documents 2.3.1 read"] = rng.sample(direct, min(5, len(direct)))
    reapp = q("""MATCH (v:Version {`~id`: $source})<-[:PRODUCED_BY]-(x:Artifact)
            <-[:DERIVED_FROM]-(:Artifact {kind: 'income'})<-[:USED]-(d:Decision)
            WHERE d.day > $fixed AND d.id <> x.run + '_decision'
            RETURN DISTINCT id(d) AS id, 'decision:' + x.run + '_decision' AS earlier""")
    picked = rng.sample(sorted(reapp, key=lambda r: r["id"]), min(2, len(reapp)))
    groups["re-applications after the fix that reused a document 2.3.1 read"] = [r["id"] for r in picked]
    groups["the earlier applications those documents came from"] = sorted({r["earlier"] for r in picked})
    selfe = sorted(r["id"] for r in q("""MATCH (v:Version {`~id`: $source})<-[:PRODUCED_BY]-(:Artifact)
            <-[:DERIVED_FROM]-(:Artifact {kind: 'business_income'})<-[:DERIVED_FROM]-(:Artifact {kind: 'income'})
            <-[:USED]-(d:Decision) RETURN DISTINCT id(d) AS id LIMIT 2000"""))
    groups["self-employed applicants whose business income came from documents 2.3.1 read"] = rng.sample(selfe, min(2, len(selfe)))
    return groups, root


def lineage_drawing(ctx, source, sample="408:v3:view"):
    """The sampled decisions' typed paths back to the version, and the notices resting on them, as
    (nodes, edges, groups, root, fixed): what Cell 3.3 draws."""
    exp = _expected(ctx)
    fixed = exp["versions"][source.replace("version:", "")]["live"][1]
    groups, root = _lineage_sample(ctx, source, fixed, sample)
    ids = sorted({i for g in groups.values() for i in g})
    rows = ctx.neptune_query(("""MATCH p = (d:Decision)-[:USED|DERIVED_FROM|IDENTITY_FROM|PRODUCED_BY*1..9]->(v:Version {`~id`: $source})
        WHERE id(d) IN $ids
        UNWIND relationships(p) AS rel
        RETURN DISTINCT startNode(rel) AS src, type(rel) AS rel, endNode(rel) AS dst
        UNION
        MATCH (n:Notice)-[f:FOR]->(d:Decision) WHERE id(d) IN $ids
        MATCH (n)-[r:RESTS_ON]->(a:Artifact) WHERE a.kind IN ['income', 'ratios']
        RETURN n AS src, type(r) AS rel, a AS dst""").replace("$ids", json.dumps(ids)), {"source": source})["results"]
    nodes, edges = {}, []
    for r in rows:
        for side in ("src", "dst"):
            n = r[side]
            nid, props = n["~id"], n.get("~properties", {})
            label = (n.get("~labels") or ["?"])[0]
            kind = {"Decision": "decision", "Notice": "notice", "Version": "version"}.get(label, props.get("kind", "?"))
            tip = {"decision": f"{props.get('application_id', '')}, {props.get('outcome', '')}, decided {props.get('day', '')}",
                   "notice": f"adverse action notice, {props.get('day', '')}",
                   "version": f"{props.get('name', nid)}, live from {props.get('live_from', '')}"}.get(
                kind, f"{kind.replace('_', ' ')}, {props.get('day') or props.get('built', '')}: {nid}")
            nodes.setdefault(nid, {"kind": kind, "outcome": props.get("outcome"), "day": props.get("day", ""),
                                   "tip": tip, "employer": props.get("employer")})
        edges.append((r["src"]["~id"], r["dst"]["~id"], r["rel"]))
    return nodes, sorted(set(edges)), groups, root, fixed, exp


def show_from_source(query):
    """Cell 3.1: draw a lineage query in Neptune's graph view (%%oc) with its source on the left,
    so the view reads from 2.3.1 out to the decisions. Lineage edges point back to what each result
    was built from, so the notebook's usual left-to-right layout would put 2.3.1 on the right.
    The usual layout is put back for the cells after this one."""
    from IPython import get_ipython
    ws.set_graph_layout("RL")
    try:
        get_ipython().run_cell_magic(
            "oc", '-qp params -g {"Decision":"outcome","Artifact":"kind","Version":"~labels","Notice":"~labels"} '
                  '-d {"Decision":"day","Version":"name","Artifact":"kind","Notice":"day"} -l 24 -rel 20', query)
    finally:
        ws.set_graph_layout()
    return True


def draw_lineage(ctx, source, sample="408:v3:view"):
    """Cell 3.3: a fixed-seed sample of the walk's decisions in five groups, and every node on their
    paths back to the version, one column per hop from it (agent/lineage_view.py)."""
    from IPython.display import HTML, display
    from agent import lineage_view as lv
    nodes, edges, groups, root, fixed, exp = lineage_drawing(ctx, source, sample)
    # Keep one decision from each group in params, for anyone who wants to query them.
    ns = _state.get("ns")
    if ns is not None:
        pick = list(dict.fromkeys(g[0] for g in groups.values() if g))
        ns.setdefault("params", {}).update({"lineage": pick, "source": source})
    decs = [n for n, p in nodes.items() if p["kind"] == "decision"]
    after = [n for n in decs if nodes[n]["day"] > fixed]
    # the busiest record's paths: from the document that built it, through the record and its monthly
    # refreshes, to the incomes that took their identity from it and the decisions that used them
    hub_nodes, hub_edges = set(), set()
    if root and root in nodes:
        hub_nodes, frontier = {root}, {root}
        while frontier:
            nxt = set()
            for a, b, l in edges:
                if b in frontier and l == "IDENTITY_FROM":
                    hub_edges.add((a, b))
                    if a not in hub_nodes:
                        nxt.add(a)
            hub_nodes |= nxt
            frontier = nxt
        for a, b, l in edges:
            if l == "USED" and b in hub_nodes and nodes[b]["kind"] == "income":
                hub_edges.add((a, b))
    lv_nodes = {n: dict(p) for n, p in nodes.items()}
    lv.layout(lv_nodes, edges, source)
    deep = max((n for n in decs if "level" in lv_nodes[n]), key=lambda n: (lv_nodes[n]["level"], nodes[n]["day"]), default=None)
    first_rec = min((n for n in hub_nodes if nodes[n]["kind"] == "employer_record"), key=lambda n: nodes[n]["day"], default=None)
    notice = next((a for a, b, l in edges if l == "RESTS_ON" and nodes[b]["kind"] == "ratios"), None)
    b = exp.get("busiest_identity", {})
    import datetime
    month = lambda d: datetime.date.fromisoformat(d).strftime("%B") if d else ""
    v = exp["versions"][source.replace("version:", "")]
    s_, e_ = (datetime.date.fromisoformat(x) for x in v["live"])
    docs = {"paystubs": "pay stubs", "wvoe": "written VOE", "w2s": "W-2s", "tax_returns": "tax returns",
            "pnl": "P&L", "award_letter": "award letter"}
    doc = docs.get((root or "").rsplit(":", 1)[-1], "document")
    callouts = [(source, 1, f"doc-extract 2.3.1, {s_:%b} {s_.day} to {e_.day}", -40)]
    if first_rec:
        callouts.append((first_rec, 2, f"the employer identity 2.3.1 read\nfrom one applicant's {doc}, as {nodes[first_rec]['employer']}'s record: "
                                       f"{b.get('decisions', '?')} decisions\nrest on it", 40))
    if deep:
        callouts.append((deep, 3, f"a {month(nodes[deep]['day'])} decision,\n{lv_nodes[deep]['level']} hops out", -50))
    if notice:
        callouts.append((notice, 4, "a notice resting on a ratio\nbuilt from 2.3.1's output", -46))
    outc = {o: sum(1 for n in decs if nodes[n]["outcome"] == o) for o in ("approve", "deny", "escalate")}
    legend = [lv.chip("", f"{len(after)} of {len(decs)} decided after 2.3.2 replaced it", ring=True),
              f"<b>{len(decs)}</b> decisions drawn:" + lv.chip(lv.COLORS["approve"], f"{outc['approve']} approve")
              + lv.chip(lv.COLORS["deny"], f"{outc['deny']} deny") + lv.chip(lv.COLORS["escalate"], f"{outc['escalate']} escalate"),
              lv.chip(lv.COLORS["version"], "doc-extract 2.3.1") + lv.chip(lv.COLORS["extraction"], "document 2.3.1 read")
              + lv.chip(lv.COLORS["employer_record"], "employer record") + lv.chip(lv.COLORS["income"], "result")
              + lv.chip(lv.COLORS["notice"], "notice")
              + '<span style="display:inline-block;width:18px;height:6px;background:#cfc6f2;margin:0 4px 0 10px;'
                'vertical-align:1px"></span>the busiest record\'s paths']
    total = exp['walks']['both']['decisions']
    print(f"Drawing {len(nodes)} nodes and {len(edges)} relationships: {len(decs)} of the {total:,} decisions "
          f"that rest on 2.3.1, every node\non their paths back to it, and the notices that rest on those "
          f"decisions. Every account draws the same {len(decs)}:")
    # Before the fix first, then after; the sample itself (and its seed) is unchanged.
    order = ["the busiest employer record, before the fix", "the busiest employer record, after the fix"]
    rest = ["wage earners whose own documents 2.3.1 read",
            "self-employed applicants whose business income came from documents 2.3.1 read",
            "re-applications after the fix that reused a document 2.3.1 read",
            "the earlier applications those documents came from"]
    for g in order + rest + [g for g in groups if g not in order + rest]:
        if g in groups:
            print(f"  {len(groups[g])}  {g}")
    hub = sum(len(groups.get(g, [])) for g in order)
    if b and hub:
        print(f"We drew {hub} of the {len(decs)} from the busiest employer record, far more than its share, so "
              f"you can see how\none cached record carries 2.3.1's reading forward: {b['decisions']} decisions "
              f"rest on it. Hover over any node to\nsee what it is.")
    display(HTML(lv.svg(lv_nodes, edges, source, after_fix=after, hub_edges=hub_edges, callouts=callouts, legend=legend,
                        title="columns: hops from doc-extract 2.3.1. Trace the query to watch the walk, one hop at a time.",
                        totals=exp["walks"])))
    return True


# ---------------------------------------------------------------------------
# 4 · Check now or later
# ---------------------------------------------------------------------------
def test_copy(ctx, app_id, new_id):
    """A copy of an application under a test id, so the citation check's test hook can run on it."""
    app = json.loads(json.dumps(ctx.get_application(app_id), default=str))
    app["application_id"] = new_id
    app.setdefault("applicant", {})["name"] = app.get("applicant", {}).get("name", "") + " (test copy)"
    from agent.applications import put_application
    put_application(app)
    return new_id


def run_with_check(ctx, app_id, plant=True):
    """Cell 4.1: the test copy twice in parallel, with the check on annotate and on escalate,
    each with one test citation its own searches didn't return. Then plant LA-AUDIT-TEST."""
    import pandas as pd
    from IPython.display import display

    def one(mode):
        body = ws._invoke_once(ctx, {"capture": True, "application_id": app_id, "citation_check": mode,
                                     "test_inject_citation": True})
        return mode, body
    out = ws._run_with_spinner(lambda: list(ThreadPoolExecutor(2).map(one, ["annotate", "escalate"])),
                               "the agent evaluating your test copy twice, annotate and escalate")
    rows, decisions = {}, {}
    for mode, body in out:
        ws.render_decision(body, application=ctx.get_application(app_id))
        items = _evaluation_items(ctx, body["evaluation_id"])
        dec = next(i for i in items if i.get("is_decision"))
        decisions[mode] = dec
        rows[mode] = [dec.get("outcome"), dec.get("original_decision", "(none)"), dec.get("citation_check"),
                      ", ".join(dec.get("ungrounded_citations", [])), dec.get("test_injection", ""),
                      dec.get("escalation_reason", "(none)"), dec.get("ungrounded_month", "")]
    display(ws.styled_table(pd.DataFrame(rows, index=["outcome", "original_decision", "citation_check",
                                                      "ungrounded_citations", "test_injection", "escalation_reason",
                                                      "ungrounded_month"]).reset_index(names="on the decision item"),
                            caption="What the runtime recorded"))
    if plant:
        ws.plant_unsupported_citation(ctx)
    return decisions.get("annotate"), decisions.get("escalate")


def _scan_estimate(ctx):
    """Read units for one full Scan of the traces table, priced from a 2,000-item sample (Cell 2.2's
    question 5), kept for the session so Decision 4 can compare against it."""
    if _state.get("scan_ru") is None:
        t = ctx.dynamodb.Table(ctx.TRACES_TABLE)
        sample = t.scan(Limit=2000, ReturnConsumedCapacity="TOTAL")
        _state["scan_ru"] = round(sample["ConsumedCapacity"]["CapacityUnits"] / max(1, sample["Count"])
                                  * ws.trace_item_count(ctx))
    return _state["scan_ru"]


def show_ungrounded(ctx, query, params=None):
    """Cell 4.2: run and time your query, check its rows against the reference's (running the
    reference instead if they differ), then the planted case first, your copy, and the past denials,
    by policy; the answer's cost beside Decision 2's Scan; and how many of these denials sent a notice."""
    import pandas as pd
    from collections import Counter
    from agent import reference
    params = {**(params or {}), "ratio_rule": f"policy:{P_RATIOS}"}

    def timed(q):
        t0 = time.time()
        return ctx.neptune_query(q, params)["results"], time.time() - t0
    key = lambda rs: Counter((r.get("application"), r.get("policy"), r.get("cited_as")) for r in rs)
    want, want_s = timed(reference.UNGROUNDED)
    # Capped one row past the reference: without its WHERE NOT, the query returns every citation
    # (about two million rows), which is enough to know it isn't right yet.
    capped = query.rstrip().rstrip(";") + f"\nLIMIT {len(want) + 1}"
    try:
        rows, seconds = timed(capped)
    except Exception as e:
        rows, seconds = None, None
        print(f"❌ The query failed: {str(e)[:300]}")
    if rows is not None and key(rows) == key(want):
        print(f"✅ Your query matches the reference: {len(rows):,} citations no search returned.")
    else:
        if rows is not None and len(rows) > len(want):
            print(f"❌ Not yet: your query returns more than the reference's {len(want):,} rows."
                  + (" Without a WHERE NOT, it returns every citation, retrieved or not."
                     if "WHERE NOT" not in re.sub(r"//[^\n]*", "", query).upper() else ""))
        elif rows is not None:
            print(f"❌ Not yet: your query returned {len(rows):,} rows; the reference returns {len(want):,}.")
        print("   Showing the reference query's answer, so the rest of the page still works.\n")
        rows, seconds = want, want_s
    df = pd.DataFrame(rows)
    if df.empty or not (df["application"] == "LA-AUDIT-TEST").any():
        print("❌ LA-AUDIT-TEST isn't in these rows: its decision may not be in the graph yet. "
              "Run catch_up(\"plant\"), then this cell again.")
        return True
    print("✅ Caught LA-AUDIT-TEST: it cites HUD 4000.1 II.A.5.b, which no search in it returned.")
    if (df["application"] == "LA-TEST-00148").any():
        print("✅ Caught your annotate copy, LA-TEST-00148. Your escalate copy isn't here: it was escalated, not denied.")
    past = df[df["application"].str.startswith("HIST-")]
    by = past.groupby("policy")["application"].nunique().sort_values(ascending=False)
    n_past = past["application"].nunique()
    print(f"{n_past:,} past II.A.5.d denials cite a policy no search returned.")
    ws.bar_chart(list(by.index), list(by.values), "Past denials citing a policy no search returned, by policy",
                 unit="denials")
    scan = _scan_estimate(ctx)
    took = f" in {seconds:.1f} seconds" if seconds is not None else ""
    print(f"That's Decision 2's question 5, answered{took}, with no index and no Scan. In DynamoDB, no key "
          f"held it: Cell 2.2 priced it at about {scan:,} read units, about ${scan * RRU_PRICE:.3f}, plus join code.")
    notices = ctx.neptune_query("""MATCH (:Policy {`~id`: $ratio_rule})<-[:VIOLATED]-(d:Decision {outcome: 'deny'})
        -[:CITED_POLICY]->(p:Policy) WHERE NOT (d)-[:RETRIEVED_POLICY]->(p) AND d.application_id STARTS WITH 'HIST-'
        WITH DISTINCT d MATCH (n:Notice)-[:FOR]->(d) RETURN count(DISTINCT d) AS sent""",
        {"ratio_rule": f"policy:{P_RATIOS}"})["results"]
    if notices and notices[0]["sent"]:
        print(f"{notices[0]['sent']:,} of them sent an adverse action notice: those applicants were given reasons "
              "that rest on a rule the decision never read. Cell 4.2a follows a few of them to it.")
    return True


def planted_case(ctx):
    rows = ctx.neptune_query("""MATCH (:Application {id: 'LA-AUDIT-TEST'})-[:HAS_DECISION]->(d:Decision)
        RETURN id(d) AS decision, d.evaluation_id AS evaluation_id LIMIT 1""")["results"]
    if not rows:
        print("No planted case found: run Cell 4.1, or catch_up(\"plant\"), then this cell again.")
        return None
    items = _evaluation_items(ctx, rows[0]["evaluation_id"])
    dec = next(i for i in items if i.get("is_decision"))
    reason = dec.get("reasoning") or "; ".join(dec.get("adverse_action_reasons", []))
    print(f"LA-AUDIT-TEST's stated reason, from its decision item:\n  \"{reason}\"")
    return {"decision": rows[0]["decision"], "reason": reason}


def embed(ctx, text):
    """The text as a vector, with the Knowledge Base's own embedding model."""
    r = ctx.bedrock_runtime.invoke_model(modelId="amazon.titan-embed-text-v2:0",
                                         body=json.dumps({"inputText": text}))
    return json.loads(r["body"].read())["embedding"]


def inline(query, **vectors):
    """Neptune Analytics takes no parameters inside CALL, so a vector goes into the text."""
    for name, vec in vectors.items():
        query = query.replace(f"${name}", "[" + ",".join(f"{x:.6f}" for x in vec) + "]")
    return query


def show_closest(rows, reason):
    import pandas as pd
    from IPython.display import display
    df = pd.DataFrame(rows)
    if df.empty:
        print("No passages scored.")
        return True
    df["text"] = df["text"].str.slice(0, 160) + "..."
    display(ws.styled_table(df.head(8), caption="The cited policies' passages, by similarity to the planted reason"))
    print("Similarity measures how close a passage's words are to the stated reason, not whether its policy applies.")
    print("No search in this evaluation returned HUD 4000.1 II.A.5.b, so the record can't show the agent read the text it cites.")
    return True
