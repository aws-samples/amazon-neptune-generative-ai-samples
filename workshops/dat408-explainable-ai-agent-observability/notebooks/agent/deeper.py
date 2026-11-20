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
"""deeper.py — the checks for 02 Go deeper.ipynb's exercises. Each check runs your answer, compares
it with the reference answer on the same data, and saves it to solution/ when it matches; the
MCP server then runs your file instead of the reference."""
import json
import time
import uuid

from agent import reference
from agent import workshop as ws
from agent.session import _state


def _ctx():
    return _state["ctx"]


def _rows(rows):
    return sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)


def check_query(name, query, params, save_as=None, blank="✏️ YOUR"):
    """Run your query and the reference's with the same parameters; save yours if they match."""
    ctx = _ctx()
    if blank in query:
        print("Fill in the line marked ✏️, then run this cell again.")
        return None
    t0 = time.time()
    try:
        got = ctx.neptune_query(query, params)["results"]
    except Exception as e:
        print(f"❌ The query failed: {str(e)[:300]}")
        return None
    secs = time.time() - t0
    want = ctx.neptune_query(getattr(reference, name), params)["results"]
    if _rows(got) != _rows(want):
        print(f"❌ Not yet: your query returned {len(got):,} rows; the reference returns {len(want):,}.")
        if got:
            print("   Your first row:", got[0])
        print("   The reference's first row:", want[0] if want else "(none)")
        return None
    print(f"✅ Your query matches the reference: {len(got):,} rows in {secs:.1f} s.")
    if save_as:
        ws.save_answer(save_as, query)
    return None


def check_function(name, fn, *args, save_as=None, key=None):
    """Call your function and the reference's with the same arguments; save yours if they match."""
    got, want = fn(*args), getattr(reference, name)(*args)
    norm = key or (lambda r: r)
    if norm(got) != norm(want):
        print(f"❌ Not yet: your {fn.__name__} returned something different from the reference's.")
        return None
    print(f"✅ Your {fn.__name__} returns the same as the reference.")
    if save_as:
        ws.save_answer(save_as, fn)
    return None


def check_get_evidence(fn, eval_id):
    """G.1: the evaluation's items, header and steps, in sort-key order, with no sorting in Python."""
    if fn(eval_id) is None:
        print("Write the Query, then run this cell again.")
        return None
    key = lambda items: [(i["SK"], i.get("observation_sha256")) for i in items]
    return check_function("get_evidence", fn, eval_id, save_as="get_evidence", key=key)


def check_policy_months(fn, policy="HUD 4000.1 II.A.5.d"):
    """G.3: one policy's monthly items, with the read units it cost."""
    r = fn(policy)
    if not r or "ConsumedCapacity" not in r:
        print("❌ Return the Query's response, with ReturnConsumedCapacity='TOTAL', so you can see the cost.")
        return None
    key = lambda r: [(i["SK"], int(i["decisions_failing"])) for i in r["Items"]]
    check_function("policy_months", fn, policy, save_as="policy_months", key=key)
    print(f"   {len(r['Items'])} months for {r['ConsumedCapacity']['CapacityUnits']} read units.")
    return None


# --- G.4 and G.5: option B's stream transform, on a throwaway copy ---------------------------
FOOTPRINT = """
MATCH (d:Decision {`~id`: $decision})
OPTIONAL MATCH (d)-[r]->()
RETURN type(r) AS rel, count(r) AS n ORDER BY rel
"""


def _copy_records(eval_id, copy_id):
    """The evaluation's stream records, renamed to a throwaway evaluation and application."""
    records = ws._stream_records(_ctx(), eval_id)
    out = []
    for r in records:
        img = json.loads(json.dumps(r["dynamodb"]["NewImage"]).replace(eval_id, copy_id))
        img["application_id"] = {"S": f"LA-COPY-{copy_id[-6:]}"}
        out.append(img)
    return out


def _footprint(decision_gid, query=FOOTPRINT):
    return {r["rel"]: r["n"] for r in _ctx().neptune_query(query, {"decision": decision_gid})["results"] if r["rel"]}


def _delete(copy_id):
    _ctx().neptune_query("""MATCH (d:Decision {`~id`: $d}) OPTIONAL MATCH (a:Application)-[:HAS_DECISION]->(d)
        DETACH DELETE d, a""", {"d": f"decision:{copy_id}_decision"})


def test_transform(project_step, eval_id):
    """G.4: your project_step on a throwaway copy of an evaluation's records: delivered once,
    twice, and in reverse. Each must leave the reference transform's footprint."""
    import pandas as pd
    from IPython.display import display
    from agent import transform as ref
    ids = [f"gd-{uuid.uuid4().hex[:6]}" for _ in range(3)]
    try:
        records = {k: _copy_records(eval_id, k) for k in ids}
        for img in records[ids[0]]:
            ref.project_step(img)                                  # the reference, once
        want = _footprint(f"decision:{ids[0]}_decision")
        for img in records[ids[1]] * 2:                          # yours, twice
            project_step(img)
        twice = _footprint(f"decision:{ids[1]}_decision")
        for img in reversed(records[ids[2]]):                    # yours, in reverse
            project_step(img)
        reverse = _footprint(f"decision:{ids[2]}_decision")
        # G.4 builds the decision's tools, retrievals, citations and failures; the reference
        # also links passages and bands, which this test leaves out.
        scope = {"USED_TOOL", "RETRIEVED_POLICY", "CITED_POLICY", "VIOLATED"}
        want, twice, reverse = ({k: v for k, v in f.items() if k in scope} for f in (want, twice, reverse))
        rels = sorted(set(want) | set(twice) | set(reverse))
        display(ws.styled_table(pd.DataFrame({"relationship": rels, "reference": [want.get(r, 0) for r in rels],
                                              "yours, delivered twice": [twice.get(r, 0) for r in rels],
                                              "yours, in reverse": [reverse.get(r, 0) for r in rels]}),
                                caption="One evaluation's decision in the graph, by relationship"))
    finally:
        for k in ids:
            _delete(k)
    if twice == want and reverse == want:
        print("✅ Twice and in reverse, your transform builds exactly what the reference does.")
    else:
        print("❌ Not the same: check each MERGE's id, and that every edge is MERGEd, not CREATEd.")
    return None


def prove_replay_safe(footprint_query, eval_id):
    """G.5: your footprint query, then the same records delivered to the deployed transform again;
    the footprint must not change. Then a poison record, which only it may fail."""
    ctx = _ctx()
    if "✏️" in footprint_query:
        print("Write the footprint query, then run this cell again.")
        return None
    dec = f"decision:{eval_id}_decision"
    before = _footprint(dec, footprint_query)
    if not before:
        print("❌ Your footprint returned nothing for this decision: return rel and n, one row per relationship type.")
        return None
    failures = ws.replay_evaluation(ctx, eval_id)
    after = _footprint(dec, footprint_query)
    print(f"Before the replay: {before}\nAfter:            {after}")
    if failures or after != before:
        print(f"❌ The replay changed the graph or failed: {failures}")
        return None
    print("✅ Delivered again, nothing changed: every write MERGEd onto what was there.")
    reported, poison = ws.send_poison_record(ctx, eval_id)
    ok = [f.get("itemIdentifier") for f in reported] == [poison]
    print(("✅ " if ok else "❌ ") + f"A malformed record in the same batch was reported alone: {reported}")
    ws.save_answer("footprint", footprint_query)
    return None
