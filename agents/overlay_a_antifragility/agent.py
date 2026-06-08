"""Overlay A Antifragility Scorer agent (BC8 enhance per Sprint 13 P1.5).

Apply Overlay A: "did system get stronger this week vs last?"
- NPS delta
- Churn delta
- Completion delta
- Refund rate delta
- Customer satisfaction delta

Trigger event: overlay_a.antifragility_score
Output: weekly antifragility score + 5 metrics delta + verdict (stronger/stable/weaker).
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

log = logging.getLogger("camas.overlay_a_antifragility")

EXPECTED_EVENTS = {"overlay_a.antifragility_score"}

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 2500
DEFAULT_TIMEOUT = 90.0


SUBMIT_ANTIFRAGILITY_TOOL = {
    "name": "submit_antifragility_score",
    "description": "Submit antifragility weekly score per venture",
    "input_schema": {
        "type": "object",
        "properties": {
            "venture": {"type": "string"},
            "week_label": {"type": "string", "description": "vd: W23-2026"},
            "previous_week_label": {"type": "string"},
            "nps_current": {"type": "number"},
            "nps_previous": {"type": "number"},
            "nps_delta": {"type": "number"},
            "churn_pct_current": {"type": "number"},
            "churn_pct_previous": {"type": "number"},
            "churn_delta_pct": {"type": "number"},
            "completion_pct_current": {"type": "number"},
            "completion_pct_previous": {"type": "number"},
            "completion_delta_pct": {"type": "number"},
            "refund_pct_current": {"type": "number"},
            "refund_pct_previous": {"type": "number"},
            "refund_delta_pct": {"type": "number"},
            "csat_current": {"type": "number"},
            "csat_previous": {"type": "number"},
            "csat_delta": {"type": "number"},
            "antifragility_score": {
                "type": "integer",
                "minimum": -10,
                "maximum": 10,
                "description": "-10 system weakened → 10 system strengthened week-over-week",
            },
            "verdict": {
                "type": "string",
                "description": "STRONGER | STABLE | WEAKER | FRAGILE",
            },
            "biggest_improvement": {"type": "string"},
            "biggest_decline": {"type": "string"},
            "stressor_response": {
                "type": "string",
                "description": "Did system handle stressor (refund spike/NPS drop/churn spike) by getting stronger or weaker?",
            },
            "recommendation": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": [
            "venture",
            "week_label",
            "antifragility_score",
            "verdict",
            "summary",
        ],
    },
}


def build_antifragility_prompt(venture: str, current_data: dict, previous_data: dict) -> str:
    return f"""Bạn là chuyên gia Antifragility Analysis theo framework v2 Overlay A.

Triết lý: hệ thống KHÔNG chỉ ổn định (robust) mà phải MẠNH HƠN sau mỗi stressor (antifragile).

# Venture
{venture}

# Current week data
{json.dumps(current_data, ensure_ascii=False, indent=2)[:2000]}

# Previous week data
{json.dumps(previous_data, ensure_ascii=False, indent=2)[:2000]}

# Task

Calculate 5 metrics week-over-week delta + antifragility verdict:

## Metrics
1. **NPS delta**: current - previous (positive = stronger)
2. **Churn pct delta**: previous - current (positive = stronger, less churn)
3. **Completion pct delta**: current - previous (positive = stronger)
4. **Refund pct delta**: previous - current (positive = stronger, less refund)
5. **CSAT delta**: current - previous (positive = stronger)

## Antifragility score (-10 to +10)
- +7 to +10: STRONGER (most metrics improved + stressor handled gracefully)
- +3 to +6: STABLE-improving
- -2 to +2: STABLE (no significant delta)
- -3 to -6: WEAKER (declining trend)
- -7 to -10: FRAGILE (multiple metrics declined, stressor broke system)

## Stressor response analysis
Identify nếu có stressor tuần này (refund spike, NPS drop, completion drop). Phân tích:
- Did system absorb + improve? → ANTIFRAGILE
- Did system maintain? → ROBUST
- Did system degrade? → FRAGILE

## Recommendation
1-2 actions để tăng antifragility tuần tới.

# Quality requirements
- Honest delta (KHÔNG bias positive)
- Recommendations actionable
- Verdict reflect actual data

Output qua tool submit_antifragility_score.
"""


class OverlayAAntifragility(BaseBC):
    """Overlay A Antifragility Scorer (BC8 enhance per Sprint 13 P1.5)."""

    name = "overlay_a_antifragility"
    scope = "Weekly antifragility score (Overlay A Anti-fragility framework v2)"
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
        venture = ctx.venture_context or "all"
        current_data = payload.get("current_week", {})
        previous_data = payload.get("previous_week", {})

        if not current_data or not previous_data:
            current_data, previous_data = await self._retrieve_weekly_data(venture)

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "ANTHROPIC_API_KEY chưa set"},
            )

        prompt = build_antifragility_prompt(venture, current_data, previous_data)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_ANTIFRAGILITY_TOOL],
                tool_choice={"type": "tool", "name": "submit_antifragility_score"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("overlay_a_antifragility LLM fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        score = result.get("antifragility_score", 0)
        verdict = result.get("verdict", "?")
        week = result.get("week_label", "?")
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = f"antifragility venture={venture} week={week} score={score}/10 verdict={verdict}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:800],
            "keywords": ["antifragility", venture, verdict.lower(), week],
            "tags": ["overlay_a", "antifragility", venture, verdict.lower(), date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"overlay_a.antifragility_score {date_str} venture={venture} score={score}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=result,
            emitted_memories=[memory_entry],
        )

    async def _retrieve_weekly_data(self, venture: str) -> tuple[dict, dict]:
        """Retrieve current + previous week metrics."""
        if not self.memory.ready:
            return {}, {}
        try:
            records = await self.memory.retrieve(
                query=f"NPS churn completion refund CSAT {venture}",
                categories=["venture_state", "task"],
                venture=venture if venture != "all" else None,
                k=20,
                max_age_days=14,
            )
            if not records:
                return {}, {}
            mid = len(records) // 2
            return (
                {"records": [r.content[:200] for r in records[:mid]]},
                {"records": [r.content[:200] for r in records[mid:]]},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("retrieve weekly fail: %r", exc)
            return {}, {}

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_antifragility_score"
            ):
                return block.input or {}
        return {"error": "No tool_use block"}
