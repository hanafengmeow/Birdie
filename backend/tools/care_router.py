"""care_router: routes symptom descriptions to care settings. See CLAUDE.md for full spec.

Architecture:
  Step 1  Context extraction — Claude extracts symptom context from user_message
           (skipped if caller already provides a complete extracted_context dict)
  Step 2  Routing decision — Claude applies the routing framework from CLAUDE.md;
           key plan facts (telehealth_covered, pcp_referral_required) are injected
  Step 3  Coverage overlay — programmatic copay lookup from plan_json fields
  Step 4  Prior auth check — keyword-match against plan_json.prior_auth_flags

Hard rules enforced (CLAUDE.md):
  - NEVER diagnose or recommend specific treatments
  - NEVER confirm a provider is in-network
  - ALWAYS end response with the exact disclaimer text
  - Mental health routing must NEVER be mixed with physical symptom routing
  - plan_json None → general guidance + "Upload your SBC" note
"""

import json
from typing import Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from config import (
    DISCLAIMER,
    MODEL,
    VALID_CARE_TYPES,
    _COPAY_FIELD,
    _PRIOR_AUTH_KEYWORDS,
    _SPECIALIST_CARE_TYPES,
)
from prompts.care_router import CONTEXT_SYSTEM_PROMPT, ROUTING_SYSTEM_PROMPT
from utils import _strip_fences


# ── Helpers ────────────────────────────────────────────────────────────────────

def _plan_field(plan_json: Optional[dict], field: str) -> Optional[dict]:
    """Safely return a plan field entry dict."""
    if not plan_json:
        return None
    entry = plan_json.get(field)
    return entry if isinstance(entry, dict) else None


def _plan_value(plan_json: Optional[dict], field: str):
    """Safely return the .value of a plan field."""
    entry = _plan_field(plan_json, field)
    return entry.get("value") if entry else None


def _is_complete_context(ctx: Optional[dict]) -> bool:
    """Return True if all four context keys are present and non-empty."""
    if not ctx:
        return False
    return all(
        ctx.get(k)
        for k in ("symptom_description", "severity", "time_sensitivity", "time_of_day")
    )


# ── Step 1: Context extraction ─────────────────────────────────────────────────

def _extract_context(user_message: str, user_language: str) -> dict:
    """Call Claude to extract symptom context from a raw user message."""
    llm = ChatAnthropic(model=MODEL, max_tokens=512)  # type: ignore[call-arg]
    try:
        resp = llm.invoke([
            SystemMessage(content=CONTEXT_SYSTEM_PROMPT),
            HumanMessage(content=f"User message: {user_message}"),
        ])
        ctx = json.loads(_strip_fences(str(resp.content)))
        return {
            "symptom_description": ctx.get("symptom_description", user_message[:80]),
            "severity": ctx.get("severity", "routine"),
            "time_sensitivity": ctx.get("time_sensitivity", "flexible"),
            "time_of_day": ctx.get("time_of_day", "unknown"),
        }
    except Exception:
        return {
            "symptom_description": user_message[:80],
            "severity": "routine",
            "time_sensitivity": "flexible",
            "time_of_day": "unknown",
        }


# ── Step 2: Routing decision ───────────────────────────────────────────────────

def _build_routing_context(
    user_message: str,
    ctx: dict,
    plan_json: Optional[dict],
    user_language: str,
) -> str:
    telehealth_covered = _plan_value(plan_json, "telehealth_covered")
    pcp_referral_required = _plan_value(plan_json, "pcp_referral_required")

    lines = [
        f"user_language: {user_language}",
        f"user_message: {user_message}",
        f"symptom_description: {ctx['symptom_description']}",
        f"severity: {ctx['severity']}",
        f"time_sensitivity: {ctx['time_sensitivity']}",
        f"time_of_day: {ctx['time_of_day']}",
    ]
    if plan_json is not None:
        lines.append(f"telehealth_covered: {telehealth_covered}")
        lines.append(f"pcp_referral_required: {pcp_referral_required}")
    else:
        lines.append("plan_json: not available (no SBC uploaded yet)")

    return "\n".join(lines)


def _route_care(
    user_message: str,
    ctx: dict,
    plan_json: Optional[dict],
    user_language: str,
) -> dict:
    """Call Claude to determine care routing. Returns {care_type, reason, alternative_options}."""
    llm = ChatAnthropic(model=MODEL, max_tokens=1024)  # type: ignore[call-arg]
    context_str = _build_routing_context(user_message, ctx, plan_json, user_language)

    try:
        resp = llm.invoke([
            SystemMessage(content=ROUTING_SYSTEM_PROMPT),
            HumanMessage(content=context_str),
        ])
        routing = json.loads(_strip_fences(str(resp.content)))
        care_type = routing.get("care_type", "pcp")
        if care_type not in VALID_CARE_TYPES:
            care_type = "pcp"
        return {
            "care_type": care_type,
            "reason": routing.get("reason", "Based on your symptoms."),
            "alternative_options": [
                {
                    "care_type": alt.get("care_type", "pcp"),
                    "reason": alt.get("reason", ""),
                }
                for alt in routing.get("alternative_options", [])
                if isinstance(alt, dict) and alt.get("care_type") in VALID_CARE_TYPES
            ],
        }
    except Exception:
        return {
            "care_type": "pcp",
            "reason": "Unable to determine routing. Please consult a primary care provider.",
            "alternative_options": [],
        }


# ── Step 3: Coverage overlay ───────────────────────────────────────────────────

def _get_coverage(care_type: str, plan_json: Optional[dict]) -> dict:
    """Return coverage dict {copay, confidence, note} for the given care_type."""
    if not plan_json:
        return {
            "copay": None,
            "confidence": "MISSING",
            "note": "Upload your SBC for plan-specific cost information.",
        }

    field = _COPAY_FIELD.get(care_type)
    entry = _plan_field(plan_json, field) if field else None
    copay = entry.get("value") if entry else None
    confidence = entry.get("confidence", "MISSING") if entry else "MISSING"

    if copay is None:
        phone = _plan_value(plan_json, "insurer_phone")
        note = (
            f"Not found in your plan — call {phone}"
            if phone
            else "Not found in your plan — call your insurer."
        )
    else:
        note = "Call to verify current amounts with your insurer."
        if care_type == "er":
            waived = _plan_value(plan_json, "er_copay_waived_if_admitted")
            if waived is True:
                note = (
                    "Copay may be waived if you are admitted as an inpatient. "
                    "Call to verify."
                )
        if care_type == "telehealth":
            covered = _plan_value(plan_json, "telehealth_covered")
            if covered is False:
                note = "Telehealth may not be covered by your plan. Call to verify."

    return {"copay": copay, "confidence": confidence, "note": note}


# ── Step 4: Prior auth check ───────────────────────────────────────────────────

def _check_prior_auth(care_type: str, plan_json: Optional[dict]) -> Optional[str]:
    """Return verbatim prior auth flag + call message if care_type matches, else None."""
    flags = _plan_value(plan_json, "prior_auth_flags")
    if not isinstance(flags, list) or not flags:
        return None

    keywords = _PRIOR_AUTH_KEYWORDS.get(care_type, [])
    matched = [
        flag for flag in flags
        if any(kw.lower() in flag.lower() for kw in keywords)
    ]
    if not matched:
        return None

    verbatim = "; ".join(matched)
    return f"{verbatim} — Call the number on your insurance card before scheduling."


# ── Referral check ─────────────────────────────────────────────────────────────

def _check_referral(care_type: str, plan_json: Optional[dict]) -> bool:
    """Return True if the plan requires a PCP referral for this care type."""
    if care_type not in _SPECIALIST_CARE_TYPES:
        return False
    return bool(_plan_value(plan_json, "pcp_referral_required"))


# ── Public API ─────────────────────────────────────────────────────────────────

async def run_care_router(
    user_message: str,
    extracted_context: Optional[dict],
    plan_json: Optional[dict],
    user_language: str = "en",
) -> dict:
    """Route a user's symptom description to the appropriate care setting.

    Steps:
      1. Extract context from user_message (skipped if extracted_context is complete)
      2. Routing decision via Claude
      3. Coverage overlay from plan_json
      4. Prior auth check from plan_json

    Always returns the full output structure. plan_json=None handled gracefully.
    """
    # Step 1: context extraction
    if _is_complete_context(extracted_context):
        ctx = extracted_context or {}  # extracted_context is non-None here; `or {}` narrows type
    else:
        ctx = _extract_context(user_message, user_language)

    # Step 2: routing
    routing = _route_care(user_message, ctx, plan_json, user_language)
    primary_care_type = routing["care_type"]

    # Step 3: coverage overlay
    coverage = _get_coverage(primary_care_type, plan_json)

    # Step 4: prior auth check
    prior_auth_flag = _check_prior_auth(primary_care_type, plan_json)

    # Alternatives — add coverage to each
    alternative_options = []
    for alt in routing["alternative_options"]:
        alt_coverage = _get_coverage(alt["care_type"], plan_json)
        alternative_options.append({
            "care_type": alt["care_type"],
            "reason": alt["reason"],
            "coverage": alt_coverage,
        })

    # Referral check
    referral_required = _check_referral(primary_care_type, plan_json)

    return {
        "primary_recommendation": {
            "care_type": primary_care_type,
            "reason": routing["reason"],
            "coverage": coverage,
            "prior_auth_flag": prior_auth_flag,
        },
        "alternative_options": alternative_options,
        "referral_required": referral_required,
        "disclaimer": DISCLAIMER,
        "user_language": user_language,
    }
