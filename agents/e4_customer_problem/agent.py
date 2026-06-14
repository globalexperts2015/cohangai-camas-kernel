"""E4 Customer Problem Engine. BreakoutOS CHỌN module Engine 2/9.

Weight 25% trong tổng Opportunity Score.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

from .prompt_template import SUBMIT_CUSTOMER_PROBLEM_TOOL, build_customer_problem_prompt

log = logging.getLogger("camas.e4_customer_problem")

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 8000
DEFAULT_TIMEOUT = 300.0
EXPECTED_EVENTS = {"cohort.customer_problem", "wizard.customer_problem"}


class E4CustomerProblem(BaseBC):
    name = "e4_customer_problem"
    scope = (
        "Customer Problem Engine: 6-axis loss map + Top 3 Pain với Pain Scale 1-10 "
        "+ willingness-to-pay signal. BreakoutOS CHỌN module weight 25%."
    )
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(self, llm: LLMLayer, memory: Optional[MemoryLayer] = None, model: str = DEFAULT_MODEL):
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model
        log.info("E4 init model=%s", model)

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(success=False, output_text=f"unsupported event {event}",
                               output_payload={"supported": sorted(EXPECTED_EVENTS)})

        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")
        venture = ctx.venture_context or "cohangai"

        # Bridge from /run-wizard
        raw = payload.get("customer_problem_input")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                customer_hypothesis = parsed.get("customer_hypothesis", "") or ""
                opportunity_hypothesis = parsed.get("opportunity_hypothesis", "") or ""
            except json.JSONDecodeError:
                customer_hypothesis = raw[:2000]
                opportunity_hypothesis = raw[:1500]
        else:
            customer_hypothesis = payload.get("customer_hypothesis", "") or ""
            opportunity_hypothesis = payload.get("opportunity_hypothesis", "") or ""

        if not customer_hypothesis:
            return AgentResult(success=False, output_text="missing customer_hypothesis",
                               output_payload={"error": "missing_customer_hypothesis"})

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready",
                               output_payload={"error": "llm_not_ready"})

        prompt = build_customer_problem_prompt(student_id, customer_hypothesis, opportunity_hypothesis)
        try:
            response = await self.llm.client.messages.create(
                model=self.model, max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_CUSTOMER_PROBLEM_TOOL],
                tool_choice={"type": "tool", "name": "submit_customer_problem"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:
            log.warning("E4 LLM fail student=%s err=%r", student_id, exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}",
                               output_payload={"error": str(exc)})

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        score = result.get("problem_strength_score", 0)
        verdict = result.get("verdict", "?")
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        mem = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:700],
            "keywords": ["customer_problem", "chon_module", student_id, f"pain-{score}"],
            "tags": ["e4", "customer_problem", "chon_module", "engine_2_of_9", verdict.lower(), date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"chon.customer_problem {date_str} student={student_id} score={score} verdict={verdict}",
        }
        return AgentResult(
            success=True,
            output_text=f"e4_customer_problem student={student_id} pain_score={score}/100 verdict={verdict}",
            output_payload=result,
            emitted_memories=[mem],
        )

    @staticmethod
    def _parse_response(response: Any) -> dict[str, Any]:
        for block in response.content or []:
            if (getattr(block, "type", None) == "tool_use"
                    and getattr(block, "name", None) == "submit_customer_problem"):
                data = block.input or {}
                if not data:
                    return {"error": "LLM tool_use returned empty input"}
                return data
        return {"error": "No tool_use block submit_customer_problem in response"}
