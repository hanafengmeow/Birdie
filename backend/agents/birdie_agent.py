"""birdie_agent: main LangChain agent pipeline for /api/chat.

Architecture — three steps per request:
  Step 0  Emergency fast path — pure Python keyword check, no API calls
  Step 1  Intent classification — one Claude call, JSON output
           → if follow-up needed: yield question and stop
  Step 2  Tool execution — 0-2 async tool calls (sequential when combined)
  Step 3  Response streaming — one Claude streaming call
           → text tokens streamed first
           → structured data block appended at end (if tools were called)

Streaming protocol (see CLAUDE.md §Streaming protocol):
  Text stream ends with:
    __BIRDIE_DATA_START__
    {"care_router": <result|null>, "find_care": <result|null>}
    __BIRDIE_DATA_END__
  The frontend splits on the markers to render provider cards.
"""

import json
from typing import AsyncGenerator, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from config import DISCLAIMER, MODEL
from prompts.agent import INTENT_SYSTEM_PROMPT, build_response_system_prompt
from tools.care_router import run_care_router
from tools.find_care import run_find_care
from utils import _strip_fences

# ── Streaming markers (see CLAUDE.md §Streaming protocol) ─────────────────────

DATA_MARKER_START = "__BIRDIE_DATA_START__"
DATA_MARKER_END = "__BIRDIE_DATA_END__"

# ── Emergency keyword list ─────────────────────────────────────────────────────

EMERGENCY_PATTERNS: list[str] = [
    "chest pain",
    "can't breathe",
    "cannot breathe",
    "can't breath",
    "difficulty breathing",
    "trouble breathing",
    "loss of consciousness",
    "lost consciousness",
    "unconscious",
    "not breathing",
    "severe bleeding",
    "uncontrolled bleeding",
    "stroke",
    "heart attack",
    "anaphylaxis",
    "severe allergic reaction",
    "face is swelling",
    "throat closing",
]

# ── Fallback intent when classifier fails ─────────────────────────────────────

_INTENT_FALLBACK: dict = {
    "intent": "general",
    "tools_needed": [],
    "care_type_hint": None,
    "needs_location": False,
    "ask_followup": None,
}

_VALID_TOOLS: frozenset[str] = frozenset({"care_router", "find_care"})


# ── Step 0: Emergency fast path ───────────────────────────────────────────────

def _is_emergency(message: str) -> bool:
    """Return True if message contains a hardcoded emergency keyword."""
    lower = message.lower()
    return any(p in lower for p in EMERGENCY_PATTERNS)


# ── Plan summary helper ────────────────────────────────────────────────────────

def _summarize_plan(plan_json: dict) -> dict:
    """Return {field: {value, confidence}} for all fields — compact for Claude context."""
    summary: dict = {}
    for field, entry in plan_json.items():
        if isinstance(entry, dict) and "value" in entry:
            summary[field] = {
                "value": entry.get("value"),
                "confidence": entry.get("confidence", "MISSING"),
            }
    return summary


# ── Step 1: Intent classification ─────────────────────────────────────────────

def _classify_intent(
    message: str,
    has_plan: bool,
    has_location: bool,
    user_language: str,
) -> dict:
    """One Claude call to classify intent and determine which tools to invoke."""
    llm = ChatAnthropic(model=MODEL, max_tokens=512)  # type: ignore[call-arg]
    user_content = (
        f"user_language: {user_language}\n"
        f"has_plan_json: {has_plan}\n"
        f"has_location: {has_location}\n"
        f"user_message: {message}\n\n"
        "Output JSON only."
    )
    try:
        resp = llm.invoke([
            SystemMessage(content=INTENT_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ])
        result = json.loads(_strip_fences(str(resp.content)))
        # Sanitize tools_needed — keep only recognised tool names
        result["tools_needed"] = [
            t for t in result.get("tools_needed", []) if t in _VALID_TOOLS
        ]
        return {**_INTENT_FALLBACK, **result}
    except Exception:
        return _INTENT_FALLBACK


# ── Step 2: Tool execution ─────────────────────────────────────────────────────

async def _run_tools(
    intent: dict,
    message: str,
    plan_json: Optional[dict],
    location: Optional[dict],
    user_language: str,
) -> dict:
    """Execute 0-2 tool calls based on intent. Sequential for combined case
    so find_care uses the actual care_type returned by care_router."""
    tools = intent.get("tools_needed", [])
    care_type_hint = intent.get("care_type_hint") or "urgent_care"
    results: dict = {"care_router": None, "find_care": None}

    if not tools:
        return results

    # care_router (may set actual care_type for find_care)
    if "care_router" in tools:
        try:
            results["care_router"] = await run_care_router(
                user_message=message,
                extracted_context=None,
                plan_json=plan_json,
                user_language=user_language,
            )
        except Exception:
            results["care_router"] = None

    # find_care — use router's actual care_type when available
    if "find_care" in tools:
        if results["care_router"]:
            primary = results["care_router"].get("primary_recommendation", {})
            care_type = primary.get("care_type", care_type_hint)
        else:
            care_type = care_type_hint

        # ER routing means call 911 — skip Maps search
        if care_type == "er":
            return results

        if location:
            try:
                results["find_care"] = await run_find_care(
                    care_type=care_type,
                    location=location,
                    open_now=True,
                    plan_json=plan_json,
                    user_language=user_language,
                )
            except Exception:
                results["find_care"] = None
        # No location → find_care skipped; intent classifier should have asked,
        # but as safety net we silently omit rather than crash.

    return results


# ── Step 3: Response streaming ─────────────────────────────────────────────────

async def _stream_response(
    message: str,
    intent: dict,
    tool_results: dict,
    plan_json: Optional[dict],
    user_language: str,
) -> AsyncGenerator[str, None]:
    """Stream Claude's narrative response, then append structured data block."""
    llm = ChatAnthropic(model=MODEL, max_tokens=800)  # type: ignore[call-arg]
    system_prompt = build_response_system_prompt(user_language, DISCLAIMER)

    # Build human message
    parts: list[str] = [f"User message: {message}"]

    if plan_json:
        summary = _summarize_plan(plan_json)
        parts.append(f"Plan data (value + confidence per field):\n{json.dumps(summary, indent=2)}")
    else:
        parts.append("Plan data: not uploaded — respond with general guidance and upload prompt")

    if tool_results.get("care_router"):
        parts.append(
            f"Care routing result:\n{json.dumps(tool_results['care_router'], indent=2)}"
        )

    if tool_results.get("find_care"):
        fc = tool_results["find_care"]
        n = len(fc.get("results", []))
        ct = fc.get("care_type", "")
        parts.append(
            f"Provider search: {n} result(s) found for '{ct}'. "
            "The frontend renders these as cards — do NOT list clinic names or addresses in text."
        )

    user_content = "\n\n".join(parts)

    # Stream text tokens
    async for chunk in llm.astream([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content),
    ]):
        if chunk.content:
            yield str(chunk.content)

    # Append structured data block if any tool returned results
    has_data = any(v is not None for v in tool_results.values())
    if has_data:
        data_json = json.dumps({
            "care_router": tool_results.get("care_router"),
            "find_care": tool_results.get("find_care"),
        })
        yield f"\n{DATA_MARKER_START}\n{data_json}\n{DATA_MARKER_END}"


# ── Public API ─────────────────────────────────────────────────────────────────

async def run_birdie_agent(request) -> AsyncGenerator[str, None]:
    """Main entry point for /api/chat.

    Accepts a ChatRequest (from main.py) and yields text chunks for StreamingResponse.
    Follows the three-step pipeline: emergency check → intent → tools → stream.
    """
    message: str = request.message or ""
    plan_json: Optional[dict] = request.plan_json
    location: Optional[dict] = (
        {"lat": request.location.lat, "lng": request.location.lng}
        if request.location else None
    )
    user_language: str = (request.user_language or "en")

    # Step 0: Emergency fast path — no Claude calls, immediate response
    if _is_emergency(message):
        if user_language.startswith("zh"):
            yield "这听起来像是医疗紧急情况。请立即拨打911。"
        else:
            yield (
                "This sounds like a medical emergency. "
                "Call 911 immediately or go to the nearest emergency room."
            )
        return

    # Step 1: Intent classification
    intent = _classify_intent(
        message=message,
        has_plan=plan_json is not None,
        has_location=location is not None,
        user_language=user_language,
    )

    # Follow-up question if critical info is missing (primarily: location for find_care)
    ask = intent.get("ask_followup")
    if ask:
        yield ask
        return

    # Step 2: Tool execution
    tool_results = await _run_tools(intent, message, plan_json, location, user_language)

    # Step 3: Stream response
    async for chunk in _stream_response(message, intent, tool_results, plan_json, user_language):
        yield chunk
