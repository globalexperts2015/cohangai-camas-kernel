"""E7 Solution Design Engine. BreakoutOS CHỌN module Engine 5/9."""
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

from .prompt_template import SUBMIT_SOLUTION_DESIGN_TOOL, build_solution_design_prompt

log = logging.getLogger("camas.e7_solution_design")
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 6000
DEFAULT_TIMEOUT = 240.0
EXPECTED_EVENTS = {"cohort.solution_design", "wizard.solution_design"}


class E7SolutionDesign(BaseBC):
    name = "e7_solution_design"
    scope = "Solution Design Engine. 7 product type fit + primary + secondary + anti-recommendation. BreakoutOS CHỌN module."
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
        log.info("E7 init model=%s", model)

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(success=False, output_text=f"unsupported event {event}",
                               output_payload={"supported": sorted(EXPECTED_EVENTS)})
        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")
        venture = ctx.venture_context or "cohangai"

        raw = payload.get("solution_design_input")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                founder_profile = parsed.get("founder_profile", {}) or {}
                customer_hypothesis = parsed.get("customer_hypothesis", "") or ""
                problem_map = parsed.get("problem_map", {}) or {}
                desire_map = parsed.get("desire_map", {}) or {}
                lifestyle_choice = parsed.get("lifestyle_choice", "solo_ai") or "solo_ai"
            except json.JSONDecodeError:
                founder_profile = {"raw": raw[:1000]}
                customer_hypothesis = raw[:1000]
                problem_map = {}
                desire_map = {}
                lifestyle_choice = "solo_ai"
        else:
            founder_profile = payload.get("founder_profile", {}) or {}
            customer_hypothesis = payload.get("customer_hypothesis", "") or ""
            problem_map = payload.get("problem_map", {}) or {}
            desire_map = payload.get("desire_map", {}) or {}
            lifestyle_choice = payload.get("lifestyle_choice", "solo_ai") or "solo_ai"

        if not founder_profile and not customer_hypothesis:
            return AgentResult(success=False, output_text="missing both founder_profile and customer_hypothesis",
                               output_payload={"error": "missing_inputs"})

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready",
                               output_payload={"error": "llm_not_ready"})

        prompt = build_solution_design_prompt(student_id, founder_profile, customer_hypothesis,
                                              problem_map, desire_map, lifestyle_choice)
        try:
            response = await self.llm.client.messages.create(
                model=self.model, max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_SOLUTION_DESIGN_TOOL],
                tool_choice={"type": "tool", "name": "submit_solution_design"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:
            log.warning("E7 LLM fail student=%s err=%r", student_id, exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}",
                               output_payload={"error": str(exc)})

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        score = result.get("solution_design_score", 0)
        primary = result.get("primary_recommendation", {}).get("product_type", "?")
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        mem = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:700],
            "keywords": ["solution_design", "chon_module", student_id, primary],
            "tags": ["e7", "solution_design", "chon_module", "engine_5_of_9", primary, date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"chon.solution_design {date_str} student={student_id} primary={primary} score={score}",
        }
        return AgentResult(
            success=True,
            output_text=f"e7_solution_design student={student_id} primary={primary} score={score}/100",
            output_payload=result,
            emitted_memories=[mem],
        )

    @staticmethod
    def _parse_response(response: Any) -> dict[str, Any]:
        for block in response.content or []:
            if (getattr(block, "type", None) == "tool_use"
                    and getattr(block, "name", None) == "submit_solution_design"):
                data = block.input or {}
                if not data:
                    return {"error": "LLM tool_use returned empty input"}
                return data
        return {"error": "No tool_use block submit_solution_design in response"}
