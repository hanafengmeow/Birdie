"""Tests for backend/tools/care_router.py

Strategy: mock all Claude API calls so tests run without API keys.

Pure unit tests (no mocks):
  _is_complete_context, _plan_field, _plan_value,
  _get_coverage, _check_prior_auth, _check_referral

Integration tests (Claude mocked):
  run_care_router — various routing scenarios

Run from backend/:
  python -m pytest tests/test_care_router.py -v
  python tests/test_care_router.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch
import tools.care_router as cr

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

MOCK_PLAN_JSON = {
    "er_copay":                    {"value": "$150",  "confidence": "HIGH",    "page": 2, "bbox": None, "source_text": "ER: $150 copay"},
    "er_copay_waived_if_admitted": {"value": True,    "confidence": "HIGH",    "page": 2, "bbox": None, "source_text": "waived if admitted"},
    "urgent_care_copay":           {"value": "$50",   "confidence": "HIGH",    "page": 2, "bbox": None, "source_text": "Urgent Care: $50"},
    "telehealth_copay":            {"value": "$0",    "confidence": "HIGH",    "page": 2, "bbox": None, "source_text": "Telehealth: $0"},
    "telehealth_covered":          {"value": True,    "confidence": "HIGH",    "page": 2, "bbox": None, "source_text": "covered"},
    "primary_care_copay":          {"value": "$20",   "confidence": "HIGH",    "page": 2, "bbox": None, "source_text": "PCP: $20"},
    "specialist_copay":            {"value": "$40",   "confidence": "HIGH",    "page": 2, "bbox": None, "source_text": "Specialist: $40"},
    "mental_health_copay":         {"value": "$20",   "confidence": "HIGH",    "page": 2, "bbox": None, "source_text": "Mental Health: $20"},
    "generic_drug_copay":          {"value": "$10",   "confidence": "HIGH",    "page": 3, "bbox": None, "source_text": "Generic: $10"},
    "pcp_referral_required":       {"value": False,   "confidence": "HIGH",    "page": 1, "bbox": None, "source_text": None},
    "prior_auth_flags":            {"value": ["MRI", "CT Scan", "Inpatient Hospital Admission", "Physical Therapy"],
                                    "confidence": "HIGH", "page": 3, "bbox": None, "source_text": "Prior Auth required for..."},
    "insurer_phone":               {"value": "1-800-555-1234", "confidence": "HIGH", "page": 3, "bbox": None, "source_text": "Customer Service"},
    "insurer_provider_finder_url": {"value": "https://example.com/find", "confidence": "HIGH", "page": 3, "bbox": None, "source_text": None},
}

COMPLETE_CONTEXT = {
    "symptom_description": "fever and chills",
    "severity": "urgent",
    "time_sensitivity": "today",
    "time_of_day": "afternoon",
}

MOCK_ROUTING_URGENT_CARE = {
    "care_type": "urgent_care",
    "reason": "Your symptoms suggest an urgent but non-emergency situation.",
    "alternative_options": [
        {"care_type": "telehealth", "reason": "Available if urgent care is not convenient."},
    ],
}

MOCK_ROUTING_ER = {
    "care_type": "er",
    "reason": "Chest pain requires immediate emergency evaluation.",
    "alternative_options": [],
}

MOCK_ROUTING_MENTAL_HEALTH = {
    "care_type": "mental_health",
    "reason": "Mental health services are the right fit for anxiety.",
    "alternative_options": [
        {"care_type": "telehealth", "reason": "Telehealth therapy is often available same-day."},
    ],
}

MOCK_ROUTING_PT = {
    "care_type": "pt",
    "reason": "Physical therapy is recommended for your knee pain.",
    "alternative_options": [],
}

MOCK_ROUTING_PCP = {
    "care_type": "pcp",
    "reason": "Your plan requires a PCP referral before PT. Visit your PCP first.",
    "alternative_options": [
        {"care_type": "pt", "reason": "PT is your destination after getting the referral."},
    ],
}

MOCK_EXTRACT_CONTEXT = {
    "symptom_description": "fever and chills",
    "severity": "urgent",
    "time_sensitivity": "today",
    "time_of_day": "afternoon",
}


def _mock_route(routing_dict: dict):
    """Return a mock that patches _route_care to return the given routing dict."""
    return patch("tools.care_router._route_care", return_value=routing_dict)


def _mock_extract(ctx_dict: dict = None):
    """Return a mock that patches _extract_context to return the given context dict."""
    return patch("tools.care_router._extract_context", return_value=ctx_dict or MOCK_EXTRACT_CONTEXT)


# ─────────────────────────────────────────────────────────────────────────────
# _is_complete_context
# ─────────────────────────────────────────────────────────────────────────────

def test_is_complete_context_true():
    assert cr._is_complete_context(COMPLETE_CONTEXT) is True
    print("✓ test_is_complete_context_true")


def test_is_complete_context_none():
    assert cr._is_complete_context(None) is False
    print("✓ test_is_complete_context_none")


def test_is_complete_context_missing_key():
    partial = {k: v for k, v in COMPLETE_CONTEXT.items() if k != "time_of_day"}
    assert cr._is_complete_context(partial) is False
    print("✓ test_is_complete_context_missing_key")


def test_is_complete_context_empty_string_value():
    ctx = {**COMPLETE_CONTEXT, "symptom_description": ""}
    assert cr._is_complete_context(ctx) is False
    print("✓ test_is_complete_context_empty_string_value")


# ─────────────────────────────────────────────────────────────────────────────
# _plan_field / _plan_value
# ─────────────────────────────────────────────────────────────────────────────

def test_plan_field_returns_dict():
    entry = cr._plan_field(MOCK_PLAN_JSON, "er_copay")
    assert entry == MOCK_PLAN_JSON["er_copay"]
    print("✓ test_plan_field_returns_dict")


def test_plan_field_none_plan_json():
    assert cr._plan_field(None, "er_copay") is None
    print("✓ test_plan_field_none_plan_json")


def test_plan_field_missing_key():
    assert cr._plan_field(MOCK_PLAN_JSON, "nonexistent_field") is None
    print("✓ test_plan_field_missing_key")


def test_plan_value_returns_value():
    assert cr._plan_value(MOCK_PLAN_JSON, "er_copay") == "$150"
    print("✓ test_plan_value_returns_value")


def test_plan_value_none_plan_json():
    assert cr._plan_value(None, "er_copay") is None
    print("✓ test_plan_value_none_plan_json")


# ─────────────────────────────────────────────────────────────────────────────
# _get_coverage
# ─────────────────────────────────────────────────────────────────────────────

def test_coverage_plan_none_returns_upload_note():
    cov = cr._get_coverage("er", None)
    assert cov["copay"] is None
    assert cov["confidence"] == "MISSING"
    assert "Upload" in cov["note"] or "upload" in cov["note"].lower()
    print("✓ test_coverage_plan_none_returns_upload_note")


def test_coverage_er_returns_copay():
    cov = cr._get_coverage("er", MOCK_PLAN_JSON)
    assert cov["copay"] == "$150"
    assert cov["confidence"] == "HIGH"
    print("✓ test_coverage_er_returns_copay")


def test_coverage_er_waived_note():
    """ER copay waived if admitted → note must mention it."""
    cov = cr._get_coverage("er", MOCK_PLAN_JSON)
    assert "waived" in cov["note"].lower() or "inpatient" in cov["note"].lower()
    print("✓ test_coverage_er_waived_note")


def test_coverage_er_not_waived_no_waived_note():
    plan = {**MOCK_PLAN_JSON, "er_copay_waived_if_admitted": {"value": False, "confidence": "HIGH", "page": None, "bbox": None, "source_text": None}}
    cov = cr._get_coverage("er", plan)
    assert "waived" not in cov["note"].lower()
    print("✓ test_coverage_er_not_waived_no_waived_note")


def test_coverage_urgent_care():
    cov = cr._get_coverage("urgent_care", MOCK_PLAN_JSON)
    assert cov["copay"] == "$50"
    assert cov["confidence"] == "HIGH"
    print("✓ test_coverage_urgent_care")


def test_coverage_telehealth():
    cov = cr._get_coverage("telehealth", MOCK_PLAN_JSON)
    assert cov["copay"] == "$0"
    print("✓ test_coverage_telehealth")


def test_coverage_telehealth_not_covered_note():
    plan = {
        **MOCK_PLAN_JSON,
        "telehealth_covered": {"value": False, "confidence": "HIGH", "page": None, "bbox": None, "source_text": None},
    }
    cov = cr._get_coverage("telehealth", plan)
    assert "not be covered" in cov["note"].lower() or "may not" in cov["note"].lower()
    print("✓ test_coverage_telehealth_not_covered_note")


def test_coverage_pcp():
    cov = cr._get_coverage("pcp", MOCK_PLAN_JSON)
    assert cov["copay"] == "$20"
    print("✓ test_coverage_pcp")


def test_coverage_pt_uses_specialist():
    """PT maps to specialist_copay field."""
    cov = cr._get_coverage("pt", MOCK_PLAN_JSON)
    assert cov["copay"] == "$40"
    print("✓ test_coverage_pt_uses_specialist")


def test_coverage_mental_health():
    cov = cr._get_coverage("mental_health", MOCK_PLAN_JSON)
    assert cov["copay"] == "$20"
    print("✓ test_coverage_mental_health")


def test_coverage_null_copay_includes_phone():
    """When copay is null, note should include insurer phone number."""
    plan = {
        **MOCK_PLAN_JSON,
        "urgent_care_copay": {"value": None, "confidence": "MISSING", "page": None, "bbox": None, "source_text": None},
    }
    cov = cr._get_coverage("urgent_care", plan)
    assert cov["copay"] is None
    assert "1-800-555-1234" in cov["note"]
    print("✓ test_coverage_null_copay_includes_phone")


def test_coverage_all_care_types_return_dict():
    """Every valid care_type must return a dict with copay, confidence, note."""
    for ct in cr.VALID_CARE_TYPES:
        cov = cr._get_coverage(ct, MOCK_PLAN_JSON)
        for key in ("copay", "confidence", "note"):
            assert key in cov, f"{ct}: missing key '{key}'"
    print("✓ test_coverage_all_care_types_return_dict")


# ─────────────────────────────────────────────────────────────────────────────
# _check_prior_auth
# ─────────────────────────────────────────────────────────────────────────────

def test_prior_auth_none_plan_json():
    assert cr._check_prior_auth("er", None) is None
    print("✓ test_prior_auth_none_plan_json")


def test_prior_auth_no_flags():
    plan = {**MOCK_PLAN_JSON, "prior_auth_flags": {"value": None, "confidence": "MISSING", "page": None, "bbox": None, "source_text": None}}
    assert cr._check_prior_auth("er", plan) is None
    print("✓ test_prior_auth_no_flags")


def test_prior_auth_er_matches_inpatient():
    """'Inpatient Hospital Admission' should match 'er' via 'hospital admission' keyword."""
    result = cr._check_prior_auth("er", MOCK_PLAN_JSON)
    assert result is not None
    assert "Inpatient Hospital Admission" in result
    assert "Call the number on your insurance card" in result
    print("✓ test_prior_auth_er_matches_inpatient")


def test_prior_auth_pt_matches_physical_therapy():
    """'Physical Therapy' in flags should match 'pt' via 'physical therapy' keyword."""
    result = cr._check_prior_auth("pt", MOCK_PLAN_JSON)
    assert result is not None
    assert "Physical Therapy" in result
    assert "Call the number on your insurance card" in result
    print("✓ test_prior_auth_pt_matches_physical_therapy")


def test_prior_auth_pcp_no_match():
    """'MRI', 'CT Scan', 'Inpatient Hospital Admission', 'Physical Therapy' don't match pcp keywords."""
    result = cr._check_prior_auth("pcp", MOCK_PLAN_JSON)
    assert result is None
    print("✓ test_prior_auth_pcp_no_match")


def test_prior_auth_returns_verbatim_text():
    """Returned text must include the exact verbatim flag from the SBC."""
    result = cr._check_prior_auth("er", MOCK_PLAN_JSON)
    assert "Inpatient Hospital Admission" in result   # verbatim SBC wording
    print("✓ test_prior_auth_returns_verbatim_text")


# ─────────────────────────────────────────────────────────────────────────────
# _check_referral
# ─────────────────────────────────────────────────────────────────────────────

def test_referral_not_required_for_er():
    assert cr._check_referral("er", MOCK_PLAN_JSON) is False
    print("✓ test_referral_not_required_for_er")


def test_referral_not_required_for_pcp():
    assert cr._check_referral("pcp", MOCK_PLAN_JSON) is False
    print("✓ test_referral_not_required_for_pcp")


def test_referral_not_required_when_plan_says_false():
    """PT is a specialist type but plan says pcp_referral_required=False."""
    assert cr._check_referral("pt", MOCK_PLAN_JSON) is False
    print("✓ test_referral_not_required_when_plan_says_false")


def test_referral_required_pt_when_plan_true():
    plan = {**MOCK_PLAN_JSON, "pcp_referral_required": {"value": True, "confidence": "HIGH", "page": None, "bbox": None, "source_text": None}}
    assert cr._check_referral("pt", plan) is True
    print("✓ test_referral_required_pt_when_plan_true")


def test_referral_required_mental_health_when_plan_true():
    plan = {**MOCK_PLAN_JSON, "pcp_referral_required": {"value": True, "confidence": "HIGH", "page": None, "bbox": None, "source_text": None}}
    assert cr._check_referral("mental_health", plan) is True
    print("✓ test_referral_required_mental_health_when_plan_true")


def test_referral_false_when_plan_none():
    assert cr._check_referral("pt", None) is False
    print("✓ test_referral_false_when_plan_none")


# ─────────────────────────────────────────────────────────────────────────────
# run_care_router — full pipeline integration tests (Claude mocked)
# ─────────────────────────────────────────────────────────────────────────────

def test_full_pipeline_output_structure():
    """All required top-level keys must be present in every response."""
    with _mock_route(MOCK_ROUTING_URGENT_CARE), _mock_extract():
        result = asyncio.run(cr.run_care_router(
            user_message="I have a fever",
            extracted_context=None,
            plan_json=MOCK_PLAN_JSON,
            user_language="en",
        ))

    assert "primary_recommendation" in result
    assert "alternative_options" in result
    assert "referral_required" in result
    assert "disclaimer" in result
    assert "user_language" in result

    rec = result["primary_recommendation"]
    for key in ("care_type", "reason", "coverage", "prior_auth_flag"):
        assert key in rec, f"primary_recommendation missing '{key}'"

    cov = rec["coverage"]
    for key in ("copay", "confidence", "note"):
        assert key in cov, f"coverage missing '{key}'"

    print("✓ test_full_pipeline_output_structure")


def test_full_pipeline_disclaimer_always_present():
    """Disclaimer must be exactly the required string."""
    with _mock_route(MOCK_ROUTING_ER), _mock_extract():
        result = asyncio.run(cr.run_care_router(
            user_message="chest pain",
            extracted_context=None,
            plan_json=None,
            user_language="en",
        ))
    assert result["disclaimer"] == cr.DISCLAIMER
    print("✓ test_full_pipeline_disclaimer_always_present")


def test_full_pipeline_plan_none_coverage_note():
    """plan_json=None → coverage note must mention uploading SBC."""
    with _mock_route(MOCK_ROUTING_URGENT_CARE), _mock_extract():
        result = asyncio.run(cr.run_care_router(
            user_message="I have a fever",
            extracted_context=None,
            plan_json=None,
            user_language="en",
        ))
    note = result["primary_recommendation"]["coverage"]["note"]
    assert "upload" in note.lower() or "SBC" in note
    print("✓ test_full_pipeline_plan_none_coverage_note")


def test_full_pipeline_er_routing_returns_er():
    with _mock_route(MOCK_ROUTING_ER), _mock_extract():
        result = asyncio.run(cr.run_care_router(
            user_message="chest pain, can't breathe",
            extracted_context=None,
            plan_json=MOCK_PLAN_JSON,
            user_language="en",
        ))
    assert result["primary_recommendation"]["care_type"] == "er"
    print("✓ test_full_pipeline_er_routing_returns_er")


def test_full_pipeline_er_coverage_waived_note():
    """ER with waived_if_admitted=True → note must mention waived/inpatient."""
    with _mock_route(MOCK_ROUTING_ER), _mock_extract():
        result = asyncio.run(cr.run_care_router(
            user_message="chest pain",
            extracted_context=None,
            plan_json=MOCK_PLAN_JSON,
            user_language="en",
        ))
    note = result["primary_recommendation"]["coverage"]["note"]
    assert "waived" in note.lower() or "inpatient" in note.lower()
    print("✓ test_full_pipeline_er_coverage_waived_note")


def test_full_pipeline_prior_auth_attached_for_er():
    """ER routing + 'Inpatient Hospital Admission' flag → prior_auth_flag not None."""
    with _mock_route(MOCK_ROUTING_ER), _mock_extract():
        result = asyncio.run(cr.run_care_router(
            user_message="chest pain",
            extracted_context=None,
            plan_json=MOCK_PLAN_JSON,
            user_language="en",
        ))
    flag = result["primary_recommendation"]["prior_auth_flag"]
    assert flag is not None
    assert "Inpatient Hospital Admission" in flag
    assert "Call the number on your insurance card" in flag
    print("✓ test_full_pipeline_prior_auth_attached_for_er")


def test_full_pipeline_no_prior_auth_when_no_match():
    """PCP routing with no matching prior auth flags → prior_auth_flag is None."""
    routing_pcp = {"care_type": "pcp", "reason": "Routine follow-up.", "alternative_options": []}
    with _mock_route(routing_pcp), _mock_extract():
        result = asyncio.run(cr.run_care_router(
            user_message="follow-up visit",
            extracted_context=None,
            plan_json=MOCK_PLAN_JSON,
            user_language="en",
        ))
    assert result["primary_recommendation"]["prior_auth_flag"] is None
    print("✓ test_full_pipeline_no_prior_auth_when_no_match")


def test_full_pipeline_pt_prior_auth_attached():
    """PT routing + 'Physical Therapy' flag → prior_auth_flag not None."""
    with _mock_route(MOCK_ROUTING_PT), _mock_extract():
        result = asyncio.run(cr.run_care_router(
            user_message="knee pain from running",
            extracted_context=None,
            plan_json=MOCK_PLAN_JSON,
            user_language="en",
        ))
    flag = result["primary_recommendation"]["prior_auth_flag"]
    assert flag is not None
    assert "Physical Therapy" in flag
    print("✓ test_full_pipeline_pt_prior_auth_attached")


def test_full_pipeline_referral_required_true():
    """PT with pcp_referral_required=True → referral_required is True."""
    plan_with_referral = {
        **MOCK_PLAN_JSON,
        "pcp_referral_required": {"value": True, "confidence": "HIGH", "page": None, "bbox": None, "source_text": None},
    }
    with _mock_route(MOCK_ROUTING_PT), _mock_extract():
        result = asyncio.run(cr.run_care_router(
            user_message="knee pain",
            extracted_context=None,
            plan_json=plan_with_referral,
            user_language="en",
        ))
    assert result["referral_required"] is True
    print("✓ test_full_pipeline_referral_required_true")


def test_full_pipeline_referral_required_false_for_er():
    """ER routing → referral_required must always be False."""
    with _mock_route(MOCK_ROUTING_ER), _mock_extract():
        result = asyncio.run(cr.run_care_router(
            user_message="chest pain",
            extracted_context=None,
            plan_json=MOCK_PLAN_JSON,
            user_language="en",
        ))
    assert result["referral_required"] is False
    print("✓ test_full_pipeline_referral_required_false_for_er")


def test_full_pipeline_skips_extract_when_context_provided():
    """If extracted_context is complete, _extract_context must NOT be called."""
    with _mock_route(MOCK_ROUTING_URGENT_CARE):
        with patch("tools.care_router._extract_context") as mock_extract:
            asyncio.run(cr.run_care_router(
                user_message="fever",
                extracted_context=COMPLETE_CONTEXT,
                plan_json=MOCK_PLAN_JSON,
                user_language="en",
            ))
        mock_extract.assert_not_called()
    print("✓ test_full_pipeline_skips_extract_when_context_provided")


def test_full_pipeline_calls_extract_when_context_missing():
    """If extracted_context is None, _extract_context must be called exactly once."""
    with _mock_route(MOCK_ROUTING_URGENT_CARE):
        with patch("tools.care_router._extract_context", return_value=MOCK_EXTRACT_CONTEXT) as mock_extract:
            asyncio.run(cr.run_care_router(
                user_message="fever",
                extracted_context=None,
                plan_json=MOCK_PLAN_JSON,
                user_language="en",
            ))
        mock_extract.assert_called_once()
    print("✓ test_full_pipeline_calls_extract_when_context_missing")


def test_full_pipeline_alternative_options_have_coverage():
    """Each item in alternative_options must have a coverage dict."""
    with _mock_route(MOCK_ROUTING_URGENT_CARE), _mock_extract():
        result = asyncio.run(cr.run_care_router(
            user_message="fever",
            extracted_context=None,
            plan_json=MOCK_PLAN_JSON,
            user_language="en",
        ))
    for alt in result["alternative_options"]:
        assert "care_type" in alt
        assert "reason" in alt
        assert "coverage" in alt
        cov = alt["coverage"]
        for key in ("copay", "confidence", "note"):
            assert key in cov, f"alternative coverage missing '{key}'"
    print("✓ test_full_pipeline_alternative_options_have_coverage")


def test_full_pipeline_user_language_echoed():
    """user_language in response must match the input."""
    with _mock_route(MOCK_ROUTING_URGENT_CARE), _mock_extract():
        result = asyncio.run(cr.run_care_router(
            user_message="发烧",
            extracted_context=None,
            plan_json=MOCK_PLAN_JSON,
            user_language="zh",
        ))
    assert result["user_language"] == "zh"
    print("✓ test_full_pipeline_user_language_echoed")


def test_full_pipeline_mental_health_routing():
    """Mental health routing returns mental_health care_type."""
    with _mock_route(MOCK_ROUTING_MENTAL_HEALTH), _mock_extract():
        result = asyncio.run(cr.run_care_router(
            user_message="I've been feeling really anxious",
            extracted_context=None,
            plan_json=MOCK_PLAN_JSON,
            user_language="en",
        ))
    assert result["primary_recommendation"]["care_type"] == "mental_health"
    assert result["primary_recommendation"]["coverage"]["copay"] == "$20"
    print("✓ test_full_pipeline_mental_health_routing")


def test_full_pipeline_invalid_care_type_falls_back_to_pcp():
    """If Claude returns an invalid care_type, _route_care falls back to pcp."""
    bad_routing = {"care_type": "urgent_care", "reason": "test", "alternative_options": []}
    # Force _route_care to return an invalid type by monkeypatching json.loads via a bad Claude response
    # Easier: patch _route_care to directly return a bad value, then ensure run_care_router handles it
    # Actually _route_care validates internally — let's test its validation directly
    with patch("tools.care_router.ChatAnthropic") as mock_cls:
        inst = MagicMock()
        inst.invoke.return_value = MagicMock(content='{"care_type": "helicopter", "reason": "fly there", "alternative_options": []}')
        mock_cls.return_value = inst
        with _mock_extract():
            result = asyncio.run(cr.run_care_router(
                user_message="test",
                extracted_context=None,
                plan_json=None,
                user_language="en",
            ))
    # _route_care validation coerces invalid care_type to "pcp"
    assert result["primary_recommendation"]["care_type"] == "pcp"
    print("✓ test_full_pipeline_invalid_care_type_falls_back_to_pcp")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    test_is_complete_context_true,
    test_is_complete_context_none,
    test_is_complete_context_missing_key,
    test_is_complete_context_empty_string_value,
    test_plan_field_returns_dict,
    test_plan_field_none_plan_json,
    test_plan_field_missing_key,
    test_plan_value_returns_value,
    test_plan_value_none_plan_json,
    test_coverage_plan_none_returns_upload_note,
    test_coverage_er_returns_copay,
    test_coverage_er_waived_note,
    test_coverage_er_not_waived_no_waived_note,
    test_coverage_urgent_care,
    test_coverage_telehealth,
    test_coverage_telehealth_not_covered_note,
    test_coverage_pcp,
    test_coverage_pt_uses_specialist,
    test_coverage_mental_health,
    test_coverage_null_copay_includes_phone,
    test_coverage_all_care_types_return_dict,
    test_prior_auth_none_plan_json,
    test_prior_auth_no_flags,
    test_prior_auth_er_matches_inpatient,
    test_prior_auth_pt_matches_physical_therapy,
    test_prior_auth_pcp_no_match,
    test_prior_auth_returns_verbatim_text,
    test_referral_not_required_for_er,
    test_referral_not_required_for_pcp,
    test_referral_not_required_when_plan_says_false,
    test_referral_required_pt_when_plan_true,
    test_referral_required_mental_health_when_plan_true,
    test_referral_false_when_plan_none,
    test_full_pipeline_output_structure,
    test_full_pipeline_disclaimer_always_present,
    test_full_pipeline_plan_none_coverage_note,
    test_full_pipeline_er_routing_returns_er,
    test_full_pipeline_er_coverage_waived_note,
    test_full_pipeline_prior_auth_attached_for_er,
    test_full_pipeline_no_prior_auth_when_no_match,
    test_full_pipeline_pt_prior_auth_attached,
    test_full_pipeline_referral_required_true,
    test_full_pipeline_referral_required_false_for_er,
    test_full_pipeline_skips_extract_when_context_provided,
    test_full_pipeline_calls_extract_when_context_missing,
    test_full_pipeline_alternative_options_have_coverage,
    test_full_pipeline_user_language_echoed,
    test_full_pipeline_mental_health_routing,
    test_full_pipeline_invalid_care_type_falls_back_to_pcp,
]

if __name__ == "__main__":
    print("=" * 60)
    print("Birdie care_router test suite")
    print("=" * 60)
    passed = 0
    failed = 0
    for fn in ALL_TESTS:
        try:
            fn()
            passed += 1
        except Exception as exc:
            print(f"✗ {fn.__name__}")
            print(f"  ERROR: {exc}")
            import traceback
            traceback.print_exc()
            failed += 1
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
