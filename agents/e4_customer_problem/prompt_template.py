"""Prompt + tool schema cho E4 Customer Problem Engine.

BreakoutOS CHỌN module Engine 2: Pain Map 6 trục mất mát + Pain Scale 1-10
+ Top 3 pain ranked + customer loses if NOT solved.

Inputs:
  - customer_hypothesis (str): mô tả khách target (ai, ở đâu, làm gì)
  - opportunity_hypothesis (str): cơ hội founder đang đánh giá

Output: 6-axis Loss Map + Top 3 Pain + Pain Scale + Pain Score 0-100
"""
from __future__ import annotations

import json
from typing import Any


SUBMIT_CUSTOMER_PROBLEM_TOOL: dict[str, Any] = {
    "name": "submit_customer_problem",
    "description": (
        "Submit Customer Problem Map: 6-axis loss + Top 3 Pain ranked với Pain Scale 1-10 "
        "+ Problem Strength Score 0-100. Pain 7-10 là pain bán được. KHÔNG bịa pain."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "problem_strength_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "Tổng strength of problem 0-100. 80+ = pain mạnh khách sẵn sàng trả. <50 = pain yếu, không bán được.",
            },
            "verdict": {
                "type": "string",
                "enum": ["CRITICAL_PAIN", "STRONG_PAIN", "MODERATE_PAIN", "WEAK_PAIN", "NO_PAIN"],
            },
            "customer_definition": {
                "type": "object",
                "properties": {
                    "who": {"type": "string", "description": "1 câu mô tả khách cụ thể"},
                    "where": {"type": "string", "description": "Họ ở đâu, làm gì"},
                    "current_state": {"type": "string", "description": "Tình trạng hiện tại"},
                },
                "required": ["who", "where", "current_state"],
            },
            "top_3_pains": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "rank": {"type": "integer", "minimum": 1, "maximum": 3},
                        "pain_statement": {"type": "string"},
                        "pain_scale": {"type": "integer", "minimum": 1, "maximum": 10},
                        "evidence": {"type": "string", "description": "Tại sao tin pain này có thật"},
                        "frequency": {"type": "string", "enum": ["daily", "weekly", "monthly", "occasional"]},
                    },
                    "required": ["rank", "pain_statement", "pain_scale", "evidence", "frequency"],
                },
            },
            "loss_map_6_axes": {
                "type": "object",
                "description": "Khách mất gì nếu KHÔNG giải quyết. Mỗi trục: severity 0-10 + statement.",
                "properties": {
                    "money_loss": {
                        "type": "object",
                        "properties": {
                            "severity": {"type": "integer", "minimum": 0, "maximum": 10},
                            "statement": {"type": "string"},
                        },
                        "required": ["severity", "statement"],
                    },
                    "time_loss": {
                        "type": "object",
                        "properties": {
                            "severity": {"type": "integer", "minimum": 0, "maximum": 10},
                            "statement": {"type": "string"},
                        },
                        "required": ["severity", "statement"],
                    },
                    "opportunity_loss": {
                        "type": "object",
                        "properties": {
                            "severity": {"type": "integer", "minimum": 0, "maximum": 10},
                            "statement": {"type": "string"},
                        },
                        "required": ["severity", "statement"],
                    },
                    "health_loss": {
                        "type": "object",
                        "properties": {
                            "severity": {"type": "integer", "minimum": 0, "maximum": 10},
                            "statement": {"type": "string"},
                        },
                        "required": ["severity", "statement"],
                    },
                    "relationship_loss": {
                        "type": "object",
                        "properties": {
                            "severity": {"type": "integer", "minimum": 0, "maximum": 10},
                            "statement": {"type": "string"},
                        },
                        "required": ["severity", "statement"],
                    },
                    "confidence_loss": {
                        "type": "object",
                        "properties": {
                            "severity": {"type": "integer", "minimum": 0, "maximum": 10},
                            "statement": {"type": "string"},
                        },
                        "required": ["severity", "statement"],
                    },
                },
                "required": ["money_loss", "time_loss", "opportunity_loss", "health_loss", "relationship_loss", "confidence_loss"],
            },
            "willingness_to_pay_signal": {
                "type": "string",
                "enum": ["HIGH", "MEDIUM", "LOW", "UNKNOWN"],
                "description": "HIGH = khách đã trả tiền cho solution alternative. UNKNOWN = chưa có evidence.",
            },
            "customer_problem_report": {
                "type": "string",
                "description": (
                    "Báo cáo markdown 400-700 từ tiếng Việt. ## Khách là ai + ## Top 3 nỗi đau + "
                    "## Khách mất gì nếu không fix + ## Willingness to pay + ## Verdict. KHÔNG em-dash."
                ),
            },
        },
        "required": [
            "problem_strength_score", "verdict", "customer_definition",
            "top_3_pains", "loss_map_6_axes", "willingness_to_pay_signal",
            "customer_problem_report",
        ],
    },
}


def build_customer_problem_prompt(
    student_id: str,
    customer_hypothesis: str,
    opportunity_hypothesis: str,
) -> str:
    customer_clean = (customer_hypothesis or "").strip()[:2000]
    opportunity_clean = (opportunity_hypothesis or "").strip()[:1500]

    return f"""Bạn là E4 Customer Problem Engine trong BreakoutOS CHỌN module.

Nhiệm vụ: Đào sâu vấn đề khách hàng thật của opportunity dưới đây. Output Pain Map 6 trục + Top 3 Pain với Pain Scale 1-10.

# Student ID
{student_id}

# Customer Hypothesis (khách target)
{customer_clean}

# Opportunity Hypothesis (sản phẩm/dịch vụ founder đang cân nhắc)
{opportunity_clean}

# Framework đánh giá

1. Pain Scale 1-10:
   - 1-3: bất tiện nhỏ, khách không trả tiền
   - 4-6: pain rõ nhưng khách chịu được
   - 7-8: pain ảnh hưởng cuộc sống/business, khách sẵn sàng trả
   - 9-10: pain critical, khách trả bất kỳ giá nào (nhưng ít gặp)

2. 6 trục mất mát mỗi pain gây ra:
   - Tiền: doanh thu mất, chi phí phát sinh
   - Thời gian: giờ phí, năng suất giảm
   - Cơ hội: deal mất, market share, mất khách
   - Sức khỏe: stress, bệnh, kiệt sức
   - Quan hệ: gia đình, partner, đối tác
   - Tự tin: identity, hình ảnh bản thân, danh tiếng

3. Willingness to pay HIGH chỉ nếu có evidence khách ĐÃ trả cho alternative.

# Rules nghiêm khắc

1. Stick với customer_hypothesis. KHÔNG bịa pain mà customer không có.
2. Mỗi pain phải kèm EVIDENCE thực tế (insight từ hypothesis).
3. Pain Scale 9-10 chỉ cấp nếu pain CRITICAL (chết người, phá sản, mất gia đình).
4. Loss_map_6_axes severity 0-10 honest. KHÔNG inflate.
5. Tiếng Việt thuần, câu ngắn 5-15 từ, KHÔNG em-dash.

Output qua tool submit_customer_problem đầy đủ 7 fields.
"""
