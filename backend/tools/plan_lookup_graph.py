"""LangGraph Gleaning loop nodes and state for plan_lookup.

Contains only pure-Python nodes (no Claude calls) and the GleaningState TypedDict.
Claude-calling nodes (_node_validator_agent, _node_re_extraction) stay in
plan_lookup.py to keep the graph builder and patch targets in one place.
"""

import re
from typing import TypedDict

from config import (
    BOOL_FIELDS,
    FIELD_NAMES,
    LIST_FIELDS,
    MAX_GLEANING_ITERATIONS,
)


# ── State ─────────────────────────────────────────────────────────────────────

class GleaningState(TypedDict):
    """LangGraph state. Nodes return partial dicts; LangGraph merges them.

    CLAUDE.md specifies 6 fields:
      raw_text_a, raw_text_b, extracted_json, validation_feedback,
      iteration_count, final_json

    2 additional fields required for LangGraph conditional routing:
      schema_valid     — True after Node 1 passes; routes → Node 2
      validator_passed — True after Node 2 passes; routes → Node 4

    Validator metadata (per_field_confidence, conflict_values) is piggybacked
    inside extracted_json under __per_field_confidence / __conflict_values keys.
    This avoids adding more state fields and keeps LangGraph merging simple.
    """
    # ── CLAUDE.md spec fields ─────────────────────────────────
    raw_text_a: str
    raw_text_b: str
    extracted_json: dict        # also carries __per_field_confidence, __conflict_values
    validation_feedback: str    # issues passed from Node 1/2 → Node 3
    iteration_count: int        # incremented in Node 3; hard cap = 2
    final_json: dict            # written by Node 4; returned as API response
    # ── LangGraph internal routing ────────────────────────────
    schema_valid: bool          # Node 1 result; routes → Node 2 or Node 3
    validator_passed: bool      # Node 2 result; routes → Node 4 or Node 3


# ── Helpers ───────────────────────────────────────────────────────────────────

def _empty_schema() -> dict:
    """Return a null-filled schema dict — the safe default for any failure."""
    return {
        f: {"value": None, "page": None, "bbox": None, "source_text": None}
        for f in FIELD_NAMES
    }


# ── Node 1: Schema Validator ──────────────────────────────────────────────────

def _node_schema_validator(state: GleaningState) -> dict:
    """Programmatic schema check — no API call, fast.

    Validates all 19 fields are present with correct sub-keys and value types:
    - Bool fields: bool|null only
    - List fields: list|null only
    - page: int|null only
    On fail → Node 3 (re_extraction). On pass → Node 2 (validator_agent).
    """
    extracted = state["extracted_json"]
    issues: list[str] = []

    for field in FIELD_NAMES:
        if field not in extracted:
            issues.append(f"Missing field: {field}")
            continue
        entry = extracted[field]
        if not isinstance(entry, dict):
            issues.append(f"{field}: must be a dict, got {type(entry).__name__}")
            continue
        for sub in ("value", "page", "bbox", "source_text"):
            if sub not in entry:
                issues.append(f"{field}.{sub}: key absent")
        val = entry.get("value")
        if field in BOOL_FIELDS and val is not None and not isinstance(val, bool):
            issues.append(
                f"{field}.value: must be bool|null, got {type(val).__name__} ({val!r})"
            )
        if field in LIST_FIELDS and val is not None and not isinstance(val, list):
            issues.append(
                f"{field}.value: must be list|null, got {type(val).__name__}"
            )
        pg = entry.get("page")
        if pg is not None and not isinstance(pg, int):
            issues.append(f"{field}.page: must be int|null, got {type(pg).__name__}")

    schema_valid = len(issues) == 0
    feedback = state["validation_feedback"]
    if issues:
        feedback = "SCHEMA ISSUES:\n" + "\n".join(f"  - {i}" for i in issues)

    return {"schema_valid": schema_valid, "validation_feedback": feedback}


# ── Node 4: Confidence Labeling ───────────────────────────────────────────────

def _node_confidence_labeling(state: GleaningState) -> dict:
    """Node 4 — Assign HIGH / MED / CONFLICT / MISSING to every field. Final node.

    Reads per_field_confidence and conflict_values from dunder keys in extracted_json.
    CONFLICT fields: per CLAUDE.md "keep both" — value_b is added so the frontend
    can display both parser values in the conflict pill.
    """
    extracted = state["extracted_json"]

    # Extract validator metadata embedded by Node 2
    per_field_confidence: dict = extracted.get("__per_field_confidence", {})
    conflict_values: dict = extracted.get("__conflict_values", {})

    raw_a = state["raw_text_a"].lower()
    raw_b = state["raw_text_b"].lower()

    final: dict = {}
    for field in FIELD_NAMES:
        entry = dict(extracted.get(
            field,
            {"value": None, "page": None, "bbox": None, "source_text": None},
        ))
        val = entry.get("value")

        if field in per_field_confidence:
            confidence = per_field_confidence[field]
        elif val is None:
            confidence = "MISSING"
        else:
            # Programmatic fallback: keyword presence check in each parser's text
            val_words = [w for w in re.split(r"[\s,$]+", str(val)) if len(w) > 2]
            in_a = any(w.lower() in raw_a for w in val_words) if val_words else False
            in_b = any(w.lower() in raw_b for w in val_words) if val_words else False
            if in_a and in_b:
                confidence = "HIGH"
            elif in_a or in_b:
                confidence = "MED"
            else:
                confidence = "MED"  # extracted but not programmatically verifiable

        entry["confidence"] = confidence

        # CONFLICT: "keep both" per CLAUDE.md — attach parser_b value
        if confidence == "CONFLICT" and field in conflict_values:
            cv = conflict_values[field]
            if isinstance(cv, dict):
                entry["value_b"] = cv.get("parser_b")

        final[field] = entry

    return {"final_json": final}


# ── Routing ───────────────────────────────────────────────────────────────────

def _route_after_schema(state: GleaningState) -> str:
    if state.get("schema_valid"):
        return "validator_agent"
    if state["iteration_count"] >= MAX_GLEANING_ITERATIONS:
        return "confidence_labeling"
    return "re_extraction"


def _route_after_validator(state: GleaningState) -> str:
    if state.get("validator_passed"):
        return "confidence_labeling"
    if state["iteration_count"] >= MAX_GLEANING_ITERATIONS:
        return "confidence_labeling"
    return "re_extraction"
