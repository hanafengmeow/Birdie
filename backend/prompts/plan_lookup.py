"""Prompt strings for the plan_lookup tool."""

from config import FIELD_NAMES

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

SCHEMA_TEMPLATE = (
    "{\n"
    + ",\n".join(
        f'  "{f}": {{"value": null, "page": null, "bbox": null, "source_text": null}}'
        for f in FIELD_NAMES
    )
    + "\n}"
)

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
