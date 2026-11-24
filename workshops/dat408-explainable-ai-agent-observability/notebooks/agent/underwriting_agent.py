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
DAT408 - Loan Underwriting Agent (ReAct Pattern)
Pre-built for attendees. They instrument it with observability.

Key design:
- Uses Bedrock Knowledge Base for lending policy retrieval (RAG)
- Applications sourced from DynamoDB (not hardcoded)
- Agent REASONS over retrieved policy text — decisions are LLM-generated
- Trace callback allows attendees to plug in DynamoDB instrumentation
"""
import json
import time
import uuid
import boto3

# Bedrock client (initialized in __init__ or by caller)
_bedrock = None
MODEL_ID = "us.anthropic.claude-sonnet-5"

# Import tools
from .tools import (
    pull_credit_report,
    verify_income,
    calculate_dti,
    evaluate_collateral,
    retrieve_lending_policy,
)

SYSTEM_PROMPT = """You are an AI loan underwriting agent at an FHA-approved mortgage lender. Your job is to evaluate FHA-insured home purchase loan applications by gathering relevant data, retrieving the applicable policies, and making a decision based on those policies.

The policies in the knowledge base are real: sections of the FHA Single Family Housing Policy Handbook 4000.1 (HUD), which set the underwriting requirements, and sections of Regulation B (12 CFR 1002) and Regulation Z (12 CFR 1026). Evaluate each application as a manual underwrite under HUD 4000.1 II.A.5.

You operate under strict regulatory requirements. Under the Equal Credit Opportunity Act (ECOA) and CFPB Circular 2022-03, you MUST be able to provide specific, accurate reasons for any adverse action (denial). Your reasoning must be traceable and explainable.

## Available Tools

- pull_credit_report(application_id): Pull the applicant's credit report — score, payment history, derogatory marks, utilization
- verify_income(application_id): Verify employment and income — stated vs verified, employer, tenure
- calculate_dti(application_id): Calculate debt-to-income ratio — front-end, back-end, disposable income
- evaluate_collateral(application_id): Assess property/collateral value and LTV ratio. Skip this for unsecured personal loans.
- retrieve_lending_policy(query): **Retrieve relevant lending policy sections from the knowledge base.** Use this to look up specific requirements before making a decision. Example queries: "maximum LTV for a purchase based on minimum decision credit score", "qualifying ratio limits and compensating factors for manual underwriting", "derogatory credit and collection accounts", "employment history requirements", "adverse action notice reasons"

## Decision Framework

1. GATHER DATA: Use the first four tools to collect applicant information
2. RETRIEVE POLICY: Use retrieve_lending_policy to look up the policy that sets the threshold for EVERY factor you evaluated: credit-score eligibility, LTV limits, qualifying ratios and compensating factors, and credit history or income requirements when they are a concern. Use one focused query per factor. You can only cite (and therefore only give as an adverse-action reason) a policy you retrieved.
3. ANALYZE: Compare the gathered data against the retrieved policy thresholds
4. DECIDE: Produce one of three decisions:
   - **approve**: Application meets all policy requirements
   - **deny**: Application violates one or more policy requirements with no compensating factors
   - **escalate**: Application could be approvable only with conditions a human must verify (for example qualifying ratios that require documented compensating factors) or has borderline characteristics requiring senior underwriter review

## Required Output Format

After gathering all information, you MUST produce a final decision in this exact JSON format:

```json
{
  "decision": "approve|deny|escalate",
  "reasoning": "Clear explanation of the decision based on retrieved policy",
  "policies_cited": ["HUD 4000.1 II.A.5.d viii", "12 CFR 1002.9(a)(2)", ...],
  "policies_violated": ["HUD 4000.1 II.A.2.b", ...],
  "risk_factors": ["factor 1", "factor 2", ...],
  "adverse_action_reasons": ["specific reason 1", ...] 
}
```

The adverse_action_reasons field is REQUIRED for deny decisions (per ECOA/Regulation B). Each reason must be specific and relate to factors actually evaluated — never use vague language like "did not meet standards."

policies_cited lists every policy section you relied on, including ones the application satisfied or that only gave context. policies_violated lists ONLY the sections whose requirements this application failed to meet (for example a DTI above the stated maximum), and it must list EVERY one of them: ECOA requires the principal reasons for a denial, so each failed requirement needs its policy retrieved, cited and listed here. It is a subset of policies_cited, it is REQUIRED for deny decisions, and it is empty for approvals.

## ReAct Pattern

You MUST follow the ReAct pattern for each step:

Thought: [your reasoning about what to do next]
Action: [tool_name]
Action Input: [input to the tool as JSON]

IMPORTANT: After writing "Action Input:", STOP IMMEDIATELY. Do NOT write "Observation:" — the system will provide the real observation. Never simulate, hallucinate, or generate tool responses yourself.

After receiving an observation, continue with another Thought/Action cycle.
When you have gathered sufficient information AND retrieved relevant policies, produce your final decision.

## Critical rules (do not violate)

1. Your FIRST response MUST be a single Thought and a single Action that calls a tool. Do NOT include the decision JSON in your first response.
2. Do NOT output the final decision JSON until you have called ALL of these tools at least once: pull_credit_report, verify_income, calculate_dti, and retrieve_lending_policy (also call evaluate_collateral for secured loans). You cannot decide before gathering data and policy.
3. Emit exactly ONE Thought and ONE Action per response, then stop and wait for the Observation. Never put a Thought/Action and the decision JSON in the same response.
4. policies_cited must contain ONLY policies that retrieve_lending_policy actually returned in this evaluation. Cite each as the Policy ID shown in the retrieved text (for example "HUD 4000.1 II.A.5.d" or "12 CFR 1002.9"), optionally followed by the paragraph. Never cite a policy from memory.
"""

TOOLS = {
    "pull_credit_report": pull_credit_report,
    "verify_income": verify_income,
    "calculate_dti": calculate_dti,
    "evaluate_collateral": evaluate_collateral,
    "retrieve_lending_policy": retrieve_lending_policy,
}


class UnderwritingAgent:
    def __init__(self, trace_callback=None, region="us-east-1", model_id=None):
        """
        Initialize the underwriting agent.

        Args:
            trace_callback: Optional function called after each step.
                           Signature: callback(evaluation_id, step_num, thought, action,
                                              action_input, observation, application_id)
                           This is where attendees plug in their DynamoDB instrumentation.
            region: AWS region for Bedrock.
            model_id: Override the default model ID.
        """
        global _bedrock, MODEL_ID
        self.trace_callback = trace_callback
        self.region = region
        if model_id:
            MODEL_ID = model_id
        _bedrock = boto3.client("bedrock-runtime", region_name=region)

    def evaluate(self, application: dict, verbose: bool = False, max_steps: int = 20) -> dict:
        """
        Evaluate a loan application using the ReAct reasoning loop.

        Args:
            application: Dict with full loan application (from DynamoDB)
            verbose: If True, print each reasoning step
            max_steps: Maximum reasoning steps before forced escalation

        Returns:
            Dict with decision, reasoning, policies_cited, risk_factors,
            and adverse_action_reasons
        """
        evaluation_id = str(uuid.uuid4())
        application_id = application.get("application_id", "UNKNOWN")

        # Build the initial prompt with application summary
        app_summary = self._format_application_summary(application)
        messages = [
            {
                "role": "user",
                "content": f"Evaluate this loan application and produce an underwriting decision.\n\n{app_summary}",
            }
        ]

        # Core tools the agent must call before any decision is accepted. This
        # forces real ReAct steps instead of a one-shot decision with invented
        # policies. evaluate_collateral is only needed for secured loans, so it
        # is not required here.
        required_tools = {"pull_credit_report", "verify_income", "calculate_dti", "retrieve_lending_policy"}
        tools_called = set()

        for step_num in range(max_steps):
            # Call Bedrock
            response = self._call_llm(messages)

            # Accept a final decision ONLY after the core evidence tools have run.
            if self._contains_final_decision(response) and required_tools.issubset(tools_called):
                decision = self._extract_decision(response)

                # Emit final trace
                if self.trace_callback:
                    self.trace_callback(
                        evaluation_id=evaluation_id,
                        step_num=step_num,
                        thought=f"Final decision: {decision.get('decision', 'unknown')}",
                        action="FINAL_DECISION",
                        action_input=json.dumps(decision),
                        observation=decision,
                        application_id=application_id,
                    )

                if verbose:
                    print(f"\n{'='*60}")
                    print(f"FINAL DECISION: {decision.get('decision', 'unknown').upper()}")
                    print(f"{'='*60}")

                return decision

            # Parse the ReAct response into one Thought/Action/Action Input.
            thought, action, action_input = self._parse_response(response)

            # No runnable tool call (the model tried to decide early, or named an
            # unknown tool): direct it to gather the data it still needs and loop
            # again. Bounded by max_steps, so this cannot spin forever.
            if action not in TOOLS:
                missing = ", ".join(sorted(required_tools - tools_called)) or "the required tools"
                if verbose:
                    print(f"\n--- Step {step_num + 1}: gathering ---")
                    print(f"No tool call yet; directing the agent to call: {missing}")
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Do not produce a decision yet. You still need to call these tools: {missing}. "
                        "Respond with a single Thought and one Action that calls one of them."
                    ),
                })
                continue

            if verbose:
                print(f"\n--- Step {step_num + 1} ---")
                print(f"Thought: {thought[:200]}")
                print(f"Action: {action}")
                print(f"Action Input: {action_input[:100]}")

            # Execute the tool
            try:
                tool_input = (
                    json.loads(action_input)
                    if isinstance(action_input, str) and action_input.strip()
                    else {}
                )
            except json.JSONDecodeError:
                tool_input = {"query": action_input} if action == "retrieve_lending_policy" else {}

            # Inject application data into tool calls
            tool_input["_application"] = application
            tool_input["application_id"] = application_id
            observation = TOOLS[action](**tool_input)
            tools_called.add(action)

            if verbose:
                obs_str = json.dumps(observation) if isinstance(observation, dict) else str(observation)
                print(f"Observation: {obs_str[:300]}...")

            # --- TRACE CALLBACK: Where attendees plug in DynamoDB ---
            if self.trace_callback:
                self.trace_callback(
                    evaluation_id=evaluation_id,
                    step_num=step_num,
                    thought=thought,
                    action=action,
                    action_input=action_input,
                    observation=observation,
                    application_id=application_id,
                )

            # Add to conversation for next iteration
            messages.append({"role": "assistant", "content": response})
            obs_str = json.dumps(observation, default=str) if isinstance(observation, dict) else str(observation)
            messages.append({"role": "user", "content": f"Observation: {obs_str}"})

        # Max steps exceeded — force escalation
        return {
            "decision": "escalate",
            "reasoning": "Agent exceeded maximum reasoning steps. Escalating to human underwriter for manual review.",
            "policies_cited": [],
            "policies_violated": [],
            "risk_factors": ["excessive_reasoning_steps"],
            "adverse_action_reasons": [],
        }

    def _format_application_summary(self, application: dict) -> str:
        """Format application data for the initial prompt."""
        applicant = application.get("applicant", {})
        loan = application.get("loan", {})

        summary = f"""## Loan Application: {application.get('application_id', 'N/A')}

**Applicant:** {applicant.get('name', 'N/A')}
**Annual Income (stated):** ${applicant.get('annual_income', 0):,.0f}
**Employment:** {applicant.get('employment_status', 'N/A')}, {applicant.get('years_employed', 0)} years
**Existing Debt:** ${applicant.get('existing_debt', 0):,.0f}

**Loan Type:** {loan.get('type', 'N/A')} ({loan.get('program', 'N/A')})
**Amount Requested:** ${loan.get('amount_requested', 0):,.0f}
**Term:** {loan.get('term_months', 0)} months
**Property Value:** {f"${loan.get('property_value'):,.0f}" if loan.get('property_value') else 'N/A (unsecured)'}
**Property Type:** {loan.get('property_type', 'N/A')}

Please gather data using the available tools, retrieve applicable lending policies, and produce your underwriting decision."""
        return summary

    def _call_llm(self, messages: list) -> str:
        """Call Bedrock with the conversation history.

        Retries up to 3 times on ThrottlingException and ServiceException
        with exponential backoff + jitter (base 2s, max 10s).
        """
        import random
        from botocore.exceptions import ClientError

        max_retries = 3
        base_delay = 2.0
        max_delay = 10.0

        for attempt in range(max_retries + 1):
            try:
                response = _bedrock.invoke_model(
                    modelId=MODEL_ID,
                    body=json.dumps(
                        {
                            "anthropic_version": "bedrock-2023-05-31",
                            "max_tokens": 2048,
                            # Sonnet 5 rejects non-default temperature and runs adaptive
                            # thinking when omitted; keep the ReAct loop text-only.
                            "thinking": {"type": "disabled"},
                            "system": SYSTEM_PROMPT,
                            "messages": messages,
                        }
                    ),
                )
                result = json.loads(response["body"].read())
                return next(b["text"] for b in result["content"] if b["type"] == "text")

            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code in ("ThrottlingException", "ServiceException") and attempt < max_retries:
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                    print(
                        f"  ⚠️  Bedrock {error_code} (attempt {attempt + 1}/{max_retries + 1}). "
                        f"Retrying in {delay:.1f}s... This is normal with many concurrent users."
                    )
                    time.sleep(delay)
                else:
                    raise RuntimeError(
                        f"Bedrock call failed after {attempt + 1} attempt(s): {error_code} — {e}\n"
                        f"💡 If throttling persists, wait 30s and retry. "
                        f"You can also check your Bedrock service quotas in the AWS console."
                    ) from e

    def _parse_response(self, response_text: str) -> tuple:
        """Parse Thought/Action/Action Input from LLM response.

        Handles both plain ('Thought:') and markdown-bold ('**Thought:**')
        formats, and backtick-wrapped JSON in Action Input.
        """
        import re

        thought = ""
        action = ""
        action_input = ""

        # Pattern: optional ** before label, label, optional ** after colon, value
        # Matches: "Thought: x", "**Thought:** x", "**Thought**: x", etc.
        _FIELD = re.compile(
            r"^\*{0,2}(Thought|Action\s+Input|Action)\*{0,2}\s*:\s*\*{0,2}\s*(.*)",
            re.IGNORECASE,
        )

        lines = response_text.strip().split("\n")
        current_field = None

        for line in lines:
            m = _FIELD.match(line.strip())
            if m:
                label = m.group(1).strip().lower().replace(" ", "_")  # "action_input"
                value = m.group(2).strip().strip("`").strip()
                if label == "thought":
                    current_field = "thought"
                    thought = value
                elif label == "action_input":
                    current_field = "action_input"
                    action_input = value
                elif label == "action":
                    current_field = "action"
                    action = value.strip("`")
            elif current_field == "thought":
                thought += " " + line.strip()
            elif current_field == "action_input":
                stripped = line.strip().strip("`")
                # Stop accumulating if the model ran on past "Action Input:" and
                # started hallucinating its own Observation / next Thought / Action.
                # The system prompt says to STOP after Action Input, but models
                # sometimes continue; this prevents that tail from corrupting the
                # tool input (e.g. '{"query": "x"} Observation: {...}').
                if re.match(r"^\*{0,2}(Observation|Thought|Action)\b", stripped, re.IGNORECASE):
                    current_field = None
                    continue
                # Skip markdown separator lines (---, ===, ***)
                if stripped and not re.match(r"^[-=*]{3,}$", stripped):
                    action_input += " " + stripped

        return thought, action, action_input.strip().strip("`")

    def _contains_final_decision(self, response_text: str) -> bool:
        """Check if the response contains a final JSON decision block with a valid decision value."""
        import re
        # Try ```json block first — must parse and have valid 'decision' key
        json_match = re.search(r"```json\s*\n?(.*?)\n?\s*```", response_text, re.DOTALL)
        if json_match:
            try:
                obj = json.loads(json_match.group(1))
                if isinstance(obj, dict) and obj.get("decision") in ("approve", "deny", "escalate"):
                    return True
            except (json.JSONDecodeError, ValueError):
                pass
        # Check for raw JSON where "decision" key is set to a valid value
        for decision in ("approve", "deny", "escalate"):
            if re.search(r'\{\s*"decision"\s*:\s*"' + decision + r'"', response_text):
                return True
        return False

    def _extract_decision(self, response_text: str) -> dict:
        """Extract the final decision JSON from the response."""
        import re

        _VALID = ("approve", "deny", "escalate")

        # 1. Try ```json ... ``` block first
        json_match = re.search(r"```json\s*\n?(.*?)\n?\s*```", response_text, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group(1))
                if isinstance(result, dict) and result.get("decision") in _VALID:
                    return self._fill_empty_fields(result, response_text)
            except json.JSONDecodeError:
                pass

        # 2. Scan every { position and let Python's JSON parser decide — handles
        #    apostrophes, newlines, and any other character that trips up regex counting
        decoder = json.JSONDecoder()
        start = 0
        while True:
            pos = response_text.find("{", start)
            if pos == -1:
                break
            try:
                obj, _ = decoder.raw_decode(response_text, pos)
                if isinstance(obj, dict) and obj.get("decision") in _VALID:
                    return self._fill_empty_fields(obj, response_text)
            except json.JSONDecodeError:
                pass
            start = pos + 1

        # 3. Text-based fallback
        decision = "escalate"
        if "approve" in response_text.lower() and "deny" not in response_text.lower():
            decision = "approve"
        elif "deny" in response_text.lower() or "decline" in response_text.lower():
            decision = "deny"

        result = {
            "decision": decision,
            "reasoning": response_text[:500],
            "policies_cited": [],
            "policies_violated": [],
            "risk_factors": [],
            "adverse_action_reasons": [],
        }
        return self._fill_empty_fields(result, response_text)

    def _fill_empty_fields(self, decision: dict, response_text: str) -> dict:
        """Post-process: fill empty structured fields from the full response text.
        The model often puts policy references in the reasoning prose but omits
        the structured lists — extract them rather than forcing a costly retry.
        """
        import re

        # policies_cited: scan for real policy ids (HUD 4000.1 sections, 12 CFR sections)
        if not decision.get("policies_cited"):
            refs = list(dict.fromkeys(
                re.findall(r'HUD 4000\.1 [IVX]+\.[A-Z]\.\d+\.[a-z](?:\s+[ivx]+)?|12 CFR \d{4}\.\d+(?:\([a-z0-9]+\))*', response_text)
            ))
            if refs:
                decision["policies_cited"] = refs

        # adverse_action_reasons: pull sentences from reasoning that name policy violations
        if decision.get("decision") in ("deny", "escalate") and not decision.get("adverse_action_reasons"):
            reasoning = decision.get("reasoning", "")
            sentences = [
                s.strip() for s in re.split(r'[.\n]', reasoning)
                if len(s.strip()) > 30 and any(
                    kw in s.lower() for kw in
                    ["below", "exceed", "above", "fail", "violat", "not meet", "insufficient"]
                )
            ]
            if sentences:
                decision["adverse_action_reasons"] = sentences[:4]

        # policies_violated is never inferred from prose: a violation is a claim
        # only the agent can make. Missing means none were stated.
        decision.setdefault("policies_violated", [])

        return decision
