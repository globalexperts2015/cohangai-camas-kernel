"""BC19 Funnel 7 Phases Architect agent, production-grade.

Framework encoder: Brunson 7 Phases Funnel + Eagle Camp IPS 19 + Anna CIS Module 6.
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
    SUBMIT_FUNNEL_TOOL,
    build_funnel_prompt,
    load_knowledge_base,
)

log = logging.getLogger("camas.bc19_funnel_architect")

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 6000
DEFAULT_TIMEOUT = 180.0


class BC19FunnelArchitect(BaseBC):
    """BC19 Funnel 7 Phases Architect, encode Brunson + Eagle IPS + Anna CIS M6."""

    name = "bc19_funnel_architect"
    scope = "Design 7-phase funnel architecture per venture (Brunson 7 Phases + Eagle IPS 19 + Anna CIS M6)"
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
        log.info("BC19 init model=%s knowledge_base_len=%d", model, len(self.knowledge_base))

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        ladder = payload.get("ladder", {})
        offers = payload.get("offers", [])
        persona = payload.get("persona", {})
        venture = ctx.venture_context or "all"

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_funnel_prompt(ladder, offers, persona, venture, self.knowledge_base)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_FUNNEL_TOOL],
                tool_choice={"type": "tool", "name": "submit_funnel"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC19 LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        funnel = self._parse_response(response)
        if "error" in funnel:
            return AgentResult(success=False, output_text=funnel["error"], output_payload=funnel)

        ltv = funnel.get("total_expected_ltv_vnd", 0)
        entry = funnel.get("entry_point", "unknown")
        emails = funnel.get("phase_5_ascend_email_sequence", [])
        summary = f"funnel venture={venture} entry={entry} emails={len(emails)} LTV={ltv:,}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(funnel, ensure_ascii=False)[:800],
            "keywords": ["funnel", "7_phases", venture, entry],
            "tags": ["bc19", "funnel", "7-phases", venture, entry],
            "venture": venture,
            "category": "venture_state",
            "context": f"7-phase funnel venture={venture} entry={entry} LTV={ltv:,}",
        }

        return AgentResult(success=True, output_text=summary, output_payload=funnel, emitted_memories=[memory_entry])

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_funnel":
                return block.input or {}
        return {"error": "No tool_use block"}
