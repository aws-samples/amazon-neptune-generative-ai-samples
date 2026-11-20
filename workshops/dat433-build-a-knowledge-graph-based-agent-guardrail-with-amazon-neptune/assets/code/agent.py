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
agent.py

The guarded AnyCompany procurement agent, hosted on Amazon Bedrock AgentCore
Runtime. Deployed from notebook 1.4 (Cell 4.4) by deploy_agent.py, which ships
this file together with:

    guardrail.py            the Strands agent and its tools (given)
    neptune_guard.py        the BeforeToolCallEvent hook, which YOU wrote (Cell 1.1)
    guard_rules.py          its three decisions (block_message given; Go deeper G.1 and G.2 are YOURS)
    verify.py               the harness that runs your queries (given)
    queries/violations.cypher, queries/recommend.cypher   YOUR queries

So the deployed agent is exactly the agent you tested in the notebook, enforcing
exactly the rules you wrote. AgentCore Runtime's ENIs sit in the workshop VPC
with inbound access to Neptune, so verify.py's openCypher calls work unchanged.

Every request gets a fresh agent and a fresh guard: no state leaks between
callers.

Local usage (exercises the same logic without AgentCore Runtime):
    python3 agent.py --demo

Hosted usage (how AgentCore Runtime invokes it; deploy_agent.py's
entryPoint=["agent.py"] runs it with no arguments, so app.run() is the default):
    python3 agent.py
"""

import sys

from bedrock_agentcore.runtime import BedrockAgentCoreApp

from guardrail import build_agent, run, print_trace
from neptune_guard import NeptuneGuardPlugin

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload):
    """AgentCore Runtime entrypoint.

    `payload` is the JSON body the caller sent to invoke_agent_runtime, e.g.
        {"prompt": "Please draft a PO for 50 units of Server Hardware from ..."}

    Returns {"result": <the agent's reply>, "trace": [<one entry per tool call>]}.
    """
    prompt = payload.get("prompt", "")
    if not prompt:
        return {"error": "payload must include a 'prompt' field"}
    return run(build_agent(guard=NeptuneGuardPlugin()), prompt)


if __name__ == "__main__":
    if "--demo" in sys.argv:
        from scenarios import SCENARIOS
        for label, prompt in SCENARIOS:
            print("=" * 76)
            print(f"{label}\n\n{prompt}")
            print("=" * 76)
            out = run(build_agent(guard=NeptuneGuardPlugin()), prompt)
            print_trace(out["trace"])
            print("\n" + out["result"] + "\n")
    else:
        app.run()
