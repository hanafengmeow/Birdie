"""Shared constants for all Birdie backend tools.

Import from here instead of defining inline in tool files.
"""

from typing import Optional

# ── Model ─────────────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-20250514"   # never change this (CLAUDE.md hard rule)

# ── plan_lookup constants ──────────────────────────────────────────────────────

MAX_GLEANING_ITERATIONS = 2          # hard cap; always return best result at limit

FIELD_NAMES: list[str] = [
    "deductible_individual",
    "deductible_family",
    "out_of_pocket_max_individual",
    "out_of_pocket_max_family",
    "primary_care_copay",
    "specialist_copay",
    "urgent_care_copay",
    "er_copay",
    "er_copay_waived_if_admitted",
    "telehealth_copay",
    "telehealth_covered",
    "generic_drug_copay",
    "preferred_drug_copay",
    "mental_health_copay",
    "in_network_required",
    "pcp_referral_required",
    "prior_auth_flags",
    "insurer_phone",
    "insurer_provider_finder_url",
]

# value must be bool|null (never a string like "yes"/"true")
BOOL_FIELDS: set[str] = {
    "er_copay_waived_if_admitted",
    "telehealth_covered",
    "in_network_required",
    "pcp_referral_required",
}

# value must be list[str]|null
LIST_FIELDS: set[str] = {"prior_auth_flags"}

# ── care_router constants ──────────────────────────────────────────────────────

DISCLAIMER = (
    "This is navigation guidance only, not medical advice. "
    "Call 911 for emergencies."
)

VALID_CARE_TYPES: frozenset[str] = frozenset({
    "er", "urgent_care", "telehealth", "pcp", "pharmacy", "mental_health", "pt",
})

# care_type → plan_json copay field
_COPAY_FIELD: dict[str, str] = {
    "er":            "er_copay",
    "urgent_care":   "urgent_care_copay",
    "telehealth":    "telehealth_copay",
    "pcp":           "primary_care_copay",
    "pharmacy":      "generic_drug_copay",    # closest: generic / OTC guidance
    "mental_health": "mental_health_copay",
    "pt":            "specialist_copay",      # PT billed as specialist in most plans
}

# care_type → keywords for matching against prior_auth_flags
_PRIOR_AUTH_KEYWORDS: dict[str, list[str]] = {
    "er":           ["emergency", "inpatient", "hospital admission", "er visit"],
    "urgent_care":  ["urgent care"],
    "pcp":          ["primary care", "office visit", "preventive care"],
    "telehealth":   ["telehealth", "virtual", "online visit"],
    "pharmacy":     ["drug", "prescription", "medication", "specialty drug"],
    "mental_health": ["mental health", "behavioral health", "psychiatric",
                      "therapy", "counseling", "outpatient mental"],
    "pt":           ["physical therapy", "rehabilitation", "musculoskeletal",
                     "chiropractic", "occupational therapy"],
}

# Care types that require PCP referral (when the plan requires referrals)
_SPECIALIST_CARE_TYPES: frozenset[str] = frozenset({"pt", "mental_health"})

# ── find_care constants ────────────────────────────────────────────────────────

MAX_RESULTS = 5
SEARCH_RADIUS_METERS = 16000       # ~10 miles (standard care types)
SPECIALIST_SEARCH_RADIUS = 32000   # ~20 miles (specialists are sparser)

CARE_TYPE_MAPPING: dict[str, Optional[str]] = {
    "urgent_care":   "urgent care clinic",
    "er":            "emergency room hospital",
    "pcp":           "primary care physician clinic",
    "pharmacy":      "pharmacy",
    "mental_health": "mental health clinic therapist",
    "pt":            "physical therapy clinic",
    "telehealth":    None,  # special case — skip Maps
    "specialist":    None,  # uses search_query from intent classifier
}

NETWORK_STATUS = "verify_required"
NETWORK_NOTE = "Call to verify if this provider accepts your insurance"

# ── Intent classification constants ──────────────────────────────────────────

CONFIDENCE_HIGH_THRESHOLD = 0.85   # use zero-shot result directly
CONFIDENCE_LOW_THRESHOLD = 0.70    # fall back to few-shot re-classification
# 0.70-0.85 → few-shot only for complex intents (combined, symptom_routing, visit_prep)

COMPLEX_INTENTS: frozenset[str] = frozenset({
    "combined", "symptom_routing", "visit_prep",
})

# ── Conversation history constants ───────────────────────────────────────────

MAX_HISTORY_TURNS = 10             # max recent turns to forward (20 messages)
HISTORY_TRIM_TOKENS = 3000         # max tokens for trim_messages
