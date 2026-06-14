"""Overlay A Cohort Comparison agent (BC3 enhance per Sprint 13 P1.5).

Apply Overlay A Anti-fragility framework v2:
1. Cohort A-B comparison: this week vs last week cohort, measure differential
2. Refund reason causal loop: tag refund → identify which Stage caused → recommend back

Trigger event: overlay_a.cohort_compare
Output: comparison report + causal stage analysis + recommendations.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
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

log = logging.getLogger("camas.overlay_a_cohort_comparison")

EXPECTED_EVENTS = {"overlay_a.cohort_compare"}

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 3500
DEFAULT_TIMEOUT = 120.0


SUBMIT_COMPARISON_TOOL = {
    "name": "submit_cohort_comparison",
    "description": "Submit cohort A-B comparison + refund causal loop",
    "input_schema": {
        "type": "object",
        "properties": {
            "venture": {"type": "string"},
            "period_a_label": {"type": "string", "description": "Current cohort (vd: K2 9-11/6)"},
            "period_b_label": {"type": "string", "description": "Previous cohort (vd: K1 May)"},
            "metric_deltas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string"},
                        "value_a": {"type": "number"},
                        "value_b": {"type": "number"},
                        "delta_pct": {"type": "number"},
                        "verdict": {"type": "string", "description": "improved | stable | declined"},
                    },
                },
                "description": "Metric comparison: conversion, refund, NPS, completion, churn",
            },
            "refund_causal_analysis": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "refund_reason": {"type": "string"},
                        "refund_count": {"type": "integer"},
                        "framework_stage_caused": {
                            "type": "string",
                            "description": "stage_3 niche | stage_5 demand | stage_9 offer | stage_15 delivery | etc",
                        },
                        "loop_back_agent": {
                            "type": "string",
                            "description": "Agent should fix: niche_validator | offer_engineer | bc10_coaching_delivery | etc",
                        },
                        "recommendation": {"type": "string"},
                    },
                },
            },
            "differential_score": {
                "type": "integer",
                "minimum": -10,
                "maximum": 10,
                "description": "-10 declined → 10 improved cohort A vs B",
            },
            "biggest_improvement_metric": {"type": "string"},
            "biggest_decline_metric": {"type": "string"},
            "key_recommendations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3-5 actions cho cohort tiếp theo",
            },
            "summary": {"type": "string"},
        },
        "required": [
            "venture",
            "period_a_label",
            "period_b_label",
            "metric_deltas",
            "differential_score",
            "summary",
        ],
    },
}


def build_comparison_prompt(
    venture: str, cohort_a_data: dict, cohort_b_data: dict, refunds: list[dict]
) -> str:
    return f"""Bạn là chuyên gia Anti-fragility Cohort Comparison theo framework v2 Overlay A.

# Venture
{venture}

# Cohort A (current)
{json.dumps(cohort_a_data, ensure_ascii=False, indent=2)[:2000]}

# Cohort B (previous, comparison baseline)
{json.dumps(cohort_b_data, ensure_ascii=False, indent=2)[:2000]}

# Refund data
{json.dumps(refunds, ensure_ascii=False, indent=2)[:2000]}

# Task

## 1. Metric deltas
So sánh metrics critical giữa A vs B:
- Conversion rate (frontend → tier mid)
- Refund rate
- NPS (Net Promoter Score)
- Completion rate (modules finished)
- Churn rate

Mỗi metric: value_a, value_b, delta_pct, verdict (improved/stable/declined).

## 2. Refund causal loop analysis
Mỗi refund reason → identify Stage trong framework v2 đã caused:
- Stage 3 Niche (wrong audience)
- Stage 5 Demand (no PMF)
- Stage 9 Offer (mismatch value/price)
- Stage 11 Content (misleading promise)
- Stage 14 Funnel (wrong flow)
- Stage 15 Delivery (poor delivery)

Per refund: loop_back_agent gợi ý agent nào cần fix (niche_validator/offer_engineer/bc10/etc).

## 3. Differential score
-10 (cohort A declined dramatically) → 10 (cohort A improved dramatically).

## 4. Key recommendations
3-5 actions concrete cho cohort tiếp theo.

# Quality requirements
- KHÔNG bịa metric không có data
- Specific delta % với reasoning
- Recommendations actionable

Output qua tool submit_cohort_comparison.
"""


class OverlayACohortComparison(BaseBC):
    """Overlay A Cohort Comparison (BC3 enhance per Sprint 13 P1.5)."""

    name = "overlay_a_cohort_comparison"
    scope = "Cohort A-B comparison + refund causal loop (Overlay A Anti-fragility)"
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
        cohort_a_data = payload.get("cohort_a", {})
        cohort_b_data = payload.get("cohort_b", {})
        refunds = payload.get("refunds", [])

        if not cohort_a_data or not cohort_b_data:
            # Auto-retrieve last 2 cohorts from memory
            cohort_a_data, cohort_b_data = await self._retrieve_cohorts(venture)

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "ANTHROPIC_API_KEY chưa set"},
            )

        prompt = build_comparison_prompt(venture, cohort_a_data, cohort_b_data, refunds)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_COMPARISON_TOOL],
                tool_choice={"type": "tool", "name": "submit_cohort_comparison"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("overlay_a_cohort LLM fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        comparison = self._parse_response(response)
        if "error" in comparison:
            return AgentResult(success=False, output_text=comparison["error"], output_payload=comparison)

        diff_score = comparison.get("differential_score", 0)
        period_a = comparison.get("period_a_label", "?")
        period_b = comparison.get("period_b_label", "?")
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = f"cohort compare A={period_a} vs B={period_b} diff_score={diff_score}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(comparison, ensure_ascii=False)[:800],
            "keywords": ["cohort_comparison", venture, period_a, period_b],
            "tags": ["overlay_a", "cohort_comparison", venture, date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"overlay_a.cohort_compare {date_str} A={period_a} B={period_b}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=comparison,
            emitted_memories=[memory_entry],
        )

    async def _retrieve_cohorts(self, venture: str) -> tuple[dict, dict]:
        """Retrieve last 2 cohort data from memory."""
        if not self.memory.ready:
            return {}, {}
        try:
            records = await self.memory.retrieve(
                query=f"cohort feedback completion refund {venture}",
                categories=["venture_state", "task"],
                venture=venture if venture != "all" else None,
                k=20,
                max_age_days=90,
            )
            if not records:
                return {}, {}
            mid = len(records) // 2
            return (
                {"recent_records": [r.content[:200] for r in records[:mid]]},
                {"older_records": [r.content[:200] for r in records[mid:]]},
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("retrieve cohorts fail: %r", exc)
            return {}, {}

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_cohort_comparison"
            ):
                return block.input or {}
        return {"error": "No tool_use block"}
