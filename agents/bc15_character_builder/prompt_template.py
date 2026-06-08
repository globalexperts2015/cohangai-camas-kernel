"""BC15 prompt template + tool schema."""
from __future__ import annotations

import json
from pathlib import Path


def load_knowledge_base() -> str:
    path = Path(__file__).parent / "knowledge_base.md"
    if not path.exists():
        return ""
    return path.read_text()


def build_character_prompt(founder_data: dict, story_pool: list[dict], venture: str, knowledge_base: str) -> str:
    stories_summary = "\n".join(
        f"- [{s.get('tier', '?')}] {s.get('title', s.get('content', '')[:100])}"
        for s in story_pool[:20]
    )

    return f"""Bạn là chuyên gia Attractive Character framework Russell Brunson + Dan Lok Personal Brand áp dụng cho founder Việt.

# Knowledge base (full framework)

{knowledge_base}

# Founder data
{json.dumps(founder_data, ensure_ascii=False, indent=2)[:2000]}

# Venture
{venture}

# Story pool retrieved (top 20)
{stories_summary}

# Task

Build Attractive Character profile cho founder venture "{venture}":

Quality requirements (theo knowledge_base section 5):
- 5 elements ĐẦY ĐỦ (Backstory + Parables + Polarity + Flaws + Identity)
- Backstory: ≥3 key moments với year + story_id từ pool
- Parables: ≥3 ẩn dụ dân dã (reference Anna's canonical nếu match)
- Polarity: ≥2 take-stand với reason + who_loves + who_hates
- Character flaws: ≥3 tier=public_safe ONLY
- Identity default "Reluctant Hero" trừ khi venture context override
- Voice register specific

CRITICAL constraints:
- KHÔNG bịa story không có trong pool
- KHÔNG reference private tier story trong public-safe context
- KHÔNG "mẹ đơn thân", "Perth/Adelaide", em-dash
- KHÔNG vague polarity

Output qua tool submit_character.
"""


SUBMIT_CHARACTER_TOOL = {
    "name": "submit_character",
    "description": "Submit Attractive Character profile 5 elements",
    "input_schema": {
        "type": "object",
        "properties": {
            "founder_name": {"type": "string"},
            "venture": {"type": "string"},
            "identity": {
                "type": "string",
                "description": "Leader | Adventurer | Evangelist | Reluctant Hero",
            },
            "identity_reason": {"type": "string"},
            "backstory_summary": {"type": "string"},
            "backstory_key_moments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "year": {"type": "string"},
                        "moment": {"type": "string"},
                        "tier": {"type": "string"},
                    },
                },
            },
            "parables": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "metaphor": {"type": "string"},
                        "explains": {"type": "string"},
                    },
                },
            },
            "polarity": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "stand": {"type": "string"},
                        "reason": {"type": "string"},
                        "who_loves_it": {"type": "string"},
                        "who_hates_it": {"type": "string"},
                    },
                },
            },
            "character_flaws": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "flaw": {"type": "string"},
                        "vulnerability_context": {"type": "string"},
                        "tier": {"type": "string"},
                    },
                },
            },
            "voice_pronoun_self": {"type": "string"},
            "voice_pronoun_audience": {"type": "string"},
            "voice_tone_signature": {"type": "string"},
            "passes_quality": {"type": "boolean"},
            "summary": {"type": "string"},
        },
        "required": ["founder_name", "venture", "identity", "summary"],
    },
}
