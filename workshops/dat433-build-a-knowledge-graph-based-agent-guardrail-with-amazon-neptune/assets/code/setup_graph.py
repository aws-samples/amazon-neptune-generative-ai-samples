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
setup_graph.py

Loads the AnyCompany supplier knowledge graph into Amazon Neptune using the
**Neptune bulk loader** (the production path for large graphs).

Pipeline:
    generate CSVs  ->  upload to S3  ->  POST /loader  ->  poll until COMPLETED

Why the bulk loader and not Gremlin inserts: this graph is ~120k vertices and
~1.33M edges. Inserting that with individual addV/addE calls would take hours;
the bulk loader ingests it in minutes and is what you would use in production.

Schema
------
Vertices : Supplier, Company, Product, Region, Certification, SanctionsList
Edges    : APPROVED_FOR   (Supplier -> Product,  approval_status/level/expiry)
           OPERATES_IN    (Supplier -> Region)
           OWNED_BY       (Supplier -> Company, Company -> Company)
           SANCTIONED_BY  (Company  -> SanctionsList)
           REQUIRES_CERT  (Product/Region -> Certification)
           HOLDS_CERT     (Supplier -> Certification, cert_status/expiry)

Usage (in the notebook):
    from setup_graph import bulk_load, wait_for_load, graph_summary
    load_id = bulk_load(bucket="my-bucket", prefix="guardrail/neptune_data",
                        iam_role_arn=ROLE, region="us-east-1")
    wait_for_load(load_id)
    graph_summary(g)
"""

import json
import os
import time
import urllib.request

import boto3

from generate_dataset import generate

# ── Bulk load ─────────────────────────────────────────────────────────────────

CSV_FILES = [
    "v_supplier.csv", "v_company.csv", "v_product.csv", "v_region.csv",
    "v_certification.csv", "v_sanctions_list.csv",
    "e_approved_for.csv", "e_operates_in.csv", "e_owned_by.csv",
    "e_sanctioned_by.csv", "e_requires_cert.csv", "e_holds_cert.csv",
    "v_warehouse.csv", "e_has_warehouse.csv", "e_located_in.csv", "e_stocks.csv",
    "e_ships_to.csv",
    "v_restricted_list.csv", "e_sources_from.csv", "e_on_list.csv",
]


def neptune_endpoint():
    ep = os.environ.get("NEPTUNE_ENDPOINT")
    if not ep:
        raise ValueError("NEPTUNE_ENDPOINT is not set")
    return ep, os.environ.get("NEPTUNE_PORT", "8182")


def generate_and_upload(bucket, prefix, out_dir="/tmp/neptune_data",
                        suppliers=50000, companies=5000, sanctioned=40, seed=42,
                        verbose=False):
    """Generate the dataset CSVs locally and upload them to S3.

    Returns (s3_uri, counts). verbose=True prints each step (for scripts); the
    notebook shows its own progress and a counts table instead.
    """
    say = print if verbose else (lambda *a, **k: None)
    say(f"Generating dataset ({suppliers:,} suppliers)...")
    t0 = time.perf_counter()
    counts = generate(out_dir, suppliers, companies, sanctioned, seed)
    say(f"  Generated in {time.perf_counter() - t0:.1f}s")
    for k in sorted(counts):
        say(f"    {k:<16} {counts[k]:>9,}")

    s3 = boto3.client("s3")
    prefix = prefix.strip("/")
    say(f"\nUploading {len(CSV_FILES)} CSVs to s3://{bucket}/{prefix}/ ...")
    for fn in CSV_FILES:
        path = os.path.join(out_dir, fn)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        s3.upload_file(path, bucket, f"{prefix}/{fn}")
        say(f"  {fn}")
    uri = f"s3://{bucket}/{prefix}/"
    say(f"  Done -> {uri}")
    return uri, counts


def bulk_load(bucket, prefix, iam_role_arn, region="us-east-1",
              parallelism="OVERSUBSCRIBE", generate_first=True, **gen_kwargs):
    """Start a Neptune bulk load from S3. Returns the loadId.

    parallelism defaults to OVERSUBSCRIBE (use every available core): nothing else
    queries the cluster during the workshop's initial load, so max out throughput."""
    if generate_first:
        generate_and_upload(bucket, prefix, verbose=True, **gen_kwargs)

    ep, port = neptune_endpoint()
    payload = {
        "source": f"s3://{bucket}/{prefix.strip('/')}/",
        "format": "csv",                 # Gremlin CSV load format
        "iamRoleArn": iam_role_arn,
        "region": region,
        "failOnError": "FALSE",
        "parallelism": parallelism,
        "updateSingleCardinalityProperties": "FALSE",
        "queueRequest": "TRUE",
    }
    req = urllib.request.Request(
        f"https://{ep}:{port}/loader",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.loads(r.read())
    load_id = body["payload"]["loadId"]
    print(f"Bulk load started. loadId = {load_id}")
    return load_id


def load_status(load_id):
    ep, port = neptune_endpoint()
    url = f"https://{ep}:{port}/loader/{load_id}?details=true&errors=true"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def wait_for_load(load_id, poll_seconds=10, timeout_seconds=1800):
    """Poll the loader until it finishes. Returns the final status payload."""
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout_seconds:
        st = load_status(load_id)
        overall = st["payload"]["overallStatus"]
        status = overall["status"]
        if status != last:
            print(f"  [{time.time() - t0:6.0f}s] {status} "
                  f"records={overall.get('totalRecords', 0):,} "
                  f"duplicates={overall.get('totalDuplicates', 0):,} "
                  f"errors={sum(overall.get(k, 0) for k in ('parsingErrors', 'datatypeMismatchErrors', 'insertErrors')):,}")
            last = status
        if status in ("LOAD_COMPLETED", "LOAD_FAILED", "LOAD_CANCELLED",
                      "LOAD_UNEXPECTED_ERROR"):
            elapsed = time.time() - t0
            print(f"\nFinal status: {status} after {elapsed:.0f}s")
            print(f"  records loaded: {overall.get('totalRecords', 0):,}")
            if status != "LOAD_COMPLETED":
                print(f"  errors: {json.dumps(st['payload'].get('errors', {}))[:600]}")
            return st
        time.sleep(poll_seconds)
    raise TimeoutError(f"Bulk load {load_id} did not finish in {timeout_seconds}s")


def expected_loader_records(out_dir="/tmp/neptune_data"):
    """How many records the bulk loader will report for the generated CSVs.

    The loader counts every vertex and edge AND every non-empty property value as a
    record (a supplier row with four properties is five records), so this is about
    3.5x the number of rows, roughly 4.5 million for the default dataset."""
    import csv
    total = 0
    for fn in CSV_FILES:
        with open(os.path.join(out_dir, fn), newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            props = [i for i, h in enumerate(header) if not h.startswith("~")]
            for row in reader:
                total += 1 + sum(1 for i in props if i < len(row) and row[i] != "")
    return total


def bulk_load_and_wait(source_uri, iam_role_arn, region="us-east-1",
                       expected_records=None, parallelism="OVERSUBSCRIBE",
                       poll_seconds=3, timeout_seconds=1800):
    """Start a Neptune bulk load from `source_uri` (an s3:// folder) and wait for it,
    showing progress in place. This is the same loader HTTP API the %load magic
    calls. expected_records (from expected_loader_records(): vertices + edges +
    property values, which is what the loader counts) drives the progress bar.
    Returns the loadId; raises if the load does not complete."""
    from ui import progress, show_code_block

    ep, port = neptune_endpoint()
    payload = {
        "source": source_uri, "format": "csv", "iamRoleArn": iam_role_arn,
        "region": region, "failOnError": "FALSE", "parallelism": parallelism,
        "updateSingleCardinalityProperties": "FALSE", "queueRequest": "TRUE",
    }
    bar = progress("Neptune bulk loader: loading the graph from S3")
    try:
        req = urllib.request.Request(f"https://{ep}:{port}/loader",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            load_id = json.loads(r.read())["payload"]["loadId"]
    except Exception as e:
        bar.fail(f"could not start the load: {e}")
        raise

    t0 = time.time()
    while True:
        overall = load_status(load_id)["payload"]["overallStatus"]
        status, records = overall["status"], overall.get("totalRecords", 0) or 0
        frac = records / expected_records if expected_records else None
        detail = f"{status}, {records:,} records" + (f" of ~{expected_records:,}" if expected_records else "")
        if status == "LOAD_COMPLETED":
            bar.done(f"{records:,} records loaded (load id {load_id})")
            return load_id
        if status in ("LOAD_FAILED", "LOAD_CANCELLED", "LOAD_UNEXPECTED_ERROR",
                      "LOAD_S3_READ_ERROR", "LOAD_S3_ACCESS_DENIED_ERROR"):
            bar.fail(detail)
            errors = load_status(load_id)["payload"].get("errors", {})
            codes = {e.get("errorCode") for e in errors.get("errorLogs", [])}
            if codes & {"ID_ASSIGNED_TO_MULTIPLE_EDGES", "ID_ASSIGNED_TO_MULTIPLE_VERTICES"}:
                from ui import show_status
                show_status(False, "The graph already holds a DIFFERENT version of this dataset (the "
                                   "same ids connect different vertices). Reset the cluster to an "
                                   "empty graph, then load again; loading on top would mix the two.")
            show_code_block(json.dumps(errors, indent=2)[:4000], f"Loader errors ({load_id})")
            raise RuntimeError(f"Bulk load {load_id} ended with {status}")
        if time.time() - t0 > timeout_seconds:
            bar.fail(detail)
            raise TimeoutError(f"Bulk load {load_id} did not finish in {timeout_seconds}s")
        bar.update(frac, detail)
        time.sleep(poll_seconds)


# ── Stock counts: DynamoDB, not the graph ─────────────────────────────────────
# The graph keeps that a warehouse carries a product (STOCKS); the live counts go to
# the stock table, keyed by the graph's own ids, so the two join on (warehouse, product).

STOCK_LOADED = {"warehouse_id": "_meta", "product_id": "stock-load"}   # written last


def stock_loaded(table_name, region=None):
    """True once load_stock() has finished filling the table."""
    t = boto3.resource("dynamodb", region_name=region or os.environ.get("AWS_REGION")).Table(table_name)
    return "Item" in t.get_item(Key=STOCK_LOADED, ConsistentRead=True)


def load_stock(table_name, out_dir="/tmp/neptune_data", region=None, threads=16, verbose=False):
    """Fill the stock table from the generator's stock_levels.csv (about 240,000 items, a
    minute or so in parallel), then write the marker stock_loaded() looks for. Safe to
    rerun: every write is a full put of the same item."""
    import csv
    from concurrent.futures import ThreadPoolExecutor
    from generate_dataset import STOCK_LEVELS_CSV
    region = region or os.environ.get("AWS_REGION")
    with open(os.path.join(out_dir, STOCK_LEVELS_CSV), newline="") as f:
        items = [{"warehouse_id": r["warehouse_id"], "product_id": r["product_id"],
                  "units": int(r["units"]), "as_of": r["as_of"]} for r in csv.DictReader(f)]

    def write(chunk):
        # One resource per thread: boto3 resources are not thread-safe.
        table = boto3.session.Session().resource("dynamodb", region_name=region).Table(table_name)
        with table.batch_writer() as batch:
            for item in chunk:
                batch.put_item(Item=item)
        return len(chunk)

    size = -(-len(items) // threads)
    with ThreadPoolExecutor(max_workers=threads) as pool:
        done = sum(pool.map(write, [items[i:i + size] for i in range(0, len(items), size)]))
    boto3.resource("dynamodb", region_name=region).Table(table_name).put_item(
        Item={**STOCK_LOADED, "items": done, "loaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    if verbose:
        print(f"Loaded {done:,} stock items into {table_name}", flush=True)
    return done


# ── Inspection helpers ────────────────────────────────────────────────────────

def graph_summary(g):
    """Counts per label. Index-backed, so fast even on a large graph."""
    labels_v = ["Supplier", "Company", "Product", "Region",
                "Certification", "SanctionsList"]
    labels_e = ["APPROVED_FOR", "OPERATES_IN", "OWNED_BY",
                "SANCTIONED_BY", "REQUIRES_CERT", "HOLDS_CERT"]
    out = {}
    for lbl in labels_v:
        out[lbl] = g.V().hasLabel(lbl).count().next()
    for lbl in labels_e:
        out[lbl] = g.E().hasLabel(lbl).count().next()

    print("===== Graph summary =====")
    print("  Vertices")
    for lbl in labels_v:
        print(f"    {lbl:<16} {out[lbl]:>9,}")
    print("  Edges")
    for lbl in labels_e:
        print(f"    {lbl:<16} {out[lbl]:>9,}")
    print(f"  TOTAL vertices    {sum(out[l] for l in labels_v):>9,}")
    print(f"  TOTAL edges       {sum(out[l] for l in labels_e):>9,}")
    print("=========================")
    return out


def clear_graph(g, confirm=False):
    """Drop every vertex. Destructive: requires confirm=True.

    On a graph this size a full drop is slow; prefer re-running the bulk loader
    into a fresh cluster, or just leave the data in place.
    """
    if not confirm:
        raise ValueError("clear_graph() is destructive; pass confirm=True")
    print("Dropping all vertices (this can take a while on a large graph)...")
    g.V().drop().iterate()
    print("  Done.")


def main():
    bucket = os.environ.get("DATA_BUCKET")
    prefix = os.environ.get("DATA_PREFIX", "guardrail/neptune_data")
    role = os.environ.get("NEPTUNE_LOAD_ROLE_ARN")
    region = os.environ.get("AWS_REGION", "us-east-1")
    if not (bucket and role):
        raise SystemExit(
            "Set DATA_BUCKET and NEPTUNE_LOAD_ROLE_ARN (and optionally DATA_PREFIX).")

    load_id = bulk_load(bucket, prefix, role, region)
    wait_for_load(load_id)
    print("\nSetup complete. The AnyCompany knowledge graph is loaded.")


if __name__ == "__main__":
    main()
