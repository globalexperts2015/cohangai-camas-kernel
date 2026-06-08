"""L2.5 MVO Cohort Launcher (NEW), Cohangai cohort 1 week 5-6.

Stage 8 framework v2 Minimum Viable Offer (MVO) cohort approach.
Design + launch student's first paid cohort (5-15 customer) trong 30 days.

Trigger event: cohort.mvo_launch_plan
Output: cohort launch playbook (price + duration + delivery + waitlist + first 30d plan).
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

log = logging.getLogger("camas.l2_mvo_cohort_launcher")
EXPECTED_EVENTS = {"cohort.mvo_launch_plan"}
DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 5000
DEFAULT_TIMEOUT = 150.0


SUBMIT_MVO_TOOL = {
    "name": "submit_mvo_cohort_plan",
    "description": "Submit MVO cohort launch plan",
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "string"},
            "venture": {"type": "string"},
            "mvo_name": {"type": "string", "description": "MAGIC formula name"},
            "mvo_price_vnd": {"type": "integer"},
            "mvo_duration": {"type": "string", "description": "vd: 6 tuần / 30 ngày"},
            "cohort_size_target": {"type": "integer", "description": "5-15 typical"},
            "deliverable_format": {"type": "string", "description": "weekly live + group call + 1on1 / async / hybrid"},
            "core_deliverables": {"type": "array", "items": {"type": "string"}},
            "weekly_curriculum": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "week": {"type": "integer"},
                        "topic": {"type": "string"},
                        "deliverable": {"type": "string"},
                    },
                },
            },
            "waitlist_strategy": {"type": "string", "description": "Cách build waitlist 50-100 trước launch"},
            "first_30d_action_plan": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "day_range": {"type": "string"},
                        "action": {"type": "string"},
                        "deliverable": {"type": "string"},
                    },
                },
            },
            "revenue_forecast_vnd": {"type": "integer"},
            "risk_factors": {"type": "array", "items": {"type": "string"}},
            "markdown_playbook": {"type": "string", "description": "Full Markdown playbook student dashboard"},
            "summary": {"type": "string"},
        },
        "required": ["student_id", "mvo_name", "mvo_price_vnd", "cohort_size_target", "weekly_curriculum", "first_30d_action_plan", "markdown_playbook", "summary"],
    },
}


def build_mvo_prompt(student_id: str, vision: dict, niche: dict, transformation: dict, vpc: dict) -> str:
    return f"""Bạn là MVO Cohort Launcher Coach Cohangai Cohort 1, applying Stage 8 framework v2.

Triết lý: Student KHÔNG build empire trước khi launch first cohort. MVO (Minimum Viable Offer) =
5-15 customer trong 30 ngày để validate offer + tạo case study + có cash flow.

# Student
{student_id}

# Vision (L2.1)
{json.dumps(vision, ensure_ascii=False, indent=2)[:1000]}

# Niche (L2.2)
{json.dumps(niche, ensure_ascii=False, indent=2)[:1000]}

# Transformation (L2.3)
{json.dumps(transformation, ensure_ascii=False, indent=2)[:1000]}

# VPC fit (L2.4)
{json.dumps(vpc, ensure_ascii=False, indent=2)[:1000]}

# Task

Design + launch MVO cohort:

## 1. MVO name (MAGIC formula)
Magnetic + Avatar + Goal + Indicator + Container

## 2. MVO price (VND)
Price test cohort thấp hơn full version sau (vd: cohort 1 founding 1.5M vs sau 3M).

## 3. Duration
6 tuần typical (đủ deliver transformation, vừa đủ commitment student handle).

## 4. Cohort size (5-15)
Số nhỏ để student có thể serve high-touch + thu feedback.

## 5. Deliverable format
- Weekly live call (60-90 phút)
- Group community (Telegram/Slack)
- 1on1 1-2 lần trong cohort
- Async support email/DM

## 6. Core deliverables (3-5)
Tangible artifacts customer nhận sau cohort.

## 7. Weekly curriculum (per week topic + deliverable)

## 8. Waitlist strategy (50-100 trước launch)
- Free content tease (Stage 11 Content Pyramid)
- Email opt-in capture
- Free workshop / case study presentation
- 1on1 discovery call

## 9. First 30 day action plan
Day 1-7: announce + open waitlist
Day 8-15: enroll first 5
Day 16-22: enroll next 5-10
Day 23-30: kick-off cohort + first deliverable

## 10. Revenue forecast
cohort_size_target × mvo_price = expected revenue.

## 11. Risk factors (3-5)
- Underdelivery risk
- Refund risk
- Quality consistency

## 12. Markdown playbook (full dashboard)

# Quality requirements
- Pronoun "bạn"
- Concrete number + timeline
- KHÔNG em-dash

Output qua tool submit_mvo_cohort_plan.
"""


class L2MVOCohortLauncher(BaseBC):
    name = "l2_mvo_cohort_launcher"
    scope = "MVO cohort launch playbook Stage 8 (NEW wizard cohort 1 week 5-6)"
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
        vision = payload.get("vision", {})
        niche = payload.get("niche", {})
        transformation = payload.get("transformation", {})
        vpc = payload.get("vpc", {})

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_mvo_prompt(student_id, vision, niche, transformation, vpc)
        try:
            response = await self.llm.client.messages.create(
                model=self.model, max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_MVO_TOOL],
                tool_choice={"type": "tool", "name": "submit_mvo_cohort_plan"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        price = result.get("mvo_price_vnd", 0)
        size = result.get("cohort_size_target", 0)
        revenue = result.get("revenue_forecast_vnd", price * size)
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:700],
            "keywords": ["mvo", "cohort_launch", "cohort_1", student_id],
            "tags": ["l2", "mvo_cohort_launcher", "stage_8", "cohort_1", date_str],
            "venture": ctx.venture_context or "cohangai",
            "category": "pricing",
            "context": f"cohort.mvo_launch_plan {date_str} student={student_id} price={price:,}vnd",
        }
        return AgentResult(success=True, output_text=f"mvo student={student_id} price={price:,} size={size} revenue={revenue:,}", output_payload=result, emitted_memories=[memory_entry])

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_mvo_cohort_plan":
                return block.input or {}
        return {"error": "No tool_use block"}
