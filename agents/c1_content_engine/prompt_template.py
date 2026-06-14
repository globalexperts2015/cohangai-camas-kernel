"""Prompt + tool schema for C1 Content Engine.

BreakoutOS v3 Week 5. Generates a LIVE-demo content pack per student
(scope reduced for K2 demo 11/06/2026 to fit max_tokens budget):
- 5 pillars
- 20 reel ideas
- 8 FB posts
- 5 emails
- 5 blog topics
- 3 webinar topics
- 3 lead magnets
- 14-day calendar
- CTA by 5 awareness levels (Schwartz)

Original full pack (100 reel + 30 fb + 30 email + 30 blog + 12 webinar + 4 magnet
+ 30-day calendar) requires ~25K tokens output, exceeds Opus single-call budget.
Full pack runs via multi-call orchestration in production (TODO post-K2).
"""
from __future__ import annotations

import json
from typing import Any


SUBMIT_CONTENT_PACK_TOOL: dict[str, Any] = {
    "name": "submit_content_pack",
    "description": (
        "Submit BreakoutOS v3 content pack (LIVE demo scope): 5 pillars + 20 reel ideas + "
        "8 FB posts + 5 emails + 5 blog topics + 3 webinar topics + 3 lead magnets "
        "+ 14-day calendar + CTA by awareness level. KHÔNG generic, phải tham chiếu "
        "customer profile + offer + voice cụ thể."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pillars": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "core_idea": {"type": "string"},
                        "audience_pain": {"type": "string"},
                        "audience_joy": {"type": "string"},
                    },
                    "required": ["id", "name", "core_idea"],
                },
            },
            "reel_ideas": {
                "type": "array",
                "minItems": 20,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "pillar_id": {"type": "string"},
                        "hook": {"type": "string"},
                        "story": {"type": "string"},
                        "insight": {"type": "string"},
                        "system": {"type": "string"},
                        "cta": {"type": "string"},
                        "format": {"type": "string", "enum": ["15s", "30s", "60s"]},
                    },
                    "required": ["pillar_id", "hook", "story", "insight", "cta"],
                },
            },
            "fb_posts": {
                "type": "array",
                "minItems": 8,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "pillar_id": {"type": "string"},
                        "hook": {"type": "string"},
                        "problem": {"type": "string"},
                        "solution": {"type": "string"},
                        "cta": {"type": "string"},
                        "length_words": {"type": "integer"},
                    },
                    "required": ["pillar_id", "hook", "problem", "solution", "cta"],
                },
            },
            "emails": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "position": {"type": "integer"},
                        "subject": {"type": "string"},
                        "preheader": {"type": "string"},
                        "body_outline": {"type": "string"},
                        "cta": {"type": "string"},
                    },
                    "required": ["position", "subject", "body_outline", "cta"],
                },
            },
            "blog_topics": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "h1": {"type": "string"},
                        "h2_outline": {"type": "array", "items": {"type": "string"}},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                        "search_intent": {"type": "string"},
                    },
                    "required": ["title", "h1", "h2_outline"],
                },
            },
            "webinar_topics": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "hook": {"type": "string"},
                        "big_idea": {"type": "string"},
                        "offer_position": {"type": "string"},
                    },
                    "required": ["title", "hook", "big_idea"],
                },
            },
            "lead_magnets": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "format": {
                            "type": "string",
                            "enum": ["pdf_guide", "mini_course", "template_pack", "quiz"],
                        },
                        "title": {"type": "string"},
                        "audience_segment": {"type": "string"},
                        "content_outline": {"type": "string"},
                        "expected_conversion_rate": {"type": "string"},
                    },
                    "required": ["format", "title", "audience_segment", "content_outline"],
                },
            },
            "calendar_30d": {
                "type": "array",
                "minItems": 14,
                "maxItems": 14,
                "items": {
                    "type": "object",
                    "properties": {
                        "day": {"type": "integer"},
                        "reel_id": {"type": "string"},
                        "fb_post_id": {"type": "string"},
                        "email_id": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["day"],
                },
            },
            "cta_by_awareness": {
                "type": "object",
                "properties": {
                    "unaware": {"type": "string"},
                    "problem_aware": {"type": "string"},
                    "solution_aware": {"type": "string"},
                    "product_aware": {"type": "string"},
                    "most_aware": {"type": "string"},
                },
            },
        },
        "required": [
            "pillars",
            "reel_ideas",
            "fb_posts",
            "emails",
            "blog_topics",
            "webinar_topics",
            "lead_magnets",
            "calendar_30d",
            "cta_by_awareness",
        ],
    },
}


def build_content_prompt(
    student_id: str,
    customer_profile: dict[str, Any],
    offer: dict[str, Any],
    voice_register: str,
    story_pool: list[str],
) -> str:
    """Compose the system+user prompt that drives full content pack generation."""
    profile_json = json.dumps(customer_profile, ensure_ascii=False, indent=2)[:2500]
    offer_json = json.dumps(offer, ensure_ascii=False, indent=2)[:1500]
    story_json = json.dumps(story_pool, ensure_ascii=False, indent=2)[:2000]

    return f"""Bạn là Content Engine của BreakoutOS v3. Nhiệm vụ: sinh full content pack cho học viên {student_id}.

# Customer Profile (TUYỆT ĐỐI tham chiếu, không generic)
{profile_json}

# Offer (TUYỆT ĐỐI tham chiếu, không generic)
{offer_json}

# Voice Register
{voice_register}

# Story Pool (chỉ dùng story THẬT này, không bịa)
{story_json}

# Rules nghiêm khắc

1. TUYỆT ĐỐI KHÔNG dùng từ generic: "khách hàng tiềm năng", "chuyển đổi cao", "ROI tăng", "đột phá", "tối ưu hoá", "khai phóng", "tiên phong".
2. Mỗi reel idea phải reference cụ thể 1 nỗi đau từ customer profile.
3. Mỗi FB post phải solve 1 specific problem từ profile.
4. Email subject phải có specific number hoặc concrete claim.
5. Không có em-dash, không có emoji.
6. Tiếng Việt thuần. Câu ngắn 5-12 từ.
7. Mỗi cái CTA cụ thể, không "tìm hiểu thêm".
8. Story trong reels chỉ pull từ Story Pool.

Output qua tool submit_content_pack với 9 fields đầy đủ. Không thiếu cái nào.
"""
