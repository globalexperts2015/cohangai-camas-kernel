"""BC13 prompt template + tool schema."""
from __future__ import annotations

import json
from pathlib import Path


def load_knowledge_base() -> str:
    path = Path(__file__).parent / "knowledge_base.md"
    if not path.exists():
        return ""
    return path.read_text()


def build_pain_prompt(pain_text: str, customer_meta: dict, context_data: dict, knowledge_base: str) -> str:
    return f"""Bạn là chuyên gia Pain System theo CIS Module 3 Anna Đào Thị Hằng + Hormozi Value Equation + Dan Lok Pain principle.

# Knowledge base (full framework)

{knowledge_base}

# Customer meta
{json.dumps(customer_meta, ensure_ascii=False)}

# Pain text (từ conversation/feedback/DM)
{pain_text[:3000]}

# Additional context
{json.dumps(context_data, ensure_ascii=False, indent=2)[:1500]}

# Task

Phân tích pain customer + score severity:

Quality requirements:
- Identify TẤT CẢ pain explicit trong text (không bỏ sót)
- Score severity 1-10/10 cho mỗi pain (per knowledge_base section 4)
- Classify vào 4 loại (Functional/Social/Emotional/Ancillary)
- Detect 3 Rào cản (Time/Money/Skills) nếu mention
- Detect 3 Rủi ro (Financial/Social/Time) nếu mention
- Pick TOP 3 critical theo section 9 (balance 4 loại, không chỉ severity)
- Apply Urgency Rank Decision Logic section 8
- VERBATIM QUOTE từ pain text mỗi khi có (không LLM imagine)

KHÔNG bịa pain không có trong text. KHÔNG over-assign severity 10/10 cho mọi pain.

Output qua tool submit_pain_matrix.
"""


SUBMIT_PAIN_MATRIX_TOOL = {
    "name": "submit_pain_matrix",
    "description": "Submit Pain matrix 4 loại × severity + barriers + risks + urgency",
    "input_schema": {
        "type": "object",
        "properties": {
            "pains_by_type": {
                "type": "object",
                "properties": {
                    "functional": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "pain": {"type": "string"},
                                "severity": {"type": "integer", "minimum": 1, "maximum": 10},
                                "quote": {"type": "string", "description": "Verbatim quote từ pain text"},
                            },
                            "required": ["pain", "severity"],
                        },
                    },
                    "social": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "pain": {"type": "string"},
                                "severity": {"type": "integer", "minimum": 1, "maximum": 10},
                                "quote": {"type": "string"},
                            },
                            "required": ["pain", "severity"],
                        },
                    },
                    "emotional": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "pain": {"type": "string"},
                                "severity": {"type": "integer", "minimum": 1, "maximum": 10},
                                "quote": {"type": "string"},
                            },
                            "required": ["pain", "severity"],
                        },
                    },
                    "ancillary": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "pain": {"type": "string"},
                                "severity": {"type": "integer", "minimum": 1, "maximum": 10},
                                "quote": {"type": "string"},
                            },
                            "required": ["pain", "severity"],
                        },
                    },
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
            "top_3_critical": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "pain": {"type": "string"},
                        "severity": {"type": "integer", "minimum": 1, "maximum": 10},
                        "type": {"type": "string", "enum": ["functional", "social", "emotional", "ancillary"]},
                    },
                    "required": ["pain", "severity", "type"],
                },
            },
            "max_severity": {"type": "integer", "minimum": 1, "maximum": 10},
            "average_severity": {"type": "number", "minimum": 1, "maximum": 10},
            "type_distribution": {
                "type": "object",
                "description": "Count per loại",
                "properties": {
                    "functional_count": {"type": "integer"},
                    "social_count": {"type": "integer"},
                    "emotional_count": {"type": "integer"},
                    "ancillary_count": {"type": "integer"},
                },
            },
            "urgency_rank": {
                "type": "string",
                "enum": ["URGENT", "WARM", "COLD"],
            },
            "deadline_detected": {
                "type": "string",
                "description": "Deadline customer mentioned nếu có (vd: 'trong 30 ngày', '3 tháng')",
            },
            "recommended_action": {
                "type": "string",
                "description": "Action recommended theo Urgency Rank Decision section 8",
            },
            "summary": {"type": "string"},
        },
        "required": ["pains_by_type", "top_3_critical", "max_severity", "urgency_rank", "summary"],
    },
}
