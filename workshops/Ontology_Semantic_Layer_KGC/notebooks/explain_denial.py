#!/usr/bin/env python3
"""
Explain why an insurance claim was denied using SHACL eligibility validation
and Amazon Bedrock for natural language explanation.

Flow:
  1. Load ontology + data + eligibility shapes
  2. Identify denied claims (latest event = "denied")
  3. Validate each denied claim against eligibility shapes
  4. Collect SHACL violation messages
  5. Send violations + claim context to Bedrock for human-readable explanation
"""

import sys
import json
import os
import boto3
from rdflib import Graph, Namespace, Literal
from pyshacl import validate

INS = Namespace("http://example.org/insurance#")

# ---------------------------------------------------------------------------
# Graph loading
# ---------------------------------------------------------------------------

def load_graph():
    """Load ontology and instance data into a single graph."""
    g = Graph()
    g.parse("ontology.ttl")
    g.parse("data.ttl")
    return g


def load_eligibility_shapes():
    """Load the claim eligibility SHACL shapes."""
    g = Graph()
    g.parse("eligibility_shapes.ttl")
    return g


# ---------------------------------------------------------------------------
# Find denied claims
# ---------------------------------------------------------------------------

DENIED_CLAIMS_QUERY = """
PREFIX : <http://example.org/insurance#>

SELECT ?claim ?claimId ?claimAmount ?incidentDate ?policyId
WHERE {
    ?claim a :Claim ;
           :claimId ?claimId ;
           :claimAmount ?claimAmount ;
           :incidentDate ?incidentDate ;
           :forPolicy ?policy ;
           :hasEvent ?event .
    ?policy :policyId ?policyId .
    ?event :eventType "denied" ;
           :eventTimestamp ?deniedTimestamp .

    # Ensure "denied" is the latest event
    FILTER NOT EXISTS {
        ?claim :hasEvent ?laterEvent .
        ?laterEvent :eventTimestamp ?laterTime .
        FILTER (?laterTime > ?deniedTimestamp)
    }
}
ORDER BY ?claimId
"""


def find_denied_claims(data_graph):
    """Return list of denied claims with their context."""
    results = []
    for row in data_graph.query(DENIED_CLAIMS_QUERY):
        results.append({
            "claim_uri": str(row.claim),
            "claim_id": str(row.claimId),
            "claim_amount": float(row.claimAmount),
            "incident_date": str(row.incidentDate),
            "policy_id": str(row.policyId),
        })
    return results


# ---------------------------------------------------------------------------
# SHACL eligibility validation
# ---------------------------------------------------------------------------

def get_claim_context(data_graph, claim_uri):
    """Pull full context for a claim: events, policy, coverage history."""
    query = """
    PREFIX : <http://example.org/insurance#>

    SELECT ?claimId ?claimAmount ?incidentDate ?policyId
           ?eventType ?eventTimestamp ?eventAmount
           ?coverageAmount ?deductible ?premium ?validFrom ?validTo ?isCurrent
    WHERE {
        BIND(<%s> AS ?claim)
        ?claim :claimId ?claimId ;
               :claimAmount ?claimAmount ;
               :incidentDate ?incidentDate ;
               :forPolicy ?policy .
        ?policy :policyId ?policyId .

        # Events
        ?claim :hasEvent ?event .
        ?event :eventType ?eventType ;
               :eventTimestamp ?eventTimestamp .
        OPTIONAL { ?event :eventAmount ?eventAmount }

        # All coverage versions for the policy
        ?policy :hasCoverage ?coverage .
        ?coverage :coverageAmount ?coverageAmount ;
                 :deductible ?deductible ;
                 :premium ?premium ;
                 :validFrom ?validFrom ;
                 :isCurrent ?isCurrent .
        OPTIONAL { ?coverage :validTo ?validTo }
    }
    ORDER BY ?eventTimestamp ?validFrom
    """ % claim_uri

    events = {}
    coverages = {}
    claim_info = None

    for row in data_graph.query(query):
        if claim_info is None:
            claim_info = {
                "claim_id": str(row.claimId),
                "claim_amount": float(row.claimAmount),
                "incident_date": str(row.incidentDate),
                "policy_id": str(row.policyId),
            }

        evt_key = str(row.eventTimestamp)
        if evt_key not in events:
            events[evt_key] = {
                "type": str(row.eventType),
                "timestamp": str(row.eventTimestamp),
                "amount": float(row.eventAmount) if row.eventAmount else None,
            }

        cov_key = str(row.validFrom)
        if cov_key not in coverages:
            coverages[cov_key] = {
                "coverage_amount": float(row.coverageAmount),
                "deductible": float(row.deductible),
                "premium": float(row.premium),
                "valid_from": str(row.validFrom),
                "valid_to": str(row.validTo) if row.validTo else None,
                "is_current": bool(row.isCurrent),
            }

    return {
        **(claim_info or {}),
        "events": list(events.values()),
        "policy_coverages": list(coverages.values()),
    }


def validate_claim_eligibility(data_graph, eligibility_shapes):
    """
    Run eligibility shapes against the full data graph.
    Returns a dict mapping claim URIs to their violation messages.
    """
    conforms, results_graph, results_text = validate(
        data_graph,
        shacl_graph=eligibility_shapes,
        inference='rdfs',
        abort_on_first=False,
    )

    violations = {}
    if not conforms:
        # Parse the results graph for structured violation info
        SH = Namespace("http://www.w3.org/ns/shacl#")
        for result in results_graph.subjects(
            predicate=Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#").type,
            object=SH.ValidationResult,
        ):
            focus = results_graph.value(result, SH.focusNode)
            message = results_graph.value(result, SH.resultMessage)
            severity = results_graph.value(result, SH.resultSeverity)
            source = results_graph.value(result, SH.sourceShape)

            if focus:
                focus_str = str(focus)
                if focus_str not in violations:
                    violations[focus_str] = []
                violations[focus_str].append({
                    "message": str(message) if message else "Unknown violation",
                    "severity": str(severity) if severity else "Violation",
                    "source_shape": str(source) if source else None,
                })

    return conforms, violations, results_text


# ---------------------------------------------------------------------------
# Bedrock LLM explanation
# ---------------------------------------------------------------------------

# Model options (Bedrock model IDs) — ordered by cost-effectiveness for this
# use case. The task is structured text → short natural-language response,
# so smaller/faster models perform well here.
#
# | Model                     | Input $/1M | Output $/1M | Notes                          |
# |---------------------------|-----------|------------|--------------------------------|
# | Amazon Nova Micro          | $0.035    | $0.14      | Text-only, fastest, cheapest   |
# | Amazon Nova Lite           | $0.06     | $0.24      | Multimodal, very fast           |
# | Amazon Nova Pro            | $0.80     | $3.20      | Best Nova for quality           |
# | Claude Haiku 3.5           | $0.80     | $4.00      | Fast, strong instruction follow |
# | Claude Sonnet 4 (current)  | $3.00     | $15.00     | High quality, higher cost       |
#
# For this use case (structured SHACL violations → 2-4 sentence explanation),
# Nova Lite or Haiku 3.5 are the sweet spot: good instruction-following at
# a fraction of the Sonnet cost. Nova Micro works too but may be less nuanced
# on tone. Sonnet is overkill but produces the most polished output.

BEDROCK_MODELS = {
    "nova-micro":  "amazon.nova-micro-v1:0",
    "nova-lite":   "amazon.nova-lite-v1:0",
    "nova-pro":    "amazon.nova-pro-v1:0",
    "haiku":       "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "sonnet":      "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
}

DEFAULT_MODEL = "haiku"


class DenialExplainer:
    """Uses Amazon Bedrock to generate human-readable denial explanations
    from SHACL violation reports.

    Supports multiple models via the `model` parameter:
      - "nova-micro"  — cheapest, fastest (good for high volume)
      - "nova-lite"   — good balance of cost and quality
      - "nova-pro"    — best Amazon model for nuanced text
      - "haiku"       — Claude 3.5 Haiku (recommended default)
      - "sonnet"      — Claude Sonnet 4.5 (highest quality, highest cost)

    Or pass a full Bedrock model ID string directly.
    """

    def __init__(
        self,
        model=None,
        region="us-east-1",
    ):
        self.bedrock = boto3.client("bedrock-runtime", region_name=region)
        model = model or os.environ.get("BEDROCK_MODEL", DEFAULT_MODEL)
        self.model_id = BEDROCK_MODELS.get(model, model)
        self.is_nova = self.model_id.startswith("amazon.nova")

    def _build_prompt(self, claim_context: dict, violations: list[dict]) -> str:
        """Build the LLM prompt from claim context and SHACL violations."""

        violations_text = "\n".join(
            f"  - {v['message']}" for v in violations
        )

        coverages_text = "\n".join(
            f"  - ${c['coverage_amount']:,.2f} coverage, "
            f"${c['deductible']:,.2f} deductible | "
            f"{c['valid_from']} → {c['valid_to'] or 'present'} "
            f"({'CURRENT' if c['is_current'] else 'EXPIRED'})"
            for c in claim_context.get("policy_coverages", [])
        )

        events_text = "\n".join(
            f"  - {e['timestamp']} | {e['type']}"
            + (f" | ${e['amount']:,.2f}" if e.get("amount") else "")
            for e in claim_context.get("events", [])
        )

        return f"""You are a senior claims correspondence specialist at an insurance company.
A policyholder has contacted us asking why their claim was denied. Your role is to
draft a clear, respectful, and compassionate response that explains the denial.

CONTEXT — CLAIM:
  Claim ID: {claim_context['claim_id']}
  Claim Amount: ${claim_context['claim_amount']:,.2f}
  Incident Date: {claim_context['incident_date']}
  Policy: {claim_context['policy_id']}

CONTEXT — CLAIM HISTORY:
{events_text}

CONTEXT — POLICY COVERAGE PERIODS:
{coverages_text}

ELIGIBILITY FINDINGS (from automated policy rule evaluation):
{violations_text}

WRITING GUIDELINES:
- Address the policyholder directly using "your" and "you."
- Open by acknowledging the claim and expressing understanding that this is
  not the outcome they were hoping for.
- Explain the specific reason(s) for the denial using plain, everyday language.
  Reference the relevant dates, dollar amounts, and policy details from the
  context above so the explanation is concrete, not generic.
- Do NOT fabricate any details beyond what the eligibility findings state.
- Do NOT use technical jargon, internal system terminology, or legal language.
- Close with a brief note about next steps — e.g., the policyholder may
  contact us with questions or request a formal review.
- Keep the tone professional, warm, and empathetic throughout. This person
  may be dealing with a stressful situation.
- Keep the explanation to 3-5 sentences. Be concise but thorough.

Respond with a JSON object in this exact format:
{{
  "explanation": "The customer-facing denial explanation as described above.",
  "violation_summary": "A one-sentence internal-only technical summary of the eligibility rule(s) that triggered the denial."
}}"""

    def explain(self, claim_context: dict, violations: list[dict]) -> dict:
        """
        Given a claim's context and its SHACL violations, produce a
        customer-friendly explanation of why the claim was denied.
        """
        prompt = self._build_prompt(claim_context, violations)

        if self.is_nova:
            body = json.dumps({
                "inputText": prompt,
                "textGenerationConfig": {
                    "maxTokenCount": 600,
                    "temperature": 0.3,
                },
            })
        else:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 600,
                "temperature": 0.3,
                "messages": [{"role": "user", "content": prompt}],
            })

        response = self.bedrock.invoke_model(
            modelId=self.model_id,
            body=body,
        )

        result = json.loads(response["body"].read())

        # Extract text from response (different format for Nova vs Claude)
        if self.is_nova:
            content = result.get("results", [{}])[0].get("outputText", "")
        else:
            content = result["content"][0]["text"]

        try:
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            return json.loads(content)
        except Exception:
            return {"explanation": content, "violation_summary": "Parse error"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Explain insurance claim denials using SHACL + Bedrock LLM"
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help=f"Bedrock model shortname ({', '.join(BEDROCK_MODELS.keys())}) "
             f"or full model ID. Default: {DEFAULT_MODEL}. "
             f"Can also set BEDROCK_MODEL env var.",
    )
    parser.add_argument(
        "--region", "-r",
        default="us-east-1",
        help="AWS region for Bedrock (default: us-east-1)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("CLAIM DENIAL EXPLAINER — SHACL Eligibility + Bedrock LLM")
    print("=" * 70)

    # 1. Load graphs
    print("\n[1] Loading ontology, data, and eligibility shapes...")
    data_graph = load_graph()
    eligibility_shapes = load_eligibility_shapes()
    print(f"    Data: {len(data_graph)} triples")

    # 2. Run eligibility validation on all claims
    print("\n[2] Running SHACL eligibility validation...")
    conforms, violations, results_text = validate_claim_eligibility(
        data_graph, eligibility_shapes
    )
    print(f"    All claims eligible: {'✓ YES' if conforms else '✗ NO'}")

    if conforms:
        print("\n    No eligibility violations found. All claims pass.")
        return

    # 3. Find denied claims
    print("\n[3] Finding denied claims...")
    denied_claims = find_denied_claims(data_graph)
    print(f"    Found {len(denied_claims)} denied claim(s)")

    # 4. Match violations to denied claims and explain
    explainer = DenialExplainer(model=args.model, region=args.region)
    print(f"\n[4] Generating denial explanations via Bedrock...")
    print(f"    Model: {explainer.model_id}")
    print("-" * 70)

    for claim in denied_claims:
        claim_uri = claim["claim_uri"]
        claim_violations = violations.get(claim_uri, [])
        claim_context = get_claim_context(data_graph, claim_uri)

        print(f"\n  Claim {claim['claim_id']} (${claim['claim_amount']:,.2f})")
        print(f"  Policy: {claim['policy_id']} | Incident: {claim['incident_date']}")

        if not claim_violations:
            print("  ⚠️  Denied but no eligibility violations found.")
            print("     (Denial may be for reasons outside modeled business rules)")
            continue

        print(f"  SHACL violations ({len(claim_violations)}):")
        for v in claim_violations:
            print(f"    • {v['message']}")

        print("\n  Asking Bedrock for explanation...")
        try:
            result = explainer.explain(claim_context, claim_violations)
            print(f"\n  📋 Customer Explanation:")
            print(f"     {result['explanation']}")
            print(f"\n  🔧 Internal Summary:")
            print(f"     {result['violation_summary']}")
        except Exception as e:
            print(f"\n  ❌ Bedrock error: {e}")
            print("     Falling back to raw SHACL violations above.")

        print()
        print("-" * 70)

    # 5. Also show claims that have violations but aren't denied yet
    print("\n[5] Claims with eligibility issues (not yet denied):")
    print("-" * 70)
    denied_uris = {c["claim_uri"] for c in denied_claims}
    flagged = False
    for uri, viols in violations.items():
        if uri not in denied_uris:
            flagged = True
            for v in viols:
                print(f"  ⚠️  {v['message']}")
    if not flagged:
        print("  (none — all violations correspond to denied claims)")

    print("\n" + "=" * 70)
    print("COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
