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
"""history_generator.py — deterministic historical decision evidence for DAT408.

Generates N past FHA purchase-loan evaluations, decided by the same HUD 4000.1
rules the live agent retrieves (credit-score eligibility, LTV limits by credit
score, manual-underwriting qualifying ratios and compensating factors), cited
with real policy ids and the HUD edition / eCFR date in force on each decision
date. Runs at deploy time as a Lambda fan-out: shard k of K is a pure function
of (seed, k, K), so every account gets identical data.

Each shard writes three artifacts to S3:
  ddb/shard-<k>.json.gz     DynamoDB JSON for import-from-S3 into the traces table
                            (a retrieval step and a decision step per evaluation,
                            same item shape the live agent writes)
  graph/vertices|edges/<k>-*.csv
                            Neptune Analytics CSV for neptune.load, in option B's shape:
                            what decisions share (Application, Decision, Policy, Band),
                            no Step or Evidence nodes; steps stay in DynamoDB
  lineage-input/shard-<k>.json.gz
                            one line per decision inside the lineage window, for
                            lineage_generator.py (history v3)
Shared nodes (policies, tools, bands) are written once by shard 0.
"""
import csv
import gzip
import io
import json
import random
from datetime import date, datetime, timedelta, timezone

# Real HUD 4000.1 editions (issue dates from HUD's handbook archive) and the
# current Update 18. A decision cites the edition in force on its date.
HUD_EDITIONS = ["2019-10-24", "2019-12-16", "2020-11-18", "2021-04-19", "2021-07-20",
                "2021-10-26", "2021-11-09", "2022-06-29", "2023-01-18", "2023-08-09",
                "2023-10-31", "2024-05-20", "2025-01-10", "2025-08-13", "2026-08-12"]
HISTORY_START = date(2019, 10, 24)
HISTORY_END = date(2026, 9, 30)

P_ELIGIBILITY = "HUD 4000.1 II.A.1.b"
P_LTV = "HUD 4000.1 II.A.2.b"
P_CREDIT = "HUD 4000.1 II.A.5.a"
P_INCOME = "HUD 4000.1 II.A.5.b"
P_RATIOS = "HUD 4000.1 II.A.5.d"
P_ADVERSE = "12 CFR 1002.9"
P_ATR = "12 CFR 1026.43"
POLICIES = [P_ELIGIBILITY, P_LTV, P_CREDIT, P_INCOME, P_RATIOS, P_ADVERSE, P_ATR, "12 CFR 1002.12"]

# Bands follow the HUD limits, which are "at most" values: a DTI of exactly 43%
# or an LTV of exactly 96.5% is within the limit, so ratio bands include their upper
# bound (dti:43-47 means 43 < DTI <= 47). Credit-score bands are whole-number ranges.
CREDIT_BANDS = [(500, 579), (580, 619), (620, 679), (680, 739), (740, 850)]
DTI_BANDS = [(0, 43), (43, 47), (47, 50), (50, 100)]
LTV_BANDS = [(0, 80), (80, 90), (90, 96.5), (96.5, 200)]
GENERATOR_VERSION = "4"   # bump whenever generated data changes, so deploys regenerate
LINEAGE_START = date(2025, 10, 1)   # history v3's lineage covers decisions from this day on
TOOLS = ["pull_credit_report", "verify_income", "calculate_dti", "evaluate_collateral", "retrieve_lending_policy"]

UNGROUNDED_RATE = 0.012   # share of decisions that cite one policy they never retrieved


def gid(kind, key):
    """Neptune vertex ~id. Stable, so shards and live writes agree."""
    return f"{kind}:{key}"


def band(value, bands, prefix, whole_numbers=False):
    for lo, hi in bands:
        inside = (lo <= value <= hi) if whole_numbers else (lo < value <= hi or (lo == 0 and value == 0))
        if inside:
            return f"{prefix}:{lo}-{hi}"
    return f"{prefix}:{bands[-1][0]}-{bands[-1][1]}"


def version_on(policy, day):
    if policy.startswith("HUD"):
        edition = max(e for e in HUD_EDITIONS if e <= day.isoformat())
        return f"edition issued {edition}"
    return f"as in force on {day.isoformat()}"


def decide(rng):
    """One application and its HUD 4000.1 manual-underwriting outcome."""
    score = int(min(850, max(500, rng.gauss(680, 60))))
    max_ltv = 90.0 if score < 580 else 96.5
    ltv = 96.5 if rng.random() < 0.55 else round(rng.uniform(60, 96.5), 1)
    if rng.random() < 0.04:
        ltv = round(rng.uniform(max_ltv + 0.1, 100), 1)          # over the limit
    back = round(min(65, max(15, rng.gauss(40, 7))), 1)
    front = round(back * rng.uniform(0.6, 0.8), 1)
    factors = rng.choices([0, 1, 2], weights=[50, 30, 20])[0]
    derogatory = rng.random() < (0.08 if score < 620 else 0.02)
    short_employment = rng.random() < 0.03

    violated, escalate = [], False
    if ltv > max_ltv:
        violated.append(P_LTV)
    limit = 43 if score < 580 or factors == 0 else (47 if factors == 1 else 50)
    if back > limit:
        if back <= 50 and score >= 580 and factors < 2 and rng.random() < 0.5:
            escalate = True                                       # factors may exist; a human must verify
        else:
            violated.append(P_RATIOS)
    if derogatory and rng.random() < 0.5:
        violated.append(P_CREDIT)
    if short_employment and rng.random() < 0.5:
        violated.append(P_INCOME)

    outcome = "deny" if violated else ("escalate" if escalate else "approve")
    cited = [P_ELIGIBILITY, P_LTV, P_RATIOS]
    if derogatory:
        cited.append(P_CREDIT)
    if short_employment:
        cited.append(P_INCOME)
    if outcome == "deny":
        cited.append(P_ADVERSE)
    if rng.random() < 0.3:
        cited.append(P_ATR)
    retrieved = list(cited)
    if rng.random() < UNGROUNDED_RATE:
        retrieved.remove(rng.choice([p for p in cited if p != P_ELIGIBILITY]))  # cited from memory
    return {"score": score, "ltv": ltv, "front": front, "back": back, "factors": factors,
            "outcome": outcome, "cited": cited, "violated": violated, "retrieved": retrieved,
            "derogatory": derogatory, "short_employment": short_employment}


def ddb_item(fields):
    """Python dict -> DynamoDB JSON attribute map."""
    def enc(v):
        if isinstance(v, bool):
            return {"BOOL": v}
        if isinstance(v, (int, float)):
            return {"N": str(v)}
        if isinstance(v, list):
            return {"L": [enc(x) for x in v]}
        if isinstance(v, dict):
            return {"M": {k: enc(x) for k, x in v.items()}}
        return {"S": str(v)}
    return {k: enc(v) for k, v in fields.items()}


class Csv:
    def __init__(self, header):
        self.buf = io.StringIO()
        self.w = csv.writer(self.buf, lineterminator="\n")
        self.w.writerow(header)
        self.width = len(header)

    def row(self, *vals):
        assert len(vals) == self.width
        self.w.writerow(vals)

    def bytes(self):
        return self.buf.getvalue().encode()


# One CSV per node / edge type, each with only its own columns: Neptune Analytics
# stores an empty field as a real (empty-string) property, so shared wide files
# would give every node every property.
VERTEX_HEADERS = {
    "Application": ["~id", "~label", "id:String", "application_id:String", "historical:Bool"],
    "Decision": ["~id", "~label", "id:String", "application_id:String", "outcome:String", "historical:Bool",
                 "day:String", "day_short:String", "compensating_factors:Int"],
    "Policy": ["~id", "~label", "id:String"],
    "Tool": ["~id", "~label", "name:String"],
    "Band": ["~id", "~label", "id:String"],
}
EDGE_HEADERS = {
    "plain": ["~from", "~to", "~label"],
    # The edition the decision read is on the edge: `issued` is the HUD edition's issue date
    # (or, for a regulation, the date it was read), `version` its full text.
    "RETRIEVED_POLICY": ["~from", "~to", "~label", "issued:String", "version:String"],
    "CITED_POLICY": ["~from", "~to", "~label", "reference:String"],
}


def shared_vertices():
    """Policies, the retrieval tool and applicant bands: written once (shard 0)."""
    out = {lbl: Csv(VERTEX_HEADERS[lbl]) for lbl in ("Policy", "Tool", "Band")}
    for p in POLICIES:
        out["Policy"].row(gid("policy", p), "Policy", p)
    for tool in TOOLS:
        out["Tool"].row(gid("tool", tool), "Tool", tool)
    for prefix, bands in (("credit", CREDIT_BANDS), ("dti", DTI_BANDS), ("ltv", LTV_BANDS)):
        for lo, hi in bands:
            out["Band"].row(gid("band", f"{prefix}:{lo}-{hi}"), "Band", f"{prefix}:{lo}-{hi}")
    return {f"shared-vertices-{lbl}.csv": c.bytes() for lbl, c in out.items()}


def issued_on(policy, day):
    """The issue date of the edition a decision read: HUD's edition, or the day a regulation was read."""
    if policy.startswith("HUD"):
        return max(e for e in HUD_EDITIONS if e <= day.isoformat())
    return day.isoformat()


def generate_shard(k, shards, total, seed=408):
    """Return (ddb_json_gz_bytes, {relative_path: csv_bytes}, partial aggregates, lineage
    input lines) for shard k."""
    per = -(-total // shards)
    first, last = k * per, min(total, (k + 1) * per)
    rng = random.Random(f"{seed}:{k}")
    span = (HISTORY_END - HISTORY_START).days
    ddb = io.BytesIO()
    gz = gzip.GzipFile(fileobj=ddb, mode="wb")
    agg = {}   # (policy, "YYYY-MM") -> [decisions citing, decisions failing]
    lineage = []
    vx = {lbl: Csv(h) for lbl, h in VERTEX_HEADERS.items() if lbl not in ('Policy', 'Tool', 'Band')}
    ex = {lbl: Csv(h) for lbl, h in EDGE_HEADERS.items()}
    for n in range(first, last):
        d = decide(rng)
        day = HISTORY_START + timedelta(days=rng.randrange(span))
        ts = datetime(day.year, day.month, day.day, rng.randrange(8, 18), rng.randrange(60),
                      tzinfo=timezone.utc).isoformat()
        app_id, eval_id = f"HIST-{n:07d}", f"hist-{n:07d}"
        versions = {p: version_on(p, day) for p in d["retrieved"]}
        bands = {"credit_band": band(d["score"], CREDIT_BANDS, "credit", whole_numbers=True),
                 "dti_band": band(d["back"], DTI_BANDS, "dti"),
                 "ltv_band": band(d["ltv"], LTV_BANDS, "ltv"), "loan_program": "FHA 203(b)"}
        common = {"PK": f"EVAL#{eval_id}", "evaluation_id": eval_id, "application_id": app_id,
                  "step_timestamp": ts, "historical": True}
        retrieve = {**common, "SK": "STEP#000", "step_num": 0, "action": "retrieve_lending_policy",
                    "is_decision": False, "thought": "Retrieve the policies that apply.",
                    "action_input": json.dumps({"query": "FHA purchase eligibility, LTV and qualifying ratios"}),
                    "observation_summary": json.dumps({"retrieved": d["retrieved"]}),
                    "retrieved_policy_ids": d["retrieved"], "retrieved_policy_versions": versions}
        decision = {**common, "SK": "STEP#001", "step_num": 1, "action": "FINAL_DECISION",
                    "is_decision": True, "thought": f"Final decision: {d['outcome']}", "outcome": d["outcome"],
                    "policies_cited": d["cited"], "policies_violated": d["violated"],
                    "credit_score": d["score"], "ltv_pct": d["ltv"], "front_end_dti_pct": d["front"],
                    "back_end_dti_pct": d["back"], "compensating_factors": d["factors"], **bands}
        for item in (retrieve, decision):
            gz.write((json.dumps({"Item": ddb_item(item)}) + "\n").encode())
        month = day.strftime("%Y-%m")
        for p in d["cited"]:
            agg.setdefault((p, month), [0, 0])[0] += 1
        for p in d["violated"]:
            agg.setdefault((p, month), [0, 0])[1] += 1

        # Option B: what decisions share. The decision links to its application, the
        # policies it retrieved (edition on the edge), cited and failed, and its bands.
        a, dec = gid("app", app_id), gid("decision", f"{eval_id}_decision")
        vx["Application"].row(a, "Application", app_id, app_id, "true")
        vx["Decision"].row(dec, "Decision", f"{eval_id}_decision", app_id, d["outcome"], "true",
                           day.isoformat(), f"{day:%b} {day.day}", d["factors"])
        ex["plain"].row(a, dec, "HAS_DECISION")
        for p in d["retrieved"]:
            ex["RETRIEVED_POLICY"].row(dec, gid("policy", p), "RETRIEVED_POLICY", issued_on(p, day), versions[p])
        for p in d["cited"]:
            ex["CITED_POLICY"].row(dec, gid("policy", p), "CITED_POLICY", p)
        for p in d["violated"]:
            ex["plain"].row(dec, gid("policy", p), "VIOLATED")
        for b_ in ("credit_band", "dti_band", "ltv_band"):
            ex["plain"].row(dec, gid("band", bands[b_]), "IN_BAND")
        if day >= LINEAGE_START:
            lineage.append([n, ts, d["outcome"], d["violated"], d["score"], d["back"], d["derogatory"],
                            d["short_employment"]])
    gz.close()
    files = {f"vertices/{k:04d}-{lbl}.csv": c.bytes() for lbl, c in vx.items()}
    files.update({f"edges/{k:04d}-{lbl}.csv": c.bytes() for lbl, c in ex.items()})
    return ddb.getvalue(), files, agg, lineage


def handler(event, context):
    """Lambda entry point: {"bucket", "prefix", "shard", "shards", "total"}."""
    import boto3
    s3 = boto3.client("s3")
    b, pre = event["bucket"], event["prefix"].rstrip("/")
    k, shards, total = event["shard"], event["shards"], event["total"]
    ddb, files, agg, lineage = generate_shard(k, shards, total)
    s3.put_object(Bucket=b, Key=f"{pre}/ddb/shard-{k:04d}.json.gz", Body=ddb)
    s3.put_object(Bucket=b, Key=f"{pre}/lineage-input/shard-{k:04d}.json.gz",
                  Body=gzip.compress("\n".join(json.dumps(x) for x in lineage).encode()))
    if k == 0:
        files.update({f"vertices/{name}": body for name, body in shared_vertices().items()})
    for rel, body in files.items():
        s3.put_object(Bucket=b, Key=f"{pre}/graph/{rel}", Body=body)
    return {"shard": k, "ddb_bytes": len(ddb), "graph_bytes": sum(len(x) for x in files.values()),
            "aggregates": [[p, m, c, f] for (p, m), (c, f) in agg.items()]}


def aggregate_items(partials):
    """Sum shard partials into one DynamoDB JSON line per (policy, month):
    PK = POLICY#<policy id>, SK = MONTH#<yyyy-mm>. This is the precomputed
    "which policies drive denials" access pattern, written alongside the
    evidence so a single Query answers it; the live runtime keeps it current."""
    total = {}
    for rows in partials:
        for p, m, c, f in rows:
            t = total.setdefault((p, m), [0, 0])
            t[0] += c
            t[1] += f
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        for (p, m), (c, f) in sorted(total.items()):
            gz.write((json.dumps({"Item": ddb_item({
                "PK": f"POLICY#{p}", "SK": f"MONTH#{m}", "policy_id": p, "month": m,
                "decisions_citing": c, "decisions_failing": f})}) + "\n").encode())
    return buf.getvalue(), len(total)
