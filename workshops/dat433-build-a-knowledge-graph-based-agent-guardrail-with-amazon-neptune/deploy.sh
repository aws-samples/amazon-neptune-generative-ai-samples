#!/usr/bin/env bash
# MIT No Attribution
# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
#
# deploy.sh - deploy the agent guardrail workshop in your own AWS account.
#
#   ./deploy.sh [--region us-west-2] [--stack agent-guardrail] [--bucket <assets bucket>] [--yes]
#   ./deploy.sh update     [same options]   re-upload notebooks and code (restart the notebook instance to pick them up)
#   ./deploy.sh teardown   [same options] [--delete-assets-bucket]
#
# deploy    creates a private S3 bucket for the workshop assets if it doesn't exist, uploads
#           assets/ to it, and deploys cfn/workshop.yaml, which pulls the notebooks and code
#           from that bucket when the notebook instance starts. About 20 to 30 minutes.
# teardown  deletes the two AgentCore runtimes the notebooks create (they sit in the stack's
#           subnets), empties the stack's data bucket, and deletes the stack.
#
# Needs: AWS CLI v2, python3 with boto3 (teardown only), and credentials allowed to create
# IAM roles, VPCs, Neptune, SageMaker AI, DynamoDB, Lambda and AgentCore resources.
set -euo pipefail

SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
cd "$(dirname "$SELF")"

MODE="deploy"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-west-2}}"
STACK="agent-guardrail"
BUCKET=""
PREFIX="guardrail/"
NOTEBOOK_TYPE="ml.t3.xlarge"
YES=false
DELETE_ASSETS=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    deploy|update|teardown) MODE="$1"; shift ;;
    --region)  REGION="$2"; shift 2 ;;
    --stack)   STACK="$2"; shift 2 ;;
    --bucket)  BUCKET="$2"; shift 2 ;;
    --notebook-type) NOTEBOOK_TYPE="$2"; shift 2 ;;
    --delete-assets-bucket) DELETE_ASSETS=true; shift ;;
    --yes|-y)  YES=true; shift ;;
    -h|--help) sed -n '6,20p' "$SELF"; exit 0 ;;
    *) echo "Unknown argument: $1 (try --help)" >&2; exit 2 ;;
  esac
done

confirm() {
  $YES && return 0
  read -r -p "$1 [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "Aborted."; exit 1; }
}

command -v aws >/dev/null || { echo "ERROR: the AWS CLI v2 is required." >&2; exit 1; }

IDENTITY="$(aws sts get-caller-identity --output text --query '[Account,Arn]')" \
  || { echo "ERROR: no AWS credentials. Sign in (aws configure / aws sso login) and try again." >&2; exit 1; }
ACCOUNT="$(cut -f1 <<<"$IDENTITY")"
BUCKET="${BUCKET:-guardrail-assets-$ACCOUNT-$REGION}"
DATA_BUCKET="guardrail-data-$ACCOUNT-$REGION"

echo "Account : $ACCOUNT"
echo "Caller  : $(cut -f2 <<<"$IDENTITY")"
echo "Region  : $REGION"
echo "Stack   : $STACK"
echo "Assets  : s3://$BUCKET/$PREFIX"
echo "Mode    : $MODE"
echo

if [[ "$REGION" != us-* ]]; then
  echo "WARNING: the agents use the Amazon Bedrock cross-Region inference profile" >&2
  echo "         us.anthropic.claude-sonnet-5, which serves US Regions. Use us-east-1, us-east-2" >&2
  echo "         or us-west-2 unless you've changed MODEL_ID in assets/code." >&2
  echo >&2
fi

upload_assets() {
  if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
    echo "Creating private bucket s3://$BUCKET"
    if [[ "$REGION" == "us-east-1" ]]; then
      aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null
    else
      aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
        --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
    fi
    aws s3api put-public-access-block --bucket "$BUCKET" --region "$REGION" \
      --public-access-block-configuration \
      BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  fi
  aws s3 sync assets/ "s3://$BUCKET/$PREFIX" --delete --region "$REGION" \
    --exclude "*.DS_Store" --exclude "*__pycache__*" --only-show-errors
  echo "Uploaded assets/ to s3://$BUCKET/$PREFIX"
}

case "$MODE" in
  deploy)
    echo "This creates billable resources in account $ACCOUNT: a VPC with a NAT gateway, an"
    echo "Amazon Neptune cluster (db.r8g.xlarge), a SageMaker AI notebook ($NOTEBOOK_TYPE), a DynamoDB"
    echo "table, a Lambda function and an AgentCore runtime. Run './deploy.sh teardown' when done."
    confirm "Deploy stack '$STACK' in $REGION?"
    upload_assets
    echo "Deploying the stack. This takes about 20 to 30 minutes..."
    aws cloudformation deploy \
      --region "$REGION" \
      --stack-name "$STACK" \
      --template-file cfn/workshop.yaml \
      --s3-bucket "$BUCKET" --s3-prefix "${PREFIX}cfn" \
      --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
      --parameter-overrides "BucketName=$BUCKET" "BucketPrefix=$PREFIX" "AssumedRoleARNStr=" \
                            "NotebookInstanceType=$NOTEBOOK_TYPE"
    URL="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
            --query "Stacks[0].Outputs[?OutputKey=='NeptuneNotebookURL'].OutputValue | [0]" --output text)"
    echo
    echo "Done. NeptuneNotebookURL: $URL"
    echo "Open it, choose Open JupyterLab, and start with"
    echo "  workshop/1 - Build the guardrail/1.1 - Adding a hook before every tool call.ipynb"
    echo "The instance loads the graph in the background when it starts; Cell 0.1 waits if it's still going."
    ;;

  update)
    upload_assets
    NB="aws-neptune-notebook-guardrail-$STACK"
    cat <<EOF

The notebook instance copies notebooks and code from S3 when it starts. To pick up the new
files, stop and start it (your answers in workshop/your-guard/ are kept):
  aws sagemaker stop-notebook-instance  --region $REGION --notebook-instance-name $NB
  aws sagemaker wait notebook-instance-stopped --region $REGION --notebook-instance-name $NB
  aws sagemaker start-notebook-instance --region $REGION --notebook-instance-name $NB
EOF
    ;;

  teardown)
    echo "This deletes, in account $ACCOUNT ($REGION):"
    echo "  - the AgentCore runtimes ProcurementGuardedAgent and ProcurementMCP, which the notebooks created"
    echo "  - every object in the stack's data bucket s3://$DATA_BUCKET"
    echo "  - the CloudFormation stack '$STACK' (Neptune, the notebook instance, the VPC, and the rest)"
    if $DELETE_ASSETS; then echo "  - the assets bucket s3://$BUCKET"; else echo "It keeps s3://$BUCKET (add --delete-assets-bucket to remove it)."; fi
    confirm "Delete all of this? It can't be undone."
    command -v python3 >/dev/null || { echo "ERROR: python3 with boto3 is needed to delete the runtimes." >&2; exit 1; }
    REGION="$REGION" python3 - <<'PY'
import os, time, boto3
c = boto3.client("bedrock-agentcore-control", region_name=os.environ["REGION"])
names = {"ProcurementGuardedAgent", "ProcurementMCP"}
rts = [r for p in c.get_paginator("list_agent_runtimes").paginate()
       for r in p.get("agentRuntimes", []) if r.get("agentRuntimeName") in names]
for r in rts:
    print("Deleting runtime", r["agentRuntimeName"])
    c.delete_agent_runtime(agentRuntimeId=r["agentRuntimeId"])
for r in rts:
    for _ in range(90):
        try:
            c.get_agent_runtime(agentRuntimeId=r["agentRuntimeId"]); time.sleep(10)
        except c.exceptions.ResourceNotFoundException:
            print("  deleted", r["agentRuntimeName"]); break
if not rts:
    print("No notebook-created runtimes found.")
PY
    if aws s3api head-bucket --bucket "$DATA_BUCKET" 2>/dev/null; then
      aws s3 rm "s3://$DATA_BUCKET" --recursive --region "$REGION" --only-show-errors
    fi
    echo "Deleting the stack. This takes about 15 to 20 minutes..."
    aws cloudformation delete-stack --region "$REGION" --stack-name "$STACK"
    aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$STACK"
    if $DELETE_ASSETS; then
      aws s3 rb "s3://$BUCKET" --force --region "$REGION"
    fi
    echo "Teardown complete."
    ;;
esac
