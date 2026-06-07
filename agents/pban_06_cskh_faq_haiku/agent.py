"""Phòng 06 CSKH FAQ Haiku, thin alias cho BC6.

Anna chốt 2026-06-06 evening Perth: Phòng 06 và BC6 là cùng 1 agent, dual-naming
chỉ vì lịch sử kiến trúc (Funnel OS perspective vs BC layer perspective). Codebase
canonical = `agents/bc6_cskh_faq_haiku/`.

Agent này tồn tại để kernel scheduler tra cứu name `pban_06_cskh_faq_haiku` không
fail, trả về AgentResult success=False kèm hướng dẫn route lại tới BC6.
"""
from __future__ import annotations

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer


class Pban06CSKHFAQHaiku(BaseBC):
    """Alias mỏng, route caller tới bc6_cskh_faq_haiku."""

    name = "pban_06_cskh_faq_haiku"
    scope = "Alias Funnel OS Phòng 06, canonical = BC6 CSKH FAQ Haiku"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(self, llm: LLMLayer, memory: MemoryLayer) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        message = (
            "pban_06 chỉ là alias của BC6, route trực tiếp đến "
            "bc6_cskh_faq_haiku"
        )
        return AgentResult(
            success=False,
            output_text=message,
            output_payload={
                "alias_for": "bc6_cskh_faq_haiku",
                "trigger_event": ctx.trigger_event,
            },
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": message,
                    "keywords": ["alias", "bc6", "redirect"],
                    "tags": ["alias_redirect", "bc6_or_bc9"],
                    "venture": ctx.venture_context,
                    "context": "alias_redirect to bc6_cskh_faq_haiku",
                }
            ],
        )
