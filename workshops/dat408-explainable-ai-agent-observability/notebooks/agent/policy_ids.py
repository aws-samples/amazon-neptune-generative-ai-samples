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
"""Canonical policy ids, and the DynamoDB updates that keep the per-policy
decision aggregates current.

Policies are real sections of HUD Handbook 4000.1 and the eCFR, cited in many
forms ("HUD 4000.1 II.A.5.d viii", "12 CFR § 1002.9(a)(2)"). Both the evidence
graph and the aggregates key on the section id ("HUD 4000.1 II.A.5.d",
"12 CFR 1002.9"), the same normalization the stream transform applies.
"""
import re

HUD_RE = re.compile(r'(?:HUD\s*)?4000\.1\s+([IVX]+\.[A-Z]\.\d+\.[a-z])')
CFR_RE = re.compile(r'12\s*C\.?F\.?R\.?\s*(?:§\s*)?(\d{4}\.\d+)')


def normalize_policy_id(raw):
    text = str(raw or "")
    m = HUD_RE.search(text)
    if m:
        return f"HUD 4000.1 {m.group(1)}"
    m = CFR_RE.search(text)
    if m:
        return f"12 CFR {m.group(1)}"
    return None


def aggregate_updates(table_name, decision, timestamp):
    """TransactWriteItems Update entries that count one decision in the
    per-policy, per-month aggregate items (PK = POLICY#<id>, SK = MONTH#<yyyy-mm>)
    that answer "which policies drive denials" with a single Query."""
    month = timestamp[:7]
    cited = {normalize_policy_id(p) for p in decision.get("policies_cited", [])} - {None}
    failed = {normalize_policy_id(p) for p in decision.get("policies_violated", [])} - {None}
    return [{"Update": {
        "TableName": table_name,
        "Key": {"PK": {"S": f"POLICY#{policy}"}, "SK": {"S": f"MONTH#{month}"}},
        "UpdateExpression": "SET policy_id = :p, #m = :m ADD decisions_citing :c, decisions_failing :f",
        "ExpressionAttributeNames": {"#m": "month"},
        "ExpressionAttributeValues": {":p": {"S": policy}, ":m": {"S": month},
                                      ":c": {"N": str(int(policy in cited))},
                                      ":f": {"N": str(int(policy in failed))}},
    }} for policy in sorted(cited | failed)]
