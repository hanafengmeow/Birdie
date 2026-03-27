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
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

logger = logging.getLogger(__name__)

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from config import FIELD_NAMES, MAX_GLEANING_ITERATIONS, MODEL
from prompts.plan_lookup import EXTRACTION_SYSTEM_PROMPT, SCHEMA_TEMPLATE, VALIDATOR_SYSTEM_PROMPT
from utils import _strip_fences
from tools.plan_lookup_parsers import (
    _parse_with_pymupdf4llm,
    _parse_with_docling,
    _slice_to_pages,
)
from tools.plan_lookup_graph import (
    GleaningState,
    _empty_schema,
    _node_schema_validator,
    _node_confidence_labeling,
    _route_after_schema,
    _route_after_validator,
)

# Re-export imported symbols so `patch("tools.plan_lookup.XXX")` targets work
# in tests — the graph builder references these names from this module's globals.
__all__ = [
    "FIELD_NAMES",
    "GleaningState",
    "_empty_schema",
    "_node_schema_validator",
    "_node_confidence_labeling",
    "_route_after_schema",
    "_route_after_validator",
    "_parse_with_pymupdf4llm",
    "_parse_with_docling",
    "_slice_to_pages",
    "_call_extractor",
    "_node_validator_agent",
    "_node_re_extraction",
    "run_plan_lookup",
]


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 1 — PARSING (parallel runner; individual parsers in plan_lookup_parsers)
# ═════════════════════════════════════════════════════════════════════════════

async def _parse_pdf_parallel(pdf_path: str) -> tuple[str, str]:
    """Run both sync parsers in a thread pool and await both results."""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_a = loop.run_in_executor(pool, _parse_with_pymupdf4llm, pdf_path)
        fut_b = loop.run_in_executor(pool, _parse_with_docling, pdf_path)
        raw_a, raw_b = await asyncio.gather(fut_a, fut_b)
    return raw_a, raw_b


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 2 — EXTRACTION
# ═════════════════════════════════════════════════════════════════════════════

def _call_extractor(
    raw_text_a: str,
    raw_text_b: str,
    feedback: str = "",
    target_fields: Optional[list[str]] = None,
) -> dict:
    """Call Claude to extract all 19 plan fields from both parser outputs.

    On any failure returns an empty schema (all null) — hard rule: never crash.
    """
    llm = ChatAnthropic(model=MODEL, max_tokens=4096)  # type: ignore[call-arg]

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
        f"\nExtract all 19 fields. Return ONLY the JSON object. Template:\n{SCHEMA_TEMPLATE}"
    )

    try:
        response = llm.invoke([
            SystemMessage(content=EXTRACTION_SYSTEM_PROMPT),
            HumanMessage(content="\n".join(parts)),
        ])
        extracted = json.loads(_strip_fences(str(response.content)))

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
    except Exception as exc:
        logger.error("Extractor Claude call failed: %s", exc)
        return _empty_schema()


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 3 — LANGGRAPH GLEANING LOOP (Claude-calling nodes)
# ═════════════════════════════════════════════════════════════════════════════

# ── Node 2: Validator Agent ───────────────────────────────────────────────────

def _node_validator_agent(state: GleaningState) -> dict:
    """Node 2 — Separate Claude instance cross-checks extraction against raw texts.

    Validator metadata (per_field_confidence, conflict_values) is embedded into
    extracted_json under dunder keys so LangGraph merges it reliably alongside
    the existing field data without needing extra TypedDict fields.
    """
    llm = ChatAnthropic(model=MODEL, max_tokens=2048)  # type: ignore[call-arg]

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
        report = json.loads(_strip_fences(str(response.content)))
    except Exception as exc:
        # If validator fails, treat as passed — never block the pipeline
        logger.error("Validator Claude call failed: %s", exc)
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

    # Return structured JSON + raw parsed text for document Q&A
    return {
        "plan_json": final_state["final_json"],
        "plan_raw_text": raw_a[:20_000],  # Parser A markdown, capped
        "plan_name": _extract_plan_name(raw_a),
    }


def _extract_plan_name(raw_text: str) -> str:
    """Extract plan name from SBC header.

    SBC standard format has plan/insurer info in the first few lines.
    Look for lines containing identifiers like 'Blue', 'Aetna', 'United',
    or 'Plan Type:' which typically appear in the plan header row.
    """
    header = raw_text[:2000]
    lines = header.split("\n")

    def _clean(text: str) -> str:
        """Strip markdown formatting and extra whitespace."""
        import re
        text = re.sub(r"\*+", "", text)  # remove bold/italic markers
        text = text.strip("#").strip()
        text = re.sub(r"\s+", " ", text)  # collapse whitespace
        return text.strip()

    # Strategy 1: Find the line with "Plan Type:" — it typically contains the plan name
    for line in lines:
        if "plan type:" in line.lower():
            clean = _clean(line)
            # Extract everything before "Coverage for:" if present
            if "coverage for:" in clean.lower():
                clean = clean[:clean.lower().index("coverage for:")].strip()
            # Remove "Plan Type: XXX" suffix
            if "plan type:" in clean.lower():
                clean = clean[:clean.lower().index("plan type:")].strip().rstrip("|").strip()
            if clean:
                return clean

    # Strategy 2: Find line with known insurer names
    insurers = ["blue cross", "blue shield", "aetna", "united", "cigna", "kaiser", "humana", "anthem"]
    for line in lines:
        lower = line.lower().strip()
        if any(ins in lower for ins in insurers) and len(lower) > 10:
            clean = _clean(line)
            if len(clean) < 150:
                return clean

    return "Insurance Plan"
