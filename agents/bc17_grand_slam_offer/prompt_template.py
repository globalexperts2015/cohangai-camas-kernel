"""BC17 prompt template + tool schema (flat)."""
from __future__ import annotations

import json
from pathlib import Path


def load_knowledge_base() -> str:
    path = Path(__file__).parent / "knowledge_base.md"
    if not path.exists():
        return ""
    return path.read_text()


def build_offer_prompt(persona: dict, ladder_tier: dict, pain_summary: dict, joy_summary: dict, venture: str, knowledge_base: str) -> str:
    return f"""Bạn là chuyên gia Grand Slam Offer Builder theo Hormozi + Brunson Stack Method + Dan Lok USP.

# Knowledge base (full framework)

{knowledge_base}

# Venture
{venture}

# Persona (từ BC11+BC15)
{json.dumps(persona, ensure_ascii=False, indent=2)[:1500]}

# Ladder Tier (target tier from BC16)
{json.dumps(ladder_tier, ensure_ascii=False, indent=2)[:1500]}

# Pain summary
{json.dumps(pain_summary, ensure_ascii=False)[:1000]}

# Joy summary
{json.dumps(joy_summary, ensure_ascii=False)[:1000]}

# Task

Build Grand Slam Offer cho tier này:

Quality requirements:
- Core offer giải pain critical persona
- 5-10 bonuses, mỗi cái có value VND + objection addressed
- Total bonus value > 3x price (premium) hoặc > 5x (frontend)
- Guarantee type chosen + reason
- Scarcity thật (cap quantifiable)
- Urgency với deadline cụ thể
- MAGIC naming formula
- USP 1 câu rõ
- KHÔNG em-dash, no forbidden term

Output qua tool submit_offer.
"""


SUBMIT_OFFER_TOOL = {
    "name": "submit_offer",
    "description": "Submit Grand Slam Offer (flat schema)",
    "input_schema": {
        "type": "object",
        "properties": {
            "venture": {"type": "string"},
            "tier_name": {"type": "string"},
            "magic_name": {"type": "string", "description": "MAGIC formula: Magnetic + Avatar + Goal + Indicator + Container"},
            "usp": {"type": "string", "description": "Unique Selling Proposition 1 câu"},
            "core_offer": {"type": "string"},
            "core_price_vnd": {"type": "integer"},
            "core_solves_pain": {"type": "string"},
            "bonus_1_name": {"type": "string"},
            "bonus_1_value_vnd": {"type": "integer"},
            "bonus_1_addresses_objection": {"type": "string"},
            "bonus_2_name": {"type": "string"},
            "bonus_2_value_vnd": {"type": "integer"},
            "bonus_2_addresses_objection": {"type": "string"},
            "bonus_3_name": {"type": "string"},
            "bonus_3_value_vnd": {"type": "integer"},
            "bonus_3_addresses_objection": {"type": "string"},
            "bonus_4_name": {"type": "string"},
            "bonus_4_value_vnd": {"type": "integer"},
            "bonus_4_addresses_objection": {"type": "string"},
            "bonus_5_name": {"type": "string"},
            "bonus_5_value_vnd": {"type": "integer"},
            "bonus_5_addresses_objection": {"type": "string"},
            "bonus_6_name": {"type": "string"},
            "bonus_6_value_vnd": {"type": "integer"},
            "bonus_6_addresses_objection": {"type": "string"},
            "bonus_7_name": {"type": "string"},
            "bonus_7_value_vnd": {"type": "integer"},
            "bonus_7_addresses_objection": {"type": "string"},
            "total_stack_value_vnd": {"type": "integer", "description": "Sum core + all bonuses"},
            "value_to_price_ratio": {"type": "number", "description": "total_stack_value / core_price (target ≥3x)"},
            "guarantee_type": {"type": "string", "description": "Unconditional | Conditional | Anti-guarantee | Implied"},
            "guarantee_text": {"type": "string"},
            "scarcity_real": {"type": "string", "description": "Real cap (vd: 100 slot cohort)"},
            "urgency_deadline": {"type": "string", "description": "Cụ thể deadline"},
            "passes_quality": {"type": "boolean"},
            "summary": {"type": "string"},
        },
        "required": ["venture", "tier_name", "magic_name", "usp", "core_offer", "core_price_vnd", "bonus_1_name", "bonus_1_value_vnd", "total_stack_value_vnd", "guarantee_type", "summary"],
    },
}
