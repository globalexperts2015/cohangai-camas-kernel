"""Value Creation Advisor agent.

Stage 4 framework v2. Recommend product type (Service / Physical / Digital /
Community) per persona + asset bank fit. KHÔNG generic suggest, MUST tailor
theo Anna's skills + audience pay pattern + market signal.

Trigger event: value.creation_advise
Autonomy L1.
Output: product type recommendation + 3 concrete product ideas + go-to-market path.
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

log = logging.getLogger("camas.value_creation_advisor")

EXPECTED_EVENTS = {"value.creation_advise"}

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 5000
DEFAULT_TIMEOUT = 150.0


SUBMIT_VALUE_ADVISE_TOOL = {
    "name": "submit_value_advice",
    "description": "Submit value creation advice 4-type recommendation",
    "input_schema": {
        "type": "object",
        "properties": {
            "venture": {"type": "string"},
            "founder_id": {"type": "string"},
            "primary_product_type": {
                "type": "string",
                "description": "service | physical_product | digital_product | community",
            },
            "primary_type_reasoning": {"type": "string"},
            "secondary_product_type": {"type": "string"},
            "service_fit_score": {"type": "integer", "minimum": 0, "maximum": 10},
            "service_pros": {"type": "array", "items": {"type": "string"}},
            "service_cons": {"type": "array", "items": {"type": "string"}},
            "physical_fit_score": {"type": "integer", "minimum": 0, "maximum": 10},
            "physical_pros": {"type": "array", "items": {"type": "string"}},
            "physical_cons": {"type": "array", "items": {"type": "string"}},
            "digital_fit_score": {"type": "integer", "minimum": 0, "maximum": 10},
            "digital_pros": {"type": "array", "items": {"type": "string"}},
            "digital_cons": {"type": "array", "items": {"type": "string"}},
            "community_fit_score": {"type": "integer", "minimum": 0, "maximum": 10},
            "community_pros": {"type": "array", "items": {"type": "string"}},
            "community_cons": {"type": "array", "items": {"type": "string"}},
            "top_3_product_ideas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "type": {"type": "string"},
                        "core_value_prop": {"type": "string"},
                        "target_persona": {"type": "string"},
                        "price_range_vnd": {"type": "string"},
                        "time_to_first_sale_estimate": {"type": "string"},
                        "asset_required": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "go_to_market_path": {
                "type": "object",
                "properties": {
                    "week_1_action": {"type": "string"},
                    "week_2_4_action": {"type": "string"},
                    "month_2_3_action": {"type": "string"},
                    "first_revenue_milestone_vnd": {"type": "integer"},
                },
            },
            "summary": {"type": "string"},
        },
        "required": [
            "venture",
            "founder_id",
            "primary_product_type",
            "primary_type_reasoning",
            "top_3_product_ideas",
            "go_to_market_path",
            "summary",
        ],
    },
}


def build_advise_prompt(founder_id: str, venture: str, asset_bank: dict, persona: dict, market_signal: dict) -> str:
    return f"""Bạn là Value Creation Advisor theo Stage 4 framework v2 Solo Business Growth System.

# Framework: 4 loại sản phẩm
1. **Service**: 1-on-1 coaching, consulting, agency. High touch, high price, low scale.
2. **Physical Product**: mỹ phẩm, thực phẩm, đồ tiêu dùng. Inventory + logistics complexity.
3. **Digital Product**: course, ebook, template, software. Infinite scale, low margin per unit.
4. **Community**: membership, mastermind, paid group. Recurring revenue, retention focus.

# Founder context
ID: {founder_id}
Venture: {venture}

# Asset Bank (output Stage 1.1 asset_bank_inventory)
{json.dumps(asset_bank, ensure_ascii=False, indent=2)[:2000]}

# Persona target (Stage 2 customer research)
{json.dumps(persona, ensure_ascii=False, indent=2)[:1500]}

# Market signal (Stage 1.3 + Stage 3 + Stage 5)
{json.dumps(market_signal, ensure_ascii=False, indent=2)[:1500]}

# Task

Recommend product type combination cho founder:

## 1. Score 4 types (0-10 each)
Based on:
- Asset fit (founder's skills + knowledge fit which type best)
- Persona pay pattern (audience prefer which type)
- Market signal demand (what's hot in market)
- Founder lifestyle constraint (time + capital + risk)

## 2. Primary + Secondary type
Pick highest-scoring as primary. Secondary optional cho diversification.

## 3. Top 3 product ideas
Concrete ideas from analysis:
- name + type + core_value_prop + target_persona
- price_range_vnd realistic Vietnamese market
- time_to_first_sale_estimate (days/weeks)
- asset_required (from asset bank)

## 4. Go-to-market path
- Week 1 action (validate idea, 1-3 customer interview)
- Week 2-4 action (MVO design, first cohort 5-15)
- Month 2-3 action (scale to next tier)
- first_revenue_milestone_vnd

# Decision principles

- Service = best cho beginning solo (high margin, no inventory, validate fast)
- Digital Product = best cho scale after service validated
- Physical = AVOID nếu founder no logistics experience
- Community = best cho post-validation continuity

# Quality requirements
- Honest scoring (KHÔNG bias type founder yêu thích)
- Reference asset bank specific items
- Recommendations actionable + measurable
- Vietnamese market reality check
- KHÔNG em-dash

Output qua tool submit_value_advice.
"""


class ValueCreationAdvisor(BaseBC):
    """Value Creation Advisor, Stage 4 framework v2."""

    name = "value_creation_advisor"
    scope = "Recommend 4-type product fit (service/physical/digital/community) per persona + asset (Stage 4)"
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
                output_payload={"trigger_event": event, "supported": list(EXPECTED_EVENTS)},
            )

        payload = ctx.payload or {}
        founder_id = payload.get("founder_id", "unknown")
        venture = ctx.venture_context or "breakout"
        asset_bank = payload.get("asset_bank", {})
        persona = payload.get("persona", {})
        market_signal = payload.get("market_signal", {})

        if not asset_bank and not persona:
            return AgentResult(
                success=False,
                output_text="Missing asset_bank or persona",
                output_payload={"error": "need asset_bank OR persona context"},
            )

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_advise_prompt(founder_id, venture, asset_bank, persona, market_signal)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_VALUE_ADVISE_TOOL],
                tool_choice={"type": "tool", "name": "submit_value_advice"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("value_creation_advisor LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        advice = self._parse_response(response)
        if "error" in advice:
            return AgentResult(success=False, output_text=advice["error"], output_payload=advice)

        primary = advice.get("primary_product_type", "?")
        ideas = len(advice.get("top_3_product_ideas", []))
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = f"value advice founder={founder_id} primary_type={primary} ideas={ideas}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(advice, ensure_ascii=False)[:800],
            "keywords": ["value_creation", "stage_4", founder_id, primary],
            "tags": ["value_creation_advisor", "stage_4", venture, primary, date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"value.creation_advise {date_str} founder={founder_id} primary={primary}",
        }

        return AgentResult(success=True, output_text=summary, output_payload=advice, emitted_memories=[memory_entry])

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_value_advice":
                return block.input or {}
        return {"error": "No tool_use block"}
