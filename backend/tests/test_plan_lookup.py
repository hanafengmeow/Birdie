"""Tests for backend/tools/plan_lookup.py

Strategy: mock all external API calls (parsers, Claude) so tests run without
PDF files, API keys, or heavy dependencies (pymupdf4llm, docling).

What is actually tested without mocks:
  - _empty_schema() structure
  - _slice_to_pages() page filtering
  - _node_schema_validator() — pure Python, no API
  - _node_confidence_labeling() — pure Python, no API (includes CONFLICT keep-both)
  - Routing logic (_route_after_schema, _route_after_validator)
  - Full pipeline via run_plan_lookup() with all external calls mocked

Run from backend/:
  python -m pytest tests/test_plan_lookup.py -v
  python tests/test_plan_lookup.py
"""

import asyncio
import json
import os
import sys

# Make `tools` importable when running from backend/tests/ directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch
import tools.plan_lookup as pl

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

MOCK_RAW_A = """\
[PARSER_A PAGE 1]
Summary of Benefits and Coverage — Blue Cross Blue Shield

Deductible: $500 Individual / $1,000 Family
Out-of-Pocket Maximum: $3,000 Individual / $6,000 Family

[PARSER_A PAGE 2]
Primary Care (your share): $20 copay per visit
Specialist Visit (your cost): $40 copay
Urgent Care: $50 copay
Emergency Room: $150 copay, waived if admitted as inpatient
Telehealth / Virtual Visit: $0 copay — covered

[PARSER_A PAGE 3]
Generic Drugs (Tier 1): $10 copay
Preferred Brand Drugs (Tier 2): $35 copay
Mental Health Outpatient: $20 copay
Prior Authorization required for: MRI, CT Scan, Inpatient Hospital Admission

Customer Service: 1-800-555-1234
Provider Finder: https://example.com/find-provider
"""

MOCK_RAW_B = """\
[PARSER_B]
Deductible Individual: $500
Deductible Family: $1,000
OOP Max Individual: $3,000
OOP Max Family: $6,000
PCP Visit: $20
Specialist: $40
Urgent Care: $50
ER: $150 (waived if admitted)
Telehealth: $0 (covered)
Generic: $10
Brand Preferred: $35
Mental Health: $20
Prior Auth required: MRI, CT Scan, Inpatient Hospital Admission
Member Services: 1-800-555-1234
Find a Provider: https://example.com/find-provider
"""

MOCK_EXTRACTED_JSON: dict = {
    "deductible_individual":        {"value": "$500",    "page": 1, "bbox": None, "source_text": "Deductible: $500 Individual"},
    "deductible_family":            {"value": "$1,000",  "page": 1, "bbox": None, "source_text": "Deductible: $500 Individual / $1,000 Family"},
    "out_of_pocket_max_individual": {"value": "$3,000",  "page": 1, "bbox": None, "source_text": "Out-of-Pocket Maximum: $3,000 Individual"},
    "out_of_pocket_max_family":     {"value": "$6,000",  "page": 1, "bbox": None, "source_text": "Out-of-Pocket Maximum: $3,000 Individual / $6,000 Family"},
    "primary_care_copay":           {"value": "$20",     "page": 2, "bbox": None, "source_text": "Primary Care (your share): $20 copay per visit"},
    "specialist_copay":             {"value": "$40",     "page": 2, "bbox": None, "source_text": "Specialist Visit (your cost): $40 copay"},
    "urgent_care_copay":            {"value": "$50",     "page": 2, "bbox": None, "source_text": "Urgent Care: $50 copay"},
    "er_copay":                     {"value": "$150",    "page": 2, "bbox": None, "source_text": "Emergency Room: $150 copay"},
    "er_copay_waived_if_admitted":  {"value": True,      "page": 2, "bbox": None, "source_text": "waived if admitted as inpatient"},
    "telehealth_copay":             {"value": "$0",      "page": 2, "bbox": None, "source_text": "Telehealth / Virtual Visit: $0 copay"},
    "telehealth_covered":           {"value": True,      "page": 2, "bbox": None, "source_text": "Telehealth / Virtual Visit: $0 copay — covered"},
    "generic_drug_copay":           {"value": "$10",     "page": 3, "bbox": None, "source_text": "Generic Drugs (Tier 1): $10 copay"},
    "preferred_drug_copay":         {"value": "$35",     "page": 3, "bbox": None, "source_text": "Preferred Brand Drugs (Tier 2): $35 copay"},
    "mental_health_copay":          {"value": "$20",     "page": 3, "bbox": None, "source_text": "Mental Health Outpatient: $20 copay"},
    "in_network_required":          {"value": True,      "page": 1, "bbox": None, "source_text": None},
    "pcp_referral_required":        {"value": False,     "page": None, "bbox": None, "source_text": None},
    "prior_auth_flags":             {"value": ["MRI", "CT Scan", "Inpatient Hospital Admission"], "page": 3, "bbox": None, "source_text": "Prior Authorization required for: MRI, CT Scan, Inpatient Hospital Admission"},
    "insurer_phone":                {"value": "1-800-555-1234", "page": 3, "bbox": None, "source_text": "Customer Service: 1-800-555-1234"},
    "insurer_provider_finder_url":  {"value": "https://example.com/find-provider", "page": 3, "bbox": None, "source_text": "Provider Finder: https://example.com/find-provider"},
}

VALIDATOR_REPORT_PASS = {
    "passed": True,
    "issues": [],
    "per_field_confidence": {f: "HIGH" for f in pl.FIELD_NAMES},
    "conflict_values": {},
}

_BASE_STATE: pl.GleaningState = {
    "raw_text_a": MOCK_RAW_A,
    "raw_text_b": MOCK_RAW_B,
    "extracted_json": MOCK_EXTRACTED_JSON,
    "validation_feedback": "",
    "iteration_count": 0,
    "final_json": {},
    "schema_valid": False,
    "validator_passed": False,
}


def _state(**overrides) -> pl.GleaningState:
    return {**_BASE_STATE, **overrides}


# ─────────────────────────────────────────────────────────────────────────────
# _empty_schema
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_schema_has_all_fields():
    schema = pl._empty_schema()
    assert set(schema.keys()) == set(pl.FIELD_NAMES), \
        f"Expected {len(pl.FIELD_NAMES)} fields, got {len(schema)}"
    for field, entry in schema.items():
        for sub in ("value", "page", "bbox", "source_text"):
            assert sub in entry, f"{field}.{sub} missing"
        assert entry["value"] is None
    print("✓ test_empty_schema_has_all_fields")


def test_empty_schema_count():
    assert len(pl._empty_schema()) == 19
    print("✓ test_empty_schema_count — 19 fields")


# ─────────────────────────────────────────────────────────────────────────────
# _slice_to_pages
# ─────────────────────────────────────────────────────────────────────────────

def test_slice_to_pages_extracts_correct_pages():
    sliced = pl._slice_to_pages(MOCK_RAW_A, {1, 2})
    assert "Deductible" in sliced          # page 1
    assert "Primary Care" in sliced        # page 2
    assert "Generic Drugs" not in sliced   # page 3 excluded
    print("✓ test_slice_to_pages_extracts_correct_pages")


def test_slice_to_pages_empty_set_returns_full():
    # Empty page set → no slicing, return full text
    sliced = pl._slice_to_pages(MOCK_RAW_A, set())
    assert sliced == MOCK_RAW_A
    print("✓ test_slice_to_pages_empty_set_returns_full")


def test_slice_to_pages_no_markers_returns_full():
    # Parser B has no page markers → always returns full text
    sliced = pl._slice_to_pages(MOCK_RAW_B, {1})
    assert sliced == MOCK_RAW_B
    print("✓ test_slice_to_pages_no_markers_returns_full")


def test_slice_to_pages_missing_page_returns_full():
    # Requesting page 99 which doesn't exist → falls back to full text
    sliced = pl._slice_to_pages(MOCK_RAW_A, {99})
    assert sliced == MOCK_RAW_A
    print("✓ test_slice_to_pages_missing_page_returns_full")


# ─────────────────────────────────────────────────────────────────────────────
# _node_schema_validator (Node 1)
# ─────────────────────────────────────────────────────────────────────────────

def test_schema_validator_passes_valid_json():
    result = pl._node_schema_validator(_state(extracted_json=MOCK_EXTRACTED_JSON))
    assert result["schema_valid"] is True, \
        f"Expected valid, got: {result.get('validation_feedback')}"
    print("✓ test_schema_validator_passes_valid_json")


def test_schema_validator_accepts_all_null():
    """null is always valid — never infer/guess (CLAUDE.md hard rule)."""
    result = pl._node_schema_validator(_state(extracted_json=pl._empty_schema()))
    assert result["schema_valid"] is True
    print("✓ test_schema_validator_accepts_all_null")


def test_schema_validator_fails_missing_field():
    bad = {k: v for k, v in MOCK_EXTRACTED_JSON.items() if k != "deductible_individual"}
    result = pl._node_schema_validator(_state(extracted_json=bad))
    assert result["schema_valid"] is False
    assert "deductible_individual" in result["validation_feedback"]
    print("✓ test_schema_validator_fails_missing_field")


def test_schema_validator_fails_wrong_bool_type():
    bad = dict(MOCK_EXTRACTED_JSON)
    bad["er_copay_waived_if_admitted"] = {
        "value": "yes",   # string — must be bool|null
        "page": 2, "bbox": None, "source_text": "waived",
    }
    result = pl._node_schema_validator(_state(extracted_json=bad))
    assert result["schema_valid"] is False
    assert "er_copay_waived_if_admitted" in result["validation_feedback"]
    print("✓ test_schema_validator_fails_wrong_bool_type")


def test_schema_validator_fails_wrong_list_type():
    bad = dict(MOCK_EXTRACTED_JSON)
    bad["prior_auth_flags"] = {
        "value": "MRI, CT Scan",   # string — must be list|null
        "page": 3, "bbox": None, "source_text": "...",
    }
    result = pl._node_schema_validator(_state(extracted_json=bad))
    assert result["schema_valid"] is False
    assert "prior_auth_flags" in result["validation_feedback"]
    print("✓ test_schema_validator_fails_wrong_list_type")


def test_schema_validator_fails_wrong_page_type():
    bad = dict(MOCK_EXTRACTED_JSON)
    bad["primary_care_copay"] = {"value": "$20", "page": "2", "bbox": None, "source_text": "..."}
    result = pl._node_schema_validator(_state(extracted_json=bad))
    assert result["schema_valid"] is False
    print("✓ test_schema_validator_fails_wrong_page_type")


def test_schema_validator_fails_missing_subkey():
    bad = dict(MOCK_EXTRACTED_JSON)
    bad["specialist_copay"] = {"value": "$40", "page": 2}  # missing bbox, source_text
    result = pl._node_schema_validator(_state(extracted_json=bad))
    assert result["schema_valid"] is False
    print("✓ test_schema_validator_fails_missing_subkey")


# ─────────────────────────────────────────────────────────────────────────────
# _node_confidence_labeling (Node 4)
# ─────────────────────────────────────────────────────────────────────────────

def test_confidence_labeling_missing_when_null():
    result = pl._node_confidence_labeling(_state(
        extracted_json=pl._empty_schema(),
    ))
    for field in pl.FIELD_NAMES:
        assert result["final_json"][field]["confidence"] == "MISSING", \
            f"{field}: expected MISSING"
    print("✓ test_confidence_labeling_missing_when_null")


def test_confidence_labeling_uses_validator_report():
    """Validator-assigned confidence takes priority over programmatic check."""
    per_field = {f: "HIGH" for f in pl.FIELD_NAMES}
    per_field["preferred_drug_copay"] = "CONFLICT"
    result = pl._node_confidence_labeling(_state(
        extracted_json={
            **MOCK_EXTRACTED_JSON,
            "__per_field_confidence": per_field,
            "__conflict_values": {},
        },
    ))
    assert result["final_json"]["deductible_individual"]["confidence"] == "HIGH"
    assert result["final_json"]["preferred_drug_copay"]["confidence"] == "CONFLICT"
    print("✓ test_confidence_labeling_uses_validator_report")


def test_confidence_labeling_conflict_keeps_both_values():
    """CLAUDE.md spec: CONFLICT fields must keep both parser values (value_b added)."""
    per_field = {f: "HIGH" for f in pl.FIELD_NAMES}
    per_field["deductible_individual"] = "CONFLICT"
    conflict_vals = {
        "deductible_individual": {"parser_a": "$500", "parser_b": "$600"},
    }
    result = pl._node_confidence_labeling(_state(
        extracted_json={
            **MOCK_EXTRACTED_JSON,
            "__per_field_confidence": per_field,
            "__conflict_values": conflict_vals,
        },
    ))
    entry = result["final_json"]["deductible_individual"]
    assert entry["confidence"] == "CONFLICT"
    assert entry["value"] == "$500"      # primary value preserved
    assert entry["value_b"] == "$600"    # conflict value attached
    print("✓ test_confidence_labeling_conflict_keeps_both_values")


def test_confidence_labeling_high_field_has_no_value_b():
    """Non-CONFLICT fields must NOT have a value_b key."""
    result = pl._node_confidence_labeling(_state(
        extracted_json={
            **MOCK_EXTRACTED_JSON,
            "__per_field_confidence": {f: "HIGH" for f in pl.FIELD_NAMES},
            "__conflict_values": {},
        },
    ))
    for field in pl.FIELD_NAMES:
        assert "value_b" not in result["final_json"][field], \
            f"{field} should not have value_b for HIGH confidence"
    print("✓ test_confidence_labeling_high_field_has_no_value_b")


def test_confidence_labeling_programmatic_high():
    """Without validator report, HIGH assigned when value found in both raw texts."""
    result = pl._node_confidence_labeling(_state(
        extracted_json=MOCK_EXTRACTED_JSON,
    ))
    # "$500" → "500" appears in both MOCK_RAW_A and MOCK_RAW_B → HIGH
    assert result["final_json"]["deductible_individual"]["confidence"] == "HIGH"
    print("✓ test_confidence_labeling_programmatic_high")


def test_confidence_labeling_all_fields_present():
    result = pl._node_confidence_labeling(_state(
        extracted_json={
            **MOCK_EXTRACTED_JSON,
            "__per_field_confidence": {f: "HIGH" for f in pl.FIELD_NAMES},
            "__conflict_values": {},
        },
    ))
    fj = result["final_json"]
    assert set(fj.keys()) == set(pl.FIELD_NAMES)
    for field, entry in fj.items():
        for sub in ("value", "page", "bbox", "source_text", "confidence"):
            assert sub in entry, f"{field} missing sub-key '{sub}'"
        assert entry["confidence"] in ("HIGH", "MED", "CONFLICT", "MISSING")
    print("✓ test_confidence_labeling_all_fields_present")


# ─────────────────────────────────────────────────────────────────────────────
# Routing functions
# ─────────────────────────────────────────────────────────────────────────────

def test_route_schema_valid_to_validator():
    assert pl._route_after_schema(_state(schema_valid=True, iteration_count=0)) == "validator_agent"
    print("✓ test_route_schema_valid_to_validator")


def test_route_schema_invalid_to_reextraction():
    assert pl._route_after_schema(_state(schema_valid=False, iteration_count=0)) == "re_extraction"
    print("✓ test_route_schema_invalid_to_reextraction")


def test_route_schema_maxiter_to_labeling():
    """At max iterations, always go to confidence_labeling (hard rule)."""
    assert pl._route_after_schema(_state(schema_valid=False, iteration_count=2)) == "confidence_labeling"
    print("✓ test_route_schema_maxiter_to_labeling")


def test_route_validator_passed_to_labeling():
    assert pl._route_after_validator(_state(validator_passed=True, iteration_count=0)) == "confidence_labeling"
    print("✓ test_route_validator_passed_to_labeling")


def test_route_validator_failed_to_reextraction():
    assert pl._route_after_validator(_state(validator_passed=False, iteration_count=0)) == "re_extraction"
    print("✓ test_route_validator_failed_to_reextraction")


def test_route_validator_maxiter_to_labeling():
    assert pl._route_after_validator(_state(validator_passed=False, iteration_count=2)) == "confidence_labeling"
    print("✓ test_route_validator_maxiter_to_labeling")


# ─────────────────────────────────────────────────────────────────────────────
# Full pipeline integration test (all external calls mocked)
# ─────────────────────────────────────────────────────────────────────────────

def _make_claude_mock(content: str) -> MagicMock:
    """Build a mock ChatAnthropic class whose instance returns `content`."""
    inst = MagicMock()
    inst.invoke.return_value = MagicMock(content=content)
    return MagicMock(return_value=inst)


def test_full_pipeline_happy_path():
    """Full run_plan_lookup — parsers, extractor, and Claude all mocked.

    Verifies:
    - All 19 fields returned with correct sub-keys
    - Confidence labels from mocked validator report
    - Specific values match mock extraction
    - prior_auth_flags is a list (verbatim strings)
    """
    with (
        patch("tools.plan_lookup._parse_with_pymupdf4llm", return_value=MOCK_RAW_A),
        patch("tools.plan_lookup._parse_with_docling", return_value=MOCK_RAW_B),
        patch("tools.plan_lookup._call_extractor", return_value=MOCK_EXTRACTED_JSON),
        patch("tools.plan_lookup.ChatAnthropic", _make_claude_mock(json.dumps(VALIDATOR_REPORT_PASS))),
    ):
        pl._GLEANING_GRAPH = None   # force rebuild so ChatAnthropic mock is active
        result = asyncio.run(pl.run_plan_lookup(b"%PDF-1.4 fake"))

    # Structure
    assert result is not None
    assert set(result.keys()) == set(pl.FIELD_NAMES)
    for field in pl.FIELD_NAMES:
        entry = result[field]
        for sub in ("value", "page", "bbox", "source_text", "confidence"):
            assert sub in entry, f"{field} missing '{sub}'"
        assert entry["confidence"] in ("HIGH", "MED", "CONFLICT", "MISSING")

    # Values
    assert result["deductible_individual"]["value"] == "$500"
    assert result["deductible_family"]["value"] == "$1,000"
    assert result["er_copay_waived_if_admitted"]["value"] is True   # bool, not string
    assert result["telehealth_covered"]["value"] is True
    assert result["pcp_referral_required"]["value"] is False
    assert isinstance(result["prior_auth_flags"]["value"], list)
    assert result["prior_auth_flags"]["value"] == [
        "MRI", "CT Scan", "Inpatient Hospital Admission"
    ]
    assert result["insurer_phone"]["value"] == "1-800-555-1234"

    # Validator assigned HIGH for all fields
    assert result["deductible_individual"]["confidence"] == "HIGH"
    assert result["prior_auth_flags"]["confidence"] == "HIGH"

    print("✓ test_full_pipeline_happy_path")
    print(f"  Fields returned: {len(result)}")
    print(f"  deductible_individual: {result['deductible_individual']['value']} "
          f"(confidence: {result['deductible_individual']['confidence']})")
    print(f"  prior_auth_flags: {result['prior_auth_flags']['value']}")
    print(f"  insurer_phone: {result['insurer_phone']['value']}")


def test_full_pipeline_conflict_keeps_both():
    """CONFLICT fields in final output must have both value and value_b.

    Mocks _node_validator_agent directly (instead of ChatAnthropic) so the
    state update dict is injected straight into the LangGraph state — this is
    the most reliable way to test that per_field_confidence and conflict_values
    are properly merged by LangGraph and used by the labeling node.
    """
    validator_state_update = {
        "validator_passed": True,
        "validation_feedback": "",
        "extracted_json": {
            **MOCK_EXTRACTED_JSON,
            "__per_field_confidence": {
                **{f: "HIGH" for f in pl.FIELD_NAMES},
                "deductible_individual": "CONFLICT",
            },
            "__conflict_values": {
                "deductible_individual": {"parser_a": "$500", "parser_b": "$550"},
            },
        },
    }

    with (
        patch("tools.plan_lookup._parse_with_pymupdf4llm", return_value=MOCK_RAW_A),
        patch("tools.plan_lookup._parse_with_docling", return_value=MOCK_RAW_B),
        patch("tools.plan_lookup._call_extractor", return_value=MOCK_EXTRACTED_JSON),
        patch("tools.plan_lookup._node_validator_agent", return_value=validator_state_update),
    ):
        pl._GLEANING_GRAPH = None   # force graph rebuild so mock node is registered
        result = asyncio.run(pl.run_plan_lookup(b"%PDF-1.4 fake"))

    entry = result["deductible_individual"]
    assert entry["confidence"] == "CONFLICT", \
        f"Expected CONFLICT, got '{entry['confidence']}'"
    assert entry["value"] == "$500", \
        f"Primary value should be '$500', got '{entry['value']}'"
    assert entry.get("value_b") == "$550", \
        f"Conflict value_b should be '$550', got '{entry.get('value_b')}'"
    print("✓ test_full_pipeline_conflict_keeps_both")


def test_full_pipeline_parser_failure_graceful():
    """Even if both parsers fail, pipeline returns null-filled JSON (never crashes)."""
    with (
        patch("tools.plan_lookup._parse_with_pymupdf4llm", return_value="[PARSER_A_FAILED: test]"),
        patch("tools.plan_lookup._parse_with_docling", return_value="[PARSER_B_FAILED: test]"),
        patch("tools.plan_lookup._call_extractor", return_value=pl._empty_schema()),
        patch("tools.plan_lookup.ChatAnthropic", _make_claude_mock(json.dumps(VALIDATOR_REPORT_PASS))),
    ):
        pl._GLEANING_GRAPH = None
        result = asyncio.run(pl.run_plan_lookup(b"%PDF-1.4 bad"))

    assert result is not None
    assert set(result.keys()) == set(pl.FIELD_NAMES)
    for field in pl.FIELD_NAMES:
        assert result[field]["value"] is None
    print("✓ test_full_pipeline_parser_failure_graceful")


# ─────────────────────────────────────────────────────────────────────────────
# Runner (also works as pytest module)
# ─────────────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    test_empty_schema_has_all_fields,
    test_empty_schema_count,
    test_slice_to_pages_extracts_correct_pages,
    test_slice_to_pages_empty_set_returns_full,
    test_slice_to_pages_no_markers_returns_full,
    test_slice_to_pages_missing_page_returns_full,
    test_schema_validator_passes_valid_json,
    test_schema_validator_accepts_all_null,
    test_schema_validator_fails_missing_field,
    test_schema_validator_fails_wrong_bool_type,
    test_schema_validator_fails_wrong_list_type,
    test_schema_validator_fails_wrong_page_type,
    test_schema_validator_fails_missing_subkey,
    test_confidence_labeling_missing_when_null,
    test_confidence_labeling_uses_validator_report,
    test_confidence_labeling_conflict_keeps_both_values,
    test_confidence_labeling_high_field_has_no_value_b,
    test_confidence_labeling_programmatic_high,
    test_confidence_labeling_all_fields_present,
    test_route_schema_valid_to_validator,
    test_route_schema_invalid_to_reextraction,
    test_route_schema_maxiter_to_labeling,
    test_route_validator_passed_to_labeling,
    test_route_validator_failed_to_reextraction,
    test_route_validator_maxiter_to_labeling,
    test_full_pipeline_happy_path,
    test_full_pipeline_conflict_keeps_both,
    test_full_pipeline_parser_failure_graceful,
]

if __name__ == "__main__":
    print("=" * 60)
    print("Birdie plan_lookup test suite")
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
