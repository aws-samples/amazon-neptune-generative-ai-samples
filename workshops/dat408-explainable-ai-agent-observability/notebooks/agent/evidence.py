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
evidence.py — the one code path that runs your exercise answers, in the notebook
and in the MCP server alike.

The notebook's neptune_query() is run_cypher() below, and the MCP server
(mcp_server.py) calls the same run_cypher() and load_function() on the same
answer files your exercise cells saved. Nothing here holds a query or a rule of
its own: it runs openCypher text, loads a function from its source, and
fingerprints both, so you can check that what the MCP server runs is byte for
byte what your notebook ran.

Container-safe on purpose (boto3 and the standard library only): it ships in
the MCP server's AgentCore Runtime package.
"""
import hashlib
import json
from pathlib import Path

# The answers the MCP server serves, by name: the file each exercise saves
# (agent.workshop.save_answer) and where the exercise is, for error messages.
ANSWERS = {
    "get_evidence": ("get_evidence.py", "Go deeper, G.1"),
    "policy_months": ("policy_months.py", "Go deeper, G.3"),
    "ungrounded_citations": ("ungrounded_citations.cypher", "Go deeper, G.6"),
    "lineage_walk": ("lineage_walk.cypher", "DAT408, Cell 3.2"),
}
# Answers that extend the server: deployed when present, never required.
EXTRA_ANSWERS = {
    "policy_change_impact": ("policy_change_impact.cypher", "Go deeper, G.9"),
    "extra_tool": ("extra_tool.py", "Kiro, K.4"),
}
ALL_ANSWERS = {**ANSWERS, **EXTRA_ANSWERS}


def run_cypher(neptune_client, graph_id, query, params=None):
    """Run one openCypher query on Neptune Analytics and return the parsed payload."""
    resp = neptune_client.execute_query(
        graphIdentifier=graph_id,
        queryString=query,
        language="OPEN_CYPHER",
        parameters=params or {},
    )
    return json.loads(resp["payload"].read())


def load_function(source, name, namespace):
    """Define the function `name` from its source text, with `namespace` as its
    globals (for example trace_table and Key, the same names the notebook cell used)."""
    scope = dict(namespace)
    exec(compile(source, f"<answer {name}>", "exec"), scope)
    fn = scope.get(name)
    if not callable(fn):
        raise ValueError(f"{name}: the saved answer does not define a function {name}()")
    return fn


def sha256(text):
    """Fingerprint of an answer's exact text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_answers(directory):
    """{name: text} for every required answer saved in `directory`, plus any extra
    answers present. Raises with the exercise to finish if a required one is missing."""
    answers, missing = {}, []
    for name, (filename, where) in ALL_ANSWERS.items():
        path = Path(directory) / filename
        text = path.read_text() if path.exists() else ""
        if text.strip():
            answers[name] = text
        elif name in ANSWERS:
            missing.append(f"{filename} ({where})")
    if missing:
        raise FileNotFoundError("Missing answers: " + "; ".join(missing))
    return answers
