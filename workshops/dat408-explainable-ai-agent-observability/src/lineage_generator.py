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
"""lineage_generator.py — history v3: the lineage layer for DAT408's page 3.

A synthetic multi-agent build that records what each artifact took from what: amounts
(DERIVED_FROM) or employer identities (IDENTITY_FROM). It attaches to the seed-408
decisions from LINEAGE_START on and changes no outcome: it records exposure, not error.
The rules are docs/history-v3-rules.md. Deterministic: the same in every account.

Input: the lineage-input lines history_generator.py writes, one per decision in the window:
[n, timestamp, outcome, policies_violated, credit_score, back_end_dti, derogatory, short_employment].

Output (to S3, or a local folder in tests):
  graph/vertices/lineage-<label>-<part>.csv, graph/edges/lineage-<label>-<part>.csv
                      Neptune Analytics CSV, loaded after the base history
  lineage-athena/{nodes,edges}/part-<part>.csv
                      the same lineage as plain CSV, for Athena's recursive SQL (option C)
  fixtures/lineage-expected.json
                      every number page 3 prints, from an in-memory BFS over the same edges
"""
import csv
import gzip
import io
import json
import random
from array import array
from bisect import bisect_left, bisect_right
from collections import deque
from datetime import date, timedelta

SEED = "408:v3"
PART_ROWS = 500_000          # rows per CSV part, so no file is too large to build in memory
P_LTV, P_CREDIT, P_INCOME, P_RATIOS = ("HUD 4000.1 II.A.2.b", "HUD 4000.1 II.A.5.a",
                                       "HUD 4000.1 II.A.5.b", "HUD 4000.1 II.A.5.d")
HISTORY_END = date(2026, 9, 30)

# (component, version, live from). A version is live until the next one of its component.
VERSIONS = [
    ("doc-extract", "2.0.0", "2025-10-01"), ("doc-extract", "2.1.0", "2025-11-17"),
    ("doc-extract", "2.2.0", "2026-01-12"), ("doc-extract", "2.3.0", "2026-03-09"),
    ("doc-extract", "2.3.1", "2026-05-04"), ("doc-extract", "2.3.2", "2026-05-25"),
    ("doc-extract", "2.4.0", "2026-07-27"),
    ("credit-parse", "4.1.0", "2025-10-01"), ("credit-parse", "4.2.0", "2026-02-02"),
    ("credit-parse", "4.3.0", "2026-06-15"),
    ("avm-review", "1.6.0", "2025-10-01"), ("avm-review", "1.7.0", "2026-03-30"),
    ("avm-review", "1.8.0", "2026-08-03"),
    ("ratio-calc", "3.0.0", "2025-10-01"), ("ratio-calc", "3.1.0", "2026-04-20"),
    ("notice-writer", "1.2.0", "2025-10-01"),
]
MISREAD = "doc-extract:2.3.1"
EMPLOYERS = 20_000            # employer ranks 1..N, Zipf-sized
ZIPF_S = 1.07
APPRAISERS = 9_000
REAPPLY_RATE, REAPPLY_DAYS = 0.03, 120
IDENTITY_DAYS, REFRESH_DAYS = 180, 30     # a cached identity lives under 180 days, refreshed every 30
INCOME_TYPES = (("wage", 0.85), ("self", 0.10), ("fixed", 0.05))
REASON = {P_RATIOS: ("ratios", "debt-to-income"), P_LTV: ("collateral", "loan-to-value"),
          P_CREDIT: ("credit", "credit history"), P_INCOME: ("income", "length of employment")}
ATHENA_MAX_DEPTH = 10

# Node kinds, as small ints for the in-memory graph.
KINDS = ["version", "feed", "appraiser", "extraction", "employer_record", "income", "business_income",
         "ratios", "credit_report", "credit", "appraisal", "collateral", "decision", "notice"]
K = {k: i for i, k in enumerate(KINDS)}
LABELS = ["PRODUCED_BY", "DERIVED_FROM", "IDENTITY_FROM", "SIGNED_BY", "USED", "FOR", "RESTS_ON"]
L = {k: i for i, k in enumerate(LABELS)}
WALKS = {   # page 3's three walks: the edge labels each follows, inbound from the version
    "amounts": ["PRODUCED_BY", "DERIVED_FROM", "USED", "RESTS_ON"],
    "identities": ["PRODUCED_BY", "IDENTITY_FROM", "USED", "RESTS_ON"],
    "both": ["PRODUCED_BY", "DERIVED_FROM", "IDENTITY_FROM", "USED", "RESTS_ON"],
}

VERTEX_HEADERS = {
    "Version": ["~id", "~label", "component:String", "version:String", "name:String", "live_from:String"],
    "FeedBatch": ["~id", "~label", "day:String", "source:String"],
    "Appraiser": ["~id", "~label", "roster:String"],
    "Extraction": ["~id", "~label", "kind:String", "doc:String", "day:String", "model:String", "prompt:String",
                   "run:String"],
    "EmployerRecord": ["~id", "~label", "kind:String", "employer:String", "built:String", "built_from:String",
                       "builder:String", "identity_since:String"],
    "Result": ["~id", "~label", "kind:String", "day:String", "run:String", "model:String"],
    "Appraisal": ["~id", "~label", "kind:String", "day:String", "run:String", "appraiser:String"],
    "Notice": ["~id", "~label", "day:String"],
}
LABEL_OF = {"Version": "Version", "FeedBatch": "FeedBatch", "Appraiser": "Appraiser", "Extraction": "Artifact",
            "EmployerRecord": "Artifact", "Result": "Artifact", "Appraisal": "Artifact", "Notice": "Notice"}


def d_(s):
    return date.fromisoformat(s[:10])


class Parts:
    """CSV rows split into parts of PART_ROWS, each handed to `emit(name, bytes)` when full."""
    def __init__(self, name, header, emit):
        self.name, self.header, self.emit, self.part, self.rows = name, header, emit, 0, 0
        self._new()

    def _new(self):
        self.buf = io.StringIO()
        self.w = csv.writer(self.buf, lineterminator="\n")
        if self.header:
            self.w.writerow(self.header)
        self.n = 0

    def row(self, *vals):
        self.w.writerow(vals)
        self.n += 1
        self.rows += 1
        if self.n >= PART_ROWS:
            self.flush()

    def flush(self):
        if self.n:
            self.emit(f"{self.name}-{self.part:04d}.csv", self.buf.getvalue().encode())
            self.part += 1
        self._new()


def generate(lines, emit):
    """Simulate the lineage over `lines` (lineage-input rows) and hand each output file to
    emit(relative_path, bytes). Returns the expected answers (also emitted as JSON)."""
    rng = random.Random(SEED)
    lines = sorted(lines, key=lambda r: (r[1], r[0]))

    # --- outputs -------------------------------------------------------------------------
    vx = {k: Parts(f"graph/vertices/lineage-{k}", h, emit) for k, h in VERTEX_HEADERS.items()}
    ex_plain = Parts("graph/edges/lineage-plain", ["~from", "~to", "~label"], emit)
    ex_rests = Parts("graph/edges/lineage-RESTS_ON", ["~from", "~to", "~label", "reason:String"], emit)
    ath_nodes = Parts("lineage-athena/nodes/part", ["id", "label", "kind", "day", "outcome"], emit)
    ath_edges = Parts("lineage-athena/edges/part", ["src", "dst", "label"], emit)

    # --- the in-memory graph, for the expected answers -----------------------------------
    ids, kind, day_of, deny = {}, array("b"), array("i"), array("b")
    src, dst, lab = array("i"), array("i"), array("b")

    def node(vtype, nid, kd, day, *props, outcome=""):
        ids[nid] = len(kind)
        kind.append(K[kd])
        day_of.append(day.toordinal() if day else 0)
        deny.append(1 if outcome == "deny" else 0)
        if vtype:
            vx[vtype].row(nid, LABEL_OF[vtype], *props)
        ath_nodes.row(nid, LABEL_OF.get(vtype, "Decision"), kd, day.isoformat() if day else "", outcome)
        return nid

    def edge(a, b, label, reason=None):
        src.append(ids[a])
        dst.append(ids[b])
        lab.append(L[label])
        (ex_rests.row(a, b, label, reason) if reason else ex_plain.row(a, b, label))
        ath_edges.row(a, b, label)

    # --- versions, appraisers, employers ---------------------------------------------------
    by_comp, live = {}, {}
    for comp, ver, start in VERSIONS:
        by_comp.setdefault(comp, []).append((start, f"{comp}:{ver}"))
    for comp, vs in by_comp.items():
        for i, (start, key) in enumerate(vs):
            end = (d_(vs[i + 1][0]) - timedelta(days=1)) if i + 1 < len(vs) else HISTORY_END
            live[key] = (d_(start), end)
            node("Version", f"version:{key}", "version", d_(start), comp, key.split(":")[1],
                 f"{comp} {key.split(':')[1]}", start)

    comp_days = {c: [d_(s) for s, _ in vs] for c, vs in by_comp.items()}

    def version_on(comp, day):
        i = bisect_right(comp_days[comp], day) - 1
        return by_comp[comp][max(i, 0)][1]

    for a in range(1, APPRAISERS + 1):
        node("Appraiser", f"appraiser:A{a:05d}", "appraiser", None, "state roster")
    weights, acc = [], 0.0
    for r in range(1, EMPLOYERS + 1):
        acc += 1 / r ** ZIPF_S
        weights.append(acc)
    cover_rng = random.Random(SEED + ":evoe")
    covered = [False] + [cover_rng.random() < (0.98 if r <= 100 else 0.9 if r <= 1000 else 0.6 if r <= 5000 else 0.3)
                         for r in range(1, EMPLOYERS + 1)]

    feeds = set()

    def feed(day, source):
        nid = f"feed:{source}:{day.isoformat()}"
        if nid not in feeds:
            feeds.add(nid)
            node("FeedBatch", nid, "feed", day, day.isoformat(), source)
        return nid

    # --- the decisions, in time order -----------------------------------------------------
    emp_state = {}            # employer rank -> [identity_since, last_built, record id, root extraction]
    doc_runs, doc_days = [], []   # earlier decisions that read documents, for re-applications
    called = {}               # decision id -> the doc-extract version its own run called
    root_of_record = {}       # employer record id -> the extraction its identity came from
    rests_on_root = {}        # root extraction -> [decisions, after the fix]
    for n, ts, outcome, violated, score, back, derogatory, short_emp in lines:
        day = d_(ts)
        run = f"hist-{n:07d}"
        dec = f"decision:{run}_decision"
        ids[dec] = len(kind)                    # the decision node already exists in the base load
        kind.append(K["decision"])
        day_of.append(day.toordinal())
        deny.append(1 if outcome == "deny" else 0)
        ath_nodes.row(dec, "Decision", "decision", day.isoformat(), outcome)

        reuse = None
        if rng.random() < REAPPLY_RATE and doc_runs:
            lo = bisect_left(doc_days, (day - timedelta(days=REAPPLY_DAYS)).toordinal())
            if lo < len(doc_runs):
                reuse = doc_runs[rng.randrange(lo, len(doc_runs))]
        income_type = reuse["type"] if reuse else rng.choices([t for t, _ in INCOME_TYPES],
                                                              weights=[w for _, w in INCOME_TYPES])[0]
        employer = reuse["employer"] if reuse else (
            bisect_left(weights, rng.random() * weights[-1]) + 1 if income_type == "wage" else None)
        dx = version_on("doc-extract", day)

        def extract(doc):
            nid = node("Extraction", f"art:extraction:{run}:{doc}", "extraction", day, "extraction", doc,
                       day.isoformat(), f"doc-extract@{dx.split(':')[1]}", "extract-prompt@v4", run)
            edge(nid, f"version:{dx}", "PRODUCED_BY")
            called[dec] = dx
            return nid

        income = node("Result", f"art:income:{run}", "income", day, "income", day.isoformat(), run, "")
        extractions = []
        if income_type == "wage" and covered[employer] and not reuse:
            edge(income, feed(day, "evoe"), "DERIVED_FROM")
            edge(income, feed(day, "evoe"), "IDENTITY_FROM")
        elif income_type == "wage":
            if reuse:
                extractions = reuse["extractions"]
            else:
                docs = ["paystubs", "w2s"] if rng.random() < 0.6 else ["wvoe"]
                extractions = [extract(doc) for doc in docs]
            for x in extractions:
                edge(income, x, "DERIVED_FROM")
            st = emp_state.get(employer)
            if st is None or (day - st[0]).days >= IDENTITY_DAYS:
                frm = next((x for x in extractions if x.endswith(":wvoe")), extractions[0])
                rec = node("EmployerRecord", f"art:employer_record:E{employer:06d}:{day.isoformat()}",
                           "employer_record", day, "employer_record", f"E{employer:06d}", day.isoformat(),
                           frm, dec, day.isoformat())
                edge(rec, frm, "IDENTITY_FROM")
                st = emp_state[employer] = [day, day, rec, frm]
                root_of_record[rec] = frm
            while (day - st[1]).days >= REFRESH_DAYS:     # the monthly refreshes up to today
                st[1] = st[1] + timedelta(days=REFRESH_DAYS)
                rec = node("EmployerRecord", f"art:employer_record:E{employer:06d}:{st[1].isoformat()}",
                           "employer_record", st[1], "employer_record", f"E{employer:06d}", st[1].isoformat(),
                           st[2], "refresh", st[0].isoformat())
                edge(rec, st[2], "IDENTITY_FROM")
                root_of_record[rec] = st[3]
                st[2] = rec
            edge(income, st[2], "IDENTITY_FROM")
            r = rests_on_root.setdefault(st[3], [0, 0, st[2] if st[2] else ""])
            r[0] += 1
            r[1] += day > live[MISREAD][1]
        elif income_type == "self":
            extractions = reuse["extractions"] if reuse else [extract("pnl"), extract("tax_returns")]
            biz = node("Result", f"art:business_income:{run}", "business_income", day, "business_income",
                       day.isoformat(), run, "")
            for x in extractions:
                edge(biz, x, "DERIVED_FROM")
            edge(income, biz, "DERIVED_FROM")
        else:
            extractions = reuse["extractions"] if reuse else [extract("award_letter")]
            for x in extractions:
                edge(income, x, "DERIVED_FROM")
        if extractions and not reuse:
            doc_runs.append({"type": income_type, "employer": employer, "extractions": extractions})
            doc_days.append(day.toordinal())

        report = node("Result", f"art:credit_report:{run}", "credit_report", day, "credit_report",
                      day.isoformat(), run, "")
        edge(report, feed(day, "bureau"), "DERIVED_FROM")
        credit = node("Result", f"art:credit:{run}", "credit", day, "credit", day.isoformat(), run,
                      version_on("credit-parse", day))
        edge(credit, report, "DERIVED_FROM")
        edge(credit, f"version:{version_on('credit-parse', day)}", "PRODUCED_BY")
        appraiser = f"appraiser:A{rng.randrange(1, APPRAISERS + 1):05d}"
        appraisal = node("Appraisal", f"art:appraisal:{run}", "appraisal", day, "appraisal", day.isoformat(),
                         run, appraiser)
        edge(appraisal, appraiser, "SIGNED_BY")
        collateral = node("Result", f"art:collateral:{run}", "collateral", day, "collateral", day.isoformat(),
                          run, version_on("avm-review", day))
        edge(collateral, appraisal, "DERIVED_FROM")
        edge(collateral, f"version:{version_on('avm-review', day)}", "PRODUCED_BY")
        ratios = node("Result", f"art:ratios:{run}", "ratios", day, "ratios", day.isoformat(), run,
                      version_on("ratio-calc", day))
        edge(ratios, income, "DERIVED_FROM")
        edge(ratios, credit, "DERIVED_FROM")
        edge(ratios, f"version:{version_on('ratio-calc', day)}", "PRODUCED_BY")
        for art in (income, ratios, credit, collateral):
            edge(dec, art, "USED")
        if outcome == "deny":
            notice = node("Notice", f"notice:{run}", "notice", day, day.isoformat())
            edge(notice, dec, "FOR")
            edge(notice, f"version:{version_on('notice-writer', day)}", "PRODUCED_BY")
            arts = {"ratios": ratios, "collateral": collateral, "credit": credit, "income": income}
            for p in violated:
                if p in REASON:
                    which, reason = REASON[p]
                    edge(notice, arts[which], "RESTS_ON", reason)

    for p in list(vx.values()) + [ex_plain, ex_rests, ath_nodes, ath_edges]:
        p.flush()
    expected = answers(kind, day_of, deny, src, dst, lab, ids, live, called, lines)
    # The busiest employer identity built from a document 2.3.1 read: the decisions whose
    # employment check used a record carrying it (counted as the simulation ran).
    mis = [(c[0], c[1], x) for x, c in rests_on_root.items()
           if called.get("decision:" + x.split(":")[2] + "_decision") == MISREAD]
    if mis:
        top = max(mis)
        expected["busiest_identity"] = {"built_from": top[2], "decisions": top[0], "after_fix": top[1],
                                        "identities_from_misread": len(mis)}
    emit("fixtures/lineage-expected.json", json.dumps(expected, indent=1).encode())
    return expected


def answers(kind, day_of, deny, src, dst, lab, ids, live, called, lines):
    """BFS over the in-memory graph: every number page 3 prints."""
    n = len(kind)
    # Inbound adjacency (CSR): for an edge a -L-> b, b's inbound list holds (a, L).
    order = sorted(range(len(src)), key=dst.__getitem__)
    start = array("i", [0]) * (n + 1)
    for i in order:
        start[dst[i] + 1] += 1
    for v in range(n):
        start[v + 1] += start[v]
    nb_src, nb_lab = array("i", [src[i] for i in order]), array("b", [lab[i] for i in order])

    def bfs(root, labels):
        allowed = {L[x] for x in labels}
        level = {root: 0}
        q = deque([root])
        while q:
            v = q.popleft()
            for j in range(start[v], start[v + 1]):
                u = nb_src[j]
                if nb_lab[j] in allowed and u not in level:
                    level[u] = level[v] + 1
                    q.append(u)
        return level

    out = {"source": f"version:{MISREAD}", "walks": {}, "versions": {}}
    vmin, vmax = live[MISREAD]
    fixed = vmax.toordinal()
    for key in sorted(k for k in live if k.startswith("doc-extract:")):
        root = ids[f"version:{key}"]
        end = live[key][1].toordinal()
        res = {}
        for walk, labels in WALKS.items():
            level = bfs(root, labels)
            decs = [v for v in level if kind[v] == K["decision"]]
            notes = [v for v in level if kind[v] == K["notice"]]
            res[walk] = {"decisions": len(decs), "after_fix": sum(1 for v in decs if day_of[v] > end),
                         "denied": sum(deny[v] for v in decs), "notices": len(notes),
                         "deepest_decision": max((level[v] for v in decs), default=0),
                         "deepest": max(level.values()), "nodes": len(level),
                         "decisions_by_hop": {str(h): c for h, c in sorted(
                             _count(level[v] for v in decs).items())}}
            assert res[walk]["deepest"] <= ATHENA_MAX_DEPTH, (key, walk, res[walk]["deepest"])
        res["one_hop"] = sum(1 for d, v in called.items() if v == key)
        res["live"] = [live[key][0].isoformat(), live[key][1].isoformat()]
        out["versions"][key] = res
    m = out["versions"][MISREAD]
    window = [r for r in lines if vmin.isoformat() <= r[1][:10] <= vmax.isoformat()]
    out["walks"] = {w: m[w] for w in WALKS}
    out["one_hop"] = m["one_hop"]
    out["date_filter"] = {"decisions": len(window),
                          "never_used_it": len(window) - sum(1 for r in window if called.get(
                              f"decision:hist-{r[0]:07d}_decision") == MISREAD)}
    out["both_routes"] = {"after_fix": m["both"]["after_fix"],
                          "amounts_after_fix": m["amounts"]["after_fix"],
                          "identities_after_fix": m["identities"]["after_fix"]}
    out["fixed_on"] = (vmax + timedelta(days=1)).isoformat()
    return out


def _count(xs):
    c = {}
    for x in xs:
        c[x] = c.get(x, 0) + 1
    return c


def handler(event, context):
    """Lambda entry point: {"bucket", "prefix"}. Reads every lineage-input shard, writes the lineage."""
    import boto3
    s3 = boto3.client("s3")
    b, pre = event["bucket"], event["prefix"].rstrip("/")
    lines = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=b, Prefix=f"{pre}/lineage-input/"):
        for o in page.get("Contents", []):
            body = gzip.decompress(s3.get_object(Bucket=b, Key=o["Key"])["Body"].read()).decode()
            lines += [json.loads(x) for x in body.splitlines() if x]
    written = []

    def emit(rel, body):
        s3.put_object(Bucket=b, Key=f"{pre}/{rel}", Body=body)
        written.append(rel)
    expected = generate(lines, emit)
    return {"decisions": len(lines), "files": len(written),
            "decisions_resting_on_misread": expected["walks"]["both"]["decisions"]}
