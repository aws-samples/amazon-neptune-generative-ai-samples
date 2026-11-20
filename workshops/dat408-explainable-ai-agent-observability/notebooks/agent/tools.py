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
DAT408 - Underwriting Agent Tools
Simulates credit bureau APIs, income verification services, and collateral
evaluation systems. Data is derived from the application record (stored in
DynamoDB) rather than hardcoded dictionaries.

Adds a Bedrock Knowledge Base retrieval tool for lending policy lookup.
"""
import json
import boto3
from pathlib import Path

# Maps each policy document's file name to its real policy id and version
# (built by scripts/build_policy_corpus.py from HUD 4000.1 and the eCFR).
_MANIFEST_PATH = Path(__file__).with_name("policy_manifest.json")
POLICY_MANIFEST = json.loads(_MANIFEST_PATH.read_text())["policies"] if _MANIFEST_PATH.exists() else {}

# ---------------------------------------------------------------------------
# Configuration — these are populated at module load from environment or
# passed in via the agent initialization.
# ---------------------------------------------------------------------------
REGION = "us-east-1"
KB_ID = None  # Set by init_tools() after CloudFormation lookup

_bedrock_agent_runtime = None


def init_tools(region: str = "us-east-1", knowledge_base_id: str = None):
    """
    Initialize tool dependencies (Bedrock KB client, region).
    Called once from the notebook after CloudFormation outputs are retrieved.
    """
    global REGION, KB_ID, _bedrock_agent_runtime
    REGION = region
    KB_ID = knowledge_base_id
    _bedrock_agent_runtime = boto3.client(
        "bedrock-agent-runtime", region_name=REGION
    )
    print(f"✅ Tools initialized (region={REGION}, kb_id={KB_ID})")


# ===========================================================================
# TOOL 1: Pull Credit Report
# Simulates a credit bureau API call. Derives realistic data from the
# application's financial profile stored in DynamoDB.
# ===========================================================================

def pull_credit_report(application_id: str = None, _application: dict = None, **kwargs) -> dict:
    """
    Pull credit report for an applicant.
    
    Simulates Equifax/Experian/TransUnion tri-merge report.
    Derives data from the application's credit_profile field.
    """
    app = _application or {}
    app_id = application_id or app.get("application_id", "UNKNOWN")
    credit = app.get("credit_profile", {})

    if not credit:
        return {"error": f"No credit profile available for {app_id}"}

    score = credit.get("score", 0)

    return {
        "tool": "pull_credit_report",
        "application_id": app_id,
        "credit_score": score,
        "score_model": "FICO 10T",
        "payment_history": credit.get("payment_history", "unknown"),
        "derogatory_marks": credit.get("derogatory_marks", 0),
        "credit_utilization": credit.get("utilization", 0),
        "credit_utilization_pct": f"{credit.get('utilization', 0) * 100:.0f}%",
        "credit_history_years": credit.get("accounts_age_years", 0),
        "open_accounts": credit.get("open_accounts", 5),
        "hard_inquiries_12mo": credit.get("hard_inquiries", 1),
        "report_date": "2026-08-01",
        "bureau": "Tri-Merge (Equifax/Experian/TransUnion)",
    }


# ===========================================================================
# TOOL 2: Verify Income
# Simulates employer verification and income validation service.
# ===========================================================================

def verify_income(application_id: str = None, _application: dict = None, **kwargs) -> dict:
    """
    Verify applicant income and employment.
    
    Simulates The Work Number / employer direct verification.
    Derives data from the application's income_profile field.
    """
    app = _application or {}
    app_id = application_id or app.get("application_id", "UNKNOWN")
    income = app.get("income_profile", {})
    applicant = app.get("applicant", {})

    if not income:
        return {"error": f"No income profile available for {app_id}"}

    verified_annual = income.get("verified_annual", 0)
    stated_annual = applicant.get("annual_income", income.get("stated_annual", 0))

    # Calculate discrepancy
    if stated_annual > 0:
        discrepancy_pct = abs(verified_annual - stated_annual) / stated_annual
        income_match = discrepancy_pct < 0.10
    else:
        discrepancy_pct = 0
        income_match = False

    return {
        "tool": "verify_income",
        "application_id": app_id,
        "verified_annual_income": verified_annual,
        "verified_monthly_income": round(verified_annual / 12, 2),
        "stated_annual_income": stated_annual,
        "income_discrepancy_pct": f"{discrepancy_pct * 100:.1f}%",
        "income_match": income_match,
        "employment_status": income.get("employment_status", "unknown"),
        "employer": income.get("employer", "Unknown"),
        "position": income.get("position", "Unknown"),
        "years_at_current_employer": income.get("years_employed", 0),
        "employment_verified": income.get("employment_verified", True),
        "income_type": income.get("income_type", "salary"),
        "verification_method": "The Work Number (automated)",
        "verification_date": "2026-08-01",
    }


# ===========================================================================
# TOOL 3: Calculate DTI
# Computes debt-to-income ratio from application data.
# ===========================================================================

def calculate_dti(application_id: str = None, _application: dict = None, **kwargs) -> dict:
    """
    Calculate debt-to-income ratio.
    
    Computes both front-end (housing) and back-end (total) DTI ratios
    based on the application's financial data.
    """
    app = _application or {}
    app_id = application_id or app.get("application_id", "UNKNOWN")
    dti_data = app.get("dti_profile", {})
    income_profile = app.get("income_profile", {})

    if not dti_data:
        return {"error": f"No DTI data available for {app_id}"}

    monthly_income = income_profile.get("verified_annual", 0) / 12
    if monthly_income == 0:
        return {"error": f"Cannot calculate DTI — zero verified income for {app_id}"}

    existing_monthly_debt = dti_data.get("existing_monthly_debt", 0)
    proposed_payment = dti_data.get("proposed_monthly_payment", 0)
    total_monthly_obligations = existing_monthly_debt + proposed_payment

    back_end_ratio = total_monthly_obligations / monthly_income if monthly_income > 0 else 0
    front_end_ratio = proposed_payment / monthly_income if monthly_income > 0 else 0
    disposable = monthly_income - total_monthly_obligations

    return {
        "tool": "calculate_dti",
        "application_id": app_id,
        "gross_monthly_income": round(monthly_income, 2),
        "existing_monthly_debt": existing_monthly_debt,
        "proposed_monthly_payment": proposed_payment,
        "total_monthly_obligations": total_monthly_obligations,
        "back_end_dti_ratio": round(back_end_ratio, 4),
        "back_end_dti_pct": f"{back_end_ratio * 100:.1f}%",
        "front_end_dti_ratio": round(front_end_ratio, 4),
        "front_end_dti_pct": f"{front_end_ratio * 100:.1f}%",
        "monthly_disposable_income": round(disposable, 2),
        "debt_components": dti_data.get("debt_components", []),
    }


# ===========================================================================
# TOOL 4: Evaluate Collateral
# Simulates property appraisal / vehicle valuation lookup.
# ===========================================================================

def evaluate_collateral(application_id: str = None, _application: dict = None, **kwargs) -> dict:
    """
    Evaluate collateral/property value and calculate LTV.
    
    For unsecured loans, returns a notification that collateral 
    evaluation is not applicable.
    """
    app = _application or {}
    app_id = application_id or app.get("application_id", "UNKNOWN")
    collateral = app.get("collateral_profile")
    loan = app.get("loan", {})

    # Handle unsecured loans
    if collateral is None or loan.get("type") == "personal":
        return {
            "tool": "evaluate_collateral",
            "application_id": app_id,
            "collateral_type": "unsecured",
            "message": "No collateral for an unsecured loan; LTV does not apply.",
            "ltv_ratio": None,
        }

    appraised_value = collateral.get("appraised_value", 0)
    loan_amount = loan.get("amount_requested", 0)

    # Calculate LTV
    if appraised_value > 0:
        ltv = loan_amount / appraised_value
    else:
        ltv = 0

    return {
        "tool": "evaluate_collateral",
        "application_id": app_id,
        "collateral_type": collateral.get("property_type", "unknown"),
        "appraised_value": appraised_value,
        "loan_amount": loan_amount,
        "ltv_ratio": round(ltv, 4),
        "ltv_pct": f"{ltv * 100:.1f}%",
        "appraisal_status": collateral.get("appraisal_status", "complete"),
        "condition": collateral.get("condition", "unknown"),
        "property_address": collateral.get("address", "On file"),
        "appraisal_date": "2026-07-28",
        "appraiser_license": collateral.get("appraiser_license", "ST-2026-04821"),
    }


# ===========================================================================
# TOOL 5: Retrieve Lending Policy
# Queries the Bedrock Knowledge Base for relevant policy sections.
# ===========================================================================

def retrieve_lending_policy(query: str, application_id: str = None, _application: dict = None, **kwargs) -> dict:
    """
    Retrieve relevant lending policy sections from the Knowledge Base.
    
    The agent calls this tool with a natural language query describing
    what policy guidance it needs (e.g., "maximum LTV for an FHA purchase
    by credit score" or "qualifying ratio limits and compensating factors
    for manual underwriting").
    
    Returns relevant policy excerpts that the agent uses to reason
    about the underwriting decision.
    """
    app = _application or {}
    app_id = application_id or app.get("application_id", "UNKNOWN")

    if not KB_ID or not _bedrock_agent_runtime:
        return {
            "error": "Knowledge Base not initialized. Call init_tools() first.",
            "tool": "retrieve_lending_policy",
        }

    if not query:
        return {
            "error": "Query parameter is required. Describe what policy guidance you need.",
            "tool": "retrieve_lending_policy",
        }

    # Call Bedrock Knowledge Base Retrieve API
    try:
        response = _bedrock_agent_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": 5,
                }
            },
        )

        # Extract and format results
        results = []
        for i, result in enumerate(response.get("retrievalResults", [])):
            content = result.get("content", {}).get("text", "")
            source = result.get("location", {}).get("s3Location", {}).get("uri", "unknown")
            score = result.get("score", 0)
            
            # Map the source document to its policy id and version via the manifest.
            meta = POLICY_MANIFEST.get(source.split("/")[-1], {})
            policy_num = meta.get("policy_id", "Unknown")

            results.append({
                "rank": i + 1,
                "policy_reference": policy_num,
                "policy_version": meta.get("version", "unknown"),
                # The exact passage read: the Knowledge Base chunk id, which is also
                # the id of its Chunk node in the Neptune Analytics graph.
                "chunk_id": result.get("metadata", {}).get("x-amz-bedrock-kb-chunk-id"),
                "source_document": source.split("/")[-1] if "/" in source else source,
                "relevance_score": round(score, 4) if isinstance(score, float) else score,
                "content": content,
            })

        return {
            "tool": "retrieve_lending_policy",
            "application_id": app_id,
            "query": query,
            "num_results": len(results),
            "policy_excerpts": results,
        }

    except Exception as e:
        return {
            "tool": "retrieve_lending_policy",
            "application_id": app_id,
            "error": f"Knowledge Base retrieval failed: {str(e)}",
            "query": query,
        }
