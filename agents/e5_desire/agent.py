"""E5 Desire Engine. BreakoutOS CHỌN module Engine 3/9."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from kernel.base_agent import (
    AgentResult, AutonomyLevel, BaseBC, EscalationTarget, ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

from .prompt_template import SUBMIT_DESIRE_TOOL, build_desire_prompt

log = logging.getLogger("camas.e5_desire")
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 6000
DEFAULT_TIMEOUT = 240.0
EXPECTED_EVENTS = {"cohort.desire", "wizard.desire"}


class E5Desire(BaseBC):
    name = "e5_desire"
    scope = "Desire Engine 5 chiều (surface wants + deep aspirations + identity + social status + lifestyle). BreakoutOS CHỌN module."
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
        log.info("E5 init model=%s", model)

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(success=False, output_text=f"unsupported event {event}",
                               output_payload={"supported": sorted(EXPECTED_EVENTS)})
        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")
        venture = ctx.venture_context or "cohangai"

        raw = payload.get("desire_input")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                customer_hypothesis = parsed.get("customer_hypothesis", "") or ""
                problem_map = parsed.get("problem_map", {}) or {}
            except json.JSONDecodeError:
                customer_hypothesis = raw[:2000]
                problem_map = {}
        else:
            customer_hypothesis = payload.get("customer_hypothesis", "") or ""
            problem_map = payload.get("problem_map", {}) or {}

        if not customer_hypothesis:
            return AgentResult(success=False, output_text="missing customer_hypothesis",
                               output_payload={"error": "missing_customer_hypothesis"})
        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready",
                               output_payload={"error": "llm_not_ready"})

        prompt = build_desire_prompt(student_id, customer_hypothesis, problem_map)
        try:
            response = await self.llm.client.messages.create(
                model=self.model, max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_DESIRE_TOOL],
                tool_choice={"type": "tool", "name": "submit_desire_map"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:
            log.warning("E5 LLM fail student=%s err=%r", student_id, exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}",
                               output_payload={"error": str(exc)})

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        score = result.get("desire_strength_score", 0)
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        mem = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:700],
            "keywords": ["desire", "chon_module", student_id, f"desire-{score}"],
            "tags": ["e5", "desire", "chon_module", "engine_3_of_9", date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"chon.desire {date_str} student={student_id} score={score}",
        }
        return AgentResult(
            success=True,
            output_text=f"e5_desire student={student_id} desire_score={score}/100",
            output_payload=result,
            emitted_memories=[mem],
        )

    @staticmethod
    def _parse_response(response: Any) -> dict[str, Any]:
        for block in response.content or []:
            if (getattr(block, "type", None) == "tool_use"
                    and getattr(block, "name", None) == "submit_desire_map"):
                data = block.input or {}
                if not data:
                    return {"error": "LLM tool_use returned empty input"}
                return data
        return {"error": "No tool_use block submit_desire_map in response"}
