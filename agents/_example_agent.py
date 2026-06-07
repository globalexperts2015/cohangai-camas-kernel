"""Example agent showing BaseBC contract.

KHÔNG dùng production. Chỉ để dev đọc nắm pattern khi viết Phong 02, BC6, vv.
"""
from __future__ import annotations

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)


class ExampleEchoAgent(BaseBC):
    """Echo lại trigger_event + injected memories. Sanity test full pipeline."""

    name = "example_echo"
    scope = "Echo trigger event + injected memory cho test e2e"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        summary = f"event={ctx.trigger_event} memories={len(ctx.injected_memories)}"
        return AgentResult(
            success=True,
            output_text=summary,
            output_payload={"echo": ctx.payload},
        )
