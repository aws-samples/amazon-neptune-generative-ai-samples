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

# connect.sh - point Kiro CLI at the MCP server you deployed from 3 - Run it from Kiro (optional).ipynb (given).
#
# Finds the AgentCore Runtime named ProcurementMCP in this account and Region,
# and writes a Kiro agent, .kiro/agents/procurement.json, that reaches it through
# mcp-proxy-for-aws. The proxy signs every MCP request with this instance's IAM role
# (SigV4). Nothing here holds rules or logic: those are your files, running on AgentCore.
set -euo pipefail

RUNTIME_NAME="${RUNTIME_NAME:-ProcurementMCP}"
PROXY="mcp-proxy-for-aws-cli@1.7.0"
cd "$(dirname "$0")"

REGION="${AWS_REGION:-}"
if [[ -z "$REGION" ]]; then
  TOKEN=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
  REGION=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/placement/region)
fi

ARN=$(aws bedrock-agentcore-control list-agent-runtimes --region "$REGION" \
        --query "agentRuntimes[?agentRuntimeName=='${RUNTIME_NAME}'].agentRuntimeArn | [0]" --output text)
if [[ -z "$ARN" || "$ARN" == "None" ]]; then
  echo "No AgentCore Runtime named ${RUNTIME_NAME} in ${REGION}." >&2
  echo "Run Cell K.2 in 3 - Run it from Kiro (optional).ipynb first, then run this again." >&2
  exit 1
fi
STATUS=$(aws bedrock-agentcore-control get-agent-runtime --region "$REGION" \
           --agent-runtime-id "${ARN##*/}" --query status --output text)
if [[ "$STATUS" != "READY" ]]; then
  echo "${RUNTIME_NAME} is ${STATUS}, not READY yet. Wait for Cell K.2 in 3 - Run it from Kiro (optional).ipynb to finish." >&2
  exit 1
fi

ENC_ARN=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$ARN")
ENDPOINT="https://bedrock-agentcore.${REGION}.amazonaws.com/runtimes/${ENC_ARN}/invocations?qualifier=DEFAULT"

mkdir -p .kiro/agents
python3 - "$ENDPOINT" "$REGION" "$PROXY" > .kiro/agents/procurement.json <<'PY'
import json, sys
endpoint, region, proxy = sys.argv[1:4]
print(json.dumps({
    "name": "procurement",
    "description": "AnyCompany procurement, using the guarded solution you built in the workshop, "
                   "served as an MCP server on Amazon Bedrock AgentCore Runtime.",
    "prompt": "You are AnyCompany's procurement assistant. Use the procurement tools: "
              "recommend_alternatives to choose a qualified supplier that can deliver, "
              "validation_report to check an order, and draft_purchase_order to draft the PO. "
              "Report the PO number and what the guardrail checked.",
    "mcpServers": {"procurement": {"command": "uvx",
                                          "args": [proxy, endpoint, "--region", region]}},
    "tools": ["@procurement"],
    "allowedTools": ["@procurement"],
    "includeMcpJson": False,
}, indent=2))
PY

# Newer Kiro CLIs load agents in a "universal" format; convert ours in place, so Kiro uses
# this agent instead of falling back to the default one. Older CLIs lack the command.
if kiro-cli agent upgrade --help >/dev/null 2>&1; then
  kiro-cli agent upgrade --no-backup .kiro/agents >/dev/null 2>&1
fi

echo "Connected Kiro CLI to ${RUNTIME_NAME} (${REGION})."
echo "  agent:    .kiro/agents/procurement.json"
echo "  endpoint: ${ENDPOINT}"
echo
echo "Next:  kiro-cli chat --agent procurement"
