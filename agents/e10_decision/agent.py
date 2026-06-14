"""E10 Decision Engine. BreakoutOS CHỌN module Engine 8/9.

Pure deterministic aggregator. Combine 5 sub-scores với weights chốt từ spec:
  Founder Fit 20% + Customer Problem 25% + Market Demand 25% + Financial 20% + Lifestyle Fit 10%

Output Opportunity Score 0-100 + Classification + sensitivity analysis.
"""
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

log = logging.getLogger("camas.e10_decision")
EXPECTED_EVENTS = {"cohort.decision", "wizard.decision"}

WEIGHTS = {
    "founder_fit": 0.20,
    "customer_problem": 0.25,
    "market_demand": 0.25,
    "financial": 0.20,
    "lifestyle_fit": 0.10,
}


def classify_opportunity(score: int) -> str:
    if score >= 90:
        return "BUILD_IMMEDIATELY"
    if score >= 80:
        return "HIGH_PRIORITY"
    if score >= 60:
        return "TEST_FIRST"
    if score >= 40:
        return "RESEARCH_MORE"
    return "REJECT"


def compute_opportunity_score(sub_scores: dict) -> dict[str, Any]:
    """Aggregate 5 sub-scores với weights. Return full breakdown."""
    weighted_sum = 0.0
    breakdown = {}
    for engine, weight in WEIGHTS.items():
        sub_score = int(sub_scores.get(engine, 0) or 0)
        contribution = sub_score * weight
        weighted_sum += contribution
        breakdown[engine] = {
            "sub_score": sub_score,
            "weight_pct": int(weight * 100),
            "weighted_contribution": round(contribution, 1),
        }

    opportunity_score = round(weighted_sum)
    classification = classify_opportunity(opportunity_score)

    # Identify weakest + strongest engine
    weakest = min(WEIGHTS.keys(), key=lambda k: sub_scores.get(k, 0))
    strongest = max(WEIGHTS.keys(), key=lambda k: sub_scores.get(k, 0))

    # Sensitivity: bao nhiêu điểm có thể cải thiện nếu fix engine yếu nhất lên 80
    weak_score = int(sub_scores.get(weakest, 0))
    if weak_score < 80:
        improvement_potential = round((80 - weak_score) * WEIGHTS[weakest])
    else:
        improvement_potential = 0

    return {
        "opportunity_score": opportunity_score,
        "classification": classification,
        "breakdown": breakdown,
        "weakest_engine": weakest,
        "strongest_engine": strongest,
        "improvement_potential_if_fix_weakest": improvement_potential,
    }


class E10Decision(BaseBC):
    name = "e10_decision"
    scope = (
        "Decision Engine. Aggregate 5 sub-scores (Founder 20% + Problem 25% + Demand 25% + "
        "Financial 20% + Lifestyle 10%) → Opportunity Score 0-100 + GO/NO-GO classification."
    )
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(self, llm: LLMLayer, memory: Optional[MemoryLayer] = None):
        super().__init__()
        self.llm = llm
        self.memory = memory

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(success=False, output_text=f"unsupported event {event}",
                               output_payload={"supported": sorted(EXPECTED_EVENTS)})
        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")
        venture = ctx.venture_context or "cohangai"

        raw = payload.get("decision_input")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return AgentResult(success=False, output_text="decision_input must be valid JSON",
                                   output_payload={"error": "invalid_json"})
        else:
            parsed = payload

        sub_scores = parsed.get("sub_scores") or {}
        if not sub_scores:
            return AgentResult(
                success=False,
                output_text="missing sub_scores",
                output_payload={"error": "missing_sub_scores"},
            )

        result = compute_opportunity_score(sub_scores)
        score = result["opportunity_score"]
        classification = result["classification"]
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        mem = {
            "agent_name": self.name,
            "content_summary": f"decision student={student_id} opportunity_score={score} classification={classification}",
            "keywords": ["decision", "chon_module", student_id, classification, f"score-{score}"],
            "tags": ["e10", "decision", "chon_module", "engine_8_of_9", classification.lower(), date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"chon.decision {date_str} student={student_id} score={score} classification={classification}",
        }
        return AgentResult(
            success=True,
            output_text=f"e10_decision student={student_id} opportunity_score={score}/100 classification={classification}",
            output_payload=result,
            emitted_memories=[mem],
        )
