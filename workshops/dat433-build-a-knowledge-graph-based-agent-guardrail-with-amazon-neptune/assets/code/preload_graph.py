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
preload_graph.py - load the AnyCompany graph when the notebook instance starts.

The lifecycle OnStart runs this in the background, so the graph is ready before
anyone opens the notebook and the session spends no time on the bulk load. Safe to
run every start: it does nothing if the graph is already loaded or a load is running.

    1. wait until Neptune answers
    2. if the suppliers aren't there and no load is running: generate the CSVs, upload
       them to S3, and bulk load them
    3. fill the DynamoDB stock table (the live counts; the graph only says which
       warehouse carries which product), unless it's already filled
    4. compute OFAC's 50 Percent Rule once with the reference query (queries/ holds the
       reference at start), so the report has a result to read

Cell 0.1 (session.ensure_graph) waits for this, or loads the graph itself if this never ran.
Log: ~/SageMaker/workshop/helpers/preload.log
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import workshop  # noqa: E402  (loads workshop_config.txt into the environment)
from session import EXPECTED_SUPPLIERS, _loader_jobs, _supplier_count  # noqa: E402
from setup_graph import (generate_and_upload, bulk_load, load_status, wait_for_load,  # noqa: E402
                         load_stock, stock_loaded)
from session import _ensure_dataset_files  # noqa: E402

RUNNING = ("LOAD_IN_PROGRESS", "LOAD_IN_QUEUE", "LOAD_NOT_STARTED")


def wait_for_neptune(timeout_seconds=900):
    t0 = time.time()
    while True:
        try:
            return _supplier_count()
        except Exception as e:
            if time.time() - t0 > timeout_seconds:
                raise
            print(f"Neptune not ready yet ({type(e).__name__}); retrying", flush=True)
            time.sleep(15)


def main():
    n = wait_for_neptune()
    if n >= EXPECTED_SUPPLIERS:
        print(f"Graph already loaded: {n:,} suppliers", flush=True)
    else:
        running = [i for i in _loader_jobs()
                   if load_status(i)["payload"]["overallStatus"]["status"] in RUNNING]
        if running:
            print(f"A load is already running ({running[0]}); waiting for it", flush=True)
            wait_for_load(running[0], poll_seconds=10)
        else:
            bucket = os.environ["DATA_BUCKET"]
            prefix = os.environ.get("DATA_PREFIX", "guardrail/neptune_data")
            generate_and_upload(bucket, prefix, verbose=True)
            load_id = bulk_load(bucket, prefix, os.environ["NEPTUNE_LOAD_ROLE_ARN"],
                                os.environ["AWS_REGION"], generate_first=False)
            final = wait_for_load(load_id, poll_seconds=10)
            if final["payload"]["overallStatus"]["status"] != "LOAD_COMPLETED":
                raise SystemExit("Bulk load did not complete")
    table = os.environ["STOCK_TABLE"]
    if stock_loaded(table):
        print(f"Stock table already filled: {table}", flush=True)
    else:
        _ensure_dataset_files()   # deterministic: the same counts the graph was built with
        load_stock(table, verbose=True)
    if not workshop.oc("MATCH (r:PolicyRun {name: 'ofac-50-percent'}) RETURN count(r) AS n")[0]["n"]:
        from verify import apply_ownership_rule
        r = apply_ownership_rule()
        print(f"OFAC 50% rule computed: {r['rounds']} rounds, {r['suppliers']:,} suppliers blocked", flush=True)
    print("Preload complete", flush=True)


if __name__ == "__main__":
    main()
