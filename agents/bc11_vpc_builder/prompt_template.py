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
    "description": "Submit Tròn Vuông VPC canvas 6 component, schema-validated production-grade.",
    "input_schema": {
        "type": "object",
        "properties": {
            "persona_name": {"type": "string"},
            "venture": {"type": "string"},
            "trong_khach_hang": {
                "type": "object",
                "description": "Trục Tròn - Customer side",
                "properties": {
                    "jobs": {
                        "type": "object",
                        "properties": {
                            "functional": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 2,
                                "description": "Min 2 functional jobs cụ thể, có timeline/KPI",
                            },
                            "social": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                            },
                            "emotional": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                            },
                        },
                        "required": ["functional", "social", "emotional"],
                    },
                    "pains": {
                        "type": "object",
                        "properties": {
                            "functional": {"type": "array", "items": {"type": "string"}, "minItems": 2},
                            "social": {"type": "array", "items": {"type": "string"}, "minItems": 2},
                            "emotional": {"type": "array", "items": {"type": "string"}, "minItems": 2},
                            "ancillary": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["functional", "social", "emotional"],
                    },
                    "barriers": {
                        "type": "object",
                        "properties": {
                            "time": {"type": "string"},
                            "money": {"type": "string"},
                            "skills": {"type": "string"},
                        },
                    },
                    "risks": {
                        "type": "object",
                        "properties": {
                            "financial": {"type": "string"},
                            "social": {"type": "string"},
                            "time": {"type": "string"},
                        },
                    },
                    "gains": {
                        "type": "object",
                        "properties": {
                            "required": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                            "expected": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                            "desired": {"type": "array", "items": {"type": "string"}},
                            "unexpected": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["required", "expected"],
                    },
                },
                "required": ["jobs", "pains", "gains"],
            },
            "vuong_san_pham": {
                "type": "object",
                "description": "Trục Vuông - Product side",
                "properties": {
                    "products_services": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "pain_relievers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "feature": {"type": "string"},
                                "addresses_pain": {"type": "string"},
                            },
                            "required": ["feature", "addresses_pain"],
                        },
                        "minItems": 3,
                    },
                    "gain_creators": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "feature": {"type": "string"},
                                "creates_gain": {"type": "string"},
                            },
                            "required": ["feature", "creates_gain"],
                        },
                        "minItems": 2,
                    },
                },
                "required": ["products_services", "pain_relievers", "gain_creators"],
            },
            "fit_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "Mức fit Tròn ↔ Vuông. 100=mọi pair perfect, giảm cho mỗi orphan",
            },
            "orphan_pains": {
                "type": "array",
                "description": "Pain không có Pain Reliever match",
                "items": {"type": "string"},
            },
            "orphan_gains": {
                "type": "array",
                "description": "Required/Expected Gain không có Gain Creator",
                "items": {"type": "string"},
            },
            "anna_persona_match": {
                "type": "string",
                "enum": ["nhan_vien_vp", "me_bim_sua", "chu_shop", "custom", "none"],
                "description": "Match với 1 trong 3 chân dung canonical Anna nếu có",
            },
            "summary": {"type": "string"},
            "quality_check": {
                "type": "object",
                "properties": {
                    "has_em_dash": {"type": "boolean"},
                    "has_forbidden_term": {"type": "boolean"},
                    "is_generic": {"type": "boolean"},
                    "passes_quality": {"type": "boolean"},
                },
            },
        },
        "required": ["persona_name", "venture", "trong_khach_hang", "vuong_san_pham", "fit_score", "summary"],
    },
}
