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
workshop.py — one-call setup and shared helpers for the DAT408 notebooks.

agent/session.py's connect() calls setup() and bind() for every notebook.

`ctx` carries the resolved config and AWS clients (ctx.dynamodb, ctx.neptune,
ctx.lambda_, ctx.bedrock_agent, ctx.GRAPH_ID, ctx.KB_ID, ...) plus convenience
methods (ctx.neptune_query(...), ctx.get_application(...)). All the boilerplate
— boto3 upgrade, CloudFormation output lookup, client construction, agent-package
init — lives here so the notebook cells only show the teaching point.

The heavier pieces live here too: the stream replay and transaction tests Go deeper
checks against, the AgentCore Runtime invoker, the MCP server deploy, and the pictures.

Graph visualization is done with Amazon Neptune's own graph-notebook `%%oc`
cell magic (interactive, native renderer). The graph-notebook bundle and the
GRAPH_NOTEBOOK_* connection env vars (host = the Neptune Analytics graph
endpoint, service = neptune-graph) are installed by the SageMaker lifecycle at
instance start, so cells just run `%%oc` directly — no per-notebook setup.
"""
import json
import os
import sys
import time
import types
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# setup() — resolve infra, build clients, wire up the agent package
# ---------------------------------------------------------------------------
def _workshop_config():
    """The KEY=value file the notebook instance's lifecycle script writes next to
    agent/ (region and stack name). Empty when running anywhere else."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workshop_config.txt")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return dict(line.strip().split("=", 1) for line in f if "=" in line)


def _workshop_region(config):
    """The region this notebook's stack is in: the environment, then the lifecycle's
    config file, then the notebook instance's own metadata. Never a guess."""
    region = (os.environ.get("AWS_DEFAULT_REGION") or os.environ.get("AWS_REGION")
              or config.get("AWS_REGION"))
    if region:
        return region
    try:
        with open("/opt/ml/metadata/resource-metadata.json") as f:
            return json.load(f)["ResourceArn"].split(":")[3]
    except (OSError, KeyError, IndexError, ValueError):
        raise SystemExit("Can't tell which AWS region this notebook is in. Restart the notebook "
                         "instance (its start-up script records the region), then run this cell again.")


def setup(upgrade_boto3=True, verbose=True):
    """Bootstrap a notebook. Returns a WorkshopContext (a namespace of clients,
    config, and helper methods). Safe to call once at the top of any module."""
    if upgrade_boto3:
        _upgrade_boto3(verbose)

    import boto3  # imported after the upgrade so the new version is used

    config = _workshop_config()
    region = _workshop_region(config)
    stack = os.environ.get("WORKSHOP_STACK_NAME") or config.get("WORKSHOP_STACK_NAME") or "workshop-infra"
    # Clients created without an explicit region (graph-notebook's %%oc) use this too.
    os.environ.setdefault("AWS_REGION", region)
    os.environ.setdefault("AWS_DEFAULT_REGION", region)

    cfn = boto3.client("cloudformation", region_name=region)
    try:
        stack_outputs = cfn.describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]
    except Exception as e:
        if "does not exist" in str(e) or "ValidationError" in str(e):
            raise SystemExit(f"CloudFormation stack '{stack}' was not found.")
        raise
    outputs = {o["OutputKey"]: o["OutputValue"] for o in stack_outputs}

    ctx = types.SimpleNamespace()
    ctx.region = region
    ctx.stack_name = stack
    ctx.BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-5"
    ctx.GRAPH_ID = outputs["NeptuneGraphId"]
    ctx.KB_ID = outputs["KnowledgeBaseId"]
    ctx.POLICY_BUCKET = outputs["PolicyBucketName"]
    ctx.APPLICATIONS_TABLE = outputs.get("ApplicationsTableName", "dat408-applications")
    ctx.TRACES_TABLE = outputs.get("TracesTableName", "dat408-agent-traces")
    ctx.STREAM_PROCESSOR = outputs.get("StreamProcessorFunction", "dat408-stream-processor")
    # ARN of the underwriting agent hosted in Bedrock AgentCore Runtime.
    ctx.AGENT_RUNTIME_ARN = outputs.get("AgentRuntimeArn", "")
    # Historical decisions loaded into DynamoDB and Neptune at deploy time.
    ctx.HISTORICAL_DECISIONS = int(outputs.get("HistoricalDecisions", 0) or 0)
    # The Lambda that packages your answers as the MCP server (Kiro notebook).
    ctx.MCP_DEPLOY_FUNCTION = outputs.get("McpDeployFunction", "")

    # AWS clients
    ctx.dynamodb = boto3.resource("dynamodb", region_name=region)
    ctx.dynamodb_client = boto3.client("dynamodb", region_name=region)
    ctx.neptune = boto3.client("neptune-graph", region_name=region)
    ctx.lambda_ = boto3.client("lambda", region_name=region)
    ctx.bedrock_agent = boto3.client("bedrock-agent", region_name=region)
    ctx.bedrock_mgmt = boto3.client("bedrock", region_name=region)
    ctx.bedrock_runtime = boto3.client("bedrock-runtime", region_name=region)
    # AgentCore Runtime data-plane + observability read clients.
    ctx.agentcore = boto3.client("bedrock-agentcore", region_name=region)
    ctx.cloudwatch = boto3.client("cloudwatch", region_name=region)
    ctx.xray = boto3.client("xray", region_name=region)

    # openCypher, bound to this graph. The MCP server runs your saved queries with
    # this same function (agent.evidence.run_cypher).
    from agent.evidence import run_cypher

    def neptune_query(query, params=None):
        return _run_with_spinner(lambda: run_cypher(ctx.neptune, ctx.GRAPH_ID, query, params),
                                 "querying Neptune", delay=1.0)

    ctx.neptune_query = neptune_query

    # Neptune Analytics HTTPS endpoint, used to point the graph-notebook %%oc magic.
    # NOTE: get_graph returns the key as lowercase "endpoint".
    try:
        _g = ctx.neptune.get_graph(graphIdentifier=ctx.GRAPH_ID)
        ctx.graph_endpoint = _g.get("endpoint") or _g.get("Endpoint")
    except Exception:
        ctx.graph_endpoint = None

    # Wire up the underwriting-agent package and bind its helpers to ctx
    _ensure_agent_on_path()
    from agent import (
        UnderwritingAgent, init_tools, init_applications,
        get_application, list_applications, seed_applications,
    )
    init_tools(region=region, knowledge_base_id=ctx.KB_ID)
    init_applications(region=region, table_name=ctx.APPLICATIONS_TABLE)
    ctx.UnderwritingAgent = UnderwritingAgent
    ctx.get_application = get_application
    ctx.list_applications = list_applications
    ctx.seed_applications = seed_applications

    if verbose:
        print(f"✅ Setup complete (region {region})")
        print(f"   Neptune graph:   {ctx.GRAPH_ID}")
        print(f"   Knowledge Base:  {ctx.KB_ID}")
        print(f"   Applications:    {ctx.APPLICATIONS_TABLE}")
        print(f"   Traces table:    {ctx.TRACES_TABLE}")
        print(f"   Agent runtime:   {ctx.AGENT_RUNTIME_ARN or '(not deployed)'}")
    return ctx


def trace_item_count(ctx):
    """Items in the evidence table. DynamoDB's own ItemCount is refreshed only about every
    six hours, so a freshly deployed table reports 0; the deploy-time import records exactly
    how many items it wrote. Uses whichever is larger (live writes are a rounding error)."""
    table = ctx.dynamodb.Table(ctx.TRACES_TABLE)
    counted = table.item_count
    try:
        client = ctx.dynamodb.meta.client
        for imp in client.list_imports(TableArn=table.table_arn).get("ImportSummaryList", []):
            done = client.describe_import(ImportArn=imp["ImportArn"])["ImportTableDescription"]
            if done.get("ImportStatus") == "COMPLETED":
                counted = max(counted, done.get("ImportedItemCount", 0))
    except Exception:
        pass
    return counted


def bind(ctx, namespace):
    """Expose ctx's clients, config, and helpers under the plain names the
    teaching cells use — so a notebook's whole setup is just:

        from agent.workshop import setup, bind
        ctx = setup(); bind(ctx, globals())
    """
    namespace.update({
        "ctx": ctx,
        "REGION": ctx.region, "GRAPH_ID": ctx.GRAPH_ID, "KB_ID": ctx.KB_ID,
        "BEDROCK_MODEL_ID": ctx.BEDROCK_MODEL_ID,
        "APPLICATIONS_TABLE": ctx.APPLICATIONS_TABLE, "TRACE_TABLE_NAME": ctx.TRACES_TABLE,
        "STREAM_PROCESSOR": ctx.STREAM_PROCESSOR,
        "dynamodb": ctx.dynamodb, "dynamodb_client": ctx.dynamodb_client,
        "neptune_client": ctx.neptune,
        "neptune_query": ctx.neptune_query,
        "get_application": ctx.get_application, "list_applications": ctx.list_applications,
        "UnderwritingAgent": ctx.UnderwritingAgent,
        "trace_table": ctx.dynamodb.Table(ctx.TRACES_TABLE),
        "enable_graph_notebook": enable_graph_notebook,
        "AGENT_RUNTIME_ARN": ctx.AGENT_RUNTIME_ARN,
        "HISTORICAL_DECISIONS": ctx.HISTORICAL_DECISIONS,
        "invoke_agent_runtime": lambda **kw: invoke_agent_runtime(ctx, **kw),
        "show_agentcore_observability": lambda **kw: show_agentcore_observability(ctx, **kw) and None,
        "styled_table": styled_table,
        "render_decision": render_decision,
        "summarize_evidence": summarize_evidence,
        "plant_unsupported_citation": lambda **kw: plant_unsupported_citation(ctx, **kw),
        "save_answer": save_answer,
        "replay_evaluation": lambda eval_id: replay_evaluation(ctx, eval_id),
        "send_poison_record": lambda eval_id: send_poison_record(ctx, eval_id),
        "run_answer": lambda name, params=None: run_answer(ctx, name, params),
        "check_decision_transaction": lambda fn: check_decision_transaction(ctx, fn) and None,
        "draw_graph": lambda query, params=None, **kw: draw_graph(ctx, query, params, **kw),
        "bar_chart": bar_chart,
        "start_mcp_deploy": lambda: start_mcp_deploy(ctx) and None,
        # These print their results; returning None keeps the cell output to what they print.
        "finish_mcp_deploy": lambda: finish_mcp_deploy(ctx) and None,
        "mcp_server_status": lambda: mcp_server_status(ctx) and None,
        "kiro_ide_link": lambda: kiro_ide_link(ctx) and None,
    })


REQUIRED_SERVICES = {"neptune-graph", "bedrock-agentcore", "bedrock-agentcore-control"}


def _upgrade_boto3(verbose=True):
    """Upgrade boto3/botocore only if the installed version lacks a service the
    workshop calls, then flush the module cache so the new version is used without
    a kernel restart. The instance's startup script already upgrades boto3, so this
    is normally a no-op: upgrading on every setup() made each module wait on pip, and
    reloading boto3 inside a running kernel triggers a harmless but alarming
    RuntimeWarning ("coroutine ... was never awaited")."""
    import subprocess
    import boto3
    if REQUIRED_SERVICES <= set(boto3.session.Session().get_available_services()):
        return
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "boto3", "botocore"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        if verbose:
            print(f"⚠️  boto3 upgrade skipped: {r.stderr.strip()[:120]}")
        return
    # Only flush the boto* module cache when pip ACTUALLY installed a newer
    # version. Re-importing the same modules mid-kernel when boto3 is already
    # current (e.g. the SageMaker lifecycle upgraded it at startup) orphans
    # botocore's async-context coroutine, which GC later reports as a harmless
    # but alarming RuntimeWarning ("coroutine ... was never awaited").
    if "Successfully installed" in (r.stdout + r.stderr):
        for m in [k for k in list(sys.modules) if "boto" in k]:
            del sys.modules[m]


def _ensure_agent_on_path():
    for candidate in ("/home/ec2-user/SageMaker/dat408", ".", "..", "../code"):
        if os.path.isdir(os.path.join(candidate, "agent")):
            p = os.path.abspath(candidate)
            if p not in sys.path:
                sys.path.insert(0, p)
            return


# ---------------------------------------------------------------------------
# Exercise support: a scratch decision, stream replays
# ---------------------------------------------------------------------------
def new_scratch_evaluation(ctx):
    """A fresh evaluation header (SK = META, status IN_PROGRESS), as the
    runtime writes when an evaluation starts, and the decision step it will record.
    Kept a day (TTL); it never reaches the graph (no transform is deployed yet)."""
    import uuid
    eval_id = f"scratch-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    ttl = int(time.time()) + 86400
    table = ctx.dynamodb.Table(ctx.TRACES_TABLE)
    table.put_item(Item={"PK": f"EVAL#{eval_id}", "SK": "META", "evaluation_id": eval_id,
                         "application_id": "LA-SCRATCH", "status": "IN_PROGRESS",
                         "started_at": now, "ttl": ttl},
                   ConditionExpression="attribute_not_exists(PK)")
    decision = {"PK": f"EVAL#{eval_id}", "SK": "STEP#000", "evaluation_id": eval_id,
                "application_id": "LA-SCRATCH", "step_num": 0, "step_timestamp": now,
                "action": "FINAL_DECISION", "is_decision": True, "outcome": "approve",
                "thought": "Final decision: approve", "action_input": "{}", "observation_summary": "{}",
                "policies_cited": ["HUD 4000.1 II.A.5.d"], "policies_violated": [], "ttl": ttl}
    return eval_id, decision, now


def policy_month_counts(ctx, policy, now):
    """The per-policy aggregate item for the current month (decisions citing it)."""
    item = ctx.dynamodb.Table(ctx.TRACES_TABLE).get_item(
        Key={"PK": f"POLICY#{policy}", "SK": f"MONTH#{now[:7]}"}, ConsistentRead=True).get("Item", {})
    return int(item.get("decisions_citing", 0))


def _stream_records(ctx, evaluation_id):
    """The evaluation's STEP# items, shaped as the DynamoDB Stream INSERT records
    the transform received when the runtime wrote them."""
    from boto3.dynamodb.conditions import Key
    from boto3.dynamodb.types import TypeSerializer
    ser = TypeSerializer()
    items = ctx.dynamodb.Table(ctx.TRACES_TABLE).query(
        KeyConditionExpression=Key("PK").eq(f"EVAL#{evaluation_id}") & Key("SK").begins_with("STEP#"),
        ConsistentRead=True)["Items"]
    return [{"eventName": "INSERT", "dynamodb": {
        "Keys": {"PK": {"S": i["PK"]}, "SK": {"S": i["SK"]}},
        "NewImage": {k: ser.serialize(v) for k, v in i.items()},
        "SequenceNumber": f"replay-{n}"}} for n, i in enumerate(sorted(items, key=lambda x: x["SK"]))]


def _invoke_transform(ctx, records):
    resp = ctx.lambda_.invoke(FunctionName=ctx.STREAM_PROCESSOR,
                              Payload=json.dumps({"Records": records}).encode())
    body = json.loads(resp["Payload"].read() or b"{}")
    if resp.get("FunctionError"):
        raise RuntimeError(f"The transform raised instead of reporting failures: {body}")
    return body


def replay_evaluation(ctx, evaluation_id):
    """Deliver an evaluation's stream records to your deployed transform a
    second time, as Lambda's at-least-once delivery can. Returns the batchItemFailures."""
    return _invoke_transform(ctx, _stream_records(ctx, evaluation_id)).get("batchItemFailures", [])


def send_poison_record(ctx, evaluation_id):
    """One good record and one malformed one (a step with no application_id)
    in the same batch. Returns (batchItemFailures, the poison record's sequence number)."""
    good = _stream_records(ctx, evaluation_id)[:1]
    poison = json.loads(json.dumps(good[0]))
    poison["dynamodb"]["NewImage"].pop("application_id", None)
    poison["dynamodb"]["SequenceNumber"] = "poison-1"
    return _invoke_transform(ctx, good + [poison]).get("batchItemFailures", []), "poison-1"


def _record_decision_naive(ctx, evaluation_id, decision, now):
    """The same three writes as the transaction, made separately and unconditionally:
    what a first version usually looks like. Returns whether the Put replaced an item."""
    from agent.policy_ids import aggregate_updates
    table = ctx.dynamodb.Table(ctx.TRACES_TABLE)
    old = table.put_item(Item=decision, ReturnValues="ALL_OLD")
    table.update_item(Key={"PK": f"EVAL#{evaluation_id}", "SK": "META"},
                      UpdateExpression="SET #s = :done, completed_at = :now",
                      ExpressionAttributeNames={"#s": "status"},
                      ExpressionAttributeValues={":done": "COMPLETE", ":now": now})
    for action in aggregate_updates(ctx.TRACES_TABLE, decision, now):
        ctx.dynamodb_client.update_item(**action["Update"])
    return "Attributes" in old


def check_decision_transaction(ctx, record_decision):
    """Cell 2.3 and G.2: deliver one decision twice (a retry), first through three separate
    writes, then through your record_decision(), and compare what each leaves behind.
    Yours must write once, reject the retry as a whole, and count the decision once."""
    policy = "HUD 4000.1 II.A.5.d"
    table = ctx.dynamodb.Table(ctx.TRACES_TABLE)
    header = lambda e: table.get_item(Key={"PK": f"EVAL#{e}", "SK": "META"}, ConsistentRead=True)["Item"]
    later = lambda: (time.sleep(1.1), datetime.now(timezone.utc).isoformat())[1]

    return _run_with_spinner(lambda: _decision_comparison(ctx, record_decision, policy, table, header, later),
                             "delivering one decision twice through both designs", delay=0.5)(ctx)


def _decision_comparison(ctx, record_decision, policy, table, header, later):
    """The deliveries for check_decision_transaction; returns a function that shows the
    result (so the spinner never interleaves with the table)."""
    from botocore.exceptions import ClientError
    # 1. Three separate writes, delivered twice.
    n_eval, n_decision, n_now = new_scratch_evaluation(ctx)
    before = policy_month_counts(ctx, policy, n_now)
    _record_decision_naive(ctx, n_eval, n_decision, n_now)
    n_first = header(n_eval).get("completed_at")
    replaced = _record_decision_naive(ctx, n_eval, n_decision, later())
    n_header = header(n_eval)
    n_added = policy_month_counts(ctx, policy, n_now) - before

    # 2. Your transaction, delivered twice.
    y_eval, y_decision, y_now = new_scratch_evaluation(ctx)
    before = policy_month_counts(ctx, policy, y_now)
    sent = []
    hook = lambda params, **kw: sent.append(params)
    ctx.dynamodb_client.meta.events.register("provide-client-params.dynamodb.TransactWriteItems", hook)
    first_ok, retry_reasons, retry_written, y_first, first_error = False, None, False, None, None
    try:
        try:
            record_decision(y_eval, y_decision, y_now)
            first_ok = True
            y_first = header(y_eval).get("completed_at")
        except ClientError as e:
            first_error = f"{e.response['Error']['Code']}: {e.response['Error']['Message']}"
        if first_ok:
            try:
                record_decision(y_eval, y_decision, later())
                retry_written = True
            except ClientError as e:
                retry_reasons = [r.get("Code") for r in e.response.get("CancellationReasons", [])]
    finally:
        ctx.dynamodb_client.meta.events.unregister("provide-client-params.dynamodb.TransactWriteItems", hook)
    y_header = header(y_eval)
    y_added = policy_month_counts(ctx, policy, y_now) - before
    return lambda ctx: _show_decision_comparison(ctx, policy, replaced, n_header, n_first, n_added,
                                                 first_ok, retry_written, retry_reasons, y_header, y_first,
                                                 y_added, sent, first_error)


def _show_decision_comparison(ctx, policy, replaced, n_header, n_first, n_added, first_ok, retry_written,
                              retry_reasons, y_header, y_first, y_added, sent, first_error=None):
    import pandas as pd
    from IPython.display import display
    if first_error:
        print(f"❌ The first delivery failed: {first_error}")

    def done(h, first):
        if h.get("status") != "COMPLETE":
            return f"❌ still {h.get('status')}"
        if first and h.get("completed_at") != first:
            return "❌ completed twice: completed_at rewritten by the retry"
        return "✅ completed once"
    display(styled_table(pd.DataFrame([
        {"after one decision, delivered twice": "the decision step",
         "three separate writes": "❌ the retry silently replaced it" if replaced else "written",
         "your transaction": ("✅ written once; the retry was rejected" if first_ok and not retry_written
                              else "❌ the retry was written again" if retry_written else "❌ not written")},
        {"after one decision, delivered twice": "the evaluation header",
         "three separate writes": done(n_header, n_first),
         "your transaction": done(y_header, y_first)},
        {"after one decision, delivered twice": f"{policy}, this month's count",
         "three separate writes": f"{'❌' if n_added != 1 else '✅'} +{n_added} for one decision",
         "your transaction": f"{'✅' if y_added == 1 else '❌'} +{y_added} for one decision"},
        {"after one decision, delivered twice": "the policy report vs the evidence",
         "three separate writes": "❌ over-counts" if n_added > 1 else "agree",
         "your transaction": "✅ agree" if y_added == 1 else "❌ disagree"},
    ]), caption="The same retry, two designs"))

    # Why the retry was rejected, in plain words, matched to the action that refused it.
    actions = sent[-1].get("TransactItems", []) if sent else []
    if retry_reasons:
        print("Why DynamoDB rejected your retry:")
        for action, code in zip(actions, retry_reasons):
            if code != "ConditionalCheckFailed":
                continue
            if "Put" in action:
                print("   • Decision already recorded: the write-once Put found an item with this key.")
            elif "Update" in action and action["Update"]["Key"].get("SK", {}).get("S") == "META":
                print("   • Evaluation already complete: the header was no longer IN_PROGRESS.")
        print("   • So DynamoDB cancelled the whole transaction: the policy count did not move either.\n")

    put = next((a["Put"] for a in actions if "Put" in a), {})
    upd = next((a["Update"] for a in actions if "Update" in a and a["Update"]["Key"].get("SK", {}).get("S") == "META"), {})
    problems = []
    if "attribute_not_exists" not in put.get("ConditionExpression", ""):
        problems.append("the decision Put needs ConditionExpression attribute_not_exists(PK) (write-once)")
    if not upd or "COMPLETE" not in json.dumps(upd.get("ExpressionAttributeValues", {})):
        problems.append("the header Update (SK = META) must set status to COMPLETE")
    elif "IN_PROGRESS" not in json.dumps(upd.get("ExpressionAttributeValues", {})):
        problems.append("the header Update needs a condition that status is still IN_PROGRESS")
    if not first_ok:
        problems.append("the first delivery should succeed")
    if retry_written:
        problems.append("the retry was written again: a condition should cancel it")
    if y_added != 1:
        problems.append(f"your transaction counted the decision {y_added} times, not once")
    if problems:
        print("❌ Not yet: " + "; ".join(problems) + ".")
        return False
    print("✅ One decision, recorded once, however often it is delivered. This is the transaction the")
    print("   runtime uses to record every decision.")
    return True


def run_answer(ctx, name, params=None):
    """Run one of your saved openCypher answers (solution/<name>.cypher) exactly as
    the MCP server does: same file, same runner. Returns the result rows."""
    from pathlib import Path
    from agent.evidence import run_cypher
    text = (Path(SOLUTION_DIR) / f"{name}.cypher").read_text()
    return _run_with_spinner(lambda: run_cypher(ctx.neptune, ctx.GRAPH_ID, text, params),
                             "querying Neptune", delay=1.0).get("results", [])


# ---------------------------------------------------------------------------
# Graph visualization (Modules 4 & 5) - Amazon Neptune graph-notebook (%%oc)
# ---------------------------------------------------------------------------
def enable_graph_notebook(ctx, verbose=True):
    """Load Amazon Neptune's graph-notebook magics into this kernel and point
    them at the workshop's Neptune Analytics graph, so `%%oc` cells work.

    Call once per notebook (after setup/bind), before any `%%oc` cell. Safe to
    call more than once. If the graph-notebook package is not installed, prints
    a clear message instead of failing the whole cell."""
    from IPython import get_ipython
    ip = get_ipython()
    if ip is None:
        raise RuntimeError("enable_graph_notebook() must run inside a notebook.")

    # graph-notebook is driven entirely by GRAPH_NOTEBOOK_* env vars (the same
    # mechanism the SageMaker lifecycle and the DAT433 sibling workshop use).
    # We set them here from ctx so the kernel connects even if it did not inherit
    # ~/.bashrc, then load the magics. We deliberately do NOT call the
    # %%graph_notebook_config magic — its config dict has a strict schema that is
    # unnecessary when the env vars are present.
    if ctx.graph_endpoint:
        os.environ["GRAPH_NOTEBOOK_HOST"] = ctx.graph_endpoint
    os.environ["GRAPH_NOTEBOOK_PORT"] = "8182"
    os.environ["GRAPH_NOTEBOOK_SSL"] = "True"
    os.environ["GRAPH_NOTEBOOK_AUTH_MODE"] = "IAM"
    os.environ["GRAPH_NOTEBOOK_SERVICE"] = "neptune-graph"
    os.environ.setdefault("AWS_REGION", ctx.region)

    try:
        ip.run_line_magic("load_ext", "graph_notebook.magics")
    except Exception as e:
        # Already loaded is fine; anything else means the package is missing.
        if "already loaded" not in str(e).lower():
            print("graph-notebook magics unavailable:", e)
            print("  The %%oc cells need the graph-notebook bundle (installed by the "
                  "SageMaker lifecycle via install_jl4x.sh).")
            return

    if not ctx.graph_endpoint:
        print("No Neptune Analytics endpoint resolved; %%oc cannot connect.")
        return
    set_graph_layout()
    if verbose:
        print(f"✅ graph-notebook connected to {ctx.graph_endpoint} - %%oc is ready.")


def set_graph_layout(direction="LR"):
    """The %%oc views' default layout for this kernel: left to right in the direction of the
    relationships, one column per hop, physics off. The force layout's default turns a decision
    with thirty neighbors into a spiral. direction="RL" lays a view out the other way, with the
    relationships' end on the left."""
    from IPython import get_ipython
    from IPython.utils.capture import capture_output
    with capture_output():   # the options magic echoes its whole JSON, even with --silent
        get_ipython().run_cell_magic("graph_notebook_vis_options", "--silent", json.dumps({
            "groups": {g: {"color": {"background": c, "border": c}} for g, c in GRAPH_GROUPS.items()},
            "layout": {"hierarchical": {"enabled": True, "direction": direction, "sortMethod": "directed",
                                        "levelSeparation": 380, "nodeSpacing": 92, "treeSpacing": 110}},
            "physics": {"enabled": False},
            "edges": {"smooth": {"enabled": True, "type": "cubicBezier", "forceDirection": "horizontal",
                                 "roundness": 0.35}, "font": {"size": 10, "align": "horizontal",
                                                              "background": "rgba(255,255,255,0.85)"}},
            # The widget draws circles whatever the shape option says, and each circle grows with
            # its label: keep labels short (-l 24 in the cells) and the spacing above their size.
            "nodes": {"font": {"size": 13, "face": "Arial"}}}))


# ---------------------------------------------------------------------------
# AgentCore Runtime — invoke the hosted agent
# ---------------------------------------------------------------------------
_SPINNING = {"on": False}


def _run_with_spinner(work, message="working", delay=0.0):
    """Run blocking ``work()`` in a background thread while animating a
    single-line spinner with elapsed seconds, so a long call never looks frozen.
    The spinner appears only once the call has taken `delay` seconds (so fast calls
    don't flicker), and never inside another spinner. Returns work()'s result and
    re-raises any exception it raised. Outside a notebook it just calls work()."""
    try:
        from IPython import get_ipython
        interactive = get_ipython() is not None
    except Exception:
        interactive = False
    if not interactive or _SPINNING["on"]:
        return work()

    import threading
    import itertools

    holder = {}

    def _target():
        try:
            holder["result"] = work()
        except BaseException as e:  # capture so we can re-raise on the main thread
            holder["exc"] = e

    t = threading.Thread(target=_target)
    _SPINNING["on"] = True
    try:
        t.start()
        start, shown = time.time(), False
        for frame in itertools.cycle("|/-\\"):
            if not t.is_alive():
                break
            if time.time() - start >= delay:
                print(f"\r   {frame} {message} ... {time.time() - start:.0f}s", end="", flush=True)
                shown = True
            time.sleep(0.15)
        t.join()
    finally:
        _SPINNING["on"] = False
    if shown:
        print("\r" + " " * 90 + "\r", end="", flush=True)  # clear the spinner line
    if "exc" in holder:
        raise holder["exc"]
    return holder.get("result")


def _invoke_once(ctx, payload):
    resp = ctx.agentcore.invoke_agent_runtime(
        agentRuntimeArn=ctx.AGENT_RUNTIME_ARN,
        payload=json.dumps(payload).encode("utf-8"),
        contentType="application/json",
        accept="application/json",
    )
    body = json.loads(resp["response"].read())
    if isinstance(body, dict) and body.get("error"):
        raise RuntimeError(f"Agent runtime returned an error: {body['error']}")
    return body


def invoke_agent_runtime(ctx, application_id=None, application=None, capture=True,
                         verbose=True):
    """Invoke the underwriting agent hosted in Bedrock AgentCore Runtime.

    Pass either application_id (the runtime loads it from DynamoDB) or a full
    application dict. `capture` controls whether the runtime writes decision
    evidence to DynamoDB. Returns the parsed response dict from the runtime."""
    if not ctx.AGENT_RUNTIME_ARN:
        raise RuntimeError(
            "No AgentCore Runtime ARN found in the stack outputs (AgentRuntimeArn). "
            "The runtime is created at stack deploy time by the AgentPackageBuild "
            "custom resource; check that the stack finished deploying.")
    payload = {"capture": capture}
    if application is not None:
        payload["application"] = application
    elif application_id is not None:
        payload["application_id"] = application_id
    else:
        raise ValueError("Pass application_id or application.")

    if verbose:
        target = application_id or (application or {}).get("application_id", "?")
        print(f"Invoking AgentCore Runtime for {target} ...")

    # The invoke blocks for the whole server-side ReAct loop (several Bedrock
    # calls, ~15-40s). Animate a spinner with elapsed time so the cell never
    # looks frozen. The real work runs in a thread; exceptions still propagate.
    body = _run_with_spinner(
        lambda: _invoke_once(ctx, payload),
        message="agent reasoning (credit, income, DTI, policy retrieval)",
    )
    if verbose:
        decision = (body.get("decision") or {}).get("decision", "?")
        print(f"✅ Runtime returned decision: {decision}")
    return body


def show_agentcore_observability(ctx, minutes=30, verbose=True):
    """Surface the OPERATIONAL telemetry AgentCore Runtime emits for free:
    recent X-Ray trace summaries (latency / errors) and the runtime's CloudWatch
    metrics (namespace AWS/Bedrock-AgentCore), plus a deep link to the GenAI
    Observability console.

    This is the 'did it work / how fast' view. It deliberately shows what the
    telemetry does NOT contain: the WHY behind a decision. That gap is what the
    DynamoDB + Neptune decision-evidence graph fills in the rest of the workshop.
    Degrades gracefully: telemetry can take a few minutes to appear."""
    from datetime import datetime, timezone, timedelta
    import pandas as pd
    from IPython.display import display, HTML

    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)

    display(HTML(f'<h4 style="margin:8px 0 2px">AgentCore Observability, operational '
                 f'telemetry (last {minutes} min)</h4>'))

    # 1) X-Ray trace summaries: how many invocations, latency, errors.
    try:
        summaries, tok = [], None
        while True:
            kwargs = {"StartTime": start, "EndTime": end}
            if tok:
                kwargs["NextToken"] = tok
            r = ctx.xray.get_trace_summaries(**kwargs)
            summaries.extend(r.get("TraceSummaries", []))
            tok = r.get("NextToken")
            if not tok or len(summaries) >= 100:
                break
        if summaries:
            durations = [s.get("Duration", 0) for s in summaries if s.get("Duration")]
            errors = sum(1 for s in summaries if s.get("HasError") or s.get("HasFault"))
            avg = (sum(durations) / len(durations)) if durations else 0
            xray_df = pd.DataFrame([
                {"metric": "invocations traced", "value": len(summaries)},
                {"metric": "avg latency (s)", "value": round(avg, 2)},
                {"metric": "max latency (s)", "value": round(max(durations), 2) if durations else 0},
                {"metric": "errors / faults", "value": errors},
            ])
            display(styled_table(xray_df, bar_cols=["value"], caption="X-Ray traces"))
        else:
            print("X-Ray traces: none yet (telemetry can lag a few minutes).")
    except Exception as e:
        print(f"X-Ray query unavailable: {e}")

    # 2) CloudWatch metrics AgentCore Runtime publishes for this agent (namespace
    #    AWS/Bedrock-AgentCore), summed over the window.
    try:
        wanted = {"Invocations": "Sum", "Latency": "Average", "SystemErrors": "Sum",
                  "UserErrors": "Sum", "Throttles": "Sum"}
        mine = [m for page in ctx.cloudwatch.get_paginator("list_metrics").paginate(Namespace="AWS/Bedrock-AgentCore")
                for m in page["Metrics"] if m["MetricName"] in wanted and
                any(d["Name"] == "Resource" and d["Value"] == ctx.AGENT_RUNTIME_ARN for d in m["Dimensions"])]
        queries = [{"Id": f"m{i}", "MetricStat": {"Metric": m, "Period": minutes * 60, "Stat": wanted[m["MetricName"]]},
                    "Label": m["MetricName"]} for i, m in enumerate(mine)]
        values = {}
        for r in (ctx.cloudwatch.get_metric_data(MetricDataQueries=queries[i:i + 500], StartTime=start, EndTime=end)
                  ["MetricDataResults"] for i in range(0, len(queries), 500)):
            for q in r:
                values[q["Label"]] = values.get(q["Label"], 0) + sum(q["Values"]) if q["Label"] != "Latency" \
                    else max(values.get("Latency", 0), max(q["Values"], default=0))
        if values:
            rows = [{"metric": n, "last %d min" % minutes: (f"{values[n]:,.0f} ms" if n == "Latency" else f"{values[n]:,.0f}")}
                    for n in wanted if n in values]
            display(styled_table(pd.DataFrame(rows), caption="CloudWatch, AWS/Bedrock-AgentCore, this agent's runtime"))
        else:
            print("CloudWatch metrics: none for this agent in AWS/Bedrock-AgentCore yet (they arrive a minute or two after a run).")
    except Exception as e:
        print(f"CloudWatch metrics unavailable: {e}")

    # 3) Clickable deep link to the managed GenAI Observability dashboard.
    url = (f"https://{ctx.region}.console.aws.amazon.com/cloudwatch/home"
           f"?region={ctx.region}#gen-ai-observability")
    display(HTML(
        f'<p style="margin:6px 0"><b>GenAI Observability dashboard</b> '
        f'(traces, spans, tool calls, latency): '
        f'<a href="{url}" target="_blank">{url}</a></p>'
        f'<p style="color:#a15c00;margin:4px 0"><b>Note:</b> this tells you the agent '
        f'RAN and how fast, not WHY it decided. That WHY is the decision-evidence '
        f'graph you build next.</p>'
    ))
    return url


# ---------------------------------------------------------------------------
# Notebook display helpers (styled output for query results and decisions)
# ---------------------------------------------------------------------------
# JupyterLab typesets anything between two $ signs in HTML output as math, so "$45,000 ... $280,000"
# in a table turns into italic math. HTML the helpers display carries these classes, which tell its
# MathJax (2 and 3) to leave the text alone.
NO_MATH = "tex2jax_ignore mathjax_ignore"


def plain_html(html):
    """Wrap HTML for display so JupyterLab doesn't typeset its dollar amounts as math."""
    return f'<div class="{NO_MATH}">{html}</div>'


def styled_table(df, bar_cols=(), decision_col="decision", status_col=None, caption=None):
    """Return a pandas Styler with light styling: blue in-cell bars for count
    columns, color-coded decision (deny=red, approve=green, escalate=amber) and
    audit status (COMPLETE=green, INCOMPLETE=amber), index hidden. Falls back to
    the plain DataFrame if styling is unavailable in this environment."""
    try:
        _dec = {"deny": "background-color:#f8d7da", "approve": "background-color:#d4edda",
                "escalate": "background-color:#fff3cd"}
        _stat = {"COMPLETE": "background-color:#d4edda", "INCOMPLETE": "background-color:#fff3cd"}
        sty = df.style.hide(axis="index")
        ints = [c for c in df.columns if str(df[c].dtype).startswith(("int", "Int"))]
        if ints:
            sty = sty.format({c: "{:,}" for c in ints})
        cols = [c for c in bar_cols if c in df.columns]
        if cols:
            sty = sty.bar(subset=cols, color="#5b9bd5")
        if decision_col in df.columns:
            sty = sty.map(lambda v: _dec.get(str(v), ""), subset=[decision_col])
        if status_col and status_col in df.columns:
            sty = sty.map(lambda v: _stat.get(str(v), ""), subset=[status_col])
        if caption:
            sty = sty.set_caption(caption)
        # JupyterLab right-aligns cells and centers tables by default; pin both left.
        sty = sty.set_table_styles([
            {"selector": "", "props": [("margin-left", "0 !important"),
                                       ("margin-right", "auto !important")]},
            {"selector": "th, td", "props": [("text-align", "left !important")]},
            {"selector": "caption", "props": [("text-align", "left"), ("caption-side", "top"),
                                              ("font-weight", "600"), ("padding-bottom", "4px")]},
        ], overwrite=False)
        return sty.set_table_attributes(f'class="{NO_MATH}"')
    except Exception:
        return df


def render_decision(response, application=None, verdict_only=False):
    """Render an agent decision as a color-coded banner plus a styled table of
    the policies it cited, instead of plain text. `response` may be the runtime
    response ({'decision': {...}, 'evaluation_id': ...}) or a bare decision dict.
    verdict_only=True shows just the outcome banner (no reasoning or tables)."""
    import pandas as pd
    from IPython.display import display, HTML

    d = response
    if isinstance(response, dict) and isinstance(response.get("decision"), dict):
        d = response["decision"]
    outcome = str(d.get("decision", "unknown")).lower()
    color = {"approve": "#2e7d32", "deny": "#c62828", "escalate": "#f9a825"}.get(outcome, "#555")

    head = ""
    if application:
        head = (f"{application.get('application_id', '')} &middot; "
                f"{application.get('applicant', {}).get('name', '')}")
    reasoning = "" if verdict_only else (d.get("reasoning") or "")[:320]
    display(HTML(plain_html(
        f'<div style="border-left:6px solid {color};padding:8px 14px;margin:6px 0;'
        f'background:#fafafa;font-family:sans-serif">'
        f'<div style="font-size:0.8em;color:#777">{head}</div>'
        f'<div style="font-size:1.3em;font-weight:700;color:{color}">'
        f'DECISION: {outcome.upper()}</div>'
        f'<div style="margin-top:4px;color:#333">{reasoning}</div></div>'
    )))
    if verdict_only:
        return
    pols = d.get("policies_cited") or []
    if pols:
        display(styled_table(pd.DataFrame({"policy cited": pols}), caption="Policies cited"))
    if d.get("policies_violated"):
        display(styled_table(pd.DataFrame({"policy not met": d["policies_violated"]}),
                             caption="Policies the application failed (violated)"))
    if d.get("risk_factors"):
        display(styled_table(pd.DataFrame({"risk factor": d["risk_factors"]}),
                             caption="Risk factors"))
    if d.get("adverse_action_reasons"):
        display(styled_table(pd.DataFrame({"adverse action reason (ECOA)": d["adverse_action_reasons"]}),
                             caption="Adverse action reasons"))


def summarize_evidence(item):
    """One-line, human-readable summary of what a tool returned at one captured
    step (the evidence the agent had in front of it), from the stored
    observation_summary. Falls back gracefully when the stored JSON was truncated."""
    import re
    action = item.get("action", "")
    raw = item.get("observation_summary") or ""
    if action == "FINAL_DECISION":
        return f"decision recorded: {str(item.get('outcome', '?')).upper()}"
    try:
        obs = json.loads(raw)
    except (ValueError, TypeError):
        obs = None
    if isinstance(obs, dict) and obs.get("error"):
        return f"error: {obs['error']}"

    if action == "retrieve_lending_policy":
        m = re.search(r'"query"\s*:\s*"([^"]+)"', item.get("action_input") or "")
        query = m.group(1) if m else (obs or {}).get("query", "")
        refs = sorted(item.get("retrieved_policy_ids") or
                      set(re.findall(r"HUD 4000\.1 [IVX]+\.[A-Z]\.\d+\.[a-z]|12 CFR \d{4}\.\d+", raw)))
        found = ", ".join(refs) if refs else "no policy matched"
        return f'searched "{query}" -> {found}' if query else f"retrieved {found}"
    if not isinstance(obs, dict):
        return raw[:120]
    if action == "pull_credit_report":
        return (f"credit score {obs.get('credit_score')}, "
                f"{obs.get('derogatory_marks', 0)} derogatory marks, "
                f"utilization {obs.get('credit_utilization_pct', '?')}")
    if action == "verify_income":
        return (f"verified income ${obs.get('verified_annual_income', 0):,.0f}/yr "
                f"(stated ${obs.get('stated_annual_income', 0):,.0f}), "
                f"{obs.get('employment_status', 'unknown')}")
    if action == "calculate_dti":
        return (f"back-end DTI {obs.get('back_end_dti_pct', '?')} "
                f"(QM limit {obs.get('qm_threshold', '43%')}), "
                f"front-end {obs.get('front_end_dti_pct', '?')}")
    if action == "evaluate_collateral":
        if obs.get("ltv_ratio") is None:
            return "unsecured loan, no collateral evaluated"
        text = f"LTV {obs.get('ltv_pct', '?')} on appraised ${obs.get('appraised_value', 0):,.0f}"
        return text + (f", PMI required: {obs['pmi_required']}" if obs.get("pmi_required") is not None else "")
    return raw[:120]


# ---------------------------------------------------------------------------
# Exercise answers (packaged into the MCP server by the Kiro notebook)
# ---------------------------------------------------------------------------
SOLUTION_DIR = "solution"


def save_answer(name, answer):
    """Save one completed exercise to solution/, next to the notebooks: a function
    as its source (name.py), an openCypher query as name.cypher, exactly as it ran.
    The exercise cells call this only once your answer passes; the MCP server deploy
    (Kiro notebook, Cell K.2) packages these files unchanged, and the fingerprint printed
    here is the one the MCP server reports for the code it runs."""
    import inspect
    from pathlib import Path
    from agent.evidence import sha256

    out = Path(SOLUTION_DIR)
    out.mkdir(exist_ok=True)
    if callable(answer):
        path, text = out / f"{name}.py", inspect.getsource(answer)
    else:
        path, text = out / f"{name}.cypher", str(answer)
    path.write_text(text)
    print(f"(Saved your answer to {path}, sha256 {sha256(text)[:12]}: it is deployed with your MCP server.)")
    return path


MCP_RUNTIME_NAME = "dat408EvidenceMCP"


def mcp_endpoint_url(runtime_arn, region):
    """The URL MCP clients use for an MCP server hosted on AgentCore Runtime. Callers
    authenticate with IAM (SigV4); Kiro CLI does that through mcp-proxy-for-aws."""
    from urllib.parse import quote
    return (f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/"
            f"{quote(runtime_arn, safe='')}/invocations?qualifier=DEFAULT")


def start_mcp_deploy(ctx):
    """Package your saved answers as the MCP server and deploy it to AgentCore
    Runtime, in the background (about a minute). Refuses if an answer is missing.
    Prints the fingerprint of each answer it sends; finish_mcp_deploy() checks the
    deployed package against them."""
    import threading
    import boto3
    from botocore.config import Config
    from agent.evidence import ALL_ANSWERS as ANSWERS, read_answers, sha256

    try:
        answers = read_answers(SOLUTION_DIR)
    except FileNotFoundError as e:
        print(f"Not deployed. {e}.")
        print("Open each exercise listed, reveal its solution if you need to, and run its cell "
              "until it passes; it saves the answer. Then run this cell again.")
        return None
    sent = {name: sha256(text) for name, text in answers.items()}
    print("Deploying the MCP server from these answers, exactly as your cells saved them:")
    for name, digest in sent.items():
        print(f"   solution/{ANSWERS[name][0]:<28} sha256 {digest[:12]}")

    client = boto3.client("lambda", region_name=ctx.region,
                          config=Config(read_timeout=900, retries={"max_attempts": 0}))
    event = {"action": "deploy_mcp", "answers": answers,
             "environment": {"GRAPH_ID": ctx.GRAPH_ID, "TRACES_TABLE": ctx.TRACES_TABLE,
                             "AGENT_RUNTIME_ARN": ctx.AGENT_RUNTIME_ARN, "DAT408_REGION": ctx.region}}
    deploy = {"sent": sent, "started": time.time()}

    def _run():
        try:
            resp = client.invoke(FunctionName=ctx.MCP_DEPLOY_FUNCTION,
                                 Payload=json.dumps(event).encode("utf-8"))
            body = json.loads(resp["Payload"].read())
            if resp.get("FunctionError"):
                raise RuntimeError(body.get("errorMessage", body))
            deploy["result"] = body
        except Exception as e:
            deploy["error"] = e

    deploy["thread"] = threading.Thread(target=_run, daemon=True)
    deploy["thread"].start()
    ctx.mcp_deploy = deploy
    print(f"\nBuilding {MCP_RUNTIME_NAME} in the background (about a minute).")
    return deploy


def finish_mcp_deploy(ctx):
    """Wait for the MCP server deploy, then confirm the deployed package holds exactly
    the answers that were sent. Returns the MCP server's runtime ARN."""
    from agent.evidence import ALL_ANSWERS as ANSWERS
    deploy = getattr(ctx, "mcp_deploy", None)
    if not deploy:
        print("Run the deploy cell (start_mcp_deploy) first.")
        return None
    _run_with_spinner(deploy["thread"].join, message=f"building {MCP_RUNTIME_NAME}")
    if "error" in deploy:
        print(f"❌ The MCP server deploy failed: {deploy['error']}")
        return None
    result = deploy["result"]
    import hashlib
    from pathlib import Path
    import agent.evidence
    rows, all_match = [], True
    runner = hashlib.sha256(Path(agent.evidence.__file__).read_bytes()).hexdigest()
    all_match &= runner == result["evidence_py_sha256"]
    rows.append({"answer": "agent/evidence.py (the runner)", "your notebook": runner[:12],
                 "deployed package": result["evidence_py_sha256"][:12],
                 "match": "✅" if runner == result["evidence_py_sha256"] else "❌"})
    for name, digest in deploy["sent"].items():
        packaged = result["answers"].get(name)
        all_match &= packaged == digest
        rows.append({"answer": f"solution/{ANSWERS[name][0]}", "your notebook": digest[:12],
                     "deployed package": (packaged or "missing")[:12],
                     "match": "✅" if packaged == digest else "❌"})
    import pandas as pd
    from IPython.display import display
    display(styled_table(pd.DataFrame(rows), caption="What the MCP server runs, compared with what your notebook ran"))
    if not all_match:
        print("❌ The deployed package does not match your answers. Run the deploy cell again.")
        return None
    arn = result["AgentRuntimeArn"]
    print(f"✅ MCP server is live: {MCP_RUNTIME_NAME}, built in {time.time() - deploy['started']:.0f}s")
    print(f"   Runtime ARN: {arn}")
    print("   Every tool result reports the sha256 of the answer it ran; Kiro's results show the same values.")
    ctx.MCP_RUNTIME_ARN = arn
    return arn


def mcp_server_status(ctx):
    """K.3: is the MCP server up, where is it, and what are the fingerprints of
    the answers it runs (the same ones Kiro's results will show)."""
    import boto3
    import pandas as pd
    from IPython.display import display
    from agent.evidence import ALL_ANSWERS as ANSWERS, read_answers, sha256

    control = boto3.client("bedrock-agentcore-control", region_name=ctx.region)
    rt = next((r for page in control.get_paginator("list_agent_runtimes").paginate()
               for r in page["agentRuntimes"] if r["agentRuntimeName"] == MCP_RUNTIME_NAME), None)
    if rt is None:
        print("No MCP server yet: run Cell K.2 in the Kiro notebook, then this cell again.")
        return None
    mark = "✅" if rt["status"] == "READY" else "⏳"
    print(f"{mark} {MCP_RUNTIME_NAME} is {rt['status']}")
    print(f"   MCP endpoint (connect.sh finds it for you in Kiro):\n   "
          f"{mcp_endpoint_url(rt['agentRuntimeArn'], ctx.region)}\n")
    try:
        answers = read_answers(SOLUTION_DIR)
    except FileNotFoundError as e:
        print(f"{e}.")
        return rt
    display(styled_table(pd.DataFrame([
        {"answer": f"solution/{ANSWERS[n][0]}", "where you wrote it": ANSWERS[n][1],
         "sha256 (first 12)": sha256(t)[:12]} for n, t in answers.items()]),
        caption="Your answers: Kiro's results will report these fingerprints"))
    return rt


def kiro_ide_link(ctx):
    """K.6: a link to this account's Kiro IDE (the Kiro stack's URL output)."""
    import boto3
    from IPython.display import HTML, display

    url = None
    try:
        cfn = boto3.client("cloudformation", region_name=ctx.region)
        for page in cfn.get_paginator("describe_stacks").paginate():
            for st in page["Stacks"]:
                for o in st.get("Outputs", []):
                    if o["OutputKey"] == "URL" and ".cloudfront.net" in o["OutputValue"]:
                        url = o["OutputValue"]
    except Exception as e:
        print(f"(This notebook can't look up the Kiro stack: {type(e).__name__}. Use Event Outputs.)")
    if url:
        display(HTML(f'<p style="font-size:1.1em"><a href="{url}" target="_blank" rel="noopener">'
                     f'<b>Open your Kiro IDE</b></a> (opens in a new tab)</p>'))
    else:
        print("No Kiro link found from here. Use Event Outputs on the workshop page instead (below).")
    return url


# ---------------------------------------------------------------------------
# Pictures: graph views (%%oc) and charts, in one palette across the notebooks
# ---------------------------------------------------------------------------
INK, INK_2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]          # categorical slots 1-3, fixed order
OUTCOME = {"approve": "#0ca30c", "deny": "#d03b3b", "escalate": "#fab219"}   # status, always labeled
GRAPH_GROUPS = {   # node colors in the %%oc views, by group
    "Application": "#86b6ef", "Evaluation": "#b7d3f6", "Step": "#cde2fb", "Evidence": "#9ec5f4",
    "Policy": "#c3c2b7", "Tool": "#e1e0d9", "Band": "#e1e0d9", "Chunk": "#f0efec",
    **OUTCOME, "VIOLATED": "#d03b3b", "UNGROUNDED": "#d03b3b",
    "fails": "#d03b3b", "needs_review": "#fab219", "meets": "#cde2fb",       # findings, by result
    # the lineage, as in Cell 3.3's drawing (agent/lineage_view.py): artifacts by kind
    "Version": "#5b3cc4", "Notice": "#6b3a2e", "Artifact": "#e3e1da", "extraction": "#c3c2b7",
    "employer_record": "#9ec5f4", "income": "#e3e1da", "ratios": "#e3e1da", "business_income": "#e3e1da",
}


def draw_graph(ctx, query, params=None, display=None, group_by=None, highlight=None, height=420, red=(),
               tooltip=None, layered=False, legend=None, hierarchical=None, chips=None):
    """Draw a subgraph with Neptune's graph-notebook visualizer (%%oc). `query` returns
    (src, rel, dst) rows; $name placeholders are filled from `params`. `display` and
    `group_by` map a label to the property shown / used for color, `tooltip` to the property
    shown on hover, and `highlight` maps a group value (for example a policy id) to a color.
    Requires enable_graph_notebook."""
    import re
    from IPython import get_ipython
    ip = get_ipython()
    for name, value in (params or {}).items():
        if not re.fullmatch(r"[A-Za-z0-9 ._:-]+", str(value)):
            raise ValueError(f"Unexpected value for ${name}: {value!r}")
        query = query.replace(f"${name}", f"'{value}'")
    import ipywidgets as widgets
    from IPython.display import display as _display
    # Defaults: every node labeled by what it means, colored by type (decisions by outcome),
    # policies grey except the ones listed in `red`.
    display = display or _DISPLAY
    group_by = group_by or _GROUP_BY
    tooltip = tooltip or _TOOLTIP
    highlight = {**_policy_colors(red), **(highlight or {})}
    groups = {g: {"color": {"background": c, "border": c}} for g, c in {**GRAPH_GROUPS, **highlight}.items()}
    # %%oc splits its arguments on whitespace, so the JSON must contain none.
    compact = lambda d: json.dumps(d, separators=(",", ":"))
    # layered: left to right in the direction of the relationships (the start on the left,
    # each hop one column further right), physics off so nothing drifts, longer labels.
    args = ["-l 40", "-rel 22"] if layered else ["-l 24", "-rel 18", "-sp", "-sd 1500"]
    if display:
        args.append(f"-d {compact(display)}")
    if group_by:
        args.append(f"-g {compact(group_by)}")
    if tooltip:
        args.append(f"-t {compact(tooltip)}")
    # graph-notebook clears the cell's output before each magic; drawing inside an Output
    # widget keeps the text and charts printed above the graph.
    out = widgets.Output()
    # vis-network's hover box doesn't wrap, so a long thought or observation runs off the view.
    from IPython.display import HTML
    _display(HTML("<style>div.vis-tooltip{white-space:pre-wrap!important;max-width:460px;"
                  "word-break:break-word;font-size:12px;line-height:1.35}</style>"))
    # The legend is a widget of its own: graph-notebook clears text printed before it draws.
    if legend:
        import html as _html
        chip = lambda color, text: (f'<span style="display:inline-block;width:11px;height:11px;border-radius:3px;'
                                    f'background:{color};margin:0 4px 0 12px;vertical-align:-1px"></span>{text}')
        chips = chips or [("#d03b3b", "deny / fails / failed policy"), ("#fab219", "escalate / needs review"),
                          ("#0ca30c", "approve"), ("#9ec5f4", "evidence"), ("#c3c2b7", "policy")]
        box = (f'<div style="background:#f6f5f2;border:1px solid #e1e0d9;border-radius:6px;padding:8px 12px;'
               f'margin:4px 0 6px;font-size:13.5px;color:#0b0b0b;line-height:1.5">'
               f'<b>How to read this graph:</b> {_html.escape(legend)}<br>'
               f'<span style="color:#52514e">{"".join(chip(c, t) for c, t in chips)}</span></div>')
        _display(widgets.VBox([widgets.HTML(box), out]))
    else:
        _display(out)
    with out:
        # The options magic echoes the whole settings JSON even with --silent; keep it quiet.
        from IPython.utils.capture import capture_output
        with capture_output():
            ip.run_cell_magic("graph_notebook_vis_options", "--silent", json.dumps({
                "groups": groups,
                # Set on every draw: the options persist across cells in the kernel.
                "layout": {"hierarchical": {"enabled": layered, "direction": "LR", "sortMethod": "directed",
                                            "levelSeparation": 230, "nodeSpacing": 90, **(hierarchical or {})}},
                "physics": {"enabled": not layered},
                "edges": {"smooth": {"enabled": True, "type": "cubicBezier" if layered else "dynamic",
                                     "forceDirection": "horizontal", "roundness": 0.4}}}))
        ip.run_cell_magic("oc", " ".join(a for a in args if a), query)


_GROUP_BY = {"Application": "~labels", "Evaluation": "~labels", "Step": "~labels", "Evidence": "~labels",
             "Decision": "outcome", "Policy": "id", "Tool": "~labels", "Band": "~labels", "Chunk": "~labels",
             "Finding": "result"}
_DISPLAY = {"Application": "id", "Evaluation": "~labels", "Step": "action", "Evidence": "tool",
            "Decision": "outcome", "Policy": "id", "Band": "id", "Finding": "result"}
# What hovering a node shows: what the agent thought, what came back, why it decided.
_TOOLTIP = {"Application": "id", "Evaluation": "started_at", "Step": "thought", "Evidence": "observation",
            "Decision": "reasoning", "Policy": "id", "Band": "id", "Finding": "statement"}


def _policy_colors(red=()):
    """Every policy grey, except the ones that matter in this view."""
    try:
        ids = [p["policy_id"] for p in json.load(open("agent/policy_manifest.json"))["policies"].values()]
    except OSError:
        ids = []
    return {**{pid: "#c3c2b7" for pid in ids}, **{pid: GRAPH_GROUPS["VIOLATED"] for pid in red}}


def _axes(title, width=7.5, height=2.6):
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(width, height), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(colors=MUTED, labelsize=9, length=0)
    ax.set_title(title, loc="left", color=INK, fontsize=11, fontweight="600", pad=10)
    return fig, ax


def bar_chart(labels, values, title, unit="", log=False, colors=None, legend=None, fmt=None):
    """Horizontal bars, one row per label, value labels at the bar ends. `colors` is one
    color for all bars or one per bar; `legend` maps a color to what it means."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    labels, values = list(labels)[::-1], list(values)[::-1]
    cols = (colors[::-1] if isinstance(colors, list) else [colors or SERIES[0]] * len(values))
    fig, ax = _axes(title, height=0.45 * len(values) + 1.2)
    ax.barh(labels, values, height=0.55, color=cols, edgecolor=SURFACE, linewidth=2)
    if log:
        ax.set_xscale("log")
        # Plain numbers on a log axis (1, 10, 100, 1,000), not powers of ten.
        ax.xaxis.set_major_formatter(lambda v, _: f"{v:,.0f}" if v >= 1 else f"{v:g}")
    elif max(values) >= 1000:
        ax.xaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", colors=INK_2, labelsize=10)
    for y, v in enumerate(values):
        text = fmt.format(v) if fmt else (f"{v:,.1f}" if abs(v) < 100 and v != int(v) else f"{v:,.0f}")
        ax.text(v * (1.15 if log else 1.0), y, "  " + text + (f" {unit}" if unit else ""),
                va="center", color=INK_2, fontsize=9)
    ax.set_xlim(right=max(values) * (12 if log else 1.22))
    if legend:
        # Below the axis, where no bar can reach it.
        ax.legend(handles=[Patch(color=c, label=l) for c, l in legend.items()], frameon=False,
                  fontsize=9, labelcolor=INK_2, loc="upper left", bbox_to_anchor=(0, -0.14),
                  ncol=len(legend), borderaxespad=0, handlelength=1.2)
    plt.tight_layout()
    plt.show()


PLANTED_APPLICATION_ID = "LA-AUDIT-TEST"


def plant_unsupported_citation(ctx, wait_seconds=90, verbose=True):
    """Write one known-bad evaluation through the real pipeline (DynamoDB ->
    Streams -> Lambda -> Neptune): the agent retrieved only HUD 4000.1 II.A.5.d
    (qualifying ratios), but its decision also cites HUD 4000.1 II.A.5.b (income
    requirements), a policy it never retrieved. Cells 4.1 and 4.2 use it
    to prove the cited-but-never-retrieved query actually catches something.
    Fixed ids, so the graph never holds more than one copy. Returns once the
    decision is in the graph."""
    table = ctx.dynamodb.Table(ctx.TRACES_TABLE)
    eval_id = "audit-test-0001"
    # Delete first so the writes below are INSERTs: the stream trigger only passes
    # INSERT events, and an overwrite (MODIFY) would never reach the Lambda. This
    # makes re-running safe, e.g. after fixing a broken transform.
    existed = False
    for sk in ("STEP#000", "STEP#001"):
        old = table.delete_item(Key={"PK": f"EVAL#{eval_id}", "SK": sk}, ReturnValues="ALL_OLD")
        existed = existed or "Attributes" in old
    deadline = time.time() + wait_seconds

    def _decision_citations():
        found = ctx.neptune_query(
            "MATCH (d:Decision {id: $id})-[:CITED_POLICY]->(p:Policy) RETURN count(p) AS n",
            {"id": f"{eval_id}_decision"})["results"]
        return found[0].get("n", 0) if found else 0

    # On a re-run, wait for the stream's REMOVEs to clear the previous copy from the
    # graph; otherwise the wait below would see the old decision and return before
    # the new one exists.
    def clear_previous():
        while existed and _decision_citations() and time.time() < deadline:
            time.sleep(3)
    _run_with_spinner(clear_previous, "clearing the previous planted copy from the graph")
    # The passages its one retrieval read: real qualifying-ratio passages of HUD 4000.1
    # II.A.5.d, so its evidence is linked to the policy text (READ) like a live evaluation's.
    chunk_ids = [r["id"] for r in ctx.neptune_query("""
        MATCH (c:Chunk) WHERE c.`metadata_x-amz-bedrock-kb-source-uri` CONTAINS 'HUD-4000.1-II.A.5.d'
          AND NOT c.text STARTS WITH '# '
          AND (c.text CONTAINS 'Qualifying Ratios' OR c.text CONTAINS '37/47')
        RETURN id(c) AS id ORDER BY id LIMIT 3""")["results"]]
    now = datetime.now(timezone.utc).isoformat()
    ttl = int(time.time()) + 90 * 86400
    base = {"evaluation_id": eval_id, "application_id": PLANTED_APPLICATION_ID,
            "step_timestamp": now, "ttl": ttl}
    table.put_item(Item={**base, "PK": f"EVAL#{eval_id}", "SK": "STEP#000", "step_num": 0,
                         "action": "retrieve_lending_policy", "is_decision": False,
                         "thought": "Look up the qualifying ratio limits.",
                         "action_input": '{"query": "qualifying ratio limits for manual underwriting"}',
                         "observation_summary": f'{{"tool": "retrieve_lending_policy", "num_results": {len(chunk_ids)}}}',
                         "retrieved_policy_ids": ["HUD 4000.1 II.A.5.d"],
                         "retrieved_chunk_ids": chunk_ids,
                         "retrieved_policy_versions": {
                             "HUD 4000.1 II.A.5.d": "Update 18, issued 2026-08-12; section effective 2026-11-10"}})
    table.put_item(Item={**base, "PK": f"EVAL#{eval_id}", "SK": "STEP#001", "step_num": 1,
                         "action": "FINAL_DECISION", "is_decision": True,
                         "thought": "Final decision: deny", "action_input": "{}",
                         "observation_summary": "{}", "outcome": "deny",
                         "reasoning": "Qualifying ratios exceed the manual-underwriting limits, and "
                                      "employment history is shorter than two years.",
                         "policies_cited": ["HUD 4000.1 II.A.5.d viii", "HUD 4000.1 II.A.5.b"],
                         "policies_violated": ["HUD 4000.1 II.A.5.d viii", "HUD 4000.1 II.A.5.b"],
                         "risk_factors": ["qualifying ratios above limit", "short employment history"],
                         "adverse_action_reasons": ["Debt-to-income ratio above the program maximum"]})
    if verbose:
        print(f"Planted evaluation {eval_id} for {PLANTED_APPLICATION_ID}: retrieved HUD 4000.1 II.A.5.d, "
              f"cites HUD 4000.1 II.A.5.d and II.A.5.b.")
    deadline = time.time() + wait_seconds

    def arrived():
        while time.time() < deadline:
            if _decision_citations() >= 2:
                return True
            time.sleep(5)
        return False
    if _run_with_spinner(arrived, "waiting for your Lambda to project it into the graph"):
        if verbose:
            print("✅ It has flowed through the stream into the graph.")
    else:
        print("The planted decision has not reached the graph yet; wait a few seconds and re-run.")
    return eval_id
