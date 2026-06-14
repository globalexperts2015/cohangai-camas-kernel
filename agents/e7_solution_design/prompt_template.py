"""Prompt + tool schema cho E7 Solution Design Engine.

BreakoutOS CHỌN module Engine 5: Đề xuất loại sản phẩm phù hợp nhất.
7 product types: physical, digital, service, coaching, membership, saas, marketplace.
Hay combo nhiều loại.
"""
from __future__ import annotations

import json
from typing import Any


PRODUCT_TYPES = [
    "physical", "digital", "service", "coaching",
    "membership", "saas", "marketplace",
]


SUBMIT_SOLUTION_DESIGN_TOOL: dict[str, Any] = {
    "name": "submit_solution_design",
    "description": (
        "Submit Solution Design: 7 product types với fit score 0-100 mỗi loại + "
        "primary + secondary recommendation + value ladder gợi ý + delivery format."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "product_type_fit": {
                "type": "object",
                "properties": {
                    "physical": {"type": "integer", "minimum": 0, "maximum": 100},
                    "digital": {"type": "integer", "minimum": 0, "maximum": 100},
                    "service": {"type": "integer", "minimum": 0, "maximum": 100},
                    "coaching": {"type": "integer", "minimum": 0, "maximum": 100},
                    "membership": {"type": "integer", "minimum": 0, "maximum": 100},
                    "saas": {"type": "integer", "minimum": 0, "maximum": 100},
                    "marketplace": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": PRODUCT_TYPES,
            },
            "primary_recommendation": {
                "type": "object",
                "properties": {
                    "product_type": {"type": "string", "enum": PRODUCT_TYPES},
                    "rationale": {"type": "string"},
                    "estimated_price_range_vnd": {
                        "type": "object",
                        "properties": {
                            "low": {"type": "integer"},
                            "mid": {"type": "integer"},
                            "high": {"type": "integer"},
                        },
                        "required": ["low", "mid", "high"],
                    },
                    "delivery_format": {"type": "string"},
                    "time_to_mvp_weeks": {"type": "integer", "minimum": 1, "maximum": 52},
                },
                "required": ["product_type", "rationale", "estimated_price_range_vnd", "delivery_format", "time_to_mvp_weeks"],
            },
            "secondary_recommendation": {
                "type": "object",
                "properties": {
                    "product_type": {"type": "string", "enum": PRODUCT_TYPES},
                    "rationale": {"type": "string"},
                    "stack_with_primary": {"type": "boolean", "description": "True nếu nên combo với primary"},
                },
                "required": ["product_type", "rationale", "stack_with_primary"],
            },
            "anti_recommendations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "product_type": {"type": "string", "enum": PRODUCT_TYPES},
                        "why_not": {"type": "string"},
                    },
                    "required": ["product_type", "why_not"],
                },
                "minItems": 1,
                "maxItems": 3,
                "description": "1-3 product type TUYỆT ĐỐI KHÔNG nên bán cho persona này.",
            },
            "solution_design_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "Tổng confidence của solution design 0-100.",
            },
            "solution_report": {
                "type": "string",
                "description": (
                    "Báo cáo markdown 400-700 từ tiếng Việt. ## 7 product type fit + "
                    "## Primary recommendation + ## Secondary + ## Anti-recommendations + "
                    "## Delivery format + ## Price strategy. KHÔNG em-dash."
                ),
            },
        },
        "required": [
            "product_type_fit", "primary_recommendation", "secondary_recommendation",
            "anti_recommendations", "solution_design_score", "solution_report",
        ],
    },
}


def build_solution_design_prompt(
    student_id: str,
    founder_profile: dict[str, Any],
    customer_hypothesis: str,
    problem_map: dict[str, Any],
    desire_map: dict[str, Any],
    lifestyle_choice: str = "solo_ai",
) -> str:
    fp_json = json.dumps(founder_profile or {}, ensure_ascii=False, indent=2)[:2000]
    cust_clean = (customer_hypothesis or "").strip()[:1500]
    prob_json = json.dumps(problem_map or {}, ensure_ascii=False, indent=2)[:1500]
    desire_json = json.dumps(desire_map or {}, ensure_ascii=False, indent=2)[:1500]

    return f"""Bạn là E7 Solution Design Engine trong BreakoutOS CHỌN module.

Nhiệm vụ: Đề xuất 1 primary product type + 1 secondary + 1-3 anti-recommendation cho founder. 7 loại: physical, digital, service, coaching, membership, saas, marketplace.

# Student ID
{student_id}

# Founder Profile
```json
{fp_json}
```

# Customer Hypothesis
{cust_clean}

# Problem Map (Engine 2)
```json
{prob_json}
```

# Desire Map (Engine 3)
```json
{desire_json}
```

# Lifestyle Choice
{lifestyle_choice} (solo_ai / lean_team / growth_team)

# Framework đánh giá fit per product type

1. Physical: vốn cao, kho hàng, vận chuyển, fit founder có brand + supply chain
2. Digital: low margin scale, fit founder có audience + content skill
3. Service: high touch, fit founder có expertise cụ thể, scale chậm
4. Coaching: 1-to-many, high margin, fit founder có proof + audience
5. Membership: recurring revenue, fit founder có community + content engine
6. SaaS: code-heavy, fit technical founder + B2B problem
7. Marketplace: 2-side liquidity, fit founder có network 2 phía

# Rules

1. Fit score MỖI loại 0-100 phải honest. Founder không phải technical = SaaS thấp.
2. Primary phải match Founder Fit + Lifestyle Choice + Pain Scale.
3. Anti-recommendation explicit để founder TRÁNH waste vốn vào hướng sai.
4. Price range VND realistic theo market VN/Úc tuỳ ngách.
5. Time to MVP weeks honest: SaaS 12-26, Coaching 2-4, Physical 8-16.
6. Tiếng Việt thuần, câu ngắn, KHÔNG em-dash.

Output qua tool submit_solution_design đầy đủ 6 fields.
"""
