"""L2.4 VPC Fit Checker (wrap BC11 VPC Builder).

Student-facing Stage 7 wizard. Use BC11 logic + student-friendly Markdown output.
Trigger event: cohort.vpc_fit_check
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

log = logging.getLogger("camas.l2_vpc_fit_checker")

EXPECTED_EVENTS = {"cohort.vpc_fit_check"}
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 4000
DEFAULT_TIMEOUT = 120.0


SUBMIT_VPC_FIT_TOOL = {
    "name": "submit_vpc_fit_check",
    "description": "Submit VPC fit check student-friendly",
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "string"},
            "venture": {"type": "string"},
            "persona_name": {"type": "string"},
            "fit_score": {"type": "integer", "minimum": 0, "maximum": 100},
            "fit_verdict": {"type": "string", "description": "STRONG_FIT | NEEDS_REFINE | MISMATCH"},
            "tron_jobs_summary": {"type": "string"},
            "tron_pains_summary": {"type": "string"},
            "tron_gains_summary": {"type": "string"},
            "vuong_products_summary": {"type": "string"},
            "vuong_pain_relievers_summary": {"type": "string"},
            "vuong_gain_creators_summary": {"type": "string"},
            "orphan_pains_count": {"type": "integer"},
            "orphan_gains_count": {"type": "integer"},
            "coaching_advice": {"type": "string"},
            "refine_suggestions": {"type": "array", "items": {"type": "string"}},
            "markdown_report": {"type": "string", "description": "Full Markdown dashboard report"},
            "summary": {"type": "string"},
        },
        "required": ["student_id", "fit_score", "fit_verdict", "coaching_advice", "markdown_report", "summary"],
    },
}


def build_vpc_fit_prompt(student_id: str, persona: dict, product_idea: dict, transformation_context: dict) -> str:
    return f"""Bạn là VPC Fit Coach Cohangai Cohort 1, applying Eagle Camp Tròn Vuông Stage 7.

# Student
{student_id}

# Persona target (từ L2.2 niche + L2.3 transformation)
{json.dumps(persona, ensure_ascii=False, indent=2)[:1500]}

# Product idea student đưa
{json.dumps(product_idea, ensure_ascii=False, indent=2)[:1500]}

# Transformation context (L2.3 output)
{json.dumps(transformation_context, ensure_ascii=False, indent=2)[:1500]}

# Task

Check fit Tròn Vuông VPC giữa persona ↔ product idea:

## Tròn (Customer side)
- Jobs (3 loại: functional + social + emotional)
- Pains (4 loại + 3 rào cản + 3 rủi ro)
- Gains (4 loại: required + expected + desired + unexpected)

## Vuông (Product side)
- Products & Services
- Pain Relievers (mỗi pain critical phải có)
- Gain Creators (mỗi required + expected gain phải có)

## Fit score (0-100)
- 80-100 STRONG_FIT: every pair matched
- 60-79 NEEDS_REFINE: 1-3 orphans
- <60 MISMATCH: product không serve persona's actual pain

## Coaching advice
EMPATHETIC tone. Acknowledge effort, pinpoint mạnh + chỗ refine.

## Refine suggestions
Concrete: thêm Pain Reliever cho pain X, thêm Gain Creator cho gain Y.

## Markdown report cho student dashboard.

# Quality requirements
- Pronoun "bạn"
- KHÔNG em-dash
- Specific với data

Output qua tool submit_vpc_fit_check.
"""


class L2VPCFitChecker(BaseBC):
    name = "l2_vpc_fit_checker"
    scope = "Student VPC fit check Stage 7 (wrap BC11)"
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
        transformation = payload.get("transformation_context", {})

        # Bridge: support product_idea string from /run-wizard route
        product_idea_raw = payload.get("product_idea", {})
        if isinstance(product_idea_raw, str) and product_idea_raw.strip():
            try:
                product_idea = json.loads(product_idea_raw)
                if not isinstance(product_idea, dict):
                    product_idea = {"description": product_idea_raw[:500]}
            except (json.JSONDecodeError, ValueError):
                product_idea = {"description": product_idea_raw[:500]}
        else:
            product_idea = product_idea_raw or {}

        # Fallback persona nếu chain chưa chạy (LIVE student test, first wizard)
        if not persona:
            persona = {"raw_description": product_idea.get("description", ""), "_fallback": True}

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_vpc_fit_prompt(student_id, persona, product_idea, transformation)
        try:
            response = await self.llm.client.messages.create(
                model=self.model, max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_VPC_FIT_TOOL],
                tool_choice={"type": "tool", "name": "submit_vpc_fit_check"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("l2_vpc_fit LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        fit = result.get("fit_score", 0)
        verdict = result.get("fit_verdict", "?")
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:600],
            "keywords": ["vpc_fit", "cohort_1", student_id, f"fit-{fit}"],
            "tags": ["l2", "vpc_fit_checker", "stage_7", "cohort_1", verdict.lower(), date_str],
            "venture": ctx.venture_context or "cohangai",
            "category": "profile",
            "context": f"cohort.vpc_fit_check {date_str} student={student_id} fit={fit}",
        }
        return AgentResult(success=True, output_text=f"vpc_fit student={student_id} fit={fit}/100 verdict={verdict}", output_payload=result, emitted_memories=[memory_entry])

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_vpc_fit_check":
                return block.input or {}
        return {"error": "No tool_use block"}
