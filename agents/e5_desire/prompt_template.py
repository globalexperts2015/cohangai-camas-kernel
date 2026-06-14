"""Prompt + tool schema cho E5 Desire Engine.

BreakoutOS CHỌN module Engine 3: Tìm hiểu khách thực sự MUỐN điều gì.
KHÔNG chỉ pain (Engine 2). Mà còn mong muốn, khát vọng, danh tính, địa vị, lifestyle.

Output: 5-dimension Desire Map + Identity Statement + Status Symbols.
"""
from __future__ import annotations

import json
from typing import Any


SUBMIT_DESIRE_TOOL: dict[str, Any] = {
    "name": "submit_desire_map",
    "description": (
        "Submit Desire Map 5 chiều: Mong muốn + Khát vọng + Danh tính + Địa vị + Lối sống mong muốn. "
        "Pull TỪ customer hypothesis. KHÔNG generic, phải cá nhân hoá."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "desires": {
                "type": "object",
                "properties": {
                    "surface_wants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 3,
                        "maxItems": 5,
                        "description": "3-5 thứ khách NÓI họ muốn (surface level).",
                    },
                    "deep_aspirations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 2,
                        "maxItems": 4,
                        "description": "2-4 khát vọng sâu thật sự (under surface wants).",
                    },
                    "identity": {
                        "type": "object",
                        "properties": {
                            "current_identity": {"type": "string", "description": "Khách thấy mình là ai HIỆN TẠI"},
                            "desired_identity": {"type": "string", "description": "Khách muốn trở thành ai"},
                            "transformation_phrase": {"type": "string", "description": "Từ X → trở thành Y, 1 câu ngắn"},
                        },
                        "required": ["current_identity", "desired_identity", "transformation_phrase"],
                    },
                    "social_status": {
                        "type": "object",
                        "properties": {
                            "want_to_be_seen_as": {"type": "string"},
                            "want_to_avoid_being_seen_as": {"type": "string"},
                            "status_symbols": {
                                "type": "array",
                                "items": {"type": "string"},
                                "maxItems": 4,
                                "description": "Vật/hành vi khách dùng để show status",
                            },
                        },
                        "required": ["want_to_be_seen_as", "want_to_avoid_being_seen_as", "status_symbols"],
                    },
                    "lifestyle_desired": {
                        "type": "object",
                        "properties": {
                            "daily_life": {"type": "string", "description": "1 ngày lý tưởng của khách"},
                            "freedom_dimensions": {
                                "type": "array",
                                "items": {"type": "string", "enum": ["time", "money", "location", "people", "skill"]},
                                "description": "Khách priority freedom dimension nào",
                            },
                            "tradeoffs_accepted": {"type": "string", "description": "Khách sẵn sàng đánh đổi gì"},
                        },
                        "required": ["daily_life", "freedom_dimensions", "tradeoffs_accepted"],
                    },
                },
                "required": ["surface_wants", "deep_aspirations", "identity", "social_status", "lifestyle_desired"],
            },
            "desire_strength_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "Tổng strength of desires 0-100. Cao = khách đầu tư mạnh để đạt.",
            },
            "buying_trigger_phrase": {
                "type": "string",
                "description": "1 câu KHÁCH SẼ TỰ NÓI khi quyết định mua. Pull từ identity + aspirations.",
            },
            "desire_report": {
                "type": "string",
                "description": (
                    "Báo cáo markdown 400-600 từ tiếng Việt. ## Surface wants vs deep aspirations + "
                    "## Identity transformation + ## Social status + ## Lifestyle mong muốn + "
                    "## Buying trigger phrase. KHÔNG em-dash."
                ),
            },
        },
        "required": ["desires", "desire_strength_score", "buying_trigger_phrase", "desire_report"],
    },
}


def build_desire_prompt(student_id: str, customer_hypothesis: str, problem_map: dict[str, Any]) -> str:
    customer_clean = (customer_hypothesis or "").strip()[:2000]
    problem_json = json.dumps(problem_map or {}, ensure_ascii=False, indent=2)[:2500]

    return f"""Bạn là E5 Desire Engine trong BreakoutOS CHỌN module.

Nhiệm vụ: Tìm hiểu khách hàng thật sự MUỐN gì (không chỉ pain). Output Desire Map 5 chiều.

# Student ID
{student_id}

# Customer Hypothesis
{customer_clean}

# Problem Map từ Engine 2 (input chain)
```json
{problem_json}
```

# Framework

Khách không mua sản phẩm. Khách mua phiên bản mới của chính họ.

5 chiều desire:
1. Surface wants: khách NÓI họ muốn (cụ thể, thường functional)
2. Deep aspirations: thật sự khao khát sâu (emotional, identity-level)
3. Identity: từ X → trở thành Y
4. Social status: được nhìn nhận thế nào, tránh bị thấy thế nào
5. Lifestyle: 1 ngày lý tưởng, freedom dimensions ưu tiên, tradeoff chấp nhận

# Rules

1. Pull TỪ customer_hypothesis + problem_map. KHÔNG generic.
2. surface_wants vs deep_aspirations PHẢI khác nhau. Surface là cái khách NÓI, deep là cái khách CẦN.
3. identity_transformation_phrase phải ngắn, có cảm xúc, dùng được trong sales copy.
4. buying_trigger_phrase = câu KHÁCH TỰ NÓI lúc click mua (không phải pitch của founder).
5. Tiếng Việt thuần, câu ngắn 5-15 từ, KHÔNG em-dash.

Output qua tool submit_desire_map đầy đủ 4 fields.
"""
