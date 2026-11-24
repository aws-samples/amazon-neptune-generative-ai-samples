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
deploy_agent.py

Packages an agent module and its dependencies as a .zip deployment artifact
and deploys it to Amazon Bedrock AgentCore Runtime, inside the same VPC as
the Neptune cluster.

This workshop runs three things on AgentCore Runtime, deployed two ways:

    ProcurementUnguardedAgent    unguarded_agent.py  the "before" agent Cell 0.2 calls. The
                                                CloudFormation stack deploys it at stack
                                                creation (the AgentPackageBuild custom
                                                resource), not this script.
    ProcurementGuardedAgent  agent.py            the guarded agent, with the attendee's
                                                guard and queries
    ProcurementMCP    mcp_server.py       the same files as an MCP server, which
                                                Kiro CLI calls (3 - Run it from Kiro (optional).ipynb)

The last two are deployed with this script from the notebooks: the guarded agent by Cell 4.4
in notebook 1.4, the MCP server by Cell K.2 in notebook 3 (Run it from Kiro). It runs imperatively, the same way setup_graph.py starts the
Neptune bulk load: CloudFormation cannot reference a .zip that does not exist yet at
stack-create time, so the template provisions only what is knowable in advance (the
AgentCore execution role, and the AgentCore security group with its ingress rule into
Neptune). This script does the rest:

    1. Build a .zip containing the entry file, its supporting modules, and an
       arm64-compatible install of their pip dependencies (AgentCore Runtime
       is arm64-only).
    2. Upload the .zip to the workshop's DataBucket (the SageMaker role
       already has write access to this bucket for the dataset CSVs).
    3. Call CreateAgentRuntime (first deploy) or UpdateAgentRuntime
       (redeploy), pointing NetworkConfiguration at the workshop VPC subnets
       and the AgentCore security group.
    4. Poll until the runtime reaches READY, and return its ARN.

Usage (what Cell 4.4, via session.deploy_guarded, does):
    from deploy_agent import deploy_agent, wait_for_ready, invoke_deployed_agent

    common = dict(code_dir="/home/ec2-user/SageMaker/workshop", bucket=DATA_BUCKET,
                  role_arn=AGENTCORE_ROLE_ARN, subnet_ids=SUBNET_IDS,
                  security_group_id=AGENTCORE_SECURITY_GROUP_ID,
                  environment_variables={"NEPTUNE_ENDPOINT": ..., "NEPTUNE_PORT": "8182"})
    your_files = ["your-guard/neptune_guard.py", "your-guard/guard_rules.py",
                  "your-guard/queries/violations.cypher", "your-guard/queries/recommend.cypher",
                  "your-guard/queries/stock_locations.cypher", "your-guard/queries/rule_settings.json"]
    given = ["helpers/guardrail.py", "helpers/verify.py"]

    mcp_arn = deploy_agent(runtime_name="ProcurementMCP", entry_file="mcp_server.py",
                           code_files=["helpers/mcp_server.py"] + given + your_files,
                           protocol="MCP", wait=False, **common)
    guarded_arn = deploy_agent(runtime_name="ProcurementGuardedAgent", entry_file="agent.py",
                               code_files=["helpers/agent.py"] + given + your_files,
                               **common)
    wait_for_ready(mcp_arn)

    answer = invoke_deployed_agent(guarded_arn, "Please draft a PO for ...", show_calls=True)

To redeploy the un-guarded agent on a dev stack after changing unguarded_agent.py, the
same function works: deploy_agent(runtime_name="ProcurementUnguardedAgent",
entry_file="unguarded_agent.py", code_files=["unguarded_agent.py"], code_dir="static/code", ...).
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile

import boto3

# AgentCore Runtime only supports the arm64 instruction set, regardless of
# what architecture the notebook instance itself runs on. Dependencies must be
# resolved for that target explicitly, not just installed as-is.
TARGET_PYTHON_VERSION = "3.12"

# Both agents in this workshop share the same runtime dependencies: boto3 for
# Bedrock and the Neptune data API (neptunedata client), the AgentCore SDK to
# expose @app.entrypoint, and Strands Agents for the agent loop and the
# BeforeToolCallEvent hook the guard plugs into. The guarded agent talks to
# Neptune over openCypher through boto3, so no graph driver is needed.
# Keep in step with AGENT_DEPENDENCIES in lambda_build_agent_package.py.
DEPENDENCIES = ["boto3", "bedrock-agentcore", "strands-agents>=1.58,<2"]
# The MCP server (mcp_server.py, protocol="MCP") also needs the MCP Python SDK for
# its FastMCP streamable-HTTP server.
MCP_DEPENDENCIES = ["mcp>=1.10,<2"]

# Folder names in ~/SageMaker/workshop that don't belong in the package's paths.
PACKAGE_PREFIXES = ("helpers/", "your-guard/", "src/")

# AgentCore Runtime's VPC connectivity is only available in specific AZ IDs
# per Region (confirmed against a real CREATE_FAILED error naming exactly
# this list for us-east-1, and cross-checked against AWS's own "Supported
# Availability Zones" table for AgentCore Runtime VPC connectivity). AZ NAME
# to AZ ID mapping is randomized per AWS account, so CloudFormation cannot
# select the right AZs at template-authoring time; this dict is used at
# deploy time, with real ec2:DescribeAvailabilityZones access, to resolve
# which of the CANDIDATE subnets CloudFormation created actually sit in a
# supported AZ ID for the target Region.
# The complete, official list of AgentCore-supported Availability Zone IDs
# per Region, confirmed via AWS's own AgentCore VPC documentation
# (docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html,
# "Supported Availability Zones" section, fetched directly). This is a
# fixed, PUBLISHED list per Region - it is NOT randomized per AWS account.
# What IS randomized per account is the mapping from AZ NAME (e.g.
# us-east-1a) to AZ ID (e.g. use1-az1), which is why select_supported_subnets()
# below still needs a real ec2:DescribeSubnets call rather than assuming any
# particular AZ NAME maps to a supported AZ ID.
AGENTCORE_SUPPORTED_AZ_IDS = {
    "us-east-1": {"use1-az1", "use1-az2", "use1-az4"},
    "us-east-2": {"use2-az1", "use2-az2", "use2-az3"},
    "us-west-1": {"usw1-az1", "usw1-az3"},
    "us-west-2": {"usw2-az1", "usw2-az2", "usw2-az3"},
    "ap-southeast-5": {"apse5-az1", "apse5-az2", "apse5-az3"},
    "ap-south-1": {"aps1-az1", "aps1-az2", "aps1-az3"},
    "ap-south-2": {"aps2-az1", "aps2-az2", "aps2-az3"},
    "ap-northeast-2": {"apne2-az1", "apne2-az2", "apne2-az3"},
    "ap-southeast-1": {"apse1-az1", "apse1-az2", "apse1-az3"},
    "ap-southeast-2": {"apse2-az1", "apse2-az2", "apse2-az3"},
    "ap-southeast-7": {"apse7-az1", "apse7-az2", "apse7-az3"},
    "ap-northeast-1": {"apne1-az1", "apne1-az2", "apne1-az4"},
    "ca-central-1": {"cac1-az1", "cac1-az2", "cac1-az4"},
    "eu-central-1": {"euc1-az1", "euc1-az2", "euc1-az3"},
    "eu-west-1": {"euw1-az1", "euw1-az2", "euw1-az3"},
    "eu-west-2": {"euw2-az1", "euw2-az2", "euw2-az3"},
    "eu-south-1": {"eus1-az1", "eus1-az2", "eus1-az3"},
    "eu-west-3": {"euw3-az1", "euw3-az2", "euw3-az3"},
    "eu-south-2": {"eus2-az1", "eus2-az2", "eus2-az3"},
    "eu-north-1": {"eun1-az1", "eun1-az2", "eun1-az3"},
    "sa-east-1": {"sae1-az1", "sae1-az2", "sae1-az3"},
    "us-gov-west-1": {"usgw1-az1", "usgw1-az2", "usgw1-az3"},
}


def select_supported_subnets(candidate_subnet_ids: list, region: str,
                             count: int = 2) -> list:
    """Filter a list of candidate subnet IDs down to ones in an
    AgentCore-supported Availability Zone for this Region.

    CloudFormation creates one candidate subnet per AZ it can see (see
    workshop.yaml's PrivateSubnet1-4), because it has no way to know in
    advance which of the account's AZ NAMES map to AgentCore-supported AZ
    IDs - that mapping is randomized per account and only resolvable with
    real EC2 API access, which the template language does not have. This
    function does that resolution here, where boto3 credentials are
    available, and returns the first `count` candidates that qualify.

    Raises RuntimeError if fewer than `count` candidates are supported, since
    that means the workshop's VPC needs more candidate AZs than it currently
    provisions (see AGENTCORE_SUPPORTED_AZ_IDS / the PrivateSubnetN block in
    workshop.yaml).
    """
    supported_ids = AGENTCORE_SUPPORTED_AZ_IDS.get(region)
    if not supported_ids:
        raise RuntimeError(
            f"No known AgentCore-supported AZ IDs recorded for region {region!r}. "
            f"Check https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/"
            f"agentcore-vpc.html for the current list and add it to "
            f"AGENTCORE_SUPPORTED_AZ_IDS in deploy_agent.py.")

    ec2 = boto3.client("ec2", region_name=region)
    resp = ec2.describe_subnets(SubnetIds=candidate_subnet_ids)

    matched = []
    for subnet in resp["Subnets"]:
        az_id = subnet.get("AvailabilityZoneId")
        if az_id in supported_ids:
            matched.append(subnet["SubnetId"])

    if len(matched) < count:
        raise RuntimeError(
            f"Only {len(matched)} of {len(candidate_subnet_ids)} candidate "
            f"subnets are in an AgentCore-supported AZ for {region} "
            f"(supported AZ IDs: {sorted(supported_ids)}); need at least "
            f"{count}. Add more PrivateSubnetN resources to workshop.yaml "
            f"to increase the odds of covering a supported AZ.")

    return matched[:count]


def _build_zip(code_dir: str, code_files: list, out_zip: str,
               dependencies: list = None) -> str:
    """Build the deployment .zip: the given code files + arm64 pip dependencies.

    Returns the path to the built .zip.
    """
    dependencies = dependencies or DEPENDENCIES
    with tempfile.TemporaryDirectory() as tmp:
        deps_dir = os.path.join(tmp, "deps")
        os.makedirs(deps_dir, exist_ok=True)

        print(f"Resolving arm64 / Python {TARGET_PYTHON_VERSION} dependencies: "
              f"{', '.join(dependencies)}")
        # --platform targets AgentCore Runtime's arm64 Linux environment even
        # when this script runs on an x86_64 SageMaker notebook instance.
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
                "Failed to resolve arm64 dependencies for AgentCore Runtime.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}")

        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            # Agent code at the zip root, so entryPoint=[entry_file] resolves.
            # The workshop folder name (helpers/ or your-guard/) is stripped from the
            # archive name: on the notebook the code lives in ~/SageMaker/workshop/helpers
            # and your-guard, but in the container agent.py, verify.py, neptune_guard.py
            # and guard_rules.py sit at the root, with queries/ beside them (so verify.py
            # finds queries/ relative to itself).
            for fn in code_files:
                path = os.path.join(code_dir, fn)
                if not os.path.isfile(path):
                    raise FileNotFoundError(
                        f"{path} not found. Run this from the directory the "
                        f"lifecycle script staged the workshop code into.")
                arcname = next((fn[len(p):] for p in PACKAGE_PREFIXES if fn.startswith(p)), fn)
                zf.write(path, arcname=arcname)
            # Vendored dependencies alongside the code. Exclude __pycache__
            # directories and any .pyc/.pyo files: AgentCore Runtime rejects
            # deployment packages that contain them, because bytecode
            # compiled on this notebook instance's architecture/Python build
            # is not guaranteed compatible with the arm64 execution
            # environment the code actually runs in. `pip install --target`
            # can leave these behind even though we resolved wheels for the
            # target platform, so they have to be stripped explicitly rather
            # than assumed absent.
            for root, dirs, files in os.walk(deps_dir):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    if f.endswith((".pyc", ".pyo")):
                        continue
                    full = os.path.join(root, f)
                    arc = os.path.relpath(full, deps_dir)
                    zf.write(full, arcname=arc)

        size_mb = os.path.getsize(out_zip) / (1024 * 1024)
        print(f"Built {out_zip} ({size_mb:.1f} MB)")
        return out_zip


def _upload_zip(zip_path: str, bucket: str, key: str) -> None:
    s3 = boto3.client("s3")
    print(f"Uploading {zip_path} -> s3://{bucket}/{key}")
    s3.upload_file(zip_path, bucket, key)


def _find_runtime(client, name: str):
    """Return the full runtime record for an existing AgentCore Runtime with
    this name, if any (not just its ARN), so the caller can check status
    before deciding whether to update or recreate it."""
    paginator = client.get_paginator("list_agent_runtimes")
    for page in paginator.paginate():
        for rt in page.get("agentRuntimes", []):
            if rt.get("agentRuntimeName") == name:
                return rt
    return None


def deploy_agent(runtime_name: str, entry_file: str, code_files: list,
                  code_dir: str, bucket: str, role_arn: str,
                  security_group_id: str, subnet_ids: list,
                  region: str = None, prefix: str = None,
                  description: str = None, environment_variables: dict = None,
                  wait: bool = True, timeout_seconds: int = 600,
                  protocol: str = "HTTP") -> str:
    """Build, upload, and deploy an agent module to Amazon Bedrock AgentCore Runtime.

    `runtime_name` identifies the AgentCore Runtime resource (e.g.
    "ProcurementUnguardedAgent" or "ProcurementGuardedAgent"); `entry_file` is the
    module AgentCore Runtime starts (must define an @app.entrypoint handler
    and call app.run() in its __main__ guard); `code_files` is every source
    file that entry_file needs alongside it in the deployment package.

    `environment_variables` is passed straight through to CreateAgentRuntime /
    UpdateAgentRuntime's environmentVariables field. This matters for
    agent.py specifically: verify.py builds a neptunedata client from
    NEPTUNE_ENDPOINT and NEPTUNE_PORT read from os.environ, and those
    variables exist in the NOTEBOOK's shell (from workshop_config.txt) but are
    NOT automatically present inside the AgentCore Runtime container - the
    container has its own, separate environment, set only by what you pass
    here. Omitting this for the guarded agent causes verify.py to raise
    RuntimeError ("NEPTUNE_ENDPOINT is not set in the environment") the moment
    verify_supplier_relationship() is called, which AgentCore reports back
    to the caller as a generic RuntimeClientError 500 - confirmed against a
    real deployment that failed exactly this way.

    `protocol` is the runtime's server protocol: "HTTP" for an agent with an
    @app.entrypoint handler (the default), or "MCP" for an MCP server such as
    mcp_server.py, which AgentCore then serves to MCP clients at the runtime's
    invocations URL (see mcp_endpoint_url()).

    Creates the runtime on first call, updates it on subsequent calls, so
    re-running this cell after editing the agent's code redeploys your
    changes under the same runtime. Returns the AgentCore Runtime ARN.
    """
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    prefix = prefix or f"guardrail/agents/{runtime_name}"
    control = boto3.client("bedrock-agentcore-control", region_name=region)

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, "agent_deployment.zip")
        _build_zip(code_dir, code_files, zip_path,
                   DEPENDENCIES + (MCP_DEPENDENCIES if protocol == "MCP" else []))

        key = f"{prefix.strip('/')}/agent_deployment.zip"
        _upload_zip(zip_path, bucket, key)

    artifact = {
        "codeConfiguration": {
            # Confirmed against a working AWS example: the "prefix" field
            # here is the full S3 object key (including the filename), not a
            # directory-style prefix. entryPoint is a single-element array
            # naming the entrypoint file directly; AgentCore Runtime always
            # runs it as the served process with no extra arguments.
            "code": {"s3": {"bucket": bucket, "prefix": key}},
            "entryPoint": [entry_file],
            "runtime": "PYTHON_3_12",
        }
    }
    network_config = {
        "networkMode": "VPC",
        "networkModeConfig": {
            "securityGroups": [security_group_id],
            "subnets": subnet_ids,
            # Deliberately NOT setting requireServiceS3Endpoint here.
            # CreateAgentRuntime rejects it outright: "requireServiceS3Endpoint
            # cannot be set during agent creation" (confirmed against a real
            # ValidationException, not assumed). AWS's own API docs say that
            # when this field is omitted, the service default applies and the
            # service-managed S3 gateway endpoint remains provisioned - which
            # is what a VPC-mode runtime needs to actually download its code
            # package from S3 at container startup. This field can only be
            # changed later, via UpdateAgentRuntime, if you need to opt OUT
            # of that gateway (a hardening step for runtimes that no longer
            # need broad S3 access) - not something this workshop does.
        },
    }

    protocol_config = {"serverProtocol": protocol}

    existing = _find_runtime(control, runtime_name)
    if existing:
        existing_arn = existing["agentRuntimeArn"]
        existing_status = existing.get("status")
        # A runtime stuck in a failed state cannot be reliably updated: AWS
        # does not document that UpdateAgentRuntime is safe to call against
        # CREATE_FAILED/UPDATE_FAILED, and UpdateAgentRuntime can return
        # ConflictException depending on the resource's current state. Rather
        # than guess, delete the failed resource and create fresh - the
        # same outcome you would want either way, and one that does not
        # depend on undocumented behavior.
        if existing_status in ("CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED"):
            print(f"Existing AgentCore Runtime {existing_arn} is in "
                  f"{existing_status}; deleting it before recreating.")
            control.delete_agent_runtime(agentRuntimeId=existing_arn.split("/")[-1])
            _wait_for_deleted(control, existing_arn)
            existing = None

    if existing:
        print(f"Updating existing AgentCore Runtime: {existing_arn}")
        resp = control.update_agent_runtime(
            agentRuntimeId=existing_arn.split("/")[-1],
            agentRuntimeArtifact=artifact,
            networkConfiguration=network_config,
            roleArn=role_arn,
            environmentVariables=environment_variables or {},
            protocolConfiguration=protocol_config,
        )
        runtime_arn = resp.get("agentRuntimeArn", existing_arn)
    else:
        print(f"Creating AgentCore Runtime: {runtime_name}")
        resp = control.create_agent_runtime(
            agentRuntimeName=runtime_name,
            agentRuntimeArtifact=artifact,
            networkConfiguration=network_config,
            roleArn=role_arn,
            description=description or f"Knowledge graph guardrail agent: {entry_file}",
            environmentVariables=environment_variables or {},
            protocolConfiguration=protocol_config,
        )
        runtime_arn = resp["agentRuntimeArn"]

    print(f"AgentCore Runtime ARN: {runtime_arn}")

    if wait:
        _wait_for_ready(control, runtime_arn, timeout_seconds)

    return runtime_arn


def _wait_for_ready(control, runtime_arn: str, timeout_seconds: int = 600,
                    poll_seconds: int = 10):
    """Poll GetAgentRuntime until the runtime reaches READY (or fails)."""
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

def wait_for_ready(runtime_arn: str, region: str = None, timeout_seconds: int = 600):
    """Wait for a runtime started with deploy_agent(..., wait=False) to reach READY."""
    region = region or runtime_arn.split(":")[3]
    _wait_for_ready(boto3.client("bedrock-agentcore-control", region_name=region),
                    runtime_arn, timeout_seconds)


def _wait_for_deleted(control, runtime_arn: str, timeout_seconds: int = 300,
                      poll_seconds: int = 5):
    """Poll GetAgentRuntime until it raises ResourceNotFoundException,
    confirming the runtime is actually gone before recreating it under the
    same name."""
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
        f"AgentCore Runtime {runtime_arn} did not finish deleting in "
        f"{timeout_seconds}s")



def mcp_endpoint_url(runtime_arn: str, region: str = None) -> str:
    """The URL MCP clients use for an MCP server hosted on AgentCore Runtime. Callers
    authenticate with IAM (SigV4); Kiro CLI does that through mcp-proxy-for-aws."""
    from urllib.parse import quote
    region = region or runtime_arn.split(":")[3]
    return (f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/"
            f"{quote(runtime_arn, safe='')}/invocations?qualifier=DEFAULT")


def invoke_deployed_agent(runtime_arn: str, question: str, region: str = None,
                          show_calls: bool = False) -> str:
    """Call a deployed agent over the network via invoke_agent_runtime.

    Works against either agent runtime this workshop deploys: the question
    travels over the AgentCore Runtime data plane, through the agent's VPC
    ENIs, to whichever module's @app.entrypoint handler is hosted there.

    Both agents return {"result", "trace"}. With show_calls=True the trace is
    printed here, one line per tool call the agent made inside AgentCore
    (BLOCKED lines carry the guard's reasons). Returns the reply text.
    """
    region = region or os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("bedrock-agentcore", region_name=region)

    payload = json.dumps({"prompt": question}).encode()

    # Calling the agent is a blocking network round-trip (VPC -> AgentCore
    # Runtime -> Bedrock -> Neptune) that can take several seconds, longer on a
    # cold start, so show a spinner while it is in flight.
    from ui import busy, show_trace
    with busy("Waiting for the agent on Amazon Bedrock AgentCore Runtime"):
        resp = client.invoke_agent_runtime(
            agentRuntimeArn=runtime_arn,
            payload=payload,
            contentType="application/json",
            accept="application/json",
        )
        body = json.loads(resp["response"].read())
    if "error" in body:
        raise RuntimeError(f"Agent invocation error: {body['error']}")

    if show_calls:
        show_trace(body.get("trace", []))
    return body.get("result", "")


def main():
    bucket = os.environ.get("DATA_BUCKET")
    role_arn = os.environ.get("AGENTCORE_ROLE_ARN")
    sg_id = os.environ.get("AGENTCORE_SECURITY_GROUP_ID")
    region = os.environ.get("AWS_REGION", "us-east-1")
    # workshop_config.txt (the stack's OnStart) writes one candidate subnet per AZ;
    # AgentCore needs subnets in its supported AZs, so filter them as the notebook does.
    candidates = [s for s in os.environ.get("AGENTCORE_CANDIDATE_SUBNET_IDS", "").split(",") if s]
    # ~/SageMaker/workshop is the staging root: given code under helpers/, the attendee's
    # hook, guard rules and queries under your-guard/.
    code_dir = os.environ.get("CODE_DIR", os.path.join(os.path.expanduser("~"), "SageMaker", "workshop"))
    runtime_name = os.environ.get("AGENT_RUNTIME_NAME", "ProcurementGuardedAgent")
    entry_file = os.environ.get("AGENT_ENTRY_FILE", "agent.py")
    code_files_env = os.environ.get(
        "AGENT_CODE_FILES",
        "helpers/agent.py,helpers/guardrail.py,helpers/verify.py,your-guard/neptune_guard.py,"
        "your-guard/guard_rules.py,your-guard/queries/violations.cypher,"
        "your-guard/queries/recommend.cypher,your-guard/queries/stock_locations.cypher,"
        "your-guard/queries/rule_settings.json")

    missing = [n for n, v in [
        ("DATA_BUCKET", bucket), ("AGENTCORE_ROLE_ARN", role_arn),
        ("AGENTCORE_SECURITY_GROUP_ID", sg_id), ("AGENTCORE_CANDIDATE_SUBNET_IDS", candidates),
    ] if not v]
    if missing:
        raise SystemExit(f"Set the following environment variables first: "
                         f"{', '.join(missing)}")
    subnets = select_supported_subnets(candidates, region)

    runtime_arn = deploy_agent(
        runtime_name=runtime_name, entry_file=entry_file,
        code_files=code_files_env.split(","),
        code_dir=code_dir, bucket=bucket, role_arn=role_arn,
        security_group_id=sg_id, subnet_ids=subnets,
    )
    print(f"\nDeployed. Runtime ARN:\n  {runtime_arn}")


if __name__ == "__main__":
    main()
