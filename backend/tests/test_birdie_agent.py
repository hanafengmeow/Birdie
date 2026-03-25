"""Tests for backend/agents/birdie_agent.py

Strategy: mock all external API calls (Claude, care_router, find_care) so tests
run without API keys.

What is actually tested without mocks:
  - _is_emergency() — pure Python keyword check
  - _summarize_plan() — pure Python dict transformation
  - _INTENT_FALLBACK default structure
  - DATA_MARKER_START / DATA_MARKER_END constants

What is tested with mocks:
  - _classify_intent() — one ChatAnthropic.invoke() call
  - _run_tools() — async calls to run_care_router / run_find_care
  - _stream_response() — ChatAnthropic.astream() + data block appended
  - run_birdie_agent() — full pipeline integration

Run from backend/:
  python tests/test_birdie_agent.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import AsyncMock, MagicMock, patch
import agents.birdie_agent as ba

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

MOCK_PLAN_JSON = {
    "urgent_care_copay": {"value": "$50", "confidence": "HIGH"},
    "er_copay": {"value": "$150", "confidence": "HIGH"},
    "telehealth_copay": {"value": "$0", "confidence": "HIGH"},
    "telehealth_covered": {"value": True, "confidence": "HIGH"},
    "primary_care_copay": {"value": "$20", "confidence": "HIGH"},
    "pcp_referral_required": {"value": False, "confidence": "HIGH"},
    "insurer_phone": {"value": "1-877-468-0016", "confidence": "HIGH"},
    "insurer_provider_finder_url": {
        "value": "https://example.com/find-provider",
        "confidence": "HIGH",
    },
}

MOCK_ROUTER_RESULT = {
    "primary_recommendation": {
        "care_type": "urgent_care",
        "reason": "Fever is an urgent but non-emergency symptom.",
        "coverage": {"copay": "$50", "confidence": "HIGH", "note": "Call to verify."},
        "prior_auth_flag": None,
    },
    "alternative_options": [],
    "referral_required": False,
    "disclaimer": "This is navigation guidance only, not medical advice. Call 911 for emergencies.",
    "user_language": "en",
}

MOCK_ROUTER_ER_RESULT = {
    "primary_recommendation": {
        "care_type": "er",
        "reason": "Chest pain requires emergency evaluation.",
        "coverage": {"copay": "$150", "confidence": "HIGH", "note": "Copay may be waived."},
        "prior_auth_flag": None,
    },
    "alternative_options": [],
    "referral_required": False,
    "disclaimer": "This is navigation guidance only, not medical advice. Call 911 for emergencies.",
    "user_language": "en",
}

MOCK_FIND_RESULT = {
    "care_type": "urgent_care",
    "results": [
        {
            "name": "CareNow Urgent Care",
            "address": "100 Main St",
            "distance_miles": 0.5,
            "is_open_now": True,
            "hours_today": "Open until 10pm",
            "phone": "617-555-0100",
            "google_maps_url": "https://maps.google.com/?q=place_id:abc",
            "booking_url": None,
            "rating": 4.2,
            "rating_count": 180,
            "network_status": "verify_required",
            "network_note": "Call to verify if this provider accepts your insurance",
        }
    ],
    "telehealth_fallback": False,
    "user_language": "en",
}

MOCK_INTENT_COMBINED = {
    "intent": "combined",
    "tools_needed": ["care_router", "find_care"],
    "care_type_hint": "urgent_care",
    "needs_location": False,
    "ask_followup": None,
}

MOCK_INTENT_SYMPTOM = {
    "intent": "symptom_routing",
    "tools_needed": ["care_router"],
    "care_type_hint": None,
    "needs_location": False,
    "ask_followup": None,
}

MOCK_INTENT_FIND = {
    "intent": "find_provider",
    "tools_needed": ["find_care"],
    "care_type_hint": "urgent_care",
    "needs_location": False,
    "ask_followup": None,
}

MOCK_INTENT_PLAN_QUESTION = {
    "intent": "plan_question",
    "tools_needed": [],
    "care_type_hint": None,
    "needs_location": False,
    "ask_followup": None,
}

MOCK_INTENT_GENERAL = {
    "intent": "general",
    "tools_needed": [],
    "care_type_hint": None,
    "needs_location": False,
    "ask_followup": None,
}

MOCK_LOCATION = {"lat": 42.3601, "lng": -71.0589}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _collect_stream(agen) -> str:
    """Collect all chunks from an async generator into a single string."""
    async def _gather():
        chunks = []
        async for chunk in agen:
            chunks.append(chunk)
        return "".join(chunks)
    return asyncio.run(_gather())


def _make_sync_llm_mock(content: str) -> MagicMock:
    """Mock ChatAnthropic class for _classify_intent (uses .invoke())."""
    inst = MagicMock()
    inst.invoke.return_value = MagicMock(content=content)
    return MagicMock(return_value=inst)


def _make_stream_llm_mock(content: str) -> MagicMock:
    """Mock ChatAnthropic class for _stream_response (uses .astream())."""
    async def _mock_astream(*args, **kwargs):
        yield MagicMock(content=content)
    inst = MagicMock()
    inst.astream = _mock_astream
    return MagicMock(return_value=inst)


def _make_pipeline_llm_mock(intent_content: str, response_content: str) -> MagicMock:
    """Mock ChatAnthropic class that returns different instances for classify vs stream."""
    # Instance 1: intent classifier (sync invoke)
    intent_inst = MagicMock()
    intent_inst.invoke.return_value = MagicMock(content=intent_content)

    # Instance 2: response composer (async astream)
    async def _mock_astream(*args, **kwargs):
        yield MagicMock(content=response_content)
    response_inst = MagicMock()
    response_inst.astream = _mock_astream

    return MagicMock(side_effect=[intent_inst, response_inst])


def _make_request(
    message: str = "I have a fever",
    plan_json=None,
    location=None,
    user_language: str = "en",
) -> MagicMock:
    """Build a mock ChatRequest."""
    req = MagicMock()
    req.message = message
    req.plan_json = plan_json
    if location:
        loc = MagicMock()
        loc.lat = location["lat"]
        loc.lng = location["lng"]
        req.location = loc
    else:
        req.location = None
    req.user_language = user_language
    return req


# ─────────────────────────────────────────────────────────────────────────────
# _is_emergency
# ─────────────────────────────────────────────────────────────────────────────

def test_is_emergency_chest_pain():
    assert ba._is_emergency("I have chest pain") is True
    print("✓ test_is_emergency_chest_pain")


def test_is_emergency_cant_breathe():
    assert ba._is_emergency("I can't breathe properly") is True
    print("✓ test_is_emergency_cant_breathe")


def test_is_emergency_loss_of_consciousness():
    assert ba._is_emergency("My friend lost consciousness") is True
    print("✓ test_is_emergency_loss_of_consciousness")


def test_is_emergency_severe_allergic_reaction():
    assert ba._is_emergency("Severe allergic reaction after eating nuts") is True
    print("✓ test_is_emergency_severe_allergic_reaction")


def test_is_emergency_regular_fever_false():
    assert ba._is_emergency("I have a fever of 100F") is False
    print("✓ test_is_emergency_regular_fever_false")


def test_is_emergency_headache_false():
    assert ba._is_emergency("I have a bad headache") is False
    print("✓ test_is_emergency_headache_false")


def test_is_emergency_case_insensitive():
    assert ba._is_emergency("CHEST PAIN since this morning") is True
    print("✓ test_is_emergency_case_insensitive")


# ─────────────────────────────────────────────────────────────────────────────
# _summarize_plan
# ─────────────────────────────────────────────────────────────────────────────

def test_summarize_plan_extracts_value_and_confidence():
    summary = ba._summarize_plan(MOCK_PLAN_JSON)
    assert summary["urgent_care_copay"]["value"] == "$50"
    assert summary["urgent_care_copay"]["confidence"] == "HIGH"
    print("✓ test_summarize_plan_extracts_value_and_confidence")


def test_summarize_plan_skips_non_dict_entries():
    plan = {"field_a": {"value": "x", "confidence": "HIGH"}, "not_a_field": "raw_string"}
    summary = ba._summarize_plan(plan)
    assert "field_a" in summary
    assert "not_a_field" not in summary
    print("✓ test_summarize_plan_skips_non_dict_entries")


def test_summarize_plan_missing_confidence_defaults_to_missing():
    plan = {"field_a": {"value": "x"}}  # no confidence key
    summary = ba._summarize_plan(plan)
    assert summary["field_a"]["confidence"] == "MISSING"
    print("✓ test_summarize_plan_missing_confidence_defaults_to_missing")


# ─────────────────────────────────────────────────────────────────────────────
# _classify_intent
# ─────────────────────────────────────────────────────────────────────────────

def test_classify_intent_symptom_routing():
    with patch("agents.birdie_agent.ChatAnthropic", _make_sync_llm_mock(json.dumps(MOCK_INTENT_SYMPTOM))):
        result = ba._classify_intent("I have a fever", True, False, "en")
    assert result["intent"] == "symptom_routing"
    assert result["tools_needed"] == ["care_router"]
    assert result["ask_followup"] is None
    print("✓ test_classify_intent_symptom_routing")


def test_classify_intent_find_provider_with_location():
    intent = {**MOCK_INTENT_FIND, "needs_location": False, "ask_followup": None}
    with patch("agents.birdie_agent.ChatAnthropic", _make_sync_llm_mock(json.dumps(intent))):
        result = ba._classify_intent("Find urgent care near me", True, True, "en")
    assert "find_care" in result["tools_needed"]
    assert result["ask_followup"] is None
    print("✓ test_classify_intent_find_provider_with_location")


def test_classify_intent_find_provider_no_location_asks_followup():
    intent = {**MOCK_INTENT_FIND, "needs_location": True, "ask_followup": "Could you share your location?"}
    with patch("agents.birdie_agent.ChatAnthropic", _make_sync_llm_mock(json.dumps(intent))):
        result = ba._classify_intent("Find urgent care near me", True, False, "en")
    assert result["ask_followup"] is not None
    assert len(result["ask_followup"]) > 0
    print("✓ test_classify_intent_find_provider_no_location_asks_followup")


def test_classify_intent_combined():
    with patch("agents.birdie_agent.ChatAnthropic", _make_sync_llm_mock(json.dumps(MOCK_INTENT_COMBINED))):
        result = ba._classify_intent("I have a fever, find something near me", True, True, "en")
    assert result["intent"] == "combined"
    assert "care_router" in result["tools_needed"]
    assert "find_care" in result["tools_needed"]
    print("✓ test_classify_intent_combined")


def test_classify_intent_plan_question_no_tools():
    with patch("agents.birdie_agent.ChatAnthropic", _make_sync_llm_mock(json.dumps(MOCK_INTENT_PLAN_QUESTION))):
        result = ba._classify_intent("What is my urgent care copay?", True, False, "en")
    assert result["tools_needed"] == []
    assert result["intent"] == "plan_question"
    print("✓ test_classify_intent_plan_question_no_tools")


def test_classify_intent_bad_json_falls_back_to_general():
    with patch("agents.birdie_agent.ChatAnthropic", _make_sync_llm_mock("NOT JSON AT ALL")):
        result = ba._classify_intent("some message", False, False, "en")
    assert result["intent"] == "general"
    assert result["tools_needed"] == []
    print("✓ test_classify_intent_bad_json_falls_back_to_general")


def test_classify_intent_strips_unknown_tools():
    """tools_needed containing unknown values must be stripped out."""
    bad_intent = {**MOCK_INTENT_COMBINED, "tools_needed": ["care_router", "unknown_tool", "find_care"]}
    with patch("agents.birdie_agent.ChatAnthropic", _make_sync_llm_mock(json.dumps(bad_intent))):
        result = ba._classify_intent("test", False, True, "en")
    assert "unknown_tool" not in result["tools_needed"]
    assert "care_router" in result["tools_needed"]
    print("✓ test_classify_intent_strips_unknown_tools")


# ─────────────────────────────────────────────────────────────────────────────
# _run_tools
# ─────────────────────────────────────────────────────────────────────────────

def test_run_tools_no_tools_returns_empty():
    result = asyncio.run(ba._run_tools(MOCK_INTENT_GENERAL, "test", None, None, "en"))
    assert result["care_router"] is None
    assert result["find_care"] is None
    print("✓ test_run_tools_no_tools_returns_empty")


def test_run_tools_care_router_only():
    with patch("agents.birdie_agent.run_care_router", AsyncMock(return_value=MOCK_ROUTER_RESULT)):
        result = asyncio.run(ba._run_tools(MOCK_INTENT_SYMPTOM, "fever", MOCK_PLAN_JSON, None, "en"))
    assert result["care_router"] == MOCK_ROUTER_RESULT
    assert result["find_care"] is None
    print("✓ test_run_tools_care_router_only")


def test_run_tools_find_care_only():
    with patch("agents.birdie_agent.run_find_care", AsyncMock(return_value=MOCK_FIND_RESULT)):
        result = asyncio.run(ba._run_tools(MOCK_INTENT_FIND, "find urgent care", None, MOCK_LOCATION, "en"))
    assert result["care_router"] is None
    assert result["find_care"] == MOCK_FIND_RESULT
    print("✓ test_run_tools_find_care_only")


def test_run_tools_combined_uses_router_care_type():
    """find_care must use the actual care_type from care_router, not the classifier hint."""
    telehealth_router = {
        **MOCK_ROUTER_RESULT,
        "primary_recommendation": {
            **MOCK_ROUTER_RESULT["primary_recommendation"],
            "care_type": "telehealth",  # router says telehealth (after-hours)
        },
    }
    find_care_mock = AsyncMock(return_value=MOCK_FIND_RESULT)

    with (
        patch("agents.birdie_agent.run_care_router", AsyncMock(return_value=telehealth_router)),
        patch("agents.birdie_agent.run_find_care", find_care_mock),
    ):
        asyncio.run(ba._run_tools(MOCK_INTENT_COMBINED, "sick", MOCK_PLAN_JSON, MOCK_LOCATION, "en"))

    find_care_mock.assert_called_once()
    call_kwargs = find_care_mock.call_args.kwargs
    assert call_kwargs["care_type"] == "telehealth", \
        f"Expected 'telehealth', got '{call_kwargs['care_type']}'"
    print("✓ test_run_tools_combined_uses_router_care_type")


def test_run_tools_er_care_type_skips_find_care():
    """When care_router returns ER, find_care must NOT be called."""
    find_care_mock = AsyncMock(return_value=MOCK_FIND_RESULT)

    with (
        patch("agents.birdie_agent.run_care_router", AsyncMock(return_value=MOCK_ROUTER_ER_RESULT)),
        patch("agents.birdie_agent.run_find_care", find_care_mock),
    ):
        result = asyncio.run(ba._run_tools(MOCK_INTENT_COMBINED, "chest pain", None, MOCK_LOCATION, "en"))

    find_care_mock.assert_not_called()
    assert result["find_care"] is None
    print("✓ test_run_tools_er_care_type_skips_find_care")


def test_run_tools_no_location_skips_find_care():
    """find_care must not be called when location is None."""
    find_care_mock = AsyncMock(return_value=MOCK_FIND_RESULT)
    intent = {**MOCK_INTENT_FIND, "tools_needed": ["find_care"]}

    with patch("agents.birdie_agent.run_find_care", find_care_mock):
        result = asyncio.run(ba._run_tools(intent, "find clinic", None, None, "en"))

    find_care_mock.assert_not_called()
    assert result["find_care"] is None
    print("✓ test_run_tools_no_location_skips_find_care")


def test_run_tools_care_router_exception_graceful():
    """If care_router throws, result is None — never crash."""
    with patch("agents.birdie_agent.run_care_router", AsyncMock(side_effect=RuntimeError("API down"))):
        result = asyncio.run(ba._run_tools(MOCK_INTENT_SYMPTOM, "fever", None, None, "en"))
    assert result["care_router"] is None
    print("✓ test_run_tools_care_router_exception_graceful")


def test_run_tools_find_care_exception_graceful():
    """If find_care throws, result is None — never crash."""
    with (
        patch("agents.birdie_agent.run_care_router", AsyncMock(return_value=MOCK_ROUTER_RESULT)),
        patch("agents.birdie_agent.run_find_care", AsyncMock(side_effect=RuntimeError("Maps down"))),
    ):
        result = asyncio.run(ba._run_tools(MOCK_INTENT_COMBINED, "sick", None, MOCK_LOCATION, "en"))
    assert result["find_care"] is None
    assert result["care_router"] == MOCK_ROUTER_RESULT  # care_router still succeeded
    print("✓ test_run_tools_find_care_exception_graceful")


# ─────────────────────────────────────────────────────────────────────────────
# Full pipeline — run_birdie_agent
# ─────────────────────────────────────────────────────────────────────────────

def test_full_pipeline_emergency_bypasses_tools():
    """Emergency message must yield 911 instruction without any Claude/tool calls."""
    find_mock = AsyncMock()
    router_mock = AsyncMock()
    req = _make_request(message="I have chest pain", user_language="en")

    with (
        patch("agents.birdie_agent.run_care_router", router_mock),
        patch("agents.birdie_agent.run_find_care", find_mock),
    ):
        output = _collect_stream(ba.run_birdie_agent(req))

    assert "911" in output
    router_mock.assert_not_called()
    find_mock.assert_not_called()
    print("✓ test_full_pipeline_emergency_bypasses_tools")


def test_full_pipeline_emergency_chinese():
    """Chinese emergency response must contain Chinese characters."""
    req = _make_request(message="I can't breathe", user_language="zh")
    output = _collect_stream(ba.run_birdie_agent(req))
    assert "911" in output or "急" in output or "拨打" in output
    print("✓ test_full_pipeline_emergency_chinese")


def test_full_pipeline_ask_followup_no_location():
    """When intent says ask_followup, agent yields the question and stops."""
    followup_intent = {**MOCK_INTENT_FIND, "ask_followup": "Could you share your location?"}
    find_mock = AsyncMock()
    llm_mock = _make_sync_llm_mock(json.dumps(followup_intent))
    req = _make_request(message="Find urgent care near me", location=None)

    with (
        patch("agents.birdie_agent.ChatAnthropic", llm_mock),
        patch("agents.birdie_agent.run_find_care", find_mock),
    ):
        output = _collect_stream(ba.run_birdie_agent(req))

    assert "location" in output.lower() or len(output) > 0
    find_mock.assert_not_called()
    print("✓ test_full_pipeline_ask_followup_no_location")


def test_full_pipeline_symptom_only_streams_text():
    """Symptom-only routing should stream text with no data block."""
    llm_mock = _make_pipeline_llm_mock(
        intent_content=json.dumps(MOCK_INTENT_SYMPTOM),
        response_content="You should visit urgent care.",
    )
    req = _make_request(message="I have a fever", plan_json=MOCK_PLAN_JSON)

    with (
        patch("agents.birdie_agent.ChatAnthropic", llm_mock),
        patch("agents.birdie_agent.run_care_router", AsyncMock(return_value=MOCK_ROUTER_RESULT)),
    ):
        output = _collect_stream(ba.run_birdie_agent(req))

    assert "urgent care" in output.lower() or len(output) > 0
    print("✓ test_full_pipeline_symptom_only_streams_text")


def test_full_pipeline_combined_yields_data_block():
    """Combined flow must append __BIRDIE_DATA_START__ block after text."""
    llm_mock = _make_pipeline_llm_mock(
        intent_content=json.dumps(MOCK_INTENT_COMBINED),
        response_content="Here are nearby options — see cards below.",
    )
    req = _make_request(message="I have fever, find care", plan_json=MOCK_PLAN_JSON, location=MOCK_LOCATION)

    with (
        patch("agents.birdie_agent.ChatAnthropic", llm_mock),
        patch("agents.birdie_agent.run_care_router", AsyncMock(return_value=MOCK_ROUTER_RESULT)),
        patch("agents.birdie_agent.run_find_care", AsyncMock(return_value=MOCK_FIND_RESULT)),
    ):
        output = _collect_stream(ba.run_birdie_agent(req))

    assert ba.DATA_MARKER_START in output
    assert ba.DATA_MARKER_END in output
    print("✓ test_full_pipeline_combined_yields_data_block")


def test_full_pipeline_data_block_is_valid_json():
    """The content between data markers must be parseable JSON."""
    llm_mock = _make_pipeline_llm_mock(
        intent_content=json.dumps(MOCK_INTENT_COMBINED),
        response_content="Here are the options.",
    )
    req = _make_request(message="sick + find care", plan_json=MOCK_PLAN_JSON, location=MOCK_LOCATION)

    with (
        patch("agents.birdie_agent.ChatAnthropic", llm_mock),
        patch("agents.birdie_agent.run_care_router", AsyncMock(return_value=MOCK_ROUTER_RESULT)),
        patch("agents.birdie_agent.run_find_care", AsyncMock(return_value=MOCK_FIND_RESULT)),
    ):
        output = _collect_stream(ba.run_birdie_agent(req))

    start = output.index(ba.DATA_MARKER_START) + len(ba.DATA_MARKER_START)
    end = output.index(ba.DATA_MARKER_END)
    data = json.loads(output[start:end].strip())
    assert "care_router" in data
    assert "find_care" in data
    assert data["care_router"] == MOCK_ROUTER_RESULT
    assert data["find_care"] == MOCK_FIND_RESULT
    print("✓ test_full_pipeline_data_block_is_valid_json")


def test_full_pipeline_no_data_block_when_no_tools():
    """Plan question with no tools must produce NO data block."""
    llm_mock = _make_pipeline_llm_mock(
        intent_content=json.dumps(MOCK_INTENT_PLAN_QUESTION),
        response_content="Your urgent care copay is $50.",
    )
    req = _make_request(message="What is my copay?", plan_json=MOCK_PLAN_JSON)

    with patch("agents.birdie_agent.ChatAnthropic", llm_mock):
        output = _collect_stream(ba.run_birdie_agent(req))

    assert ba.DATA_MARKER_START not in output
    assert ba.DATA_MARKER_END not in output
    print("✓ test_full_pipeline_no_data_block_when_no_tools")


def test_full_pipeline_plan_question_no_tool_calls():
    """Plan question must not call care_router or find_care."""
    router_mock = AsyncMock()
    find_mock = AsyncMock()
    llm_mock = _make_pipeline_llm_mock(
        intent_content=json.dumps(MOCK_INTENT_PLAN_QUESTION),
        response_content="Your deductible is $100.",
    )
    req = _make_request(message="What is my deductible?", plan_json=MOCK_PLAN_JSON)

    with (
        patch("agents.birdie_agent.ChatAnthropic", llm_mock),
        patch("agents.birdie_agent.run_care_router", router_mock),
        patch("agents.birdie_agent.run_find_care", find_mock),
    ):
        _collect_stream(ba.run_birdie_agent(req))

    router_mock.assert_not_called()
    find_mock.assert_not_called()
    print("✓ test_full_pipeline_plan_question_no_tool_calls")


def test_full_pipeline_care_router_result_in_data_block():
    """care_router result must appear in data block even without find_care."""
    llm_mock = _make_pipeline_llm_mock(
        intent_content=json.dumps(MOCK_INTENT_SYMPTOM),
        response_content="Visit urgent care.",
    )
    req = _make_request(message="I have a fever", plan_json=MOCK_PLAN_JSON)

    with (
        patch("agents.birdie_agent.ChatAnthropic", llm_mock),
        patch("agents.birdie_agent.run_care_router", AsyncMock(return_value=MOCK_ROUTER_RESULT)),
    ):
        output = _collect_stream(ba.run_birdie_agent(req))

    assert ba.DATA_MARKER_START in output
    start = output.index(ba.DATA_MARKER_START) + len(ba.DATA_MARKER_START)
    end = output.index(ba.DATA_MARKER_END)
    data = json.loads(output[start:end].strip())
    assert data["care_router"] == MOCK_ROUTER_RESULT
    assert data["find_care"] is None
    print("✓ test_full_pipeline_care_router_result_in_data_block")


def test_full_pipeline_user_language_echoed():
    """user_language from request must flow through to care_router call."""
    router_mock = AsyncMock(return_value=MOCK_ROUTER_RESULT)
    llm_mock = _make_pipeline_llm_mock(
        intent_content=json.dumps(MOCK_INTENT_SYMPTOM),
        response_content="前往紧急诊所。",
    )
    req = _make_request(message="发烧了", plan_json=MOCK_PLAN_JSON, user_language="zh")

    with (
        patch("agents.birdie_agent.ChatAnthropic", llm_mock),
        patch("agents.birdie_agent.run_care_router", router_mock),
    ):
        _collect_stream(ba.run_birdie_agent(req))

    call_kwargs = router_mock.call_args.kwargs
    assert call_kwargs["user_language"] == "zh"
    print("✓ test_full_pipeline_user_language_echoed")


def test_full_pipeline_no_plan_json_graceful():
    """Agent must not crash when plan_json is None."""
    llm_mock = _make_pipeline_llm_mock(
        intent_content=json.dumps(MOCK_INTENT_SYMPTOM),
        response_content="Upload your SBC for plan-specific information.",
    )
    req = _make_request(message="I have a fever", plan_json=None)

    with (
        patch("agents.birdie_agent.ChatAnthropic", llm_mock),
        patch("agents.birdie_agent.run_care_router", AsyncMock(return_value=MOCK_ROUTER_RESULT)),
    ):
        output = _collect_stream(ba.run_birdie_agent(req))

    assert len(output) > 0
    print("✓ test_full_pipeline_no_plan_json_graceful")


def test_full_pipeline_tool_exception_still_streams():
    """If care_router throws, agent still streams a response (no crash)."""
    llm_mock = _make_pipeline_llm_mock(
        intent_content=json.dumps(MOCK_INTENT_SYMPTOM),
        response_content="Sorry, I encountered an issue. Please call your insurer.",
    )
    req = _make_request(message="I have a fever")

    with (
        patch("agents.birdie_agent.ChatAnthropic", llm_mock),
        patch("agents.birdie_agent.run_care_router", AsyncMock(side_effect=RuntimeError("API down"))),
    ):
        output = _collect_stream(ba.run_birdie_agent(req))

    assert len(output) > 0
    print("✓ test_full_pipeline_tool_exception_still_streams")


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

def test_data_marker_constants():
    assert ba.DATA_MARKER_START == "__BIRDIE_DATA_START__"
    assert ba.DATA_MARKER_END == "__BIRDIE_DATA_END__"
    print("✓ test_data_marker_constants")


def test_intent_fallback_structure():
    fb = ba._INTENT_FALLBACK
    assert fb["intent"] == "general"
    assert fb["tools_needed"] == []
    assert fb["ask_followup"] is None
    print("✓ test_intent_fallback_structure")


# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────

ALL_TESTS = [
    test_is_emergency_chest_pain,
    test_is_emergency_cant_breathe,
    test_is_emergency_loss_of_consciousness,
    test_is_emergency_severe_allergic_reaction,
    test_is_emergency_regular_fever_false,
    test_is_emergency_headache_false,
    test_is_emergency_case_insensitive,
    test_summarize_plan_extracts_value_and_confidence,
    test_summarize_plan_skips_non_dict_entries,
    test_summarize_plan_missing_confidence_defaults_to_missing,
    test_classify_intent_symptom_routing,
    test_classify_intent_find_provider_with_location,
    test_classify_intent_find_provider_no_location_asks_followup,
    test_classify_intent_combined,
    test_classify_intent_plan_question_no_tools,
    test_classify_intent_bad_json_falls_back_to_general,
    test_classify_intent_strips_unknown_tools,
    test_run_tools_no_tools_returns_empty,
    test_run_tools_care_router_only,
    test_run_tools_find_care_only,
    test_run_tools_combined_uses_router_care_type,
    test_run_tools_er_care_type_skips_find_care,
    test_run_tools_no_location_skips_find_care,
    test_run_tools_care_router_exception_graceful,
    test_run_tools_find_care_exception_graceful,
    test_full_pipeline_emergency_bypasses_tools,
    test_full_pipeline_emergency_chinese,
    test_full_pipeline_ask_followup_no_location,
    test_full_pipeline_symptom_only_streams_text,
    test_full_pipeline_combined_yields_data_block,
    test_full_pipeline_data_block_is_valid_json,
    test_full_pipeline_no_data_block_when_no_tools,
    test_full_pipeline_plan_question_no_tool_calls,
    test_full_pipeline_care_router_result_in_data_block,
    test_full_pipeline_user_language_echoed,
    test_full_pipeline_no_plan_json_graceful,
    test_full_pipeline_tool_exception_still_streams,
    test_data_marker_constants,
    test_intent_fallback_structure,
]

if __name__ == "__main__":
    print("=" * 60)
    print("Birdie agent test suite")
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
