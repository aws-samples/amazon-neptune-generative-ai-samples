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

# smoke-test.sh - check the Kiro instance can use your MCP server (given; for facilitators).
# One PASS/FAIL line per layer, so a failure says where to look. Run after connect.sh.
cd "$(dirname "$0")"
RUNTIME_NAME="${RUNTIME_NAME:-ProcurementMCP}"
REGION="${AWS_REGION:-$(curl -s -H "X-aws-ec2-metadata-token: $(curl -s -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" http://169.254.169.254/latest/meta-data/placement/region)}"
fails=0
check() { if eval "$2" >/tmp/smoke.out 2>&1; then echo "PASS  $1"; else echo "FAIL  $1"; sed 's/^/      /' /tmp/smoke.out | tail -5; fails=$((fails+1)); fi; }

check "AWS credentials on this instance ($(aws sts get-caller-identity --query Arn --output text 2>/dev/null | sed 's#.*assumed-role/##'))" \
      "aws sts get-caller-identity"
check "Kiro CLI installed and signed in"   "command -v kiro-cli && [[ -n \"\${KIRO_API_KEY:-}\" ]]"
check "uvx available (runs mcp-proxy-for-aws)" "command -v uvx"
check "${RUNTIME_NAME} is READY in ${REGION}" \
      "[[ \$(aws bedrock-agentcore-control list-agent-runtimes --region $REGION --query \"agentRuntimes[?agentRuntimeName=='${RUNTIME_NAME}'].status | [0]\" --output text) == READY ]]"
check "Kiro agent written by connect.sh"   "test -s .kiro/agents/procurement.json"

ENDPOINT=$(python3 -c 'import json; print(json.load(open(".kiro/agents/procurement.json"))["mcpServers"]["procurement"]["args"][1])' 2>/dev/null)
check "MCP over IAM: tools listed, and recommend_alternatives answers from Neptune" "uv run -q --no-project --with 'mcp-proxy-for-aws==1.7.0' python3 - '$ENDPOINT' '$REGION' <<'PY'
import asyncio, sys
from mcp import ClientSession
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
async def main(url, region):
    async with aws_iam_streamablehttp_client(endpoint=url, aws_service='bedrock-agentcore', aws_region=region) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name for t in (await s.list_tools()).tools}
            need = {'validation_report', 'recommend_alternatives', 'draft_purchase_order'}
            assert need <= tools, f'missing tools: {need - tools}'
            res = await s.call_tool('recommend_alternatives', {'product_name': 'Server Hardware', 'region_name': 'US-East', 'quantity': 40})
            assert not res.isError, res.content
            print('tools:', sorted(tools))
asyncio.run(main(*sys.argv[1:3]))
PY"

echo
if [[ $fails -eq 0 ]]; then echo "All checks passed: run  kiro-cli chat --agent procurement"; else echo "$fails check(s) failed."; exit 1; fi
