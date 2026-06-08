"""BC20 prompt template + tool schema (flat)."""
from __future__ import annotations

import json
from pathlib import Path


def load_knowledge_base() -> str:
    path = Path(__file__).parent / "knowledge_base.md"
    if not path.exists():
        return ""
    return path.read_text()


def build_copy_prompt(persona: dict, offer: dict, funnel_phase: str, formats: list, venture: str, knowledge_base: str) -> str:
    return f"""Bạn là chuyên gia Copywriting theo Dan Lok 8 Tactical Secrets + Brunson Soap Opera + Hormozi Hook-Retain-Reward.

# Knowledge base

{knowledge_base}

# Venture
{venture}

# Persona (từ BC11+BC15)
{json.dumps(persona, ensure_ascii=False, indent=2)[:1500]}

# Offer (từ BC17)
{json.dumps(offer, ensure_ascii=False, indent=2)[:1500]}

# Funnel phase context
{funnel_phase}

# Formats requested
{formats}

# Task

Generate copy variants cho mỗi format requested:

Quality requirements:
- 5-10 variants per format (per knowledge_base section 7)
- Mỗi variant áp dụng ≥3 Dan Lok secrets (call out + big promise + enemies + stories + specificity + pain + demonstrate + USP)
- Soap Opera 5 emails Day 1-5 nếu email sequence requested
- Hook-Retain-Reward visible mỗi piece
- Anna voice DNA pattern (Hằng/bạn, mộc mạc, concrete number)
- KHÔNG forbidden term (mẹ đơn thân, Perth, em-dash)

Output qua tool submit_copy_stack.
"""


SUBMIT_COPY_STACK_TOOL = {
    "name": "submit_copy_stack",
    "description": "Submit copy variants per format (flat schema)",
    "input_schema": {
        "type": "object",
        "properties": {
            "venture": {"type": "string"},
            "funnel_phase": {"type": "string"},
            "reel_variants": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "White box red text middle frame"},
                        "hook_first_5_sec": {"type": "string"},
                        "body": {"type": "string"},
                        "story_anchor": {"type": "string"},
                        "cta": {"type": "string"},
                        "dan_lok_secrets_used": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "fb_post_variants": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "hook_2_lines": {"type": "string"},
                        "body": {"type": "string", "description": "300-500 từ"},
                        "cta_inline": {"type": "string"},
                        "dan_lok_secrets_used": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "email_sequence_soap_opera": {
                "type": "array",
                "description": "5 emails Day 1-5 Brunson Soap Opera",
                "items": {
                    "type": "object",
                    "properties": {
                        "day": {"type": "integer"},
                        "subject": {"type": "string"},
                        "preheader": {"type": "string"},
                        "body": {"type": "string"},
                        "cta": {"type": "string"},
                        "cliffhanger": {"type": "string"},
                    },
                },
            },
            "landing_page": {
                "type": "object",
                "properties": {
                    "h1_big_promise": {"type": "string", "description": "Max 12 từ"},
                    "subheadline": {"type": "string"},
                    "pain_section": {"type": "string"},
                    "offer_section": {"type": "string"},
                    "social_proof": {"type": "string"},
                    "primary_cta": {"type": "string"},
                    "secondary_cta": {"type": "string"},
                },
            },
            "ad_variants": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "headline": {"type": "string"},
                        "body": {"type": "string"},
                        "cta_button": {"type": "string"},
                        "angle": {"type": "string", "description": "Pain | Curiosity | Status | Contrast"},
                    },
                },
            },
            "usp_one_line": {"type": "string", "description": "USP 1 câu rõ"},
            "voice_dna_match_score": {"type": "integer", "minimum": 1, "maximum": 10},
            "forbidden_term_check": {"type": "boolean", "description": "True nếu không có forbidden term"},
            "passes_quality": {"type": "boolean"},
            "summary": {"type": "string"},
        },
        "required": ["venture", "funnel_phase", "usp_one_line", "summary"],
    },
}
