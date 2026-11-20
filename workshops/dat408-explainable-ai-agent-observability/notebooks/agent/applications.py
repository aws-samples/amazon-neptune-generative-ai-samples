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
DAT408 - Loan Application Store (DynamoDB-backed)

Pre-seeded applications produce varied agent reasoning paths.
Attendees can also create their own applications via the notebook.

Application schema includes sub-profiles (credit, income, DTI, collateral)
that the mock tools use to derive realistic responses.
"""
import uuid
import boto3
from boto3.dynamodb.conditions import Attr
from decimal import Decimal
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# DynamoDB Configuration
# ---------------------------------------------------------------------------
TABLE_NAME = "dat408-applications"
REGION = "us-east-1"

_dynamodb = None
_table = None


def init_applications(region: str = "us-east-1", table_name: str = "dat408-applications"):
    """Initialize the DynamoDB connection for the application store."""
    global REGION, TABLE_NAME, _dynamodb, _table
    REGION = region
    TABLE_NAME = table_name
    _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    _table = _dynamodb.Table(TABLE_NAME)
    print(f"✅ Application store initialized (table={TABLE_NAME}, region={REGION})")


def _ensure_table():
    """Lazy initialization if init_applications hasn't been called."""
    global _dynamodb, _table
    if _table is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
        _table = _dynamodb.Table(TABLE_NAME)


# ---------------------------------------------------------------------------
# CRUD Operations
# ---------------------------------------------------------------------------

def get_application(application_id: str) -> dict:
    """Retrieve a single application by ID."""
    _ensure_table()
    response = _table.get_item(Key={"application_id": application_id})
    item = response.get("Item")
    if item:
        return _deserialize(item)
    return None


def list_applications(status: str = None) -> list:
    """List all applications, optionally filtered by status."""
    _ensure_table()
    if status:
        response = _table.scan(
            FilterExpression=Attr('application_status').eq(status),
        )
    else:
        response = _table.scan()
    return [_deserialize(item) for item in response.get("Items", [])]


def put_application(application: dict) -> dict:
    """Store an application in DynamoDB."""
    _ensure_table()
    item = _serialize(application)
    _table.put_item(Item=item)
    return application


def create_application(
    applicant_name: str,
    annual_income: int,
    credit_score: int,
    employment_years: float,
    existing_debt: float,
    loan_type: str,
    amount_requested: float,
    term_months: int = 360,
    property_value: float = None,
    property_type: str = None,
    employer: str = "Not Specified",
    position: str = "Not Specified",
) -> dict:
    """
    Create a new loan application with auto-generated profiles.
    
    This is the function attendees use in the "Explore" notebook cell.
    It generates realistic sub-profiles from the provided parameters.
    """
    app_id = f"LA-2026-{uuid.uuid4().hex[:5].upper()}"

    # Derive credit profile from score
    credit_profile = _derive_credit_profile(credit_score)

    # Derive income profile
    income_profile = _derive_income_profile(
        annual_income, employment_years, employer, position
    )

    # Derive DTI profile
    proposed_payment = _estimate_monthly_payment(amount_requested, term_months)
    dti_profile = _derive_dti_profile(
        annual_income, existing_debt, proposed_payment
    )

    # Derive collateral profile (if secured)
    collateral_profile = None
    if loan_type in ("home_purchase", "refinance", "auto") and property_value:
        collateral_profile = _derive_collateral_profile(
            property_value, property_type, loan_type
        )

    application = {
        "application_id": app_id,
        "application_status": "pending",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "applicant": {
            "name": applicant_name,
            "annual_income": annual_income,
            "employment_status": "full_time",
            "years_employed": employment_years,
            "existing_debt": existing_debt,
        },
        "loan": {
            "type": loan_type,
            "program": "FHA 203(b)" if loan_type == "home_purchase" else loan_type,
            "amount_requested": amount_requested,
            "term_months": term_months,
            "property_value": property_value,
            "property_type": property_type,
        },
        "credit_profile": credit_profile,
        "income_profile": income_profile,
        "dti_profile": dti_profile,
        "collateral_profile": collateral_profile,
    }

    put_application(application)
    print(f"✅ Application {app_id} created for {applicant_name}")
    return application


# ---------------------------------------------------------------------------
# Profile Derivation Helpers
# ---------------------------------------------------------------------------

def _derive_credit_profile(score: int) -> dict:
    """Generate a realistic credit profile from a score."""
    if score >= 780:
        return {
            "score": score,
            "payment_history": "excellent",
            "derogatory_marks": 0,
            "utilization": 0.08,
            "accounts_age_years": 15,
            "open_accounts": 8,
            "hard_inquiries": 0,
        }
    elif score >= 740:
        return {
            "score": score,
            "payment_history": "excellent",
            "derogatory_marks": 0,
            "utilization": 0.22,
            "accounts_age_years": 10,
            "open_accounts": 6,
            "hard_inquiries": 1,
        }
    elif score >= 700:
        return {
            "score": score,
            "payment_history": "good",
            "derogatory_marks": 0,
            "utilization": 0.35,
            "accounts_age_years": 7,
            "open_accounts": 5,
            "hard_inquiries": 2,
        }
    elif score >= 670:
        return {
            "score": score,
            "payment_history": "good",
            "derogatory_marks": 1,
            "utilization": 0.45,
            "accounts_age_years": 5,
            "open_accounts": 4,
            "hard_inquiries": 3,
        }
    elif score >= 640:
        return {
            "score": score,
            "payment_history": "fair",
            "derogatory_marks": 1,
            "utilization": 0.55,
            "accounts_age_years": 4,
            "open_accounts": 4,
            "hard_inquiries": 3,
        }
    elif score >= 600:
        return {
            "score": score,
            "payment_history": "fair",
            "derogatory_marks": 2,
            "utilization": 0.67,
            "accounts_age_years": 3,
            "open_accounts": 3,
            "hard_inquiries": 4,
        }
    else:
        return {
            "score": score,
            "payment_history": "poor",
            "derogatory_marks": 4,
            "utilization": 0.89,
            "accounts_age_years": 2,
            "open_accounts": 3,
            "hard_inquiries": 5,
        }


def _derive_income_profile(
    annual_income: int, years_employed: float, employer: str, position: str
) -> dict:
    """Generate income verification profile."""
    # Simulate minor discrepancy (verified slightly different from stated)
    if annual_income > 100000:
        verified = annual_income  # High earners match exactly (W-2 verified)
    elif annual_income > 60000:
        verified = annual_income  # Salaried professionals match
    else:
        verified = int(annual_income * 0.97)  # Minor rounding from hourly calc

    return {
        "verified_annual": verified,
        "stated_annual": annual_income,
        "employment_status": "full_time",
        "employer": employer,
        "position": position,
        "years_employed": years_employed,
        "employment_verified": True,
        "income_type": "salary",
    }


def _derive_dti_profile(
    annual_income: int, existing_debt: float, proposed_payment: float
) -> dict:
    """Generate DTI profile from income and debt."""
    monthly_income = annual_income / 12
    # Estimate monthly debt payments (roughly 2% of total outstanding debt)
    existing_monthly_debt = round(existing_debt * 0.02, 2) if existing_debt else 0
    total_obligations = existing_monthly_debt + proposed_payment
    ratio = total_obligations / monthly_income if monthly_income > 0 else 0
    disposable = monthly_income - total_obligations

    return {
        "existing_monthly_debt": round(existing_monthly_debt, 2),
        "proposed_monthly_payment": round(proposed_payment, 2),
        "total_monthly_obligations": round(total_obligations, 2),
        "ratio": round(ratio, 4),
        "disposable_monthly": round(max(disposable, 0), 2),
        "debt_components": [
            {"type": "existing_obligations", "monthly": round(existing_monthly_debt, 2)},
            {"type": "proposed_loan", "monthly": round(proposed_payment, 2)},
        ],
    }


def _derive_collateral_profile(
    property_value: float, property_type: str, loan_type: str
) -> dict:
    """Generate collateral evaluation profile."""
    condition = "good"
    if property_value > 600000:
        condition = "excellent"
    elif property_value < 200000:
        condition = "fair"

    return {
        "appraised_value": property_value,
        "property_type": property_type or "single_family",
        "appraisal_status": "complete",
        "condition": condition,
        "appraiser_license": "ST-2026-04821",
        "address": "On file",
    }


def _estimate_monthly_payment(loan_amount: float, term_months: int) -> float:
    """Estimate monthly payment at current market rate (~6.5% for mortgage)."""
    if term_months <= 0:
        return 0
    # Simple amortization estimate
    annual_rate = 0.065  # Approximate current rate
    monthly_rate = annual_rate / 12
    if monthly_rate == 0:
        return loan_amount / term_months
    payment = loan_amount * (monthly_rate * (1 + monthly_rate) ** term_months) / (
        (1 + monthly_rate) ** term_months - 1
    )
    return round(payment, 2)


# ---------------------------------------------------------------------------
# Serialization (handle DynamoDB Decimal types)
# ---------------------------------------------------------------------------

def _serialize(obj):
    """Convert Python types to DynamoDB-compatible types."""
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items() if v is not None}
    elif isinstance(obj, list):
        return [_serialize(i) for i in obj]
    elif isinstance(obj, bool):
        return obj
    elif isinstance(obj, float):
        return Decimal(str(round(obj, 4)))
    elif isinstance(obj, int):
        return Decimal(str(obj))
    return obj


def _deserialize(obj):
    """Convert DynamoDB Decimal types back to Python floats/ints."""
    if isinstance(obj, dict):
        return {k: _deserialize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_deserialize(i) for i in obj]
    elif isinstance(obj, Decimal):
        if obj == int(obj):
            return int(obj)
        return float(obj)
    return obj


# ---------------------------------------------------------------------------
# Pre-Seeded Applications
# These are loaded into DynamoDB during workshop setup.
# They produce varied agent reasoning paths (approve, deny, escalate).
# ---------------------------------------------------------------------------

SEED_APPLICATIONS = [
    {
        "application_id": "LA-2026-00147",
        "application_status": "pending",
        "submitted_at": "2026-07-28T09:15:00Z",
        "applicant": {
            "name": "Jane Doe",
            "annual_income": 92000,
            "employment_status": "full_time",
            "years_employed": 4,
            "existing_debt": 28000,
        },
        "loan": {
            "type": "home_purchase",
            "program": "FHA 203(b)",
            "amount_requested": 340000,
            "term_months": 360,
            "property_value": 430000,
            "property_type": "single_family",
        },
        "credit_profile": {
            "score": 745,
            "payment_history": "excellent",
            "derogatory_marks": 0,
            "utilization": 0.22,
            "accounts_age_years": 8,
            "open_accounts": 6,
            "hard_inquiries": 1,
        },
        "income_profile": {
            "verified_annual": 92000,
            "stated_annual": 92000,
            "employment_status": "full_time",
            "employer": "AnyCompany Technologies",
            "position": "Senior Software Engineer",
            "years_employed": 4,
            "employment_verified": True,
            "income_type": "salary",
        },
        "dti_profile": {
            "existing_monthly_debt": 560,
            "proposed_monthly_payment": 2149,
            "total_monthly_obligations": 2709,
            "ratio": 0.353,
            "disposable_monthly": 4958,
            "debt_components": [
                {"type": "auto_loan", "monthly": 380},
                {"type": "student_loans", "monthly": 180},
                {"type": "proposed_mortgage", "monthly": 2149},
            ],
        },
        "collateral_profile": {
            "appraised_value": 430000,
            "property_type": "single_family",
            "appraisal_status": "complete",
            "condition": "good",
            "appraiser_license": "ST-2026-04821",
            "address": "742 Maple Drive, Austin TX 78701",
        },
        "_expected_outcome": "approve",
        "_notes": "Strong applicant. MDCS 745, ratios 28.0/35.3 within the 31/43 limits (HUD 4000.1 II.A.5.d viii), LTV 79% under the 96.5% purchase maximum (II.A.2.b). Clean approval path.",
    },
    {
        "application_id": "LA-2026-00148",
        "application_status": "pending",
        "submitted_at": "2026-07-28T10:30:00Z",
        "applicant": {
            "name": "Carlos Salazar",
            "annual_income": 48000,
            "employment_status": "full_time",
            "years_employed": 1,
            "existing_debt": 22000,
        },
        "loan": {
            "type": "home_purchase",
            "program": "FHA 203(b)",
            "amount_requested": 280000,
            "term_months": 360,
            "property_value": 285000,
            "property_type": "single_family",
        },
        "credit_profile": {
            "score": 618,
            "payment_history": "fair",
            "derogatory_marks": 2,
            "utilization": 0.67,
            "accounts_age_years": 3,
            "open_accounts": 4,
            "hard_inquiries": 4,
        },
        "income_profile": {
            "verified_annual": 45000,
            "stated_annual": 48000,
            "employment_status": "full_time",
            "employer": "AnyCompany Retail",
            "position": "Assistant Manager",
            "years_employed": 1,
            "employment_verified": True,
            "income_type": "salary",
        },
        "dti_profile": {
            "existing_monthly_debt": 440,
            "proposed_monthly_payment": 1770,
            "total_monthly_obligations": 2210,
            "ratio": 0.553,
            "disposable_monthly": 1790,
            "debt_components": [
                {"type": "credit_cards", "monthly": 280},
                {"type": "personal_loan", "monthly": 160},
                {"type": "proposed_mortgage", "monthly": 1770},
            ],
        },
        "collateral_profile": {
            "appraised_value": 285000,
            "property_type": "single_family",
            "appraisal_status": "complete",
            "condition": "fair",
            "appraiser_license": "ST-2026-03195",
            "address": "1847 Elm Street, Dallas TX 75201",
        },
        "_expected_outcome": "deny",
        "_notes": "Clear denial under HUD 4000.1: LTV 98.2% exceeds the 96.5% purchase maximum (II.A.2.b), and back-end DTI 55%+ exceeds even the 40/50 compensating-factor limit (II.A.5.d viii). MDCS 618 clears FHA's 580 floor, so credit score alone is not a violation; 2 derogatory marks, 1 year at employer and income 6.3% below stated add risk.",
    },
    {
        "application_id": "LA-2026-00149",
        "application_status": "pending",
        "submitted_at": "2026-07-28T11:45:00Z",
        "applicant": {
            "name": "Saanvi Sarkar",
            "annual_income": 85000,
            "employment_status": "full_time",
            "years_employed": 6,
            "existing_debt": 41000,
        },
        "loan": {
            "type": "home_purchase",
            "program": "FHA 203(b)",
            "amount_requested": 360000,
            "term_months": 360,
            "property_value": 400000,
            "property_type": "single_family",
        },
        "credit_profile": {
            "score": 704,
            "payment_history": "good",
            "derogatory_marks": 0,
            "utilization": 0.34,
            "accounts_age_years": 9,
            "open_accounts": 7,
            "hard_inquiries": 2,
        },
        "income_profile": {
            "verified_annual": 85000,
            "stated_annual": 85000,
            "employment_status": "full_time",
            "employer": "AnyCompany Logistics",
            "position": "Operations Manager",
            "years_employed": 6,
            "employment_verified": True,
            "income_type": "salary",
        },
        "dti_profile": {
            "existing_monthly_debt": 1265,
            "proposed_monthly_payment": 2275,
            "total_monthly_obligations": 3540,
            "ratio": 0.500,
            "disposable_monthly": 3543,
            "debt_components": [
                {"type": "auto_loan", "monthly": 640},
                {"type": "student_loans", "monthly": 320},
                {"type": "credit_cards", "monthly": 305},
                {"type": "proposed_mortgage", "monthly": 2275},
            ],
        },
        "collateral_profile": {
            "appraised_value": 400000,
            "property_type": "single_family",
            "appraisal_status": "complete",
            "condition": "good",
            "appraiser_license": "ST-2026-06610",
            "address": "512 Birchwood Lane, Plano TX 75024",
        },
        "_expected_outcome": "escalate",
        "_notes": "Borderline by design: MDCS 704, LTV 90%, ratios 32.1/50.0 sit exactly at HUD 4000.1's 40/50 band (II.A.5.d viii), which is approvable only with two documented compensating factors (reserves, minimal payment increase, additional income, residual income). The agent cannot verify those, so escalation to a human underwriter is the correct outcome.",
    },

]


def seed_applications():
    """
    Load pre-seeded applications into DynamoDB.
    Called once during workshop setup.
    """
    _ensure_table()
    count = 0
    for app in SEED_APPLICATIONS:
        item = _serialize(app)
        _table.put_item(Item=item)
        count += 1
        print(f"  📋 Seeded: {app['application_id']} ({app['applicant']['name']}) → expected: {app['_expected_outcome']}")
    print(f"\n✅ Seeded {count} applications into {TABLE_NAME}")
    return count
