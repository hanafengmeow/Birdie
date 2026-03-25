# Birdie — CLAUDE.md

## Project overview
Birdie is a healthcare navigation agent for international students in the US.
Full design document: see `birdie_design_doc.md` in project root — read it before writing any tool.

Three goals:
- Help them understand (insurance plans, bills, prescriptions)
- Help them decide (where to go, what it costs, prior auth needed?)
- Help them act (clinic cards, phone numbers, booking links, what to say)

---

## Stack
- Frontend: Next.js + Tailwind + assistant-ui + react-i18next + Framer Motion → Vercel
- Backend: FastAPI + LangChain + LangGraph → Railway
- Model: claude-sonnet-4-20250514 (unified across all tools, never change this)
- PDF parsing: pymupdf4llm via PyMuPDF4LLMLoader (Parser A) + Docling (Parser B) — always run both in parallel
- External APIs: Google Maps Places, Google Maps Geocoding, RxNorm, LangSmith

## Project structure
```
/frontend         Next.js app (Vercel)
/backend          FastAPI app (Railway)
  main.py         FastAPI entry point + /api/chat streaming endpoint
  /tools          one file per tool
    plan_lookup.py
    care_router.py
    find_care.py
    drug_lookup.py
    visit_prep.py
    onboarding_flow.py
  /agents         LangChain main agent + LangGraph Gleaning loop
  .env            API keys (never commit this)
  .env.example    placeholder keys (commit this)
  requirements.txt
```

---

## Tools — priority and purpose

### T0 (must ship for demo)

**plan_lookup** — parses SBC PDF into structured JSON, stored in localStorage
**care_router** — routes symptom descriptions to care settings, never diagnoses
**find_care** — Google Maps Places search, returns provider cards

### T1 (ship if time allows)

**drug_lookup** — RxNorm API, drug coverage and generic alternatives
**visit_prep** — pre-visit checklist, pure Claude generation, no external API
**onboarding_flow** — post-SBC-upload summary card

---

## Hard rules — never break these

- NEVER diagnose medical conditions or recommend specific treatments
- NEVER confirm a provider is in-network — always append "call to verify"
- NEVER infer or guess insurance field numeric values — use null if not found in SBC
- NEVER store any PHI in the backend — localStorage only
- ALWAYS respond in user_language from request context
- ALWAYS end every care_router response with: "This is navigation guidance only, not medical advice. Call 911 for emergencies."
- ALWAYS cap plan_lookup Gleaning loop at max 2 iterations
- ALWAYS return best available result even if Gleaning loop hits max iterations

---

## plan_lookup — full architecture

### Three layers (implement in this order):

**Layer 1 — Parsing (run both parsers in parallel):**
- Parser A: `PyMuPDF4LLMLoader` from `langchain-pymupdf4llm` — outputs structured Markdown + bbox
- Parser B: `Docling` — handles complex layouts, tables, multi-column — outputs JSON + bbox

**Layer 2 — Extraction:**
- Extractor Agent: Claude with strict JSON schema prompt
- Every field output format: `{ "value": str|null, "page": int|null, "bbox": list|null, "source_text": str|null }`
- null is REQUIRED for any field not found — never infer or guess
- Prompt must include synonym list: copay / cost-sharing / member cost / your share / your cost

**Layer 3 — Validation (LangGraph Gleaning loop, max 2 iterations):**
```
Node 1: Schema Validator — check field types, formats, required fields
  → fail: go to Node 3
  → pass: go to Node 2

Node 2: Validator Agent (separate Claude instance)
  → compare Parser A vs B per field
  → check for missing fields, value conflicts
  → issues found: go to Node 3
  → all pass: go to Node 4

Node 3: Re-extraction
  → use validator feedback to re-run extractor on specific pages only
  → back to Node 1 (count iteration, stop at 2)

Node 4: Confidence Labeling
  → HIGH: both parsers agree + validator pass
  → MED: one parser only
  → CONFLICT: both found different values — keep both
  → MISSING: both null
  → write final JSON to response
```

LangGraph state object:
```python
{
  "raw_text_a": str,
  "raw_text_b": str,
  "extracted_json": dict,
  "validation_feedback": str,
  "iteration_count": int,
  "final_json": dict
}
```

### JSON schema — all fields plan_lookup must extract:
```python
{
  "deductible_individual":        { "value": str|null, "page": int|null, "bbox": list|null, "source_text": str|null, "confidence": str },
  "deductible_family":            { ... },
  "out_of_pocket_max_individual": { ... },
  "out_of_pocket_max_family":     { ... },
  "primary_care_copay":           { ... },
  "specialist_copay":             { ... },
  "urgent_care_copay":            { ... },
  "er_copay":                     { ... },
  "er_copay_waived_if_admitted":  { "value": bool|null, ... },
  "telehealth_copay":             { ... },
  "telehealth_covered":           { "value": bool|null, ... },
  "generic_drug_copay":           { ... },
  "preferred_drug_copay":         { ... },
  "mental_health_copay":          { ... },
  "in_network_required":          { "value": bool|null, ... },
  "pcp_referral_required":        { "value": bool|null, ... },
  "prior_auth_flags":             { "value": list[str]|null, ... },
  "insurer_phone":                { ... },
  "insurer_provider_finder_url":  { ... }
}
```

### prior_auth_flags:
Extract verbatim from SBC "Common Medical Events" table. Store as array of strings.
Never interpret or expand these — SBC wording is intentionally vague.
When care_router or find_care matches a scenario in prior_auth_flags, append the verbatim text + "Call the number on your insurance card before scheduling."

---

## care_router — full spec

### Input:
```python
{
  "user_message": str,
  "extracted_context": {
    "symptom_description": str,
    "severity": "emergency" | "urgent" | "routine",
    "time_sensitivity": "now" | "today" | "this_week" | "flexible",
    "time_of_day": str
  },
  "plan_json": dict | None,
  "user_language": str
}
```

### Routing decision framework:
```
Emergency → ER (regardless of insurance):
  chest pain, difficulty breathing, loss of consciousness,
  severe allergic reaction, heavy bleeding

Urgent, same-day → urgent care or telehealth:
  fever, minor injury, ear pain, UTI, mild allergic reaction
  if after hours or weekend → prefer telehealth if covered

Can wait → PCP or telehealth:
  chronic issues, follow-ups, non-acute symptoms

Medication only → pharmacy:
  mild symptoms, OTC guidance

Mental health → mental health services:
  anxiety, depression, stress, sleep issues
  NEVER mix with physical symptom routing

Musculoskeletal → PT:
  sports injury, chronic pain, posture issues
  check plan_json.pcp_referral_required
  if True → recommend PCP first, then PT
```

### Output:
```python
{
  "primary_recommendation": {
    "care_type": "urgent_care"|"er"|"telehealth"|"pcp"|"pharmacy"|"mental_health"|"pt",
    "reason": str,
    "coverage": {
      "copay": str | None,
      "confidence": "HIGH"|"MED"|"MISSING",
      "note": str
    },
    "prior_auth_flag": str | None
  },
  "alternative_options": [ { "care_type": str, "reason": str, "coverage": dict } ],
  "referral_required": bool,
  "disclaimer": "This is navigation guidance only, not medical advice. Call 911 for emergencies.",
  "user_language": str
}
```

---

## find_care — full spec

### care_type to Google Maps keyword mapping:
```python
CARE_TYPE_MAPPING = {
  "urgent_care":   "urgent care clinic",
  "er":            "emergency room hospital",
  "pcp":           "primary care physician clinic",
  "pharmacy":      "pharmacy",
  "mental_health": "mental health clinic therapist",
  "pt":            "physical therapy clinic",
  "telehealth":    None  # special case — skip Maps
}
```

### Input:
```python
{
  "care_type": str,
  "location": { "lat": float, "lng": float },
  "open_now": bool,  # default True
  "user_language": str
}
```

### Output:
```python
{
  "care_type": str,
  "results": [
    {
      "name": str,
      "address": str,
      "distance_miles": float,
      "is_open_now": bool,
      "hours_today": str,
      "phone": str | None,
      "google_maps_url": str,
      "booking_url": str | None,
      "rating": float | None,
      "rating_count": int | None,
      "network_status": "verify_required",  # ALWAYS this value
      "network_note": "Call to verify if this provider accepts your insurance"
    }
  ],
  "telehealth_fallback": bool,
  "user_language": str
}
```

### Telehealth special case:
When care_type == "telehealth", skip Google Maps entirely.
Return:
```python
{
  "care_type": "telehealth",
  "results": [{
    "name": "Telehealth via your insurance",
    "note": "Log into your insurer's app or website to start a telehealth visit",
    "insurer_url": plan_json["insurer_provider_finder_url"]["value"],
    "copay": plan_json["telehealth_copay"]["value"],
    "confidence": plan_json["telehealth_copay"]["confidence"]
  }]
}
```

---

## Plan context system

- plan_json is stored in localStorage under key `birdie_plan_context`
- Frontend reads it on every message and attaches to request body
- If null (no SBC uploaded): backend receives `plan_json: null`
- All tools must handle `plan_json: None` gracefully — return general guidance + upload prompt
- SBC PDF is processed in memory and discarded — only JSON is persisted

### Demo path — pre-loaded SHIP template:
Include a hardcoded JSON object `NORTHEASTERN_SHIP_TEMPLATE` in the backend.
Frontend has a "I'm a Northeastern student" button that POSTs this template directly to localStorage.
This allows demo to run without requiring a real SBC upload.

---

## Confidence label display (frontend)

Render as inline colored pills in chat responses:
- HIGH → green pill "✓ Confirmed"
- MED → amber pill "~ Likely — verify"
- CONFLICT → red pill "⚠ Conflict found"
- MISSING → gray pill "— Not in your plan"

---

## Provider result card (frontend component)

Each find_care result renders as an inline card in the chat:
```
┌─────────────────────────────────────┐
│ [clinic name]                       │
│ ⭐ [rating] ([count]) · [distance]  │
│ 🟢 Open until [time] / 🔴 Closed   │
│ [address]                           │
│                                     │
│ ⚠ Call to verify insurance coverage │
│                                     │
│  [📞 Call]    [🗺 Get Directions]   │
└─────────────────────────────────────┘
```
"Call" → tel: link
"Get Directions" → Google Maps URL, open in new tab

---

## Multilingual rules

- `user_language` is passed in every API request body
- All tool outputs must be in `user_language`
- System prompt: "You are Birdie... Always respond in {user_language}. All confidence labels, disclaimers, and fallback messages must also be in {user_language}."
- Static UI text managed by react-i18next
- Launch languages: "en" and "zh" (Mandarin Chinese)

---

## Fallback rules

| Situation | Response |
|---|---|
| plan_json is None | General guidance + "Upload your SBC for plan-specific answers" |
| Tool call fails | Error in user_language, suggest calling insurer |
| Google Maps no results | Suggest telehealth, provide insurer_provider_finder_url |
| Field confidence MISSING | "Not found in your plan — call [insurer_phone]" |
| care_type is emergency | Skip all tools, immediately output: "Call 911 now." |

---

## Deployment

- Frontend → Vercel (free tier), auto-deploy from GitHub main branch
- Backend → Railway ($5 starter credit), auto-deploy from GitHub main branch
- All API keys in Railway environment variables — never in code
- Frontend env var: `NEXT_PUBLIC_API_URL` = Railway backend URL

## Environment variables needed (backend)
```
ANTHROPIC_API_KEY=
GOOGLE_MAPS_API_KEY=
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=birdie
```
