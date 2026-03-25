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
SEARCH_RADIUS_METERS = 16000  # ~10 miles

CARE_TYPE_MAPPING: dict[str, Optional[str]] = {
    "urgent_care":   "urgent care clinic",
    "er":            "emergency room hospital",
    "pcp":           "primary care physician clinic",
    "pharmacy":      "pharmacy",
    "mental_health": "mental health clinic therapist",
    "pt":            "physical therapy clinic",
    "telehealth":    None,  # special case — skip Maps
}

NETWORK_STATUS = "verify_required"
NETWORK_NOTE = "Call to verify if this provider accepts your insurance"

# ── Demo data ──────────────────────────────────────────────────────────────────

# Pre-loaded plan JSON for demo / "I'm a Northeastern student" fast path.
# Represents Northeastern NUSHP 2024-25 via Aetna Student Health.
# All values are realistic approximations — verify against current SBC.
# confidence=HIGH because this data is manually curated (not parser-extracted).
NORTHEASTERN_SHIP_TEMPLATE: dict = {
    "deductible_individual": {
        "value": "$100",
        "page": 2,
        "bbox": None,
        "source_text": "Individual Deductible: $100 per plan year (in-network)",
        "confidence": "HIGH",
    },
    "deductible_family": {
        "value": "$200",
        "page": 2,
        "bbox": None,
        "source_text": "Family Deductible: $200 per plan year (in-network)",
        "confidence": "HIGH",
    },
    "out_of_pocket_max_individual": {
        "value": "$3,000",
        "page": 2,
        "bbox": None,
        "source_text": "Out-of-Pocket Maximum: $3,000 individual per plan year",
        "confidence": "HIGH",
    },
    "out_of_pocket_max_family": {
        "value": "$6,000",
        "page": 2,
        "bbox": None,
        "source_text": "Out-of-Pocket Maximum: $6,000 family per plan year",
        "confidence": "HIGH",
    },
    "primary_care_copay": {
        "value": "$20 copay",
        "page": 3,
        "bbox": None,
        "source_text": "Primary Care Visit (your share): $20 copay per visit",
        "confidence": "HIGH",
    },
    "specialist_copay": {
        "value": "$40 copay",
        "page": 3,
        "bbox": None,
        "source_text": "Specialist Office Visit: $40 copay per visit",
        "confidence": "HIGH",
    },
    "urgent_care_copay": {
        "value": "$50 copay",
        "page": 3,
        "bbox": None,
        "source_text": "Urgent Care Center: $50 copay per visit",
        "confidence": "HIGH",
    },
    "er_copay": {
        "value": "$150 copay",
        "page": 3,
        "bbox": None,
        "source_text": "Emergency Room Services: $150 copay per visit",
        "confidence": "HIGH",
    },
    "er_copay_waived_if_admitted": {
        "value": True,
        "page": 3,
        "bbox": None,
        "source_text": "Emergency room copay waived if admitted as an inpatient",
        "confidence": "HIGH",
    },
    "telehealth_copay": {
        "value": "$0 copay",
        "page": 4,
        "bbox": None,
        "source_text": "Telehealth / Virtual Visit via Teladoc: $0 copay per visit",
        "confidence": "HIGH",
    },
    "telehealth_covered": {
        "value": True,
        "page": 4,
        "bbox": None,
        "source_text": "Telehealth services covered at $0 through Aetna's Teladoc platform",
        "confidence": "HIGH",
    },
    "generic_drug_copay": {
        "value": "$10 copay",
        "page": 5,
        "bbox": None,
        "source_text": "Tier 1 — Generic Drugs: $10 copay per 30-day supply",
        "confidence": "HIGH",
    },
    "preferred_drug_copay": {
        "value": "$35 copay",
        "page": 5,
        "bbox": None,
        "source_text": "Tier 2 — Preferred Brand Drugs: $35 copay per 30-day supply",
        "confidence": "HIGH",
    },
    "mental_health_copay": {
        "value": "$20 copay",
        "page": 4,
        "bbox": None,
        "source_text": "Mental Health / Behavioral Health Outpatient: $20 copay per visit",
        "confidence": "HIGH",
    },
    "in_network_required": {
        "value": True,
        "page": 2,
        "bbox": None,
        "source_text": "This plan only pays for services from in-network providers (EPO plan)",
        "confidence": "HIGH",
    },
    "pcp_referral_required": {
        "value": False,
        "page": 2,
        "bbox": None,
        "source_text": "No referral required to see a specialist",
        "confidence": "HIGH",
    },
    "prior_auth_flags": {
        "value": [
            "Inpatient Hospital Admission",
            "MRI / CT Scan / PET Scan",
            "Outpatient Surgery",
            "Specialty Drugs",
            "Physical Therapy (more than 30 visits per year)",
            "Mental Health Inpatient Services",
        ],
        "page": 6,
        "bbox": None,
        "source_text": "Prior Authorization Required: Inpatient Hospital Admission, MRI / CT Scan / PET Scan...",
        "confidence": "HIGH",
    },
    "insurer_phone": {
        "value": "1-877-468-0016",
        "page": 8,
        "bbox": None,
        "source_text": "Questions? Call Aetna Student Health Member Services: 1-877-468-0016",
        "confidence": "HIGH",
    },
    "insurer_provider_finder_url": {
        "value": "https://www.aetnastudenthealth.com/schools/northeastern",
        "page": 8,
        "bbox": None,
        "source_text": "Find a Provider: aetnastudenthealth.com/schools/northeastern",
        "confidence": "HIGH",
    },
}
