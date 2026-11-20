#!/usr/bin/env bash
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
#
# deploy.sh: deploy DAT408 into your own AWS account, check on it, or remove it.
#
#   ./deploy.sh deploy     build the Lambda zips, upload the assets, create or update the stack
#   ./deploy.sh status     the stack's status and outputs
#   ./deploy.sh destroy    delete the stack and everything it created (asks first)
#
# Uses your current AWS credentials. Set AWS_PROFILE and AWS_REGION to choose them;
# AWS_REGION must be us-east-1, us-east-2 or us-west-2 (the models are US cross-Region
# inference profiles). STACK_NAME defaults to workshop-infra.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
STACK="${STACK_NAME:-workshop-infra}"
PREFIX="dat408/"
AWS=(aws --region "$REGION")

case "$REGION" in
  us-east-1|us-east-2|us-west-2) ;;
  *) echo "AWS_REGION must be us-east-1, us-east-2 or us-west-2 (got $REGION)." >&2; exit 1 ;;
esac
for tool in aws zip; do
  command -v "$tool" >/dev/null || { echo "This script needs '$tool' on your PATH." >&2; exit 1; }
done

ACCOUNT="$("${AWS[@]}" sts get-caller-identity --query Account --output text)"
CALLER_ARN="$("${AWS[@]}" sts get-caller-identity --query Arn --output text)"
BUCKET="dat408-assets-${ACCOUNT}-${REGION}"

echo "Account: $ACCOUNT  Region: $REGION  Stack: $STACK"
echo "Assets:  s3://$BUCKET/$PREFIX"
echo

build_zips() {
  echo "==> Building the two Lambda packages from src/"
  local tmp
  tmp="$(mktemp -d)"
  mkdir -p build
  (cd src && zip -q "$tmp/a.zip" lambda_build_agent_package.py)
  mv "$tmp/a.zip" build/lambda_build_agent_package_deployment.zip
  cp src/lambda_deploy_data.py src/history_generator.py src/lineage_generator.py "$tmp/"
  cp notebooks/agent/applications.py "$tmp/applications.py"
  (cd "$tmp" && zip -q data.zip lambda_deploy_data.py history_generator.py lineage_generator.py applications.py)
  mv "$tmp/data.zip" build/lambda_deploy_data_deployment.zip
  rm -rf "$tmp"
}

ensure_bucket() {
  if "${AWS[@]}" s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
    return
  fi
  echo "==> Creating the private assets bucket $BUCKET"
  if [[ "$REGION" == "us-east-1" ]]; then
    "${AWS[@]}" s3api create-bucket --bucket "$BUCKET" >/dev/null
  else
    "${AWS[@]}" s3api create-bucket --bucket "$BUCKET" \
      --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
  fi
  "${AWS[@]}" s3api put-public-access-block --bucket "$BUCKET" \
    --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
}

upload() {
  ensure_bucket
  echo "==> Uploading notebooks, Lambda code, and the policy corpus"
  "${AWS[@]}" s3 sync notebooks "s3://$BUCKET/${PREFIX}notebooks/" --delete --only-show-errors
  "${AWS[@]}" s3 sync build "s3://$BUCKET/${PREFIX}code/" --delete --only-show-errors
  "${AWS[@]}" s3 sync policies "s3://$BUCKET/${PREFIX}policies/" --delete --only-show-errors
}

deploy_stack() {
  echo "==> Deploying stack $STACK (the first create takes about 30 minutes)"
  "${AWS[@]}" cloudformation deploy \
    --template-file cfn/workshop-infra.yaml \
    --s3-bucket "$BUCKET" --s3-prefix cfn \
    --stack-name "$STACK" \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides "BucketName=$BUCKET" "BucketPrefix=$PREFIX" "AssumedRoleARNStr=$CALLER_ARN" \
    --tags Project=DAT408 \
    --no-fail-on-empty-changeset
  # The custom-resource Lambdas' code lives at fixed S3 keys, so a stack update never picks
  # up a rebuilt zip on its own. Push the current code explicitly.
  for fn in pkgbuilder:lambda_build_agent_package deploy-data:lambda_deploy_data; do
    "${AWS[@]}" lambda update-function-code --function-name "dat408-${fn%%:*}-$STACK" \
      --s3-bucket "$BUCKET" --s3-key "${PREFIX}code/${fn##*:}_deployment.zip" \
      --query 'LastModified' --output text >/dev/null
  done
  status
}

status() {
  "${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].StackStatus" --output text
  "${AWS[@]}" cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='NotebookInstanceUrl'].[OutputKey,OutputValue]" --output table
}

destroy() {
  echo "This deletes stack '$STACK' in account $ACCOUNT ($REGION), including its DynamoDB tables,"
  echo "Neptune Analytics graph, Knowledge Base, AgentCore runtimes, notebook instance, and the S3"
  echo "buckets it created."
  read -r -p "Type the account id ($ACCOUNT) to confirm: " answer
  [[ "$answer" == "$ACCOUNT" ]] || { echo "Aborted."; exit 1; }
  # The MCP server that 03 Kiro.ipynb deploys isn't part of the stack.
  for rt in $("${AWS[@]}" bedrock-agentcore-control list-agent-runtimes \
               --query "agentRuntimes[?starts_with(agentRuntimeName,'dat408EvidenceMCP')].agentRuntimeId" \
               --output text 2>/dev/null); do
    echo "Deleting the MCP server runtime $rt"
    "${AWS[@]}" bedrock-agentcore-control delete-agent-runtime --agent-runtime-id "$rt" >/dev/null || true
  done
  # Buckets the stack created must be empty before CloudFormation can delete them.
  for b in $("${AWS[@]}" cloudformation describe-stack-resources --stack-name "$STACK" \
              --query "StackResources[?ResourceType=='AWS::S3::Bucket'].PhysicalResourceId" --output text); do
    "${AWS[@]}" s3 rm "s3://$b" --recursive --only-show-errors 2>/dev/null || true
  done
  "${AWS[@]}" cloudformation delete-stack --stack-name "$STACK"
  echo "Waiting for the stack to delete..."
  "${AWS[@]}" cloudformation wait stack-delete-complete --stack-name "$STACK"
  echo "Deleted. The assets bucket s3://$BUCKET is kept. To remove it too:"
  echo "  aws s3 rb s3://$BUCKET --force --region $REGION"
}

case "${1:-}" in
  deploy)  build_zips; upload; deploy_stack ;;
  status)  status ;;
  destroy) destroy ;;
  *) sed -n '21,30p' "$0"; exit 1 ;;
esac
