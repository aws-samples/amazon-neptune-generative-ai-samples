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
"""lambda_deploy_data.py — CloudFormation custom resource that loads DAT408's data
at deploy time, so attendees never wait for it during the session.

ResourceProperties.Action selects the job:
  GenerateHistory   fan out the history generator (one Lambda per shard), sum the
                    per-policy aggregates, write a _SUCCESS marker. The traces
                    table then imports the result from S3.
  LoadGraph         neptune.load the generated graph files into Neptune Analytics,
                    one batch per file group. Each finished batch leaves a marker in
                    S3, so a retry or continuation never loads a batch twice (which
                    would duplicate edges). Re-invokes itself before the 15-minute
                    Lambda limit and answers CloudFormation only when done.
  IngestPolicies    copy the policy corpus into the policy bucket, create or update
                    the Knowledge Base data source, run one ingestion job, wait.
  SeedApplications  put the sample loan applications into the applications table.
Delete requests succeed without touching data (the stack deletes the resources).
"""
import json
import os
import time
import traceback
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION", "us-east-1")
ENRICHMENT_PROFILE_ID = "us.amazon.nova-2-lite-v1:0"
CONTINUE_BELOW_MS = 120_000   # hand off to a fresh invocation when less time than this remains


def respond(event, context, status, reason="", data=None):
    body = json.dumps({
        "Status": status,
        "Reason": (reason or f"See CloudWatch Log Stream: {context.log_stream_name}")[:3000],
        "PhysicalResourceId": event.get("PhysicalResourceId") or event["LogicalResourceId"],
        "StackId": event["StackId"], "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"], "Data": data or {},
    }).encode()
    req = urllib.request.Request(event["ResponseURL"], data=body, method="PUT",
                                 headers={"Content-Type": "", "Content-Length": str(len(body))})
    urllib.request.urlopen(req)


def s3_exists(s3, bucket, key):
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False


# ---------------------------------------------------------------------------
def generate_history(props, context):
    from history_generator import aggregate_items, GENERATOR_VERSION
    s3 = boto3.client("s3")
    bucket, prefix = props["Bucket"], props["Prefix"].rstrip("/")
    total, shards = int(props["Total"]), int(props["Shards"])
    marker = f"{prefix}/_SUCCESS-{total}-v{GENERATOR_VERSION}"
    if s3_exists(s3, bucket, marker):
        print(f"History for {total} decisions already generated; skipping.")
        return {"Decisions": str(total)}
    # New accounts can have a Lambda concurrency limit as low as 10, so run a few
    # shards at a time and retry when throttled.
    parallel = min(shards, int(props.get("Parallel", 8)))
    lam = boto3.client("lambda", config=Config(read_timeout=910, retries={"max_attempts": 0},
                                               max_pool_connections=parallel))

    def run(k):
        for attempt in range(8):
            try:
                r = lam.invoke(FunctionName=props["GeneratorFunction"], Payload=json.dumps(
                    {"bucket": bucket, "prefix": prefix, "shard": k, "shards": shards, "total": total}).encode())
                break
            except lam.exceptions.TooManyRequestsException:
                time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"shard {k}: throttled on every attempt")
        body = json.loads(r["Payload"].read())
        if r.get("FunctionError"):
            raise RuntimeError(f"shard {k} failed: {body}")
        return body

    t0 = time.time()
    with ThreadPoolExecutor(parallel) as pool:
        results = list(pool.map(run, range(shards)))
    agg, n = aggregate_items([r["aggregates"] for r in results])
    s3.put_object(Bucket=bucket, Key=f"{prefix}/ddb/aggregates.json.gz", Body=agg)
    s3.put_object(Bucket=bucket, Key=marker, Body=b"ok")
    print(f"Generated {total} decisions in {time.time() - t0:.0f}s; {n} aggregate items.")
    return {"Decisions": str(total)}


def generate_lineage(props, context):
    """History v3: one synchronous invocation of the lineage generator over the
    lineage input the history shards wrote. Skipped when its marker exists."""
    from history_generator import GENERATOR_VERSION
    s3 = boto3.client("s3")
    bucket, prefix, total = props["Bucket"], props["Prefix"].rstrip("/"), int(props["Total"])
    marker = f"{prefix}/_LINEAGE-{total}-v{GENERATOR_VERSION}"
    if s3_exists(s3, bucket, marker):
        print("Lineage already generated; skipping.")
        return {"Lineage": "cached"}
    lam = boto3.client("lambda", config=Config(read_timeout=910, retries={"max_attempts": 0}))
    t0 = time.time()
    r = lam.invoke(FunctionName=props["GeneratorFunction"],
                   Payload=json.dumps({"bucket": bucket, "prefix": prefix}).encode())
    body = json.loads(r["Payload"].read())
    if r.get("FunctionError"):
        raise RuntimeError(f"lineage generator failed: {body}")
    s3.put_object(Bucket=bucket, Key=marker, Body=json.dumps(body).encode())
    print(f"Lineage in {time.time() - t0:.0f}s: {body}")
    return {"Lineage": str(body.get("decisions_resting_on_misread"))}


# ---------------------------------------------------------------------------
def load_graph(event, props, context):
    """Returns None when it handed off to a continuation (no CFN response yet)."""
    s3 = boto3.client("s3")
    ng = boto3.client("neptune-graph", config=Config(read_timeout=900, retries={"max_attempts": 0}))
    bucket, prefix, graph = props["Bucket"], props["Prefix"].rstrip("/"), props["GraphId"]
    keys = [o["Key"] for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=f"{prefix}/graph/") for o in page.get("Contents", [])]
    groups = sorted({k.rsplit("/", 1)[1].split("-")[0] for k in keys
                     if not k.rsplit("/", 1)[1].startswith("shared")})
    # Vertices before edges, shared vertices (policies, tool, bands) first.
    batches = ["vertices/shared-"] + [f"vertices/{g}-" for g in groups] + [f"edges/{g}-" for g in groups]
    done = 0
    for batch in batches:
        mark = f"{prefix}/loaded/{batch.replace('/', '_')}"
        if s3_exists(s3, bucket, mark):
            done += 1
            continue
        if context.get_remaining_time_in_millis() < CONTINUE_BELOW_MS:
            print(f"{done}/{len(batches)} batches loaded; continuing in a new invocation.")
            boto3.client("lambda").invoke(FunctionName=context.function_name, InvocationType="Event",
                                          Payload=json.dumps(event).encode())
            return None
        q = (f'CALL neptune.load({{source: "s3://{bucket}/{prefix}/graph/{batch}", region: "{REGION}", '
             f'format: "csv", failOnError: true, concurrency: 16}})')
        r = json.loads(ng.execute_query(graphIdentifier=graph, language="OPEN_CYPHER",
                                        queryString=q)["payload"].read())["results"][0]
        if r.get("insertErrors"):
            raise RuntimeError(f"neptune.load {batch}: {r['insertErrors']} insert errors (loadId {r.get('loadId')})")
        s3.put_object(Bucket=bucket, Key=mark, Body=json.dumps(r).encode())
        done += 1
        print(f"loaded {batch} ({r.get('totalRecords')} records, {r.get('totalTimeSpentMillis')} ms)")
    return {"Batches": str(done)}


# ---------------------------------------------------------------------------
def ingest_policies(event, props, context):
    """Returns None when it handed off to a continuation (no CFN response yet)."""
    s3, ba = boto3.client("s3"), boto3.client("bedrock-agent")
    if "IngestionJob" in event:      # a continuation: keep waiting on the same job
        return wait_for_ingestion(event, event["IngestionJob"]["DataSourceId"],
                                  event["IngestionJob"]["IngestionJobId"], context)
    src_bucket, src_prefix = props["AssetsBucket"], props["AssetsPrefix"].rstrip("/") + "/policies/"
    dst_bucket = props["PolicyBucket"]
    src = {o["Key"].rsplit("/", 1)[1] for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=src_bucket, Prefix=src_prefix) for o in page.get("Contents", []) if o["Key"].endswith(".md")}
    src.discard("README.md")
    dst = {o["Key"].rsplit("/", 1)[1] for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=dst_bucket, Prefix="policies/") for o in page.get("Contents", [])}
    for name in dst - src:     # everything in the bucket is ingested, so remove stale documents
        s3.delete_object(Bucket=dst_bucket, Key=f"policies/{name}")
    for name in src:
        s3.copy_object(Bucket=dst_bucket, Key=f"policies/{name}",
                       CopySource={"Bucket": src_bucket, "Key": src_prefix + name})

    profile = next(p for p in boto3.client("bedrock").list_inference_profiles(
        typeEquals="SYSTEM_DEFINED", maxResults=1000)["inferenceProfileSummaries"]
        if p["inferenceProfileId"] == ENRICHMENT_PROFILE_ID)
    kb_id = props["KnowledgeBaseId"]
    config = dict(
        name="dat408-policy-docs",
        # The vectors live in this stack's Neptune graph, which stack deletion removes. With
        # DELETE, Bedrock first tries to clear them from the graph, and when that fails the
        # data source, the Knowledge Base and the whole stack deletion fail with it.
        dataDeletionPolicy="RETAIN",
        dataSourceConfiguration={"type": "S3", "s3Configuration": {
            "bucketArn": f"arn:aws:s3:::{dst_bucket}", "inclusionPrefixes": ["policies/"]}},
        vectorIngestionConfiguration={
            "chunkingConfiguration": {"chunkingStrategy": "FIXED_SIZE",
                                      "fixedSizeChunkingConfiguration": {"maxTokens": 1000, "overlapPercentage": 20}},
            "contextEnrichmentConfiguration": {"type": "BEDROCK_FOUNDATION_MODEL",
                                               "bedrockFoundationModelConfiguration": {
                                                   "modelArn": profile["inferenceProfileArn"],
                                                   "enrichmentStrategyConfiguration": {"method": "CHUNK_ENTITY_EXTRACTION"}}}})
    existing = ba.list_data_sources(knowledgeBaseId=kb_id)["dataSourceSummaries"]
    if existing:
        ds_id = existing[0]["dataSourceId"]
        ba.update_data_source(knowledgeBaseId=kb_id, dataSourceId=ds_id, **config)
    else:
        ds_id = ba.create_data_source(knowledgeBaseId=kb_id, **config)["dataSource"]["dataSourceId"]
    job_id = ba.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)["ingestionJob"]["ingestionJobId"]
    return wait_for_ingestion(event, ds_id, job_id, context)


def wait_for_ingestion(event, ds_id, job_id, context):
    """Wait for the ingestion job. Near the Lambda time limit, hand off to a new invocation
    that keeps waiting on the same job. Any failed document fails the deploy, with Bedrock's
    reasons verbatim: a Knowledge Base with policies missing would mislead every module."""
    ba = boto3.client("bedrock-agent")
    kb_id = event["ResourceProperties"]["KnowledgeBaseId"]
    while context.get_remaining_time_in_millis() > CONTINUE_BELOW_MS:
        job = ba.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id, ingestionJobId=job_id)["ingestionJob"]
        stats = job.get("statistics", {})
        if job["status"] == "COMPLETE":
            if stats.get("numberOfDocumentsFailed"):
                raise RuntimeError(f"Ingestion {job_id}: {stats['numberOfDocumentsFailed']} document(s) failed: "
                                   f"{job.get('failureReasons')}")
            print(f"Ingestion complete: {stats}")
            return {"DataSourceId": ds_id, "IngestionJobId": job_id}
        if job["status"] == "FAILED":
            raise RuntimeError(f"Ingestion failed: {job.get('failureReasons')}")
        time.sleep(15)
    print(f"Ingestion {job_id} still {job['status']} ({stats}); continuing in a new invocation.")
    boto3.client("lambda").invoke(FunctionName=context.function_name, InvocationType="Event",
                                  Payload=json.dumps({**event, "IngestionJob": {
                                      "DataSourceId": ds_id, "IngestionJobId": job_id}}).encode())
    return None


def delete_data_sources(props, context):
    """The Knowledge Base cannot be deleted while it has data sources, and this
    resource created the one it has. Delete it, and wait, so stack deletion succeeds."""
    ba = boto3.client("bedrock-agent")
    kb_id = props["KnowledgeBaseId"]
    try:
        for ds in ba.list_data_sources(knowledgeBaseId=kb_id)["dataSourceSummaries"]:
            # A data source can't be deleted while an ingestion job runs (e.g. a deploy that
            # failed mid-ingestion): stop it and wait until it has stopped.
            for st in ("STARTING", "IN_PROGRESS", "STOPPING"):
                for j in ba.list_ingestion_jobs(knowledgeBaseId=kb_id, dataSourceId=ds["dataSourceId"],
                                                filters=[{"attribute": "STATUS", "operator": "EQ",
                                                          "values": [st]}])["ingestionJobSummaries"]:
                    if st != "STOPPING":
                        try:
                            ba.stop_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds["dataSourceId"],
                                                  ingestionJobId=j["ingestionJobId"])
                        except ba.exceptions.ValidationException:
                            pass          # it reached a terminal state since it was listed
                    while ba.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds["dataSourceId"],
                                               ingestionJobId=j["ingestionJobId"])["ingestionJob"]["status"] in (
                                                   "STARTING", "IN_PROGRESS", "STOPPING"):
                        time.sleep(10)
            # Stacks deployed before dataDeletionPolicy RETAIN: switch to RETAIN first, so the
            # delete doesn't depend on clearing vectors from a graph that's about to go anyway.
            full = ba.get_data_source(knowledgeBaseId=kb_id, dataSourceId=ds["dataSourceId"])["dataSource"]
            if full.get("dataDeletionPolicy") != "RETAIN":
                ba.update_data_source(knowledgeBaseId=kb_id, dataSourceId=full["dataSourceId"], name=full["name"],
                                      dataSourceConfiguration=full["dataSourceConfiguration"],
                                      vectorIngestionConfiguration=full.get("vectorIngestionConfiguration", {}),
                                      dataDeletionPolicy="RETAIN")
            ba.delete_data_source(knowledgeBaseId=kb_id, dataSourceId=ds["dataSourceId"])
        while context.get_remaining_time_in_millis() > 30_000:
            if not ba.list_data_sources(knowledgeBaseId=kb_id)["dataSourceSummaries"]:
                return
            time.sleep(10)
    except ba.exceptions.ResourceNotFoundException:
        return


# ---------------------------------------------------------------------------
def seed_applications(props, context):
    from applications import SEED_APPLICATIONS, _serialize
    table = boto3.resource("dynamodb").Table(props["TableName"])
    for app in SEED_APPLICATIONS:
        table.put_item(Item=_serialize(app))
    return {"Applications": str(len(SEED_APPLICATIONS))}


# ---------------------------------------------------------------------------
def handler(event, context):
    props = event.get("ResourceProperties", {})
    action = props.get("Action")
    print(f"{event.get('RequestType')} {action}")
    try:
        if event["RequestType"] == "Delete":
            if action == "IngestPolicies":
                delete_data_sources(props, context)   # else the KB itself can't be deleted
            respond(event, context, "SUCCESS")
            return
        if action == "GenerateHistory":
            data = generate_history(props, context)
        elif action == "GenerateLineage":
            data = generate_lineage(props, context)
        elif action == "LoadGraph":
            data = load_graph(event, props, context)
            if data is None:
                return          # a continuation will answer CloudFormation
        elif action == "IngestPolicies":
            data = ingest_policies(event, props, context)
            if data is None:
                return          # a continuation will answer CloudFormation
        elif action == "SeedApplications":
            data = seed_applications(props, context)
        else:
            raise ValueError(f"Unknown Action {action!r}")
        respond(event, context, "SUCCESS", data=data)
    except Exception as e:
        traceback.print_exc()
        respond(event, context, "FAILED", reason=f"{action}: {e}")
