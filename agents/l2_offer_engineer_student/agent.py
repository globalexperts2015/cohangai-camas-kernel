"""L2.6 Offer Engineer Student (wrap P0.1 offer_engineer).

Student-friendly variant of offer_engineer (sprint-13 P0.1). Cohangai cohort 1 week 7.
Apply Hormozi $100M formula với coaching tone + student dashboard Markdown output.
Trigger event: cohort.offer_engineer
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

log = logging.getLogger("camas.l2_offer_engineer_student")
EXPECTED_EVENTS = {"cohort.offer_engineer"}
DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 5000
DEFAULT_TIMEOUT = 150.0


SUBMIT_STUDENT_OFFER_TOOL = {
    "name": "submit_student_offer",
    "description": "Submit Grand Slam Offer student-friendly",
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "string"},
            "venture": {"type": "string"},
            "magic_name": {"type": "string"},
            "usp_one_line": {"type": "string"},
            "core_offer": {"type": "string"},
            "core_price_vnd": {"type": "integer"},
            "value_equation_scores": {
                "type": "object",
                "properties": {
                    "dream_outcome": {"type": "integer", "minimum": 1, "maximum": 10},
                    "likelihood": {"type": "integer", "minimum": 1, "maximum": 10},
                    "time_delay_reduction": {"type": "integer", "minimum": 1, "maximum": 10},
                    "effort_reduction": {"type": "integer", "minimum": 1, "maximum": 10},
                },
            },
            "bonus_stack": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "value_vnd": {"type": "integer"},
                        "addresses_objection": {"type": "string"},
                    },
                },
            },
            "total_stack_value_vnd": {"type": "integer"},
            "value_to_price_ratio": {"type": "number"},
            "guarantee_type": {"type": "string"},
            "guarantee_terms": {"type": "string"},
            "scarcity": {"type": "string"},
            "urgency_deadline": {"type": "string"},
            "coaching_notes": {"type": "string", "description": "Empathetic coaching tone"},
            "markdown_report": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["student_id", "magic_name", "core_offer", "core_price_vnd", "bonus_stack", "total_stack_value_vnd", "markdown_report", "summary"],
    },
}


def build_student_offer_prompt(student_id: str, persona: dict, mvo: dict, transformation: dict) -> str:
    return f"""Bạn là Offer Engineer Coach Cohangai Cohort 1 week 7, applying Hormozi $100M Offers + Brunson Stack Method + Dan Lok USP.

Tone: empathetic coaching cho student first cohort. KHÔNG harsh judge.

# Student
{student_id}

# Persona target
{json.dumps(persona, ensure_ascii=False, indent=2)[:1200]}

# MVO plan (L2.5)
{json.dumps(mvo, ensure_ascii=False, indent=2)[:1500]}

# Transformation 7D (L2.3)
{json.dumps(transformation, ensure_ascii=False, indent=2)[:1500]}

# Task

Build Grand Slam Offer student-friendly:

## 1. MAGIC name (Magnetic + Avatar + Goal + Indicator + Container)
## 2. USP 1 câu
## 3. Core offer + price
## 4. Value Equation scores 1-10 mỗi lever (honest, không bias 10/10 mọi cái)
## 5. Bonus stack (5-10 items) mỗi cái: name + value_vnd + objection addressed
## 6. Total stack value + ratio (target ≥3x for premium / ≥5x for frontend)
## 7. Guarantee type + terms (Conditional recommend cho student first cohort)
## 8. Scarcity REAL (cap quantifiable)
## 9. Urgency với deadline cụ thể
## 10. Coaching notes (warm, encourage student, point ra mạnh + chỗ refine)
## 11. Markdown report dashboard-friendly

# Quality requirements
- Pronoun "bạn"
- Bonus mapped to objections cụ thể
- KHÔNG em-dash

Output qua tool submit_student_offer.
"""


class L2OfferEngineerStudent(BaseBC):
    name = "l2_offer_engineer_student"
    scope = "Student Grand Slam Offer wizard Stage 9 (wrap P0.1)"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(self, llm: LLMLayer, memory: MemoryLayer, model: str = DEFAULT_MODEL) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(success=False, output_text=f"unsupported {event}", output_payload={"supported": list(EXPECTED_EVENTS)})
        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")
        persona = payload.get("persona", {})
        mvo = payload.get("mvo", {})
        transformation = payload.get("transformation", {})

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_student_offer_prompt(student_id, persona, mvo, transformation)
        try:
            response = await self.llm.client.messages.create(
                model=self.model, max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_STUDENT_OFFER_TOOL],
                tool_choice={"type": "tool", "name": "submit_student_offer"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        magic = result.get("magic_name", "")[:50]
        price = result.get("core_price_vnd", 0)
        ratio = result.get("value_to_price_ratio", 0)
        bonuses = len(result.get("bonus_stack", []))
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:700],
            "keywords": ["offer", "cohort_1", student_id, magic],
            "tags": ["l2", "offer_engineer_student", "stage_9", "cohort_1", date_str],
            "venture": ctx.venture_context or "cohangai",
            "category": "pricing",
            "context": f"cohort.offer_engineer {date_str} student={student_id}",
        }
        return AgentResult(success=True, output_text=f"l2_offer student={student_id} magic='{magic}' price={price:,}vnd ratio={ratio}x bonuses={bonuses}", output_payload=result, emitted_memories=[memory_entry])

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_student_offer":
                return block.input or {}
        return {"error": "No tool_use block"}
