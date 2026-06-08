"""BC17 Grand Slam Offer Builder agent, production-grade.

Framework encoder: Hormozi Grand Slam Offer + Brunson Stack Method + Dan Lok USP.
"""
from __future__ import annotations

import json
import logging
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

from .prompt_template import (
    SUBMIT_OFFER_TOOL,
    build_offer_prompt,
    load_knowledge_base,
)

log = logging.getLogger("camas.bc17_grand_slam_offer")

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 6000
DEFAULT_TIMEOUT = 180.0


class BC17GrandSlamOffer(BaseBC):
    """BC17 Grand Slam Offer Builder, encode Hormozi + Brunson + Dan Lok."""

    name = "bc17_grand_slam_offer"
    scope = "Build Grand Slam Offer per ladder tier (Hormozi + Brunson Stack Method + Dan Lok USP)"
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
        self.knowledge_base = load_knowledge_base()
        log.info("BC17 init model=%s knowledge_base_len=%d", model, len(self.knowledge_base))

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        persona = payload.get("persona", {})
        ladder_tier = payload.get("ladder_tier", {})
        pain_summary = payload.get("pain_summary", {})
        joy_summary = payload.get("joy_summary", {})
        venture = ctx.venture_context or "all"

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_offer_prompt(persona, ladder_tier, pain_summary, joy_summary, venture, self.knowledge_base)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_OFFER_TOOL],
                tool_choice={"type": "tool", "name": "submit_offer"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC17 LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        offer = self._parse_response(response)
        if "error" in offer:
            return AgentResult(success=False, output_text=offer["error"], output_payload=offer)

        ratio = offer.get("value_to_price_ratio", 0)
        magic = offer.get("magic_name", "")
        bonus_count = sum(1 for i in range(1, 8) if offer.get(f"bonus_{i}_name"))
        summary = f"offer {magic[:50]} value_ratio={ratio:.1f}x bonuses={bonus_count}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(offer, ensure_ascii=False)[:800],
            "keywords": ["offer", "grand_slam", magic[:50], venture],
            "tags": ["bc17", "offer", "grand-slam", "stack-method", venture],
            "venture": venture,
            "category": "pricing",
            "context": f"Grand Slam Offer venture={venture} magic={magic[:60]} ratio={ratio:.1f}x",
        }

        return AgentResult(success=True, output_text=summary, output_payload=offer, emitted_memories=[memory_entry])

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_offer":
                return block.input or {}
        return {"error": "No tool_use block"}
