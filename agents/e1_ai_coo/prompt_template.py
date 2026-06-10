"""Prompt + tool schema for E1 AI COO Dashboard.

Hybrid rule-based + LLM. Rule engine handles deterministic metrics (lead count,
revenue trend, content backlog). LLM only invoked for ambiguous narrative
synthesis: weekly/monthly memo, qualitative red flag rationale.

Style: tiếng Việt, câu ngắn, KHÔNG em-dash, không emoji trừ ⚠️ 🚨 ở red flag.
"""
from __future__ import annotations

import json
from typing import Any


SUBMIT_COO_NARRATIVE_TOOL: dict[str, Any] = {
    "name": "submit_coo_narrative",
    "description": (
        "Submit AI COO narrative synthesis. KHÔNG generic, phải tham chiếu "
        "số liệu thật trong data + chỉ ra 1 root cause + 1 hành động cụ thể "
        "đầu tuần. Tiếng Việt, ngắn, câu sự kiện."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "1 câu tóm tắt trạng thái tuần qua, max 120 ký tự",
            },
            "wins": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {"type": "string"},
                "description": "1-3 điểm sáng concrete, có số liệu",
            },
            "losses": {
                "type": "array",
                "minItems": 0,
                "maxItems": 3,
                "items": {"type": "string"},
                "description": "0-3 điểm cần fix, có số liệu",
            },
            "root_cause": {
                "type": "string",
                "description": "Nguyên nhân gốc của loss lớn nhất, 1 câu",
            },
            "next_week_focus": {
                "type": "string",
                "description": "1 việc duy nhất cần ưu tiên tuần sau, hành động cụ thể",
            },
        },
        "required": ["headline", "wins", "losses", "next_week_focus"],
    },
}


def build_weekly_narrative_prompt(
    student_id: str,
    data: dict[str, Any],
    rule_analysis: dict[str, Any],
) -> str:
    """Build LLM prompt cho weekly narrative synthesis.

    Pre: rule engine đã chạy + có data + rule_analysis. LLM tổng hợp thành
    1 narrative tiếng Việt ngắn (4-5 câu) bằng tool submit_coo_narrative.
    """
    return f"""Bạn là AI COO cho founder solo {student_id}.

Dưới đây là báo cáo TUẦN tóm tắt số liệu thật từ database:

DATA 7 NGÀY:
{json.dumps(data, ensure_ascii=False, indent=2, default=str)[:4000]}

RULE ANALYSIS (rule engine đã chạy):
{json.dumps(rule_analysis, ensure_ascii=False, indent=2, default=str)[:2000]}

NHIỆM VỤ: Gọi tool submit_coo_narrative trả về:
- headline: 1 câu trạng thái tuần qua
- wins: 1-3 điểm sáng có số liệu cụ thể từ DATA
- losses: 0-3 điểm cần fix có số liệu cụ thể
- root_cause: nguyên nhân gốc của loss lớn nhất, 1 câu
- next_week_focus: 1 việc DUY NHẤT tuần sau, hành động cụ thể

YÊU CẦU:
- Tiếng Việt, câu ngắn, KHÔNG em-dash `—`, không emoji
- Số liệu phải khớp DATA. KHÔNG bịa
- KHÔNG generic kiểu "tăng cường marketing". Phải cụ thể như "đăng 3 reel pain-gain dùng story H07"
"""


def build_monthly_memo_prompt(
    student_id: str,
    data: dict[str, Any],
    rule_analysis: dict[str, Any],
) -> str:
    """Build LLM prompt cho monthly memo, narrative dài hơn weekly."""
    return f"""Bạn là AI COO cho founder solo {student_id}, viết MEMO THÁNG.

DATA 30 NGÀY:
{json.dumps(data, ensure_ascii=False, indent=2, default=str)[:5000]}

RULE ANALYSIS:
{json.dumps(rule_analysis, ensure_ascii=False, indent=2, default=str)[:2000]}

Gọi tool submit_coo_narrative với:
- headline: trạng thái tháng qua, focus on biggest shift
- wins: 3 wins có số + so sánh tháng trước nếu có
- losses: tối đa 3 losses
- root_cause: pattern gốc
- next_week_focus: ưu tiên SỐ 1 cho tháng sau

Tiếng Việt, KHÔNG em-dash, không emoji.
"""
