"""L2.3 Transformation Mapper 7D (NEW), Cohangai cohort 1 wizard.

Stage 6 framework v2. Map customer transformation across 7 dimensions:
1. Financial (Tài chính)
2. Time (Thời gian)
3. Skills (Kỹ năng)
4. Confidence (Tự tin)
5. Identity (Định danh)
6. Relationships (Mối quan hệ)
7. Health (Sức khoẻ)

Trigger event: cohort.transformation_map
Output: 7D before-after map + tangible vs intangible split + emotional + financial benefit cluster.
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

log = logging.getLogger("camas.l2_transformation_mapper_7d")

EXPECTED_EVENTS = {"cohort.transformation_map"}

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 4500
DEFAULT_TIMEOUT = 120.0


SUBMIT_TRANSFORMATION_TOOL = {
    "name": "submit_transformation_7d",
    "description": "Submit 7D transformation map cho customer của student",
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "string"},
            "venture": {"type": "string"},
            "customer_persona": {"type": "string"},
            "d1_financial_before": {"type": "string"},
            "d1_financial_after": {"type": "string"},
            "d1_financial_metrics": {"type": "string", "description": "Specific number/timeline"},
            "d2_time_before": {"type": "string"},
            "d2_time_after": {"type": "string"},
            "d2_time_metrics": {"type": "string"},
            "d3_skills_before": {"type": "string"},
            "d3_skills_after": {"type": "string"},
            "d3_skills_metrics": {"type": "string"},
            "d4_confidence_before": {"type": "string"},
            "d4_confidence_after": {"type": "string"},
            "d4_confidence_metrics": {"type": "string"},
            "d5_identity_before": {"type": "string"},
            "d5_identity_after": {"type": "string"},
            "d5_identity_metrics": {"type": "string"},
            "d6_relationships_before": {"type": "string"},
            "d6_relationships_after": {"type": "string"},
            "d6_relationships_metrics": {"type": "string"},
            "d7_health_before": {"type": "string"},
            "d7_health_after": {"type": "string"},
            "d7_health_metrics": {"type": "string"},
            "tangible_benefits": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tangible measurable (financial + time + skills)",
            },
            "intangible_benefits": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Intangible (confidence + identity + relationships)",
            },
            "primary_dream_outcome": {
                "type": "string",
                "description": "Hormozi Dream Outcome (specific + measurable + timeline)",
            },
            "transformation_arc_summary": {
                "type": "string",
                "description": "1-paragraph narrative arc Before → Bridge → After",
            },
            "markdown_visual_map": {
                "type": "string",
                "description": "Markdown table 7D before/after cho student dashboard",
            },
            "summary": {"type": "string"},
        },
        "required": [
            "student_id",
            "venture",
            "customer_persona",
            "primary_dream_outcome",
            "transformation_arc_summary",
            "markdown_visual_map",
            "summary",
        ],
    },
}


def build_transformation_prompt(student_id: str, customer_persona: str, vision_context: dict, niche_context: dict) -> str:
    return f"""Bạn là Transformation Mapper Coach cho Cohangai Cohort 1 student, applying Stage 6 framework v2.

Triết lý: Customer KHÔNG mua giải pháp. Customer mua TRANSFORMATION across 7 dimensions of life.

# Student
ID: {student_id}

# Customer persona target
{customer_persona}

# Vision context (L2.1 output)
{json.dumps(vision_context, ensure_ascii=False, indent=2)[:1500]}

# Niche context (L2.2 output)
{json.dumps(niche_context, ensure_ascii=False, indent=2)[:1500]}

# Task

Map transformation across 7 dimensions cho customer của student:

## 7 Dimensions

### D1: Financial (Tài chính)
- Before: financial state hiện tại
- After: financial state sau khi mua + áp dụng
- Metrics: specific number + timeline

### D2: Time (Thời gian)
- Before: time allocation hiện tại
- After: time allocation sau khi áp dụng
- Metrics: hours/week saved hoặc gained

### D3: Skills (Kỹ năng)
- Before: skill level hiện tại
- After: skill level sau khi học
- Metrics: skill acquired specific

### D4: Confidence (Tự tin)
- Before: confidence level + bằng chứng (mất ngủ, tự ti, không dám pitch)
- After: confidence level + bằng chứng (pitch confident, ngủ ngon)
- Metrics: behavioral marker

### D5: Identity (Định danh)
- Before: identity hiện tại ("nhân viên VP", "mẹ bỉm")
- After: identity mới ("solo founder", "AI Solo Empire architect")
- Metrics: how others see them differently

### D6: Relationships (Mối quan hệ)
- Before: family/friend/peer relationship state
- After: relationship improved/expanded
- Metrics: specific relationship outcome

### D7: Health (Sức khoẻ)
- Before: physical/mental health state
- After: improved health from less stress + better work-life
- Metrics: sleep/energy/stress markers

## Tangible vs Intangible cluster
- Tangible (D1-D3): measurable financial + time + skill
- Intangible (D4-D7): confidence + identity + relationships + health

## Primary Dream Outcome (Hormozi format)
Specific + measurable + timeline. Sample:
"Có thêm 15-20tr/tháng từ Shopify trong 6 tháng, giảm 30h/tuần ops, được gia đình ủng hộ"

## Transformation arc summary
1-paragraph narrative Before → Bridge (your offer) → After.

## Markdown visual map
Format dashboard-friendly:
```
| Dimension | Before | After | Metric |
|---|---|---|---|
| Financial | ... | ... | ... |
...
```

# Quality requirements
- KHÔNG generic ("better life"), MUST cụ thể với data
- Match customer_persona + vision/niche context
- Numbers + timeline mọi metric
- KHÔNG em-dash, no forbidden term

Output qua tool submit_transformation_7d.
"""


class L2TransformationMapper7D(BaseBC):
    """L2.3 Transformation Mapper 7D (NEW)."""

    name = "l2_transformation_mapper_7d"
    scope = "Map customer transformation 7D Stage 6 cho Cohangai cohort 1 student (NEW wizard)"
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
        student_id = payload.get("student_id", "unknown")
        customer_persona = payload.get("customer_persona", "").strip()
        vision_context = payload.get("vision_context", {})
        niche_context = payload.get("niche_context", {})

        if not customer_persona:
            return AgentResult(
                success=False,
                output_text="Missing customer_persona",
                output_payload={"error": "customer_persona empty"},
            )

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "LLM not ready"},
            )

        prompt = build_transformation_prompt(student_id, customer_persona, vision_context, niche_context)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_TRANSFORMATION_TOOL],
                tool_choice={"type": "tool", "name": "submit_transformation_7d"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("l2_transformation_mapper LLM fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        dream = result.get("primary_dream_outcome", "")[:80]
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = f"transformation_7d student={student_id} dream='{dream}'"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:800],
            "keywords": ["transformation_7d", "cohort_1", student_id, customer_persona[:50]],
            "tags": ["l2", "transformation_mapper", "stage_6", "cohort_1", date_str],
            "venture": ctx.venture_context or "cohangai",
            "category": "profile",
            "context": f"cohort.transformation_map {date_str} student={student_id}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=result,
            emitted_memories=[memory_entry],
        )

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_transformation_7d"
            ):
                return block.input or {}
        return {"error": "No tool_use block"}
