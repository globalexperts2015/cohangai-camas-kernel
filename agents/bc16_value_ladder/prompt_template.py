"""BC16 prompt template + tool schema (flat for LLM compliance)."""
from __future__ import annotations

import json
from pathlib import Path


def load_knowledge_base() -> str:
    path = Path(__file__).parent / "knowledge_base.md"
    if not path.exists():
        return ""
    return path.read_text()


def build_ladder_prompt(persona: dict, pain_summary: dict, joy_summary: dict, venture: str, knowledge_base: str) -> str:
    return f"""Bạn là chuyên gia Value Ladder Design theo Russell Brunson + Anna Empire Stack + Eagle Camp CL5.

# Knowledge base (full framework)

{knowledge_base}

# Venture
{venture}

# Persona context (từ BC11 VPC + BC15 Character)
{json.dumps(persona, ensure_ascii=False, indent=2)[:2000]}

# Pain summary (từ BC13)
{json.dumps(pain_summary, ensure_ascii=False, indent=2)[:1500]}

# Joy summary (từ BC14)
{json.dumps(joy_summary, ensure_ascii=False, indent=2)[:1500]}

# Task

Design Value Ladder 3-5 tier cho venture "{venture}" + persona đã profile:

Quality requirements:
- 3-5 tier (Bait → Frontend → Mid → High → Continuity)
- Mỗi tier có: name (MAGIC formula), price VND, deliverable detail, duration, guarantee
- Price progression theo knowledge_base section 7
- Match Anna Empire Stack pattern (199k → 3M → 6M → 15M → 50M) nếu Breakout venture
- Customize price tier theo persona income ceiling
- Expected conversion rate per tier
- Identify bridge tier nếu gap quá lớn
- KHÔNG em-dash, no forbidden term

Output qua tool submit_ladder.
"""


SUBMIT_LADDER_TOOL = {
    "name": "submit_ladder",
    "description": "Submit Value Ladder design 3-5 tier (flat schema)",
    "input_schema": {
        "type": "object",
        "properties": {
            "venture": {"type": "string"},
            "persona_name": {"type": "string"},
            "tier_1_name": {"type": "string", "description": "Bait tier name"},
            "tier_1_price_vnd": {"type": "integer"},
            "tier_1_purpose": {"type": "string"},
            "tier_1_deliverable": {"type": "string"},
            "tier_1_brunson_level": {"type": "string", "description": "Bait | Frontend | Mid | High | Continuity"},
            "tier_2_name": {"type": "string"},
            "tier_2_price_vnd": {"type": "integer"},
            "tier_2_purpose": {"type": "string"},
            "tier_2_deliverable": {"type": "string"},
            "tier_2_brunson_level": {"type": "string"},
            "tier_2_duration": {"type": "string"},
            "tier_2_guarantee": {"type": "string"},
            "tier_3_name": {"type": "string"},
            "tier_3_price_vnd": {"type": "integer"},
            "tier_3_purpose": {"type": "string"},
            "tier_3_deliverable": {"type": "string"},
            "tier_3_brunson_level": {"type": "string"},
            "tier_3_duration": {"type": "string"},
            "tier_3_guarantee": {"type": "string"},
            "tier_4_name": {"type": "string"},
            "tier_4_price_vnd": {"type": "integer"},
            "tier_4_purpose": {"type": "string"},
            "tier_4_deliverable": {"type": "string"},
            "tier_4_brunson_level": {"type": "string"},
            "tier_4_duration": {"type": "string"},
            "tier_4_guarantee": {"type": "string"},
            "tier_5_name": {"type": "string"},
            "tier_5_price_vnd": {"type": "integer"},
            "tier_5_purpose": {"type": "string"},
            "tier_5_deliverable": {"type": "string"},
            "tier_5_brunson_level": {"type": "string"},
            "tier_5_duration": {"type": "string"},
            "tier_5_guarantee": {"type": "string"},
            "total_ladder_value_vnd": {"type": "integer", "description": "Sum all tier prices (LTV per customer)"},
            "expected_conversion_per_tier": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tier_name": {"type": "string"},
                        "conversion_pct": {"type": "number"},
                    },
                },
            },
            "bridge_tier_recommended": {"type": "string", "description": "Nếu gap giữa tiers quá lớn"},
            "persona_income_match": {"type": "string", "description": "How ladder matches persona income"},
            "anna_empire_stack_match": {"type": "boolean", "description": "True nếu match canonical 199k/3M/6M/15M/50M"},
            "passes_quality": {"type": "boolean"},
            "summary": {"type": "string"},
        },
        "required": ["venture", "persona_name", "tier_1_name", "tier_1_price_vnd", "tier_2_name", "tier_2_price_vnd", "total_ladder_value_vnd", "summary"],
    },
}
