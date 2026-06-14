"""E9 Lifestyle Fit Engine. BreakoutOS CHỌN module Engine 7/9."""
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

from .prompt_template import SUBMIT_LIFESTYLE_FIT_TOOL, build_lifestyle_fit_prompt

log = logging.getLogger("camas.e9_lifestyle_fit")
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 5500
DEFAULT_TIMEOUT = 240.0
EXPECTED_EVENTS = {"cohort.lifestyle_fit", "wizard.lifestyle_fit"}


class E9LifestyleFit(BaseBC):
    name = "e9_lifestyle_fit"
    scope = "Lifestyle Fit Engine. 10x simulation + 5 match dimensions + deal breakers + pivots. BreakoutOS CHỌN module."
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
        log.info("E9 init model=%s", model)

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(success=False, output_text=f"unsupported event {event}",
                               output_payload={"supported": sorted(EXPECTED_EVENTS)})
        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")
        venture = ctx.venture_context or "cohangai"

        raw = payload.get("lifestyle_fit_input")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                opportunity_hypothesis = parsed.get("opportunity_hypothesis", "") or ""
                solution_design = parsed.get("solution_design", {}) or {}
                lifestyle_choice = parsed.get("lifestyle_choice", "solo_ai") or "solo_ai"
                founder_profile = parsed.get("founder_profile", {}) or {}
            except json.JSONDecodeError:
                opportunity_hypothesis = raw[:1500]
                solution_design = {}
                lifestyle_choice = "solo_ai"
                founder_profile = {}
        else:
            opportunity_hypothesis = payload.get("opportunity_hypothesis", "") or ""
            solution_design = payload.get("solution_design", {}) or {}
            lifestyle_choice = payload.get("lifestyle_choice", "solo_ai") or "solo_ai"
            founder_profile = payload.get("founder_profile", {}) or {}

        if not opportunity_hypothesis:
            return AgentResult(success=False, output_text="missing opportunity_hypothesis",
                               output_payload={"error": "missing_opportunity_hypothesis"})

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready",
                               output_payload={"error": "llm_not_ready"})

        prompt = build_lifestyle_fit_prompt(student_id, opportunity_hypothesis,
                                             solution_design, lifestyle_choice, founder_profile)
        try:
            response = await self.llm.client.messages.create(
                model=self.model, max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_LIFESTYLE_FIT_TOOL],
                tool_choice={"type": "tool", "name": "submit_lifestyle_fit"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:
            log.warning("E9 LLM fail student=%s err=%r", student_id, exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}",
                               output_payload={"error": str(exc)})

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        score = result.get("lifestyle_fit_score", 0)
        verdict = result.get("verdict", "?")
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        mem = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:700],
            "keywords": ["lifestyle_fit", "chon_module", student_id, f"score-{score}"],
            "tags": ["e9", "lifestyle_fit", "chon_module", "engine_7_of_9", verdict.lower(), date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"chon.lifestyle_fit {date_str} student={student_id} score={score} verdict={verdict}",
        }
        return AgentResult(
            success=True,
            output_text=f"e9_lifestyle_fit student={student_id} score={score}/100 verdict={verdict}",
            output_payload=result,
            emitted_memories=[mem],
        )

    @staticmethod
    def _parse_response(response: Any) -> dict[str, Any]:
        for block in response.content or []:
            if (getattr(block, "type", None) == "tool_use"
                    and getattr(block, "name", None) == "submit_lifestyle_fit"):
                data = block.input or {}
                if not data:
                    return {"error": "LLM tool_use returned empty input"}
                return data
        return {"error": "No tool_use block submit_lifestyle_fit in response"}
