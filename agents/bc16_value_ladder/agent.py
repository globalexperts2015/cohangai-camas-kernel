"""BC16 Value Ladder Designer agent, production-grade.

Framework encoder: Brunson Value Ladder + Anna Empire Stack 5 tier + Eagle Camp CL5.
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
    SUBMIT_LADDER_TOOL,
    build_ladder_prompt,
    load_knowledge_base,
)

log = logging.getLogger("camas.bc16_value_ladder")

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 6000
DEFAULT_TIMEOUT = 180.0


class BC16ValueLadder(BaseBC):
    """BC16 Value Ladder Designer, encode Brunson + Anna Empire Stack + Eagle CL5."""

    name = "bc16_value_ladder"
    scope = "Design Value Ladder 3-5 tier per venture + persona (Brunson + Anna Empire Stack + Eagle CL5)"
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
        log.info("BC16 init model=%s knowledge_base_len=%d", model, len(self.knowledge_base))

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        persona = payload.get("persona", {})
        pain_summary = payload.get("pain_summary", {})
        joy_summary = payload.get("joy_summary", {})
        venture = ctx.venture_context or "all"

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_ladder_prompt(persona, pain_summary, joy_summary, venture, self.knowledge_base)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_LADDER_TOOL],
                tool_choice={"type": "tool", "name": "submit_ladder"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC16 LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        ladder = self._parse_response(response)
        if "error" in ladder:
            return AgentResult(success=False, output_text=ladder["error"], output_payload=ladder)

        total_value = ladder.get("total_ladder_value_vnd", 0)
        anna_match = ladder.get("anna_empire_stack_match", False)
        tier_count = sum(1 for i in range(1, 6) if ladder.get(f"tier_{i}_name"))
        summary = f"ladder venture={venture} tiers={tier_count} total_value={total_value:,} anna_match={anna_match}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(ladder, ensure_ascii=False)[:800],
            "keywords": ["ladder", "value_ladder", venture, f"total-{total_value}"],
            "tags": ["bc16", "ladder", "value-ladder", "empire-stack", venture],
            "venture": venture,
            "category": "pricing",
            "context": f"Value Ladder venture={venture} tiers={tier_count} total={total_value:,} VND",
        }

        return AgentResult(success=True, output_text=summary, output_payload=ladder, emitted_memories=[memory_entry])

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_ladder":
                return block.input or {}
        return {"error": "No tool_use block"}
