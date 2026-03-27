"""Few-shot examples for intent classification fallback.

Used when Zero-Shot confidence < 0.70, or 0.70-0.85 for complex intents.
Each example is a (user_message, expected_output) pair.
"""

FEW_SHOT_EXAMPLES: list[dict] = [
    # ── symptom_routing (clear) ──────────────────────────────────────────────
    {
        "message": "I have a 101°F fever since yesterday with chills and body aches",
        "output": {
            "intent": "symptom_routing",
            "tools_needed": ["care_router"],
            "care_type_hint": None,
            "needs_location": False,
            "information_sufficient": True,
            "confidence": 0.95,
            "ask_followup": None,
        },
    },
    {
        "message": "I cut my finger deeply and it won't stop bleeding",
        "output": {
            "intent": "symptom_routing",
            "tools_needed": ["care_router"],
            "care_type_hint": None,
            "needs_location": False,
            "information_sufficient": True,
            "confidence": 0.95,
            "ask_followup": None,
        },
    },
    # ── symptom_routing (vague, need follow-up) ─────────────────────────────
    {
        "message": "I have a headache",
        "output": {
            "intent": "symptom_routing",
            "tools_needed": ["care_router"],
            "care_type_hint": None,
            "needs_location": False,
            "information_sufficient": False,
            "confidence": 0.80,
            "ask_followup": "How long have you had the headache? Is it sudden and severe, or has it been building up? Any other symptoms like fever or nausea?",
        },
    },
    {
        "message": "我发烧了",
        "output": {
            "intent": "symptom_routing",
            "tools_needed": ["care_router"],
            "care_type_hint": None,
            "needs_location": False,
            "information_sufficient": False,
            "confidence": 0.75,
            "ask_followup": "发烧多久了？体温大约多少度？有没有其他症状，比如咳嗽、头痛或身体疼痛？",
        },
    },
    # ── find_provider (clear) ────────────────────────────────────────────────
    {
        "message": "Find urgent care near me",
        "output": {
            "intent": "find_provider",
            "tools_needed": ["find_care"],
            "care_type_hint": "urgent_care",
            "needs_location": False,
            "information_sufficient": True,
            "confidence": 0.98,
            "ask_followup": None,
        },
    },
    {
        "message": "附近有药房吗",
        "output": {
            "intent": "find_provider",
            "tools_needed": ["find_care"],
            "care_type_hint": "pharmacy",
            "needs_location": False,
            "information_sufficient": True,
            "confidence": 0.95,
            "ask_followup": None,
        },
    },
    # ── find_provider (vague) ────────────────────────────────────────────────
    {
        "message": "I need to see a doctor",
        "output": {
            "intent": "find_provider",
            "tools_needed": ["find_care"],
            "care_type_hint": None,
            "needs_location": False,
            "information_sufficient": False,
            "confidence": 0.65,
            "ask_followup": "What kind of doctor are you looking for? For example, a primary care physician for a checkup, an urgent care clinic for something that needs attention today, or a specialist?",
        },
    },
    # ── combined ─────────────────────────────────────────────────────────────
    {
        "message": "I twisted my ankle playing basketball, where can I go?",
        "output": {
            "intent": "combined",
            "tools_needed": ["care_router", "find_care"],
            "care_type_hint": "urgent_care",
            "needs_location": False,
            "information_sufficient": True,
            "confidence": 0.90,
            "ask_followup": None,
        },
    },
    {
        "message": "I feel really anxious and need help",
        "output": {
            "intent": "combined",
            "tools_needed": ["care_router", "find_care"],
            "care_type_hint": "mental_health",
            "needs_location": False,
            "information_sufficient": True,
            "confidence": 0.85,
            "ask_followup": None,
        },
    },
    # ── plan_question ────────────────────────────────────────────────────────
    {
        "message": "What's my copay for urgent care?",
        "output": {
            "intent": "plan_question",
            "tools_needed": [],
            "care_type_hint": None,
            "needs_location": False,
            "information_sufficient": True,
            "confidence": 0.95,
            "ask_followup": None,
        },
    },
    {
        "message": "我的自付额是多少",
        "output": {
            "intent": "plan_question",
            "tools_needed": [],
            "care_type_hint": None,
            "needs_location": False,
            "information_sufficient": True,
            "confidence": 0.95,
            "ask_followup": None,
        },
    },
    # ── ambiguous intent ─────────────────────────────────────────────────────
    {
        "message": "PT",
        "output": {
            "intent": "find_provider",
            "tools_needed": ["find_care"],
            "care_type_hint": "pt",
            "needs_location": False,
            "information_sufficient": False,
            "confidence": 0.50,
            "ask_followup": "Are you looking to find a physical therapy clinic near you, or do you have questions about PT coverage under your plan?",
        },
    },
    {
        "message": "约PT",
        "output": {
            "intent": "find_provider",
            "tools_needed": ["find_care"],
            "care_type_hint": "pt",
            "needs_location": False,
            "information_sufficient": False,
            "confidence": 0.55,
            "ask_followup": "你是想了解 PT 预约流程和需要准备什么，还是需要我帮你找附近的 PT 诊所？",
        },
    },
    {
        "message": "I'm pregnant",
        "output": {
            "intent": "general",
            "tools_needed": [],
            "care_type_hint": None,
            "needs_location": False,
            "information_sufficient": False,
            "confidence": 0.45,
            "ask_followup": "Congratulations! Would you like help finding an OB/GYN near you, or do you have questions about your prenatal care coverage?",
        },
    },
    # ── general ──────────────────────────────────────────────────────────────
    {
        "message": "How does a deductible work?",
        "output": {
            "intent": "general",
            "tools_needed": [],
            "care_type_hint": None,
            "needs_location": False,
            "information_sufficient": True,
            "confidence": 0.95,
            "ask_followup": None,
        },
    },
    {
        "message": "What is prior authorization?",
        "output": {
            "intent": "general",
            "tools_needed": [],
            "care_type_hint": None,
            "needs_location": False,
            "information_sufficient": True,
            "confidence": 0.92,
            "ask_followup": None,
        },
    },
    # ── visit_prep ───────────────────────────────────────────────────────────
    {
        "message": "What should I bring to my doctor appointment tomorrow?",
        "output": {
            "intent": "visit_prep",
            "tools_needed": [],
            "care_type_hint": None,
            "needs_location": False,
            "information_sufficient": True,
            "confidence": 0.90,
            "ask_followup": None,
        },
    },
    {
        "message": "I have an appointment",
        "output": {
            "intent": "visit_prep",
            "tools_needed": [],
            "care_type_hint": None,
            "needs_location": False,
            "information_sufficient": False,
            "confidence": 0.60,
            "ask_followup": "What type of appointment is it? For example, a primary care visit, specialist, or urgent care? I can help you prepare.",
        },
    },
]


def build_few_shot_block() -> str:
    """Format few-shot examples as a prompt block for the intent classifier."""
    lines: list[str] = ["Here are examples of correct classifications:\n"]
    for ex in FEW_SHOT_EXAMPLES:
        import json
        lines.append(f'User: "{ex["message"]}"')
        lines.append(f"Output: {json.dumps(ex['output'])}\n")
    return "\n".join(lines)
