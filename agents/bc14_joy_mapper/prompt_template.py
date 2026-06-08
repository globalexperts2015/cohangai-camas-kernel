"""BC14 prompt template + tool schema."""
from __future__ import annotations

import json
from pathlib import Path


def load_knowledge_base() -> str:
    path = Path(__file__).parent / "knowledge_base.md"
    if not path.exists():
        return ""
    return path.read_text()


def build_joy_prompt(pain_matrix: dict, persona_context: dict, venture: str, knowledge_base: str) -> str:
    return f"""Bạn là chuyên gia Joy/Gain mapping theo CIS Module 4 Anna + Tròn Vuông Gains + Hormozi Dream Outcome.

# Knowledge base (full framework)

{knowledge_base}

# Venture
{venture}

# Persona context
{json.dumps(persona_context, ensure_ascii=False, indent=2)[:1500]}

# Pain Matrix (output BC13)
{json.dumps(pain_matrix, ensure_ascii=False, indent=2)[:2500]}

# Task

Map Joy/Gain 1:1 cho MỖI pain trong pain_matrix:

Quality requirements (theo knowledge_base section 6):
- Mỗi pain có ≥1 joy resolution
- TOP 3 pain critical → MUST có Required + Expected resolution
- Required gains ≥1
- Expected gains ≥1
- Identify 1 Wow Factor (Unexpected)
- Primary Dream Outcome theo Hormozi format (specific + measurable + timeline)
- KHÔNG generic, MUST concrete với numbers/timelines
- KHÔNG em-dash, no "mẹ đơn thân", no city specific

Output qua tool submit_joy_matrix.
"""


SUBMIT_JOY_MATRIX_TOOL = {
    "name": "submit_joy_matrix",
    "description": "Submit Joy/Gain matrix mapped 1:1 với Pain (CIS M4 + Tròn Vuông Gains + Hormozi)",
    "input_schema": {
        "type": "object",
        "properties": {
            "joys_by_type": {
                "type": "object",
                "properties": {
                    "required": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "gain": {"type": "string"},
                                "addresses_pain": {"type": "string"},
                                "dream_outcome": {"type": "string", "description": "Specific + measurable + timeline"},
                            },
                            "required": ["gain", "addresses_pain"],
                        },
                    },
                    "expected": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "gain": {"type": "string"},
                                "addresses_pain": {"type": "string"},
                                "dream_outcome": {"type": "string"},
                            },
                            "required": ["gain", "addresses_pain"],
                        },
                    },
                    "desired": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "gain": {"type": "string"},
                                "addresses_pain": {"type": "string"},
                            },
                        },
                    },
                    "unexpected": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "gain": {"type": "string"},
                                "wow_factor_reason": {"type": "string"},
                            },
                        },
                    },
                },
                "required": ["required", "expected"],
            },
            "pain_to_joy_pairs": {
                "type": "array",
                "minItems": 1,
                "description": "1:1 mapping mỗi pain → ≥1 joy",
                "items": {
                    "type": "object",
                    "properties": {
                        "pain": {"type": "string"},
                        "pain_severity": {"type": "integer"},
                        "joy": {"type": "string"},
                        "joy_type": {"type": "string", "enum": ["required", "expected", "desired", "unexpected"]},
                    },
                    "required": ["pain", "joy", "joy_type"],
                },
            },
            "primary_dream_outcome": {
                "type": "string",
                "description": "Hormozi Dream Outcome chính: specific + measurable + timeline",
            },
            "wow_factor": {
                "type": "string",
                "description": "Unexpected gain mạnh nhất cho persona này",
            },
            "value_equation_audit": {
                "type": "object",
                "description": "Hormozi 4 lever audit",
                "properties": {
                    "dream_outcome_strength": {"type": "integer", "minimum": 1, "maximum": 10},
                    "likelihood_strength": {"type": "integer", "minimum": 1, "maximum": 10},
                    "time_delay_reduction": {"type": "integer", "minimum": 1, "maximum": 10},
                    "effort_reduction": {"type": "integer", "minimum": 1, "maximum": 10},
                },
            },
            "quality_check": {
                "type": "object",
                "properties": {
                    "all_pains_mapped": {"type": "boolean"},
                    "top_3_have_required_expected": {"type": "boolean"},
                    "wow_factor_identified": {"type": "boolean"},
                    "dream_outcome_specific": {"type": "boolean"},
                    "passes_quality": {"type": "boolean"},
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["joys_by_type", "pain_to_joy_pairs", "primary_dream_outcome", "summary"],
    },
}
