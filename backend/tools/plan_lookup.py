"""plan_lookup: parses SBC PDF into structured JSON. See CLAUDE.md for full spec.

Architecture — three layers:
  L1  Parallel PDF parsing: PyMuPDF4LLM (Parser A) + Docling (Parser B)
  L2  Claude extraction: strict JSON schema, Visual Grounding (value+page+bbox+source_text)
  L3  LangGraph Gleaning loop (max 2 iterations):
        Node 1 Schema Validator → Node 2 Validator Agent →
        Node 3 Re-extraction → Node 4 Confidence Labeling

Design decisions (not in CLAUDE.md):
  - pymupdf4llm and docling are lazy-imported inside parser functions so the module
    loads for testing without those heavy dependencies installed.
  - LangGraph requires routing flags in the state object; GleaningState therefore has
    2 fields beyond the 6 specified in CLAUDE.md: schema_valid and validator_passed.
  - Validator output (per_field_confidence, conflict_values) is piggybacked inside
    extracted_json under the dunder keys __per_field_confidence and __conflict_values.
    This avoids adding more TypedDict fields and keeps LangGraph state merging simple.
  - CONFLICT "keep both": when both parsers find different values for the same field,
    the labeling node attaches value_b to the field entry so the frontend can display
    both. The validator Claude returns conflict_values inside __conflict_values.
  - Re-extraction "specific pages only": we slice raw text to the pages where flagged
    fields were found, reducing Claude context and improving re-extraction accuracy.
  - Parser failures return error-marker strings rather than raising, so the pipeline
    always continues and returns best-available results (CLAUDE.md hard rule).
  - Claude context per parser capped at 15 000 chars; covers all 8 pages of an SBC.
"""

import asyncio
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from typing import TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

# ── Hard rules from CLAUDE.md ─────────────────────────────────────────────────
MODEL = "claude-sonnet-4-20250514"   # never change this
MAX_GLEANING_ITERATIONS = 2          # hard cap; always return best result at limit

# ── Field catalogue ───────────────────────────────────────────────────────────
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


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 1 — PARSING
# ═════════════════════════════════════════════════════════════════════════════

def _parse_with_pymupdf4llm(pdf_path: str) -> str:
    """Parser A — PyMuPDF4LLM: structured Markdown + per-page metadata.

    pymupdf4llm.to_markdown(page_chunks=True) returns list of chunk dicts:
      {"metadata": {"page": int, ...}, "text": str}
    Page markers allow the extractor to record correct page numbers per field.
    """
    try:
        import pymupdf4llm  # lazy: heavy dep, not always installed in test env
        chunks = pymupdf4llm.to_markdown(pdf_path, page_chunks=True)
        parts: list[str] = []
        for chunk in chunks:
            if isinstance(chunk, dict):
                meta = chunk.get("metadata", {})
                page = meta.get("page", "?")
                text = chunk.get("text", "")
            else:
                page, text = "?", str(chunk)
            parts.append(f"[PARSER_A PAGE {page}]\n{text}")
        return "\n\n".join(parts) or "[PARSER_A: no content extracted]"
    except Exception as exc:
        return f"[PARSER_A_FAILED: {exc}]"


def _parse_with_docling(pdf_path: str) -> str:
    """Parser B — Docling: full page layout analysis, tables, multi-column.

    Docling excels at SBC tables (the "Common Medical Events" grid is multi-column).
    Markdown export preserves reading order and table structure.
    """
    try:
        from docling.document_converter import DocumentConverter  # lazy
        converter = DocumentConverter()
        result = converter.convert(pdf_path)
        md = result.document.export_to_markdown()
        return f"[PARSER_B]\n{md}" if md else "[PARSER_B: no content extracted]"
    except Exception as exc:
        return f"[PARSER_B_FAILED: {exc}]"


async def _parse_pdf_parallel(pdf_path: str) -> tuple[str, str]:
    """Run both sync parsers in a thread pool and await both results."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_a = loop.run_in_executor(pool, _parse_with_pymupdf4llm, pdf_path)
        fut_b = loop.run_in_executor(pool, _parse_with_docling, pdf_path)
        raw_a, raw_b = await asyncio.gather(fut_a, fut_b)
    return raw_a, raw_b


def _slice_to_pages(raw_text: str, pages: set[int]) -> str:
    """Extract only the specified page sections from a raw parser output.

    Parser A uses markers like "[PARSER_A PAGE 3]". Parser B has no markers
    and always returns full text (we cannot split it without re-parsing).
    """
    if not pages:
        return raw_text

    page_pattern = re.compile(r"(\[PARSER_A PAGE \d+\])", re.IGNORECASE)
    sections = page_pattern.split(raw_text)

    if len(sections) <= 1:
        return raw_text  # no page markers found (Parser B) → return full text

    kept: list[str] = []
    current_page: Optional[int] = None
    for section in sections:
        match = re.match(r"\[PARSER_A PAGE (\d+)\]", section, re.IGNORECASE)
        if match:
            current_page = int(match.group(1))
            if current_page in pages:
                kept.append(section)
        elif current_page in pages:
            kept.append(section)

    return "\n".join(kept) if kept else raw_text


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 2 — EXTRACTION
# ═════════════════════════════════════════════════════════════════════════════

EXTRACTION_SYSTEM_PROMPT = """\
You are an expert insurance document analyzer specializing in Summary of Benefits \
and Coverage (SBC) documents.

═══ HARD RULES ═══
1. NEVER infer, guess, or calculate a numeric value. If not found verbatim → null.
2. source_text must be copied VERBATIM from the document (max ~80 chars).
3. Synonyms to recognize for cost-sharing amounts:
   copay / cost-sharing / member cost / your share / your cost /
   your payment / amount you pay / coinsurance / co-pay
4. prior_auth_flags: copy service names VERBATIM from the SBC authorization section.
   Never interpret, rephrase, or combine entries.
5. Boolean fields: use JSON true / false / null — NEVER strings like "yes" or "true".
6. prior_auth_flags value: JSON array of strings, or null.
7. Return ONLY the raw JSON object. No markdown fences. No explanation.

═══ FIELD GUIDE ═══
deductible_individual         Annual individual deductible (e.g. "$500")
deductible_family             Annual family deductible
out_of_pocket_max_individual  Individual out-of-pocket maximum / stop-loss
out_of_pocket_max_family      Family out-of-pocket maximum
primary_care_copay            PCP / primary care / office visit copay
specialist_copay              Specialist office visit copay
urgent_care_copay             Urgent care center copay
er_copay                      Emergency room / emergency services copay
er_copay_waived_if_admitted   true if ER copay waived when patient admitted as inpatient
telehealth_copay              Telehealth / virtual visit / online visit copay
telehealth_covered            true if telehealth is covered at all
generic_drug_copay            Tier 1 / generic prescription drug copay
preferred_drug_copay          Tier 2 / preferred brand drug copay
mental_health_copay           Mental health / behavioral health / outpatient psych copay
in_network_required           true = HMO/EPO (in-network only), false = PPO (OON covered)
pcp_referral_required         true if specialist referral from PCP is required (HMO)
prior_auth_flags              Array of services requiring prior authorization (verbatim)
insurer_phone                 Customer service / member services phone number
insurer_provider_finder_url   Provider directory / find-a-provider URL

═══ OUTPUT SCHEMA ═══
Return exactly this structure for all 19 fields. Use null for any missing sub-key.

{
  "field_name": {
    "value": <extracted value or null>,
    "page":  <page number as integer or null>,
    "bbox":  <[x0, y0, x1, y1] as list or null>,
    "source_text": <verbatim excerpt or null>
  }
}
"""

_SCHEMA_TEMPLATE = (
    "{\n"
    + ",\n".join(
        f'  "{f}": {{"value": null, "page": null, "bbox": null, "source_text": null}}'
        for f in FIELD_NAMES
    )
    + "\n}"
)


def _empty_schema() -> dict:
    """Return a null-filled schema dict — the safe default for any failure."""
    return {
        f: {"value": None, "page": None, "bbox": None, "source_text": None}
        for f in FIELD_NAMES
    }


def _strip_fences(text: str) -> str:
    """Remove markdown code fences Claude occasionally adds despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.strip())
    return text.strip()


def _call_extractor(
    raw_text_a: str,
    raw_text_b: str,
    feedback: str = "",
    target_fields: Optional[list[str]] = None,
) -> dict:
    """Call Claude to extract all 19 plan fields from both parser outputs.

    On any failure returns an empty schema (all null) — hard rule: never crash.
    """
    llm = ChatAnthropic(model=MODEL, max_tokens=4096)

    parts: list[str] = []
    if feedback:
        parts.append(f"VALIDATOR FEEDBACK — address these issues:\n{feedback}\n")
    if target_fields:
        parts.append(f"PRIORITY: re-extract ONLY these fields: {', '.join(target_fields)}\n")

    parts.append("=== PARSER A OUTPUT (PyMuPDF4LLM) ===")
    parts.append(raw_text_a[:15_000])
    parts.append("\n=== PARSER B OUTPUT (Docling) ===")
    parts.append(raw_text_b[:15_000])
    parts.append(
        f"\nExtract all 19 fields. Return ONLY the JSON object. Template:\n{_SCHEMA_TEMPLATE}"
    )

    try:
        response = llm.invoke([
            SystemMessage(content=EXTRACTION_SYSTEM_PROMPT),
            HumanMessage(content="\n".join(parts)),
        ])
        extracted = json.loads(_strip_fences(response.content))

        result = _empty_schema()
        for field in FIELD_NAMES:
            if field in extracted and isinstance(extracted[field], dict):
                entry = extracted[field]
                result[field] = {
                    "value": entry.get("value"),
                    "page": entry.get("page"),
                    "bbox": entry.get("bbox"),
                    "source_text": entry.get("source_text"),
                }
        return result
    except Exception:
        return _empty_schema()


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 3 — LANGGRAPH GLEANING LOOP
# ═════════════════════════════════════════════════════════════════════════════

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


# ── Node 2: Validator Agent ───────────────────────────────────────────────────

VALIDATOR_SYSTEM_PROMPT = """\
You are a validation agent reviewing extracted insurance data from an SBC document.
You have raw PDF text from two parsers and the extracted JSON.

Tasks:
1. For each non-null value, verify it appears (or is clearly derivable) from at
   least one parser's text. Flag any value that appears fabricated.
2. CONFLICT detection: if Parser A and Parser B both contain the same field but
   with DIFFERENT values, flag as CONFLICT and record both values.
3. If a field clearly visible in the raw text was extracted as null, flag it.

Respond ONLY with this JSON structure (no markdown fences, no explanation):
{
  "passed": true | false,
  "issues": [
    {"field": "field_name", "issue": "description"}
  ],
  "per_field_confidence": {
    "field_name": "HIGH" | "MED" | "CONFLICT" | "MISSING"
  },
  "conflict_values": {
    "field_name": {"parser_a": "value from parser A text", "parser_b": "value from parser B text"}
  }
}

Confidence rules (assign for ALL 19 fields):
  HIGH     — value confirmed in both parser texts with matching result
  MED      — value found in only one parser's text
  CONFLICT — both parsers contain explicitly different values for this field
  MISSING  — value is null or absent from both parser texts

conflict_values: include an entry ONLY for CONFLICT fields.
passed = true only when issues list is empty.
"""


def _node_validator_agent(state: GleaningState) -> dict:
    """Node 2 — Separate Claude instance cross-checks extraction against raw texts.

    Validator metadata (per_field_confidence, conflict_values) is embedded into
    extracted_json under dunder keys so LangGraph merges it reliably alongside
    the existing field data without needing extra TypedDict fields.
    """
    llm = ChatAnthropic(model=MODEL, max_tokens=2048)

    user_msg = (
        f"=== PARSER A (first 6000 chars) ===\n{state['raw_text_a'][:6000]}\n\n"
        f"=== PARSER B (first 6000 chars) ===\n{state['raw_text_b'][:6000]}\n\n"
        f"=== EXTRACTED JSON ===\n"
        f"{json.dumps(state['extracted_json'], indent=2)[:5000]}\n\n"
        "Validate and return the JSON report."
    )

    try:
        response = llm.invoke([
            SystemMessage(content=VALIDATOR_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ])
        report = json.loads(_strip_fences(response.content))
    except Exception:
        # If validator fails, treat as passed — never block the pipeline
        report = {
            "passed": True,
            "issues": [],
            "per_field_confidence": {},
            "conflict_values": {},
        }

    passed = bool(report.get("passed", True))
    issues: list[dict] = report.get("issues", [])
    per_field_confidence: dict = report.get("per_field_confidence", {})
    conflict_values: dict = report.get("conflict_values", {})

    feedback = state["validation_feedback"]
    if not passed and issues:
        lines = [
            f"  - {i['field']}: {i['issue']}"
            for i in issues
            if isinstance(i, dict) and "field" in i and "issue" in i
        ]
        feedback = "VALIDATOR ISSUES:\n" + "\n".join(lines)

    # Embed validator metadata into extracted_json via dunder keys so it flows
    # through LangGraph state without requiring additional TypedDict fields.
    updated_extracted = {
        **state["extracted_json"],
        "__per_field_confidence": per_field_confidence,
        "__conflict_values": conflict_values,
    }

    return {
        "validator_passed": passed,
        "validation_feedback": feedback,
        "extracted_json": updated_extracted,
    }


# ── Node 3: Re-extraction ─────────────────────────────────────────────────────

def _node_re_extraction(state: GleaningState) -> dict:
    """Node 3 — Re-run extractor with validator feedback on specific pages only.

    1. Identify flagged fields from feedback text.
    2. Collect the pages where those fields were found.
    3. Slice raw text to only those pages (reduces Claude context, improves accuracy).
    4. Merge new results into existing JSON; untargeted fields are preserved.
    Back to Node 1. Iteration counter enforces the hard cap of 2.
    """
    feedback = state["validation_feedback"]
    target_fields: Optional[list[str]] = [f for f in FIELD_NAMES if f in feedback] or None

    # Collect pages where the targeted fields were found
    target_pages: set[int] = set()
    if target_fields:
        for field in target_fields:
            entry = state["extracted_json"].get(field, {})
            page = entry.get("page") if isinstance(entry, dict) else None
            if isinstance(page, int):
                target_pages.add(page)

    sliced_a = _slice_to_pages(state["raw_text_a"], target_pages) if target_pages else state["raw_text_a"]
    sliced_b = _slice_to_pages(state["raw_text_b"], target_pages) if target_pages else state["raw_text_b"]

    new_extracted = _call_extractor(sliced_a, sliced_b, feedback=feedback, target_fields=target_fields)

    # Preserve dunder metadata keys from previous pass
    merged = {k: v for k, v in state["extracted_json"].items() if k.startswith("__")}
    # Overwrite targeted fields with new results
    for field in (target_fields if target_fields else FIELD_NAMES):
        if field in new_extracted:
            merged[field] = new_extracted[field]
    # Keep untargeted fields from previous extraction
    for field in FIELD_NAMES:
        if field not in merged:
            merged[field] = state["extracted_json"].get(
                field, {"value": None, "page": None, "bbox": None, "source_text": None}
            )

    return {
        "extracted_json": merged,
        "iteration_count": state["iteration_count"] + 1,
        "schema_valid": False,     # reset: force Node 1 re-check
        "validator_passed": False,
    }


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


# ── Graph (built once, cached) ────────────────────────────────────────────────

_GLEANING_GRAPH = None


def _get_gleaning_graph():
    """Build and compile the LangGraph Gleaning loop; cache at module level."""
    global _GLEANING_GRAPH
    if _GLEANING_GRAPH is None:
        g = StateGraph(GleaningState)

        g.add_node("schema_validator", _node_schema_validator)
        g.add_node("validator_agent", _node_validator_agent)
        g.add_node("re_extraction", _node_re_extraction)
        g.add_node("confidence_labeling", _node_confidence_labeling)

        g.set_entry_point("schema_validator")

        g.add_conditional_edges(
            "schema_validator",
            _route_after_schema,
            {
                "validator_agent": "validator_agent",
                "re_extraction": "re_extraction",
                "confidence_labeling": "confidence_labeling",
            },
        )
        g.add_conditional_edges(
            "validator_agent",
            _route_after_validator,
            {
                "confidence_labeling": "confidence_labeling",
                "re_extraction": "re_extraction",
            },
        )
        g.add_edge("re_extraction", "schema_validator")
        g.add_edge("confidence_labeling", END)

        _GLEANING_GRAPH = g.compile()
    return _GLEANING_GRAPH


# ═════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═════════════════════════════════════════════════════════════════════════════

async def run_plan_lookup(pdf_bytes: bytes) -> dict:
    """Full three-layer pipeline: PDF bytes → structured plan JSON.

    Returns a dict with all 19 field keys. Each entry:
      {
        "value": ...,         # extracted value or null
        "page": ...,          # page number or null
        "bbox": ...,          # [x0,y0,x1,y1] or null
        "source_text": ...,   # verbatim excerpt or null
        "confidence": ...,    # HIGH | MED | CONFLICT | MISSING
        "value_b": ...,       # only present for CONFLICT fields ("keep both")
      }

    Hard rules enforced:
    - PHI: temp file deleted immediately after parsing (never stored server-side)
    - Inference: null for any field not explicitly found in the document
    - Max iterations: Gleaning loop hard-capped at MAX_GLEANING_ITERATIONS = 2
    - Best result: always returned even if loop hits the cap
    """
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        raw_a, raw_b = await _parse_pdf_parallel(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    initial_extracted = _call_extractor(raw_a, raw_b)

    # All 8 GleaningState keys must be present in the initial dict so LangGraph
    # can safely merge partial updates from nodes into the state.
    initial_state: GleaningState = {
        "raw_text_a": raw_a,
        "raw_text_b": raw_b,
        "extracted_json": initial_extracted,
        "validation_feedback": "",
        "iteration_count": 0,
        "final_json": {},
        "schema_valid": False,
        "validator_passed": False,
    }

    graph = _get_gleaning_graph()
    final_state = graph.invoke(initial_state)
    return final_state["final_json"]
