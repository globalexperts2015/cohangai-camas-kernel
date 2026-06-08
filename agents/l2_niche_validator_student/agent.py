"""L2.2 Niche Validator Student (wrap P1.1 niche_validator).

Student-friendly variant của niche_validator. Cohangai cohort 1 week 2.

Diff với P1.1:
- Input: student niche statement (có thể vague hơn Anna's commercial-grade)
- Output: Markdown report explain 3 indicator + student-friendly recommendation
- Tone: coaching, not auditor

Trigger event: cohort.niche_validate
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

log = logging.getLogger("camas.l2_niche_validator_student")

EXPECTED_EVENTS = {"cohort.niche_validate"}

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 3000
DEFAULT_TIMEOUT = 90.0


SUBMIT_STUDENT_NICHE_TOOL = {
    "name": "submit_student_niche",
    "description": "Submit student-friendly niche validation report",
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "string"},
            "niche_statement": {"type": "string"},
            "validation_score": {"type": "integer", "minimum": 0, "maximum": 3},
            "verdict": {
                "type": "string",
                "description": "STRONG | VIABLE | NEEDS_REFINE",
            },
            "indicator_1_clarity_feedback": {"type": "string"},
            "indicator_2_audience_feedback": {"type": "string"},
            "indicator_3_demand_feedback": {"type": "string"},
            "coaching_advice": {
                "type": "string",
                "description": "Empathetic coaching tone, encourage student",
            },
            "refined_niche_suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3-5 narrower/different angle nếu cần refine",
            },
            "next_step_homework": {
                "type": "string",
                "description": "1-2 concrete homework cho week tiếp theo",
            },
            "markdown_report": {
                "type": "string",
                "description": "Full Markdown report cho student dashboard",
            },
            "summary": {"type": "string"},
        },
        "required": [
            "student_id",
            "niche_statement",
            "validation_score",
            "verdict",
            "coaching_advice",
            "next_step_homework",
            "markdown_report",
            "summary",
        ],
    },
}


def build_student_niche_prompt(student_id: str, niche_statement: str, vision_context: dict) -> str:
    return f"""Bạn là Niche Coach cho Cohangai Cohort 1 student, tone empathetic + encouraging.

Student vừa hoàn thành Vision Clarity (week 1). Bây giờ week 2: pick niche.

# Student
ID: {student_id}

# Vision context (từ L2.1 Vision Clarity)
{json.dumps(vision_context, ensure_ascii=False, indent=2)[:1500]}

# Niche statement student đưa
"{niche_statement}"

# Task

Validate niche với 3-indicator framework Stage 3, NHƯNG output student-friendly:

## 1. Clarity check (Indicator 1)
- Niche statement clear không?
- Student dễ explain trong 30 giây không?
- Feedback EMPATHETIC, không judge

## 2. Audience size check (Indicator 2)
- Estimate audience size Vietnamese market
- Realistic check vs vision context

## 3. Demand check (Indicator 3)
- Có search demand không?
- Có competitor không (good sign hay bad)?

## 4. Coaching advice
Tone: anh chị, không "thầy/expert".
- Acknowledge effort student bỏ ra
- Pinpoint điểm mạnh trong niche statement
- Nhẹ nhàng identify chỗ cần refine

## 5. Refined suggestions (3-5)
Nếu niche too broad/narrow/unclear, đề xuất narrower angle aligned với vision.

## 6. Next step homework
Week 3 student làm gì cụ thể (1-2 actions).

## 7. Full Markdown report
Format dashboard-friendly cho student LMS:
```
# Niche Validation Report
## Niche của bạn
## Đánh giá tổng quan
## 3 indicator
## Coaching advice
## Refined suggestions
## Homework week tiếp
```

# Quality requirements
- EMPATHETIC tone, KHÔNG harsh judge
- Reference vision context để giữ alignment
- KHÔNG em-dash
- Pronoun: "bạn"

Output qua tool submit_student_niche.
"""


class L2NicheValidatorStudent(BaseBC):
    """L2.2 Student niche validator (wrap P1.1)."""

    name = "l2_niche_validator_student"
    scope = "Student niche validation wizard Cohangai cohort 1 week 2 (wrap P1.1)"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        model: str = DEFAULT_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(
                success=False,
                output_text=f"{self.name} không xử lý event này",
                output_payload={
                    "trigger_event": event,
                    "supported": list(EXPECTED_EVENTS),
                },
            )

        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")
        niche_statement = payload.get("niche_statement", "").strip()
        vision_context = payload.get("vision_context", {})

        if not niche_statement or len(niche_statement) < 10:
            return AgentResult(
                success=False,
                output_text="Missing niche_statement",
                output_payload={"error": "niche_statement < 10 chars"},
            )

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "LLM not ready"},
            )

        prompt = build_student_niche_prompt(student_id, niche_statement, vision_context)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_STUDENT_NICHE_TOOL],
                tool_choice={"type": "tool", "name": "submit_student_niche"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("l2_niche_validator_student LLM fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        verdict = result.get("verdict", "?")
        score = result.get("validation_score", 0)
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = f"l2_niche student={student_id} score={score}/3 verdict={verdict}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:600],
            "keywords": ["l2_niche", "cohort_1", student_id],
            "tags": ["l2", "niche_validator_student", "stage_3", "cohort_1", date_str],
            "venture": ctx.venture_context or "cohangai",
            "category": "profile",
            "context": f"cohort.niche_validate {date_str} student={student_id}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=result,
            emitted_memories=[memory_entry],
        )

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_student_niche"
            ):
                return block.input or {}
        return {"error": "No tool_use block"}
