"""birdie_agent: main LangChain agent pipeline for /api/chat.

Architecture — three steps per request:
  Step 0  Emergency fast path — pure Python keyword check, no API calls
  Step 1  Intent classification — confidence-gated, up to 2 Claude calls
           → Round 1: Zero-Shot → confidence score
           → Round 2: Few-Shot fallback if confidence < threshold
           → if follow-up needed: yield question and stop
  Step 2  Tool execution — 0-2 async tool calls (sequential when combined)
  Step 3  Response streaming — one Claude streaming call with conversation history
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
import logging
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from config import (
    COMPLEX_INTENTS,
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_LOW_THRESHOLD,
    DISCLAIMER,
    MODEL,
)
from prompts.agent import INTENT_SYSTEM_PROMPT, build_response_system_prompt
from prompts.few_shot import build_few_shot_block
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
    "search_query": None,
    "needs_location": False,
    "confidence": 0.5,
    "information_sufficient": True,
    "ask_followup": None,
}

_VALID_TOOLS: frozenset[str] = frozenset({"care_router", "find_care"})


# ── Step 0: Emergency fast path ───────────────────────────────────────────────

def _is_emergency(message: str) -> bool:
    """Return True if message contains a hardcoded emergency keyword."""
    lower = message.lower()
    return any(p in lower for p in EMERGENCY_PATTERNS)


# ── Conversation history helpers ──────────────────────────────────────────────

def _format_history_for_intent(history: list[dict]) -> str:
    """Format conversation history as a compact block for intent classification."""
    if not history:
        return ""
    lines: list[str] = ["Conversation so far:"]
    for turn in history:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if not content:
            continue
        # Strip data markers from assistant messages
        if DATA_MARKER_START in content:
            content = content.split(DATA_MARKER_START)[0].strip()
        if role == "user":
            lines.append(f"  User: {content}")
        elif role == "assistant":
            lines.append(f"  Birdie: {content}")
    return "\n".join(lines)


def _build_history_messages(history: list[dict]) -> list:
    """Convert conversation history dicts to LangChain message objects for response streaming."""
    msgs: list = []
    for turn in history:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if not content:
            continue
        # Strip data markers from assistant messages
        if DATA_MARKER_START in content:
            content = content.split(DATA_MARKER_START)[0].strip()
        if role == "user":
            msgs.append(HumanMessage(content=content))
        elif role == "assistant":
            msgs.append(AIMessage(content=content))
    return msgs


def _trim_history(history: list[dict], max_turns: int = 10) -> list[dict]:
    """Keep only the most recent N turns (user+assistant pairs)."""
    # Each turn = 1 message. Keep last max_turns*2 messages (pairs).
    max_messages = max_turns * 2
    if len(history) <= max_messages:
        return history
    return history[-max_messages:]


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


# ── Step 1: Intent classification (confidence-gated) ────────────────────────

def _run_classifier(
    system_prompt: str,
    message: str,
    has_plan: bool,
    has_location: bool,
    user_language: str,
    history: list[dict],
) -> dict:
    """Single Claude call for intent classification. Used by both zero-shot and few-shot."""
    llm = ChatAnthropic(model=MODEL, max_tokens=512)  # type: ignore[call-arg]

    parts: list[str] = []

    # Add conversation history if available
    history_block = _format_history_for_intent(history)
    if history_block:
        parts.append(history_block)

    parts.append(
        f"user_language: {user_language}\n"
        f"has_plan_json: {has_plan}\n"
        f"has_location: {has_location}\n"
        f"user_message: {message}\n\n"
        "Output JSON only."
    )

    user_content = "\n\n".join(parts)

    try:
        resp = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ])
        result = json.loads(_strip_fences(str(resp.content)))
        result["tools_needed"] = [
            t for t in result.get("tools_needed", []) if t in _VALID_TOOLS
        ]
        return {**_INTENT_FALLBACK, **result}
    except Exception:
        return _INTENT_FALLBACK


def _classify_intent(
    message: str,
    has_plan: bool,
    has_location: bool,
    user_language: str,
    history: list[dict],
) -> dict:
    """Confidence-gated intent classification.

    Round 1: Zero-Shot classification with confidence score.
    Round 2 (conditional): Few-Shot fallback if confidence is too low.
      - confidence >= 0.85 → use zero-shot result
      - confidence < 0.70  → always fall back to few-shot
      - 0.70-0.85          → few-shot only for complex intents
    """
    # Round 1: Zero-Shot
    result = _run_classifier(
        system_prompt=INTENT_SYSTEM_PROMPT,
        message=message,
        has_plan=has_plan,
        has_location=has_location,
        user_language=user_language,
        history=history,
    )

    confidence = result.get("confidence", 0.5)

    # High confidence → use directly
    if confidence >= CONFIDENCE_HIGH_THRESHOLD:
        return result

    # Low confidence → always few-shot
    needs_few_shot = confidence < CONFIDENCE_LOW_THRESHOLD

    # Medium confidence → few-shot only for complex intents
    if not needs_few_shot and result.get("intent") in COMPLEX_INTENTS:
        needs_few_shot = True

    if needs_few_shot:
        few_shot_prompt = INTENT_SYSTEM_PROMPT + "\n\n" + build_few_shot_block()
        result = _run_classifier(
            system_prompt=few_shot_prompt,
            message=message,
            has_plan=has_plan,
            has_location=has_location,
            user_language=user_language,
            history=history,
        )

    return result


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
    search_query = intent.get("search_query")
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
                    search_query=search_query,
                )
            except Exception:
                results["find_care"] = None

    return results


# ── Step 3: Response streaming ─────────────────────────────────────────────────

async def _stream_response(
    message: str,
    intent: str,
    tool_results: dict,
    plan_json: Optional[dict],
    plan_raw_text: Optional[str],
    user_language: str,
    history: list[dict],
) -> AsyncGenerator[str, None]:
    """Stream Claude's narrative response with conversation history, then append structured data block.

    For plan_question intent: includes full plan_raw_text so Claude can answer
    any question about the SBC document precisely.
    For other intents: only includes the structured JSON summary (cheaper).
    """
    # plan_question with raw text needs more output room for detailed answers
    max_tok = 800 if intent == "plan_question" else 400
    llm = ChatAnthropic(model=MODEL, max_tokens=max_tok)  # type: ignore[call-arg]
    system_prompt = build_response_system_prompt(user_language, DISCLAIMER)

    # Start with system message
    messages: list = [SystemMessage(content=system_prompt)]

    # Add conversation history as alternating messages for multi-turn context
    history_msgs = _build_history_messages(history)
    messages.extend(history_msgs)

    # Build current user message with context
    parts: list[str] = [f"User message: {message}"]

    if plan_raw_text and intent == "plan_question":
        # Full document context for plan questions — enables precise answers
        logger.info("plan_question: injecting plan_raw_text (%d chars)", len(plan_raw_text))
        parts.append(
            "FULL PLAN DOCUMENT (answer ONLY from this document, do not guess):\n"
            f"{plan_raw_text[:15000]}"
        )
    elif plan_raw_text and plan_json:
        # Other intents with plan: send raw text as supplementary context (truncated)
        # This covers cases where care_router needs plan details beyond the 19 fields
        summary = _summarize_plan(plan_json)
        parts.append(f"Plan data (value + confidence per field):\n{json.dumps(summary, indent=2)}")
    elif plan_json:
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
    messages.append(HumanMessage(content=user_content))

    # Stream text tokens
    async for chunk in llm.astream(messages):
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
    plan_raw_text: Optional[str] = request.plan_raw_text
    location: Optional[dict] = (
        {"lat": request.location.lat, "lng": request.location.lng}
        if request.location else None
    )
    user_language: str = (request.user_language or "en")
    history: list[dict] = _trim_history(request.conversation_history or [])

    logger.info(
        "run_birdie_agent: plan_json=%s, plan_raw_text=%s chars, history=%d turns",
        "yes" if plan_json else "no",
        len(plan_raw_text) if plan_raw_text else "null",
        len(history),
    )

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

    # Step 1: Intent classification (confidence-gated)
    intent = _classify_intent(
        message=message,
        has_plan=plan_json is not None,
        has_location=location is not None,
        user_language=user_language,
        history=history,
    )

    # Follow-up question if critical info is missing
    ask = intent.get("ask_followup")
    if ask:
        yield ask
        return

    # Step 2: Tool execution
    tool_results = await _run_tools(intent, message, plan_json, location, user_language)

    # Step 3: Stream response with conversation history
    intent_type = intent.get("intent", "general")
    async for chunk in _stream_response(
        message, intent_type, tool_results, plan_json, plan_raw_text,
        user_language, history,
    ):
        yield chunk
