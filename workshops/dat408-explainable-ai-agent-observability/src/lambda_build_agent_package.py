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
lambda_build_agent_package.py

CloudFormation custom resource handler that owns the DAT408 underwriting agent's
Amazon Bedrock AgentCore Runtime end to end: it builds the deployment .zip
(runtime_app.py at the zip root + the `agent/` package + arm64 dependencies),
uploads it to S3, and CREATES (or updates, or deletes) the AgentCore Runtime via
the bedrock-agentcore-control API. It returns the runtime's ARN as a custom
resource attribute (Fn::GetAtt AgentPackageBuild.AgentRuntimeArn).

NETWORK MODE: PUBLIC. The DAT408 agent talks only to public AWS service APIs
(Bedrock, DynamoDB, Neptune Analytics with PublicConnectivity, Bedrock Agent
runtime for KB retrieval), so the runtime needs no customer VPC. This drops the
entire VPC/subnet/NAT/AZ-filtering apparatus that a VPC-attached runtime (e.g. a
runtime reaching an in-VPC Neptune cluster) would require.

WHY A CUSTOM RESOURCE (and not a native AWS::BedrockAgentCore::Runtime):
CloudFormation cannot run `pip install` to resolve the agent's arm64
dependencies into the S3 zip that CodeConfiguration.Code.S3 must point at. This
Lambda builds and uploads that object, then calls create/update_agent_runtime,
and returns only the runtime ARN as a plain scalar attribute.

MCP SERVER (direct invoke, not CloudFormation): at the end of Module 3 the
notebook invokes this Lambda with {"action": "deploy_mcp", "answers": {...}}: the
attendee's saved exercise answers, as text. It builds a second runtime,
dat408EvidenceMCP, with the MCP server protocol: mcp_server.py at the zip root,
the same agent/ package, and the answers under solution/ exactly as received. It
returns the sha256 of every answer it wrote, so the notebook can confirm that what
it deployed is what it ran.

DELETE behaviour: on stack Delete this handler deletes the AgentCore Runtime it
created (looked up by name) and the MCP server runtime, then returns SUCCESS.
"""

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

import boto3

AGENT_DEPENDENCIES = ["boto3", "bedrock-agentcore"]
# The MCP server needs the MCP Python SDK (FastMCP streamable HTTP), not the
# AgentCore SDK.
MCP_DEPENDENCIES = ["boto3", "mcp>=1.10,<2"]
MCP_ENTRY_FILE = "mcp_server.py"
# Environment the notebook may set on the MCP runtime (nothing else is passed on).
MCP_ENV_KEYS = {"GRAPH_ID", "TRACES_TABLE", "AGENT_RUNTIME_ARN", "DAT408_REGION"}
TARGET_PYTHON_VERSION = "3.12"

# How long to wait (seconds) for the runtime to reach READY / finish deleting.
# Kept under the Lambda's own Timeout so the handler always has time to POST its
# CloudFormation response before the Lambda is killed.
READY_TIMEOUT_SECONDS = 600
DELETE_TIMEOUT_SECONDS = 300

# agent package files that must NOT ship in the runtime zip: workshop.py pulls in
# notebook-only packages (graph_notebook, ipywidgets) in its function bodies and
# is never imported by runtime_app.py. Each runtime also leaves out the other's
# entrypoint.
SKIP_AGENT_FILES = {"workshop.py", MCP_ENTRY_FILE}
SKIP_MCP_FILES = {"workshop.py", "runtime_app.py"}


def _download_agent_dir(bucket, prefix, dest_dir):
    """Download the whole agent/ package from the Workshop Studio assets bucket
    (s3://<bucket>/<prefix>notebooks/agent/) into dest_dir. Returns the local
    agent dir path."""
    s3 = boto3.client("s3")
    src_prefix = f"{prefix.rstrip('/')}/notebooks/agent/"
    agent_dir = os.path.join(dest_dir, "agent")
    os.makedirs(agent_dir, exist_ok=True)
    paginator = s3.get_paginator("list_objects_v2")
    found = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=src_prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel = key[len(src_prefix):]
            if not rel or rel.endswith("/") or "__pycache__" in rel:
                continue
            local = os.path.join(agent_dir, rel)
            os.makedirs(os.path.dirname(local), exist_ok=True)
            print(f"Downloading s3://{bucket}/{key}")
            s3.download_file(bucket, key, local)
            found += 1
    if found == 0:
        raise RuntimeError(
            f"No agent source found under s3://{bucket}/{src_prefix}. "
            "Did sync-assets.sh run and Workshop Studio upload static/code/agent?")
    return agent_dir


def _build_zip(agent_dir, entry_file, out_zip, dependencies=AGENT_DEPENDENCIES,
               skip=SKIP_AGENT_FILES, extra_files=None):
    """Build the deployment zip:
      - entry_file (runtime_app.py or mcp_server.py) at the ZIP ROOT (AgentCore entryPoint),
      - every other agent module under agent/ so `from agent.* import ...` works,
      - extra_files ({path in zip: text}) written exactly as given,
      - the arm64 dependencies at the root.
    Excludes __pycache__/.pyc/.pyo (a confirmed AgentCore rejection reason) and
    the modules in `skip`."""
    with tempfile.TemporaryDirectory() as deps_tmp:
        deps_dir = os.path.join(deps_tmp, "deps")
        os.makedirs(deps_dir, exist_ok=True)

        cmd = [
            sys.executable, "-m", "pip", "install",
            "--platform", "manylinux2014_aarch64",
            "--python-version", TARGET_PYTHON_VERSION,
            "--implementation", "cp",
            "--only-binary=:all:",
            "--target", deps_dir,
            *dependencies,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                "Failed to resolve arm64 dependencies for the agent zip.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}")

        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            # agent package modules
            for root, dirs, files in os.walk(agent_dir):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    if f.endswith((".pyc", ".pyo")) or f in skip:
                        continue
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, agent_dir)
                    if rel == entry_file:
                        arc = entry_file            # entrypoint at zip root
                    else:
                        arc = os.path.join("agent", rel)   # under the package
                    zf.write(full, arcname=arc)
            for arc, text in (extra_files or {}).items():
                zf.writestr(arc, text.encode("utf-8"))
            # dependencies at the root
            for root, dirs, files in os.walk(deps_dir):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    if f.endswith((".pyc", ".pyo")):
                        continue
                    full = os.path.join(root, f)
                    arc = os.path.relpath(full, deps_dir)
                    zf.write(full, arcname=arc)
    return out_zip


def _find_runtime(control, name):
    paginator = control.get_paginator("list_agent_runtimes")
    for page in paginator.paginate():
        for rt in page.get("agentRuntimes", []):
            if rt.get("agentRuntimeName") == name:
                return rt
    return None


def _wait_for_ready(control, runtime_arn, timeout_seconds=READY_TIMEOUT_SECONDS,
                    poll_seconds=10):
    import time
    runtime_id = runtime_arn.split("/")[-1]
    t0 = time.time()
    last_status = None
    while time.time() - t0 < timeout_seconds:
        resp = control.get_agent_runtime(agentRuntimeId=runtime_id)
        status = resp.get("status")
        if status != last_status:
            print(f"  [{time.time() - t0:5.0f}s] status: {status}")
            last_status = status
        if status == "READY":
            print("AgentCore Runtime is READY.")
            return resp
        if status in ("CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED"):
            raise RuntimeError(f"AgentCore Runtime deployment failed: {resp}")
        time.sleep(poll_seconds)
    raise TimeoutError(
        f"AgentCore Runtime {runtime_arn} did not reach READY in {timeout_seconds}s")


def _wait_for_deleted(control, runtime_arn, timeout_seconds=DELETE_TIMEOUT_SECONDS,
                      poll_seconds=5):
    import time
    runtime_id = runtime_arn.split("/")[-1]
    t0 = time.time()
    while time.time() - t0 < timeout_seconds:
        try:
            control.get_agent_runtime(agentRuntimeId=runtime_id)
        except control.exceptions.ResourceNotFoundException:
            print(f"  Deleted {runtime_arn}.")
            return
        time.sleep(poll_seconds)
    raise TimeoutError(
        f"AgentCore Runtime {runtime_arn} did not finish deleting in {timeout_seconds}s")


def _create_or_update_runtime(control, runtime_name, artifact, network_config,
                              role_arn, description, environment_variables,
                              protocol="HTTP"):
    """Create on first deploy, update on later deploys. A runtime stuck in a
    *_FAILED state is deleted and recreated."""
    existing = _find_runtime(control, runtime_name)
    if existing and existing.get("status") in (
            "CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED"):
        existing_arn = existing["agentRuntimeArn"]
        print(f"Existing runtime {existing_arn} is {existing['status']}; deleting before recreating.")
        control.delete_agent_runtime(agentRuntimeId=existing_arn.split("/")[-1])
        _wait_for_deleted(control, existing_arn)
        existing = None

    if existing:
        existing_arn = existing["agentRuntimeArn"]
        print(f"Updating existing AgentCore Runtime: {existing_arn}")
        resp = control.update_agent_runtime(
            agentRuntimeId=existing_arn.split("/")[-1],
            agentRuntimeArtifact=artifact,
            networkConfiguration=network_config,
            roleArn=role_arn,
            environmentVariables=environment_variables,
            protocolConfiguration={"serverProtocol": protocol},
        )
        return resp.get("agentRuntimeArn", existing_arn)

    print(f"Creating AgentCore Runtime: {runtime_name}")
    resp = control.create_agent_runtime(
        agentRuntimeName=runtime_name,
        agentRuntimeArtifact=artifact,
        networkConfiguration=network_config,
        roleArn=role_arn,
        description=description,
        environmentVariables=environment_variables,
        protocolConfiguration={"serverProtocol": protocol},
    )
    return resp["agentRuntimeArn"]


def build_and_deploy(props, region):
    assets_bucket = props["AssetsBucketName"]
    assets_prefix = props["AssetsBucketPrefix"]
    data_bucket = props["DataBucket"]
    entry_file = props.get("EntryPoint", "runtime_app.py")
    runtime_name = props["AgentRuntimeName"]
    role_arn = props["RoleArn"]
    description = props.get("Description", "DAT408 underwriting agent (AgentCore Runtime)")
    deploy_key = props.get("DeployKey", "dat408/agents/underwriting-agent/agent_package.zip")
    environment_variables = props.get("EnvironmentVariables", {}) or {}

    with tempfile.TemporaryDirectory() as tmp:
        agent_dir = _download_agent_dir(assets_bucket, assets_prefix, tmp)
        if not os.path.exists(os.path.join(agent_dir, entry_file)):
            raise RuntimeError(
                f"Entry file {entry_file!r} not found in the downloaded agent package.")
        zip_path = os.path.join(tmp, "agent_package.zip")
        _build_zip(agent_dir, entry_file, zip_path)

        s3 = boto3.client("s3")
        print(f"Uploading built agent zip to s3://{data_bucket}/{deploy_key}")
        s3.upload_file(zip_path, data_bucket, deploy_key)

    artifact = {
        "codeConfiguration": {
            "code": {"s3": {"bucket": data_bucket, "prefix": deploy_key}},
            "entryPoint": [entry_file],
            "runtime": "PYTHON_3_12",
        }
    }
    network_config = {"networkMode": "PUBLIC"}

    control = boto3.client("bedrock-agentcore-control", region_name=region)
    runtime_arn = _create_or_update_runtime(
        control, runtime_name, artifact, network_config, role_arn,
        description, environment_variables)
    print(f"AgentCore Runtime ARN: {runtime_arn}")
    _wait_for_ready(control, runtime_arn)

    return {"Bucket": data_bucket, "Key": deploy_key, "AgentRuntimeArn": runtime_arn}


def deploy_mcp(event, region):
    """Build and deploy the MCP server from the attendee's answers (direct invoke)."""
    import hashlib
    answers = event.get("answers") or {}
    environment = {k: v for k, v in (event.get("environment") or {}).items() if k in MCP_ENV_KEYS}
    runtime_name = os.environ["MCP_RUNTIME_NAME"]
    data_bucket = os.environ["DATA_BUCKET"]
    deploy_key = f"dat408/agents/{runtime_name}/agent_package.zip"

    with tempfile.TemporaryDirectory() as tmp:
        agent_dir = _download_agent_dir(os.environ["ASSETS_BUCKET"], os.environ["ASSETS_PREFIX"], tmp)
        # The answer names and files come from the same agent/evidence.py the
        # notebook and the MCP server use.
        for mod in [m for m in sys.modules if m == "agent" or m.startswith("agent.")]:
            del sys.modules[mod]           # a warm container must not reuse an older copy
        sys.path.insert(0, tmp)
        from agent.evidence import ALL_ANSWERS, ANSWERS, sha256
        missing = [f"{f} ({where})" for name, (f, where) in ANSWERS.items()
                   if not str(answers.get(name, "")).strip()]
        if missing:
            raise ValueError("Missing answers: " + "; ".join(missing))
        # Required answers, plus whichever extras (Module 4) were sent.
        sent = [name for name in ALL_ANSWERS if str(answers.get(name, "")).strip()]
        files = {f"solution/{ALL_ANSWERS[name][0]}": answers[name] for name in sent}
        zip_path = os.path.join(tmp, "agent_package.zip")
        _build_zip(agent_dir, MCP_ENTRY_FILE, zip_path, MCP_DEPENDENCIES, SKIP_MCP_FILES, files)
        # Fingerprint what actually went into the package, read back from the zip.
        with zipfile.ZipFile(zip_path) as zf:
            packaged = {name: sha256(zf.read(f"solution/{ALL_ANSWERS[name][0]}").decode("utf-8"))
                        for name in sent}
            evidence_py = hashlib.sha256(zf.read("agent/evidence.py")).hexdigest()
        boto3.client("s3").upload_file(zip_path, data_bucket, deploy_key)

    artifact = {"codeConfiguration": {
        "code": {"s3": {"bucket": data_bucket, "prefix": deploy_key}},
        "entryPoint": [MCP_ENTRY_FILE], "runtime": "PYTHON_3_12"}}
    control = boto3.client("bedrock-agentcore-control", region_name=region)
    runtime_arn = _create_or_update_runtime(
        control, runtime_name, artifact, {"networkMode": "PUBLIC"}, os.environ["MCP_ROLE_ARN"],
        "DAT408 decision-evidence MCP server, built from the attendee's answers",
        environment, protocol="MCP")
    _wait_for_ready(control, runtime_arn)
    return {"AgentRuntimeArn": runtime_arn, "answers": packaged, "evidence_py_sha256": evidence_py}


def delete_runtime(props, region):
    control = boto3.client("bedrock-agentcore-control", region_name=region)
    # The MCP server runtime is created from the notebook, not by CloudFormation,
    # so the stack's delete removes it here too.
    for runtime_name in (props.get("AgentRuntimeName"), os.environ.get("MCP_RUNTIME_NAME")):
        if runtime_name:
            _delete_runtime_named(control, runtime_name)


def _delete_runtime_named(control, runtime_name):
    existing = _find_runtime(control, runtime_name)
    if not existing:
        print(f"Runtime {runtime_name!r} not found; nothing to delete.")
        return
    arn = existing["agentRuntimeArn"]
    print(f"Deleting AgentCore Runtime {arn}")
    try:
        control.delete_agent_runtime(agentRuntimeId=arn.split("/")[-1])
        _wait_for_deleted(control, arn)
    except control.exceptions.ResourceNotFoundException:
        print("Runtime already gone.")


def _send_cfn_response(event, context, status, reason="", data=None, physical_id=None):
    response_body = json.dumps({
        "Status": status,
        "Reason": reason or f"See CloudWatch Log Stream: {context.log_stream_name}",
        "PhysicalResourceId": physical_id or context.log_stream_name,
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data or {},
    }).encode("utf-8")
    req = urllib.request.Request(
        url=event["ResponseURL"], data=response_body, method="PUT",
        headers={"Content-Type": "", "Content-Length": str(len(response_body))})
    urllib.request.urlopen(req)


def handler(event, context):
    region = os.environ.get("AWS_REGION", "us-east-1")
    if "RequestType" not in event:
        # Direct invoke from the notebook (Module 3): deploy the MCP server. Errors
        # propagate to the caller as a Lambda function error.
        if event.get("action") != "deploy_mcp":
            raise ValueError(f"Unknown action: {event.get('action')!r}")
        return deploy_mcp(event, region)
    print(f"RequestType: {event.get('RequestType')}")
    props = event.get("ResourceProperties", {})
    physical_id = props.get("AgentRuntimeName", context.log_stream_name)

    try:
        request_type = event["RequestType"]
        if request_type in ("Create", "Update"):
            attributes = build_and_deploy(props, region)
            missing = [k for k in ("Bucket", "Key", "AgentRuntimeArn") if k not in attributes]
            if missing:
                raise RuntimeError(
                    f"build_and_deploy() returned without required keys {missing}. "
                    f"Full attributes: {attributes!r}")
            _send_cfn_response(event, context, "SUCCESS", data=attributes, physical_id=physical_id)
        elif request_type == "Delete":
            delete_runtime(props, region)
            _send_cfn_response(event, context, "SUCCESS", physical_id=physical_id)
        else:
            _send_cfn_response(event, context, "FAILED",
                               reason=f"Unknown RequestType: {request_type}",
                               physical_id=physical_id)
    except Exception as e:
        print(f"Handler failed: {e}")
        import traceback
        traceback.print_exc()
        _send_cfn_response(event, context, "FAILED", reason=str(e), physical_id=physical_id)


# ── Build instructions for THIS LAMBDA's OWN deployment zip ────────────────
# Run ./scripts/build-lambda-package.sh, which vendors boto3/botocore for x86_64
# (Lambda's default architecture) and packages this file as
# lambda_build_agent_package.py. boto3 must be recent enough to expose the
# bedrock-agentcore-control client (>=1.40.0).
