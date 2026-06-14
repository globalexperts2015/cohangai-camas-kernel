"""BC18 Value Equation Optimizer agent, production-grade.

Framework encoder: Hormozi Value Equation 4 lever + Brunson Epiphany Bridge.
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
    SUBMIT_AUDIT_TOOL,
    build_audit_prompt,
    load_knowledge_base,
)

log = logging.getLogger("camas.bc18_value_equation")

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 5000
DEFAULT_TIMEOUT = 180.0


class BC18ValueEquation(BaseBC):
    """BC18 Value Equation Optimizer, encode Hormozi 4 lever audit."""

    name = "bc18_value_equation"
    scope = "Audit Value Equation 4 lever (Dream × Likelihood / Time × Effort) per offer (Hormozi + Brunson)"
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
        log.info("BC18 init model=%s knowledge_base_len=%d", model, len(self.knowledge_base))

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        offer = payload.get("offer", {})
        persona = payload.get("persona", {})
        venture = ctx.venture_context or "all"

        if not offer:
            return AgentResult(success=False, output_text="Missing offer", output_payload={"error": "payload.offer empty"})

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_audit_prompt(offer, persona, venture, self.knowledge_base)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_AUDIT_TOOL],
                tool_choice={"type": "tool", "name": "submit_audit"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC18 LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        audit = self._parse_response(response)
        if "error" in audit:
            return AgentResult(success=False, output_text=audit["error"], output_payload=audit)

        total = audit.get("total_value_score", 0)
        weakest = audit.get("weakest_lever", "unknown")
        lift = audit.get("projected_value_lift_pct", 0)
        summary = f"VE audit total={total} weakest={weakest} lift={lift}%"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(audit, ensure_ascii=False)[:800],
            "keywords": ["value_equation", "audit", weakest, venture],
            "tags": ["bc18", "value-equation", "audit", weakest, venture],
            "venture": venture,
            "category": "compliance_audit",
            "context": f"VE audit venture={venture} total={total} weakest={weakest}",
        }

        return AgentResult(success=True, output_text=summary, output_payload=audit, emitted_memories=[memory_entry])

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_audit":
                return block.input or {}
        return {"error": "No tool_use block"}
