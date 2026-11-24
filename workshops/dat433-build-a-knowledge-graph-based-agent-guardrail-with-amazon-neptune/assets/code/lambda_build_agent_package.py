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

CloudFormation custom resource handler that owns the un-guarded agent's
AgentCore Runtime end to end: it builds the deployment .zip for
unguarded_agent.py, uploads it to S3, filters the candidate VPC subnets down
to AgentCore-supported Availability Zones, and then CREATES (or updates, or
deletes) the AWS Bedrock AgentCore Runtime itself via the
bedrock-agentcore-control API. It returns the runtime's ARN as a custom
resource attribute (Fn::GetAtt AgentPackageBuild.AgentRuntimeArn).

WHY THIS IS ONE CUSTOM RESOURCE AND NOT "custom-resource-build + native
AWS::BedrockAgentCore::Runtime":
An earlier design split the work: this Lambda built the zip and returned two
subnet IDs as scalar attributes (Subnet0/Subnet1), and a native
AWS::BedrockAgentCore::Runtime resource consumed them via
Fn::GetAtt AgentPackageBuild.Subnet0/.Subnet1 for its NetworkConfiguration.
That coupling was the entire failure surface: the native resource's create
kept failing with "CustomResource attribute error: Vendor response doesn't
contain Subnet0 attribute" - i.e. CloudFormation evaluating a Fn::GetAtt on
this custom resource's response against a strict, typed native property.
Collapsing both jobs into a single custom resource removes that GetAtt
entirely: the subnet IDs never leave this Lambda's process - they are passed
straight into create_agent_runtime's networkModeConfig here - so there is no
Subnet0/Subnet1 attribute for CloudFormation to fail to resolve, and no
native runtime resource depending on one. The runtime's ARN is the only
thing the rest of the stack needs, and it is returned as a plain scalar
attribute.

WHAT CLOUDFORMATION CANNOT DO ALONE (and why this Lambda exists):
1. Run `pip install` to resolve unguarded_agent.py's arm64 dependencies into
   a deployable zip. CodeConfiguration.Code.S3 is a pointer to a pre-existing
   S3 object; something has to build and upload that object.
2. Resolve which of the VPC's candidate private subnets sit in an
   AgentCore-supported Availability Zone ID. AgentCore Runtime's VPC
   connectivity only works in specific AZ IDs per Region, and the AZ NAME ->
   AZ ID mapping is randomized per AWS account, so CloudFormation's !GetAZs
   cannot pick the right subnets - it needs a real ec2:DescribeSubnets call.

DELETE behaviour: on stack Delete this handler deletes the AgentCore Runtime
it created (looked up by name), then returns SUCCESS. The built zip in
DataBucket is removed with the bucket itself and needs no action here.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

import boto3

AGENT_DEPENDENCIES = ["boto3", "bedrock-agentcore", "strands-agents>=1.58,<2"]
TARGET_PYTHON_VERSION = "3.12"

# How long to wait (seconds) for the runtime to reach READY / finish deleting.
# Kept well under the Lambda's own Timeout (see workshop.yaml's
# AgentPackageBuilderFunction.Timeout) so the handler always has time to POST
# its CloudFormation response before the Lambda is killed.
READY_TIMEOUT_SECONDS = 600
DELETE_TIMEOUT_SECONDS = 300

# The complete, official list of AgentCore-supported Availability Zone IDs
# per Region, from AWS's AgentCore VPC documentation
# (docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html,
# "Supported Availability Zones"). This is a fixed, PUBLISHED list per Region -
# it is NOT randomized per AWS account. What IS randomized per account is the
# mapping from AZ NAME (e.g. us-east-1a) to AZ ID (e.g. use1-az1), which is why
# _select_supported_subnets() calls ec2:DescribeSubnets to resolve each
# candidate subnet's AvailabilityZoneId and filters against this table.
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


def _select_supported_subnets(candidate_subnet_ids, region, count=2):
    supported_ids = AGENTCORE_SUPPORTED_AZ_IDS.get(region)
    if not supported_ids:
        raise RuntimeError(f"No known AgentCore-supported AZ IDs for region {region!r}.")

    ec2 = boto3.client("ec2", region_name=region)
    resp = ec2.describe_subnets(SubnetIds=candidate_subnet_ids)

    matched = [s["SubnetId"] for s in resp["Subnets"]
              if s.get("AvailabilityZoneId") in supported_ids]

    if len(matched) < count:
        raise RuntimeError(
            f"Only {len(matched)} of {len(candidate_subnet_ids)} candidate "
            f"subnets are AgentCore-supported for {region}; need {count}.")
    return matched[:count]


def _download_agent_source(bucket, prefix, entry_file, tmp_dir):
    s3 = boto3.client("s3")
    key = f"{prefix.rstrip('/')}/code/{entry_file}"
    dest = os.path.join(tmp_dir, entry_file)
    print(f"Downloading agent source from s3://{bucket}/{key}")
    s3.download_file(bucket, key, dest)
    return dest


def _build_zip(agent_source_path, entry_file, out_zip):
    """Build the deployment zip: the entry file plus its arm64 dependencies.
    Excludes __pycache__/.pyc/.pyo - a confirmed AgentCore Runtime rejection
    reason for deployment packages."""
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
            *AGENT_DEPENDENCIES,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                "Failed to resolve arm64 dependencies for the agent zip.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}")

        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(agent_source_path, arcname=entry_file)
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
    """Return the full runtime record for an existing AgentCore Runtime with
    this name, if any, so the caller can decide whether to update, recreate,
    or delete it."""
    paginator = control.get_paginator("list_agent_runtimes")
    for page in paginator.paginate():
        for rt in page.get("agentRuntimes", []):
            if rt.get("agentRuntimeName") == name:
                return rt
    return None


def _wait_for_ready(control, runtime_arn, timeout_seconds=READY_TIMEOUT_SECONDS,
                    poll_seconds=10):
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


def _wait_for_deleted(control, runtime_arn, timeout_seconds=DELETE_TIMEOUT_SECONDS,
                      poll_seconds=5):
    """Poll GetAgentRuntime until it raises ResourceNotFoundException,
    confirming the runtime is gone before recreating under the same name."""
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


def _create_or_update_runtime(control, runtime_name, artifact, network_config,
                              role_arn, description):
    """Create the runtime on first deploy, update it on subsequent deploys.
    A runtime stuck in a *_FAILED state is deleted and recreated, since
    UpdateAgentRuntime is not documented as safe against those states."""
    existing = _find_runtime(control, runtime_name)
    if existing and existing.get("status") in (
            "CREATE_FAILED", "UPDATE_FAILED", "DELETE_FAILED"):
        existing_arn = existing["agentRuntimeArn"]
        print(f"Existing runtime {existing_arn} is {existing['status']}; "
              f"deleting before recreating.")
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
            environmentVariables={},
        )
        return resp.get("agentRuntimeArn", existing_arn)

    print(f"Creating AgentCore Runtime: {runtime_name}")
    resp = control.create_agent_runtime(
        agentRuntimeName=runtime_name,
        agentRuntimeArtifact=artifact,
        networkConfiguration=network_config,
        roleArn=role_arn,
        description=description,
        environmentVariables={},
    )
    return resp["agentRuntimeArn"]


def build_and_deploy(props, region):
    """Download agent source, build + upload the zip, filter the candidate
    subnets to AgentCore-supported AZs, and create/update the AgentCore
    Runtime. Returns a dict of custom resource attributes including
    AgentRuntimeArn."""
    assets_bucket = props["AssetsBucketName"]
    assets_prefix = props["AssetsBucketPrefix"]
    data_bucket = props["DataBucket"]
    entry_file = props.get("EntryPoint", "unguarded_agent.py")
    runtime_name = props["AgentRuntimeName"]
    role_arn = props["RoleArn"]
    security_group_id = props["SecurityGroupId"]
    description = props.get(
        "Description", f"Un-guarded procurement agent ({entry_file})")
    deploy_key = props.get("DeployKey",
                           "guardrail/agents/unguarded-agent/agent_package.zip")

    candidate_subnets_raw = props.get("AgentCoreCandidateSubnetIds", "")
    if not candidate_subnets_raw:
        raise RuntimeError(
            "AgentCoreCandidateSubnetIds was empty or missing in "
            "ResourceProperties; workshop.yaml's AgentPackageBuild resource "
            f"always sets it. received props={props!r}")
    candidate_subnet_ids = [s.strip() for s in candidate_subnets_raw.split(",") if s.strip()]
    subnet_ids = _select_supported_subnets(candidate_subnet_ids, region)

    with tempfile.TemporaryDirectory() as tmp:
        agent_source = _download_agent_source(
            assets_bucket, assets_prefix, entry_file, tmp)
        zip_path = os.path.join(tmp, "agent_package.zip")
        _build_zip(agent_source, entry_file, zip_path)

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
    network_config = {
        "networkMode": "VPC",
        "networkModeConfig": {
            "securityGroups": [security_group_id],
            "subnets": subnet_ids,
        },
    }

    control = boto3.client("bedrock-agentcore-control", region_name=region)
    runtime_arn = _create_or_update_runtime(
        control, runtime_name, artifact, network_config, role_arn, description)
    print(f"AgentCore Runtime ARN: {runtime_arn}")
    _wait_for_ready(control, runtime_arn)

    return {
        "Bucket": data_bucket,
        "Key": deploy_key,
        "AgentRuntimeArn": runtime_arn,
    }


def delete_runtime(props, region):
    """Best-effort delete of the AgentCore Runtime this resource created,
    looked up by name. Missing runtime is treated as already-deleted."""
    runtime_name = props.get("AgentRuntimeName")
    if not runtime_name:
        print("No AgentRuntimeName in properties; nothing to delete.")
        return
    control = boto3.client("bedrock-agentcore-control", region_name=region)
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


def _send_cfn_response(event, context, status, reason="", data=None,
                       physical_id=None):
    """Send a response to the CloudFormation custom resource pre-signed S3 URL
    per the documented cfn-response HTTP PUT contract."""
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
    """CloudFormation custom resource entrypoint."""
    print(f"RequestType: {event.get('RequestType')}")
    region = os.environ.get("AWS_REGION", "us-east-1")
    props = event.get("ResourceProperties", {})
    # Stable physical id (the runtime name) so Update never triggers a
    # replacement Delete of the just-created runtime.
    physical_id = props.get("AgentRuntimeName", context.log_stream_name)

    try:
        request_type = event["RequestType"]
        if request_type in ("Create", "Update"):
            attributes = build_and_deploy(props, region)
            # Last line of defense: the stack references
            # Fn::GetAtt AgentPackageBuild.AgentRuntimeArn. If that key is
            # ever missing, fail loudly here instead of letting CloudFormation
            # surface the opaque "Vendor response doesn't contain ..." error.
            missing = [k for k in ("Bucket", "Key", "AgentRuntimeArn")
                       if k not in attributes]
            if missing:
                raise RuntimeError(
                    f"build_and_deploy() returned without required keys "
                    f"{missing}. Full attributes: {attributes!r}")
            _send_cfn_response(event, context, "SUCCESS", data=attributes,
                               physical_id=physical_id)
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
        _send_cfn_response(event, context, "FAILED", reason=str(e),
                           physical_id=physical_id)


# ── Build instructions for THIS LAMBDA's OWN deployment zip ────────────────
# (Separate from the AGENT's zip, which this handler builds at runtime into
# /tmp - see build_and_deploy() above.) Run ./scripts/build-lambda-package.sh,
# which packages this file alone as lambda_build_agent_package.py; the python3.12
# runtime's own boto3 provides the bedrock-agentcore-control client.
