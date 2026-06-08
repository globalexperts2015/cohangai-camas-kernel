"""BC18 prompt template + tool schema (flat)."""
from __future__ import annotations

import json
from pathlib import Path


def load_knowledge_base() -> str:
    path = Path(__file__).parent / "knowledge_base.md"
    if not path.exists():
        return ""
    return path.read_text()


def build_audit_prompt(offer: dict, persona: dict, venture: str, knowledge_base: str) -> str:
    return f"""Bạn là chuyên gia Value Equation Audit theo Hormozi + Brunson Epiphany Bridge.

# Knowledge base

{knowledge_base}

# Venture
{venture}

# Existing offer (audit subject)
{json.dumps(offer, ensure_ascii=False, indent=2)[:2500]}

# Persona context
{json.dumps(persona, ensure_ascii=False)[:1000]}

# Task

Audit Value Equation 4 levers:

Quality requirements:
- Honest score per lever (range 4-9 typical, KHÔNG bias 10/10 everything)
- Identify weakest lever
- 3-5 SPECIFIC actions để improve weakest (concrete examples, not vague)
- Projected value lift (new_value / old_value)
- Revised Dream Outcome statement (Hormozi format)
- Compare với Anna's Empire Stack benchmarks (Foundation 8.0, Customer 7.75, Coaching 9.25)

Output qua tool submit_audit.
"""


SUBMIT_AUDIT_TOOL = {
    "name": "submit_audit",
    "description": "Submit Value Equation audit (flat schema)",
    "input_schema": {
        "type": "object",
        "properties": {
            "venture": {"type": "string"},
            "offer_name": {"type": "string"},
            "dream_outcome_score": {"type": "integer", "minimum": 1, "maximum": 10},
            "dream_outcome_evidence": {"type": "string"},
            "likelihood_score": {"type": "integer", "minimum": 1, "maximum": 10},
            "likelihood_evidence": {"type": "string"},
            "time_delay_score": {"type": "integer", "minimum": 1, "maximum": 10, "description": "Higher = LESS delay"},
            "time_delay_evidence": {"type": "string"},
            "effort_score": {"type": "integer", "minimum": 1, "maximum": 10, "description": "Higher = LESS effort"},
            "effort_evidence": {"type": "string"},
            "total_value_score": {"type": "number"},
            "weakest_lever": {"type": "string", "enum": ["dream_outcome", "likelihood", "time_delay", "effort"]},
            "improvement_action_1": {"type": "string"},
            "improvement_action_2": {"type": "string"},
            "improvement_action_3": {"type": "string"},
            "improvement_action_4": {"type": "string"},
            "improvement_action_5": {"type": "string"},
            "projected_value_lift_pct": {"type": "number", "description": "Expected lift after improvements"},
            "revised_dream_outcome": {"type": "string", "description": "Hormozi format: specific + measurable + timeline"},
            "anna_benchmark_comparison": {"type": "string", "description": "vs Foundation 8.0/Customer 7.75/Coaching 9.25"},
            "passes_quality": {"type": "boolean"},
            "summary": {"type": "string"},
        },
        "required": ["venture", "offer_name", "dream_outcome_score", "likelihood_score", "time_delay_score", "effort_score", "total_value_score", "weakest_lever", "improvement_action_1", "summary"],
    },
}
