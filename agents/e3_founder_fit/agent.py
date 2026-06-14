"""E3 Founder Fit Engine agent.

BreakoutOS CHỌN module Engine 1/9. Score founder vs opportunity 0-100.
Weight 20% trong tổng Opportunity Score.

Trigger events:
  - cohort.founder_fit: full module run (orchestrator)
  - wizard.founder_fit: standalone test via /cohort/run-wizard

Input payload:
  - student_id: str
  - founder_profile: dict (experience + skills + expertise + story + network + assets + content + customers)
  - opportunity_hypothesis: str
  - lifestyle_choice: str (solo_ai | lean_team | growth_team)

Output payload:
  - founder_fit_score: int 0-100
  - verdict: EXCELLENT_FIT / STRONG_FIT / MODERATE_FIT / WEAK_FIT / POOR_FIT
  - sub_scores: dict 8 fields
  - strengths: list[str]
  - gaps: list[str]
  - unfair_advantages: list[str]
  - founder_profile_report: str (markdown)
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

from .prompt_template import SUBMIT_FOUNDER_FIT_TOOL, build_founder_fit_prompt

log = logging.getLogger("camas.e3_founder_fit")

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 6000
DEFAULT_TIMEOUT = 240.0

EXPECTED_EVENTS = {"cohort.founder_fit", "wizard.founder_fit"}


class E3FounderFit(BaseBC):
    """E3 Founder Fit Engine, BreakoutOS CHỌN module Engine 1/9."""

    name = "e3_founder_fit"
    scope = (
        "Founder Fit Engine 0-100 score. Đánh giá founder vs opportunity dựa trên "
        "8 sub-scores: experience + skill + expertise + story + network + assets + "
        "content + customer_list. BreakoutOS CHỌN module weight 20%."
    )
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: Optional[MemoryLayer] = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model
        log.info("E3 init model=%s", model)

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(
                success=False,
                output_text=f"unsupported event {event}",
                output_payload={"supported": sorted(EXPECTED_EVENTS)},
            )

        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")
        venture = ctx.venture_context or "cohangai"

        # Bridge: support founder_fit_input string from /run-wizard route
        founder_fit_input = payload.get("founder_fit_input")
        if isinstance(founder_fit_input, str) and founder_fit_input.strip():
            try:
                parsed = json.loads(founder_fit_input)
                founder_profile = parsed.get("founder_profile", {}) or {}
                opportunity_hypothesis = parsed.get("opportunity_hypothesis", "") or ""
                lifestyle_choice = parsed.get("lifestyle_choice", "solo_ai") or "solo_ai"
            except json.JSONDecodeError:
                founder_profile = {"raw_description": founder_fit_input[:1500]}
                opportunity_hypothesis = founder_fit_input[:1000]
                lifestyle_choice = "solo_ai"
        else:
            founder_profile = payload.get("founder_profile", {}) or {}
            opportunity_hypothesis = payload.get("opportunity_hypothesis", "") or ""
            lifestyle_choice = payload.get("lifestyle_choice", "solo_ai") or "solo_ai"

        if not founder_profile:
            return AgentResult(
                success=False,
                output_text="missing founder_profile",
                output_payload={"error": "missing_founder_profile"},
            )
        if not opportunity_hypothesis:
            return AgentResult(
                success=False,
                output_text="missing opportunity_hypothesis",
                output_payload={"error": "missing_opportunity_hypothesis"},
            )

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "llm_not_ready"},
            )

        prompt = build_founder_fit_prompt(
            student_id=student_id,
            founder_profile=founder_profile,
            opportunity_hypothesis=opportunity_hypothesis,
            lifestyle_choice=lifestyle_choice,
        )

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_FOUNDER_FIT_TOOL],
                tool_choice={"type": "tool", "name": "submit_founder_fit"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("E3 LLM fail student=%s err=%r", student_id, exc)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(
                success=False,
                output_text=result["error"],
                output_payload=result,
            )

        score = result.get("founder_fit_score", 0)
        verdict = result.get("verdict", "?")
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:700],
            "keywords": ["founder_fit", "chon_module", student_id, f"score-{score}"],
            "tags": [
                "e3", "founder_fit", "chon_module", "engine_1_of_9",
                verdict.lower(), date_str,
            ],
            "venture": venture,
            "category": "venture_state",
            "context": (
                f"chon.founder_fit {date_str} student={student_id} "
                f"score={score} verdict={verdict}"
            ),
        }

        summary = (
            f"e3_founder_fit student={student_id} score={score}/100 "
            f"verdict={verdict} venture={venture}"
        )

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=result,
            emitted_memories=[memory_entry],
        )

    @staticmethod
    def _parse_response(response: Any) -> dict[str, Any]:
        """Extract tool_use block from Anthropic response."""
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_founder_fit"
            ):
                data = block.input or {}
                if not data:
                    return {"error": "LLM tool_use returned empty input"}
                return data
        return {"error": "No tool_use block submit_founder_fit in response"}
