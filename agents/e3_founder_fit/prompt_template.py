"""Prompt + tool schema cho E3 Founder Fit Engine.

BreakoutOS CHỌN module Engine 1: đánh giá mức độ phù hợp giữa founder và
opportunity hypothesis. Stack: Opus 4.7, ~30s.

Input:
- founder_profile (dict): experience_years + skills[] + expertise + personal_story
  + achievements[] + network + assets + existing_content + existing_customers
- opportunity_hypothesis (str): mô tả cơ hội đang đánh giá

Output: founder_fit_score 0-100 + 8 sub-scores + founder_profile_report markdown
"""
from __future__ import annotations

import json
from typing import Any


SUBMIT_FOUNDER_FIT_TOOL: dict[str, Any] = {
    "name": "submit_founder_fit",
    "description": (
        "Submit Founder Fit Score 0-100 + 8 sub-scores + Founder Profile Report. "
        "Đánh giá HONEST mức độ phù hợp giữa founder và opportunity. "
        "KHÔNG khen sáo rỗng. Stick với evidence trong founder_profile."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "founder_fit_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "Weighted average của 8 sub-scores, làm tròn integer.",
            },
            "verdict": {
                "type": "string",
                "enum": ["EXCELLENT_FIT", "STRONG_FIT", "MODERATE_FIT", "WEAK_FIT", "POOR_FIT"],
                "description": "EXCELLENT 90+, STRONG 75-89, MODERATE 55-74, WEAK 35-54, POOR <35",
            },
            "sub_scores": {
                "type": "object",
                "properties": {
                    "experience_match": {"type": "integer", "minimum": 0, "maximum": 100},
                    "skill_match": {"type": "integer", "minimum": 0, "maximum": 100},
                    "expertise_match": {"type": "integer", "minimum": 0, "maximum": 100},
                    "story_strength": {"type": "integer", "minimum": 0, "maximum": 100},
                    "network_strength": {"type": "integer", "minimum": 0, "maximum": 100},
                    "asset_strength": {"type": "integer", "minimum": 0, "maximum": 100},
                    "content_strength": {"type": "integer", "minimum": 0, "maximum": 100},
                    "customer_list_strength": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": [
                    "experience_match", "skill_match", "expertise_match",
                    "story_strength", "network_strength", "asset_strength",
                    "content_strength", "customer_list_strength",
                ],
            },
            "strengths": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 5,
                "description": "2-5 điểm mạnh CỤ THỂ của founder cho opportunity này. Quote evidence từ profile.",
            },
            "gaps": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 5,
                "description": "2-5 gap cụ thể founder cần fill (skill, network, asset chưa có).",
            },
            "unfair_advantages": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
                "description": "Tối đa 3 unfair advantage founder có mà người khác KHÔNG dễ copy.",
            },
            "founder_profile_report": {
                "type": "string",
                "description": (
                    "Báo cáo markdown 400-700 từ tiếng Việt. Cấu trúc: ## Tóm tắt + "
                    "## Điểm mạnh (kèm evidence) + ## Gap (kèm mitigation) + "
                    "## Lợi thế cạnh tranh + ## Verdict. KHÔNG dùng dấu em-dash."
                ),
            },
        },
        "required": [
            "founder_fit_score", "verdict", "sub_scores",
            "strengths", "gaps", "founder_profile_report",
        ],
    },
}


def build_founder_fit_prompt(
    student_id: str,
    founder_profile: dict[str, Any],
    opportunity_hypothesis: str,
    lifestyle_choice: str = "solo_ai",
) -> str:
    """Compose prompt cho Founder Fit Engine."""
    profile_json = json.dumps(founder_profile, ensure_ascii=False, indent=2)[:3500]
    opportunity_clean = (opportunity_hypothesis or "").strip()[:1500]

    return f"""Bạn là E3 Founder Fit Engine trong BreakoutOS CHỌN module.

Nhiệm vụ: Đánh giá HONEST mức độ phù hợp giữa founder và opportunity hypothesis dưới đây. Score 0-100.

# Student ID
{student_id}

# Founder Profile
```json
{profile_json}
```

# Opportunity Hypothesis (cơ hội founder đang cân nhắc bán)
{opportunity_clean}

# Lifestyle Target
{lifestyle_choice} (solo_ai = 1 người + AI <30h/tuần, lean_team = 3-5 nhân viên <40h, growth_team = 10+ nhân viên 50h+)

# Rules đánh giá nghiêm khắc

1. KHÔNG khen sáo rỗng. Mỗi strength/gap phải kèm EVIDENCE cụ thể từ profile.
2. Score 100 = founder có TẤT CẢ experience + skill + network + content + customer cho ngách này. Hiếm có.
3. Score 70-85 = founder fit tốt, cần bù 1-2 gap nhỏ.
4. Score 40-60 = founder cần học/build nhiều trước khi launch.
5. Score <40 = mismatch nghiêm trọng, recommend pivot.
6. 8 sub-scores:
   - experience_match: kinh nghiệm trong lĩnh vực opportunity này
   - skill_match: kỹ năng technical/sales/marketing cần có
   - expertise_match: chuyên môn sâu (vs surface knowledge)
   - story_strength: câu chuyện cá nhân tạo trust với khách target
   - network_strength: connection sẵn có trong ngành
   - asset_strength: tài sản hữu hình + vô hình (vốn, IP, brand)
   - content_strength: nội dung đã publish (FB posts, video, blog)
   - customer_list_strength: contact list hiện có fit với target
7. unfair_advantages CHỈ liệt kê nếu founder THẬT SỰ có (KHÔNG bịa).
8. Markdown report 400-700 từ, tiếng Việt thuần, KHÔNG em-dash, câu ngắn 5-15 từ.

Output qua tool submit_founder_fit, đầy đủ 8 sub-scores + strengths + gaps + verdict + report.
"""
