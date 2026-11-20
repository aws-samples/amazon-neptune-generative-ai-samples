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
# connect.sh - point Kiro CLI at the MCP server you deployed in the Kiro notebook (given).
#
# Finds the AgentCore Runtime named dat408EvidenceMCP in this account and Region, and
# writes a Kiro agent, .kiro/agents/dat408-examiner.json, that reaches it through
# mcp-proxy-for-aws. The proxy signs every MCP request with this instance's IAM role
# (SigV4). Nothing here holds queries or logic: those are your answers, running on AgentCore.
set -euo pipefail

RUNTIME_NAME="${RUNTIME_NAME:-dat408EvidenceMCP}"
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
  echo "Run Cell K.2 in the Kiro notebook first, then run this again." >&2
  exit 1
fi
STATUS=$(aws bedrock-agentcore-control get-agent-runtime --region "$REGION" \
           --agent-runtime-id "${ARN##*/}" --query status --output text)
if [[ "$STATUS" != "READY" ]]; then
  echo "${RUNTIME_NAME} is ${STATUS}, not READY yet. Wait for Cell K.2 in the Kiro notebook to print MCP server is live." >&2
  exit 1
fi

ENC_ARN=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$ARN")
ENDPOINT="https://bedrock-agentcore.${REGION}.amazonaws.com/runtimes/${ENC_ARN}/invocations?qualifier=DEFAULT"

mkdir -p .kiro/agents
python3 - "$ENDPOINT" "$REGION" "$PROXY" > .kiro/agents/dat408-examiner.json <<'PY'
import json, sys
endpoint, region, proxy = sys.argv[1:4]
print(json.dumps({
    "name": "dat408-examiner",
    "description": "A fair-lending examiner's assistant, using the decision-evidence solution you "
                   "built in DAT408, served as an MCP server on Amazon Bedrock AgentCore Runtime.",
    "prompt": "You help a fair-lending examiner investigate an AI underwriting agent's loan "
              "decisions. Answer ONLY from the dat408-evidence tools: never from your own "
              "knowledge of HUD, FHA or lending rules, and never guess a policy, number or reason "
              "the tools did not return. If the tools do not answer a question, say so. Answer the "
              "question asked, briefly and in plain words, facts first, as you would to an examiner; "
              "do not explain how the tools or queries work unless asked. When a tool returns several "
              "evaluations of an application, answer about the most recent one unless asked about "
              "others. End each answer with one line, 'Answered with:', listing each tool you used "
              "and, when its result has one, the first 12 characters of the sha256 of the answer file "
              "it ran. Evidence observations are truncated summaries: decide whether a cited policy "
              "was retrieved only with ungrounded_citations.",
    "mcpServers": {"dat408-evidence": {"command": "uvx",
                                       "args": [proxy, endpoint, "--region", region]}},
    "tools": ["@dat408-evidence"],
    "allowedTools": ["@dat408-evidence"],
    "includeMcpJson": False,
}, indent=2))
PY

echo "Connected Kiro CLI to ${RUNTIME_NAME} (${REGION})."
echo "  agent:    .kiro/agents/dat408-examiner.json"
echo "  endpoint: ${ENDPOINT}"
echo
echo "Next:  kiro-cli chat --agent dat408-examiner"
