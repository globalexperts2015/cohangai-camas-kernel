"""BC11 prompt template + tool schema, separated for testability."""
from __future__ import annotations

import json
from pathlib import Path


def load_knowledge_base() -> str:
    """Load knowledge_base.md rich content."""
    path = Path(__file__).parent / "knowledge_base.md"
    if not path.exists():
        return ""
    return path.read_text()


def build_canvas_prompt(
    venture: str,
    persona_name: str,
    customer_data: dict,
    canonical_facts: list[dict],
    knowledge_base: str,
) -> str:
    """Build prompt for VPC canvas generation."""
    canonical_summary = "\n".join(
        f"- [{f.get('category', '?')}] {f.get('content', '')[:200]}"
        for f in canonical_facts[:10]
    )

    return f"""Bạn là chuyên gia Value Proposition Canvas (Tròn Vuông) áp dụng cho venture Việt.

# Framework knowledge (rich)

{knowledge_base}

# Context venture
- Venture: {venture}
- Persona target: {persona_name}

# Canonical fact venture (retrieved từ memory)
{canonical_summary}

# Customer data input
{json.dumps(customer_data, ensure_ascii=False, indent=2)[:2000]}

# Task

Build Tròn Vuông VPC canvas đầy đủ 6 component cho persona "{persona_name}" của venture "{venture}".

Quality requirements (per knowledge_base.md section 5):
- 6 component đầy đủ
- Jobs có ≥2 functional + ≥1 social + ≥1 emotional
- Pains có ≥2 trong mỗi 4 loại (Functional/Social/Emotional/Ancillary)
- Gains có ≥1 trong mỗi 4 loại (Required/Expected/Desired/Unexpected)
- Mỗi Pain có ≥1 Pain Reliever (no orphan)
- Mỗi Required + Expected Gain có ≥1 Gain Creator
- Fit score ≥80
- KHÔNG generic, MUST cụ thể với data input
- KHÔNG dùng dấu em-dash (—)
- KHÔNG dùng "mẹ đơn thân", "Perth/Adelaide/Gold Coast"

Reference 3 chân dung Anna canonical (Nhân viên VP / Mẹ bỉm sữa / Chủ shop) trong knowledge_base.md nếu persona match.

Output qua tool submit_canvas. Detect orphan_pains + orphan_gains nếu có.
"""


SUBMIT_CANVAS_TOOL = {
    "name": "submit_canvas",
    "description": "Submit Tròn Vuông VPC canvas 6 component (flat schema for LLM compliance)",
    "input_schema": {
        "type": "object",
        "properties": {
            "persona_name": {"type": "string"},
            "venture": {"type": "string"},
            "jobs_functional": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Functional jobs cụ thể, có timeline/KPI (≥2)",
            },
            "jobs_social": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Social jobs về status/image (≥1)",
            },
            "jobs_emotional": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Emotional jobs về cảm giác (≥1)",
            },
            "pains_functional": {"type": "array", "items": {"type": "string"}},
            "pains_social": {"type": "array", "items": {"type": "string"}},
            "pains_emotional": {"type": "array", "items": {"type": "string"}},
            "pains_ancillary": {"type": "array", "items": {"type": "string"}},
            "barrier_time": {"type": "string"},
            "barrier_money": {"type": "string"},
            "barrier_skills": {"type": "string"},
            "risk_financial": {"type": "string"},
            "risk_social": {"type": "string"},
            "risk_time": {"type": "string"},
            "gains_required": {"type": "array", "items": {"type": "string"}},
            "gains_expected": {"type": "array", "items": {"type": "string"}},
            "gains_desired": {"type": "array", "items": {"type": "string"}},
            "gains_unexpected": {"type": "array", "items": {"type": "string"}},
            "products_services": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Vuông: list sản phẩm/dịch vụ",
            },
            "pain_relievers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "feature": {"type": "string"},
                        "addresses_pain": {"type": "string"},
                    },
                },
                "description": "Vuông: pain relievers (≥3, mỗi pain critical phải có)",
            },
            "gain_creators": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "feature": {"type": "string"},
                        "creates_gain": {"type": "string"},
                    },
                },
                "description": "Vuông: gain creators (≥2, required/expected gains phải có)",
            },
            "fit_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "orphan_pains": {"type": "array", "items": {"type": "string"}},
            "orphan_gains": {"type": "array", "items": {"type": "string"}},
            "anna_persona_match": {
                "type": "string",
                "description": "nhan_vien_vp | me_bim_sua | chu_shop | custom | none",
            },
            "passes_quality": {"type": "boolean"},
            "summary": {"type": "string"},
        },
        "required": ["persona_name", "venture", "jobs_functional", "pains_functional", "products_services", "pain_relievers", "gain_creators", "fit_score", "summary"],
    },
}
