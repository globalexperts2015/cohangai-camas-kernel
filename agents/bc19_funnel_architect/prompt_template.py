"""BC19 prompt template + tool schema (flat)."""
from __future__ import annotations

import json
from pathlib import Path


def load_knowledge_base() -> str:
    path = Path(__file__).parent / "knowledge_base.md"
    if not path.exists():
        return ""
    return path.read_text()


def build_funnel_prompt(ladder: dict, offers: list, persona: dict, venture: str, knowledge_base: str) -> str:
    return f"""Bạn là chuyên gia Funnel Architecture theo Brunson 7 Phases + Eagle Camp IPS 19 + Anna CIS Module 6.

# Knowledge base

{knowledge_base}

# Venture
{venture}

# Persona
{json.dumps(persona, ensure_ascii=False, indent=2)[:1500]}

# Ladder (từ BC16)
{json.dumps(ladder, ensure_ascii=False, indent=2)[:2000]}

# Offers per tier (từ BC17)
{json.dumps(offers, ensure_ascii=False, indent=2)[:2000]}

# Task

Design Funnel 7 Phases end-to-end:

Quality requirements:
- All 7 phases mapped (Pre-frame → Qualify Subscribers → Buyers → Hyperactive → Ascend → Environment → Identity)
- Mỗi phase có tactic + tool + asset
- Conversion target per phase (theo benchmarks knowledge_base section 6)
- Entry point identified (cold ad / warm referral / hot list)
- OTO post frontend defined
- Email sequence Day 1-30 outlined (key emails)
- High-ticket gate mechanism (discovery call / webinar)
- Continuity hook
- Match Anna's Empire Stack pattern

Output qua tool submit_funnel.
"""


SUBMIT_FUNNEL_TOOL = {
    "name": "submit_funnel",
    "description": "Submit 7-phase funnel architecture (flat schema)",
    "input_schema": {
        "type": "object",
        "properties": {
            "venture": {"type": "string"},
            "entry_point": {"type": "string", "description": "cold_ad | warm_referral | hot_list"},
            "phase_1_preframe_tactic": {"type": "string"},
            "phase_1_asset": {"type": "string"},
            "phase_2_subscriber_tactic": {"type": "string"},
            "phase_2_asset": {"type": "string"},
            "phase_2_conversion_pct": {"type": "number"},
            "phase_3_buyer_tactic": {"type": "string"},
            "phase_3_frontend_offer": {"type": "string"},
            "phase_3_price_vnd": {"type": "integer"},
            "phase_3_conversion_pct": {"type": "number"},
            "phase_4_oto_tactic": {"type": "string", "description": "One-Time Offer post frontend"},
            "phase_4_oto_offer": {"type": "string"},
            "phase_4_oto_price_vnd": {"type": "integer"},
            "phase_4_conversion_pct": {"type": "number"},
            "phase_5_ascend_email_sequence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "day": {"type": "integer"},
                        "subject": {"type": "string"},
                        "cta": {"type": "string"},
                    },
                },
                "description": "Key emails Day 1-30 nurture",
            },
            "phase_5_ascend_target_tier": {"type": "string"},
            "phase_6_environment_change": {"type": "string", "description": "discovery_call_30m | webinar_90m | in_person"},
            "phase_6_high_ticket_offer": {"type": "string"},
            "phase_6_price_vnd": {"type": "integer"},
            "phase_7_identity_community": {"type": "string", "description": "Telegram group, badge, alumni network"},
            "phase_7_continuity_hook": {"type": "string"},
            "total_expected_ltv_vnd": {"type": "integer"},
            "anna_empire_stack_match": {"type": "boolean"},
            "passes_quality": {"type": "boolean"},
            "summary": {"type": "string"},
        },
        "required": ["venture", "entry_point", "phase_1_preframe_tactic", "phase_2_subscriber_tactic", "phase_3_buyer_tactic", "phase_3_frontend_offer", "phase_5_ascend_email_sequence", "phase_6_environment_change", "phase_7_identity_community", "summary"],
    },
}
