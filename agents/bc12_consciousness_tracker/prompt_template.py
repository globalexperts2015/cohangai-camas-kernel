"""BC12 prompt template + tool schema."""
from __future__ import annotations

import json
from pathlib import Path


def load_knowledge_base() -> str:
    path = Path(__file__).parent / "knowledge_base.md"
    if not path.exists():
        return ""
    return path.read_text()


def build_classify_prompt(messages: list[str], customer_meta: dict, knowledge_base: str) -> str:
    msgs_text = "\n".join(f"- {m[:300]}" for m in messages[:10])
    return f"""Bạn là chuyên gia tâm lý khách hàng theo framework 8 Cấp Ý Thức Eagle Camp Phạm Thành Long.

# Knowledge base (full framework)

{knowledge_base}

# Customer meta
{json.dumps(customer_meta, ensure_ascii=False)}

# Recent messages (latest 10, newest first)
{msgs_text}

# Task

Phân tích messages + meta để xác định cấp ý thức (1-8) của customer.

Quality requirements:
- Pick ĐÚNG 1 cấp chủ đạo (1-8)
- Detect secondary level nếu có dấu hiệu
- Confidence score 0-100 (theo knowledge_base section 5)
- Behavioral indicators verbatim quote từ messages (cite exactly)
- Recommended message register theo knowledge_base section 3
- Detect upgrade signals (cấp X → X+1) nếu có
- Default cấp 3 (Phong kiến) cho new lead không đủ data

Output qua tool submit_classification.
"""


SUBMIT_CLASSIFICATION_TOOL = {
    "name": "submit_classification",
    "description": "Submit consciousness level classification 1-8 (Eagle Camp framework)",
    "input_schema": {
        "type": "object",
        "properties": {
            "primary_level": {
                "type": "integer",
                "minimum": 1,
                "maximum": 8,
            },
            "primary_level_name": {
                "type": "string",
                "enum": ["Bản năng", "Mê tín", "Phong kiến", "Phụng sự", "Lý tưởng", "Trí tuệ", "Từ bi", "Giác ngộ"],
            },
            "secondary_level": {
                "type": "integer",
                "minimum": 1,
                "maximum": 8,
            },
            "confidence": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
            },
            "behavioral_indicators": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "indicator": {"type": "string", "description": "What pattern observed"},
                        "verbatim_quote": {"type": "string", "description": "Exact quote từ message"},
                    },
                },
                "minItems": 1,
            },
            "language_cluster": {
                "type": "string",
                "enum": ["lower_self", "higher_self_begin", "awakened"],
                "description": "Cluster theo knowledge_base section 2",
            },
            "recommended_register": {
                "type": "string",
                "description": "Message register phù hợp cấp (theo section 3 mapping)",
            },
            "sample_headline": {
                "type": "string",
                "description": "Sample headline content cho customer này",
            },
            "upgrade_signals": {
                "type": "array",
                "description": "Dấu hiệu customer đang lên cấp cao hơn (section 4)",
                "items": {"type": "string"},
            },
            "anti_pattern_warning": {
                "type": "string",
                "description": "Cảnh báo nếu over-assign cấp 7-8 không đủ evidence",
            },
            "summary": {"type": "string"},
        },
        "required": ["primary_level", "primary_level_name", "confidence", "behavioral_indicators", "language_cluster", "recommended_register", "summary"],
    },
}
