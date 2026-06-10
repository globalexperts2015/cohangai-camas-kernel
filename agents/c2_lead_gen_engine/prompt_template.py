"""C2 Lead Gen Engine prompt template + tool schema (flat).

Generate 30-day Lead Generation plan + 5 channel strategy + 4 lead magnets
adapted from Content Engine output + tagging logic + funnel map for BreakoutOS v3
Week 6 (Cohort 1 students).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def load_channel_strategies() -> dict[str, str]:
    """Load all 5 channel strategy MD files into a dict {channel_key: content}."""
    base = Path(__file__).parent / "channel_strategies"
    out: dict[str, str] = {}
    for key in ["fb_personal", "community", "tiktok_reels", "youtube", "seo_blog"]:
        path = base / f"{key}.md"
        if path.exists():
            out[key] = path.read_text()
        else:
            out[key] = ""
    return out


def load_lead_magnet_templates() -> dict[str, str]:
    """Load all 4 lead magnet template MD files into a dict {format_key: content}."""
    base = Path(__file__).parent / "lead_magnet_templates"
    out: dict[str, str] = {}
    for key in ["pdf_guide", "mini_course", "template_pack", "quiz"]:
        path = base / f"{key}.md"
        if path.exists():
            out[key] = path.read_text()
        else:
            out[key] = ""
    return out


def _format_channel_kb(channel_kb: dict[str, str]) -> str:
    """Render channel KB sections, truncate mỗi cái 1200 char tránh prompt nổ."""
    chunks: list[str] = []
    for k, v in channel_kb.items():
        chunks.append(f"## {k}\n\n{v[:1200]}")
    return "\n\n".join(chunks)


def _format_magnet_kb(magnet_kb: dict[str, str]) -> str:
    chunks: list[str] = []
    for k, v in magnet_kb.items():
        chunks.append(f"## {k}\n\n{v[:1000]}")
    return "\n\n".join(chunks)


def build_lead_gen_prompt(
    student_id: str,
    customer_profile: dict,
    content_engine_output: dict,
    student_advantages: dict,
    budget_monthly_vnd: int,
    channel_kb: Optional[dict[str, str]] = None,
    magnet_kb: Optional[dict[str, str]] = None,
) -> str:
    channel_kb = channel_kb or {}
    magnet_kb = magnet_kb or {}
    return f"""Bạn là Lead Gen Engine của BreakoutOS v3.

# Channel knowledge base (5 kênh)

{_format_channel_kb(channel_kb)}

# Lead magnet template knowledge base (4 format)

{_format_magnet_kb(magnet_kb)}

# Student ID
{student_id}

# Customer Profile
{json.dumps(customer_profile, ensure_ascii=False, indent=2)[:2000]}

# Content Engine Output (4 lead magnet ideas + 100 reel + 30 FB + ...)
{json.dumps(content_engine_output, ensure_ascii=False, indent=2)[:2000]}

# Student advantages (audience đã có ở đâu)
{json.dumps(student_advantages, ensure_ascii=False, indent=2)}

# Budget tháng
{budget_monthly_vnd} VND

# Task

1. Chọn 1-3 kênh primary dựa trên Student advantages. Nếu student đã có FB 50K+ friends, ưu tiên fb_personal. Nếu chưa có audience, dùng community + seo_blog (organic cheap).
2. Sinh 30-day daily plan: ngày 1-7 setup, 8-14 content + traffic build, 15-21 lead magnet launch, 22-30 nurture + follow up.
3. Adapt 4 lead magnets từ Content Engine output, mỗi cái có form_fields cụ thể + delivery method.
4. Tagging logic theo source/magnet/channel.
5. Referral strategy với incentive cụ thể.
6. Funnel map 4 stage với conversion benchmark realistic.

# Rules

- KHÔNG generic: không "tăng nhận diện thương hiệu", không "thu hút khách hàng tiềm năng".
- Mỗi action có time investment cụ thể (giờ).
- Daily plan có deliverable cuối ngày.
- Conversion benchmark: 5% landing → email signup, 2% email → buyer typical.
- Pronoun "bạn", tiếng Việt thuần, KHÔNG em-dash.
- Realistic time investment theo budget (founder solo 30-45 tuổi, 4-6 giờ/ngày làm content max).

Output qua tool submit_lead_gen_plan.
"""


SUBMIT_LEAD_GEN_TOOL = {
    "name": "submit_lead_gen_plan",
    "description": "Submit Lead Generation plan: 30-day daily action + 5 channel strategy chọn theo lợi thế học viên + 4 lead magnets adapted from Content Engine + tagging logic + funnel map 4 stage with conversion benchmarks.",
    "input_schema": {
        "type": "object",
        "properties": {
            "primary_channels": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "string",
                    "enum": ["fb_personal", "community", "tiktok_reels", "youtube", "seo_blog"],
                },
            },
            "daily_plan_30d": {
                "type": "array",
                "minItems": 30,
                "maxItems": 30,
                "items": {
                    "type": "object",
                    "properties": {
                        "day": {"type": "integer"},
                        "channel": {"type": "string"},
                        "action": {"type": "string"},
                        "expected_outcome": {"type": "string"},
                        "time_hours": {"type": "number"},
                    },
                    "required": ["day", "channel", "action", "expected_outcome"],
                },
            },
            "lead_magnets_final": {
                "type": "array",
                "minItems": 4,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "format": {"type": "string"},
                        "title": {"type": "string"},
                        "audience_segment": {"type": "string"},
                        "form_fields": {"type": "array", "items": {"type": "string"}},
                        "delivery_method": {"type": "string"},
                        "follow_up_email_sequence": {"type": "string"},
                    },
                    "required": ["format", "title", "audience_segment", "form_fields"],
                },
            },
            "tally_form_specs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "magnet_id": {"type": "string"},
                        "form_title": {"type": "string"},
                        "fields": {"type": "array", "items": {"type": "object"}},
                        "thank_you_page_url": {"type": "string"},
                    },
                },
            },
            "tag_logic": {
                "type": "object",
                "properties": {
                    "by_source": {"type": "object"},
                    "by_magnet": {"type": "object"},
                    "by_channel": {"type": "object"},
                },
            },
            "referral_strategy": {
                "type": "object",
                "properties": {
                    "trigger": {"type": "string"},
                    "incentive": {"type": "string"},
                    "tracking_mechanism": {"type": "string"},
                },
            },
            "funnel_map": {
                "type": "object",
                "properties": {
                    "awareness": {
                        "type": "object",
                        "properties": {
                            "target_volume": {"type": "integer"},
                            "conversion_to_next": {"type": "string"},
                        },
                    },
                    "interest": {
                        "type": "object",
                        "properties": {
                            "target_volume": {"type": "integer"},
                            "conversion_to_next": {"type": "string"},
                        },
                    },
                    "decision": {
                        "type": "object",
                        "properties": {
                            "target_volume": {"type": "integer"},
                            "conversion_to_next": {"type": "string"},
                        },
                    },
                    "action": {
                        "type": "object",
                        "properties": {"target_volume": {"type": "integer"}},
                    },
                },
            },
        },
        "required": [
            "primary_channels",
            "daily_plan_30d",
            "lead_magnets_final",
            "tag_logic",
            "referral_strategy",
            "funnel_map",
        ],
    },
}
