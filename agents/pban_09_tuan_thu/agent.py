"""Phòng 09 Tuân thủ, thin alias cho BC9.

Anna chốt 2026-06-06 evening Perth: Phòng 09 và BC9 là cùng 1 agent compliance
officer. Codebase canonical = `agents/bc9_compliance_officer/`. Agent này tồn
tại để kernel scheduler tra cứu name `pban_09_tuan_thu` không fail.
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


class Pban09TuanThu(BaseBC):
    """Alias mỏng, route caller tới bc9_compliance_officer."""

    name = "pban_09_tuan_thu"
    scope = "Alias Funnel OS Phòng 09, canonical = BC9 Compliance Officer"
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
            "pban_09 chỉ là alias của BC9, route trực tiếp đến "
            "bc9_compliance_officer"
        )
        return AgentResult(
            success=False,
            output_text=message,
            output_payload={
                "alias_for": "bc9_compliance_officer",
                "trigger_event": ctx.trigger_event,
            },
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": message,
                    "keywords": ["alias", "bc9", "redirect"],
                    "tags": ["alias_redirect", "bc6_or_bc9"],
                    "venture": ctx.venture_context,
                    "context": "alias_redirect to bc9_compliance_officer",
                }
            ],
        )
