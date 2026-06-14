"""BC14 Joy/Gain Mapper agent, production-grade.

Framework encoder: Anna CIS Module 4 + Tròn Vuông Gains 4 loại + Hormozi Dream Outcome.
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
    SUBMIT_JOY_MATRIX_TOOL,
    build_joy_prompt,
    load_knowledge_base,
)

log = logging.getLogger("camas.bc14_joy_mapper")

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 3000
DEFAULT_TIMEOUT = 90.0


class BC14JoyMapper(BaseBC):
    """BC14 Joy/Gain Mapper, production-grade."""

    name = "bc14_joy_mapper"
    scope = "Map Joy/Gain 1:1 với Pain matrix (CIS Module 4 + Tròn Vuông Gains + Hormozi Dream Outcome)"
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
        log.info(
            "BC14 init model=%s knowledge_base_len=%d",
            model,
            len(self.knowledge_base),
        )

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        pain_matrix = payload.get("pain_matrix", {})
        persona_context = payload.get("persona_context", {})
        venture = ctx.venture_context or "all"

        if not pain_matrix or not pain_matrix.get("pains_by_type"):
            return AgentResult(
                success=False,
                output_text="Missing pain_matrix",
                output_payload={"error": "payload.pain_matrix empty"},
            )

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_joy_prompt(pain_matrix, persona_context, venture, self.knowledge_base)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_JOY_MATRIX_TOOL],
                tool_choice={"type": "tool", "name": "submit_joy_matrix"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC14 LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        matrix = self._parse_response(response)
        if "error" in matrix:
            return AgentResult(success=False, output_text=matrix["error"], output_payload=matrix)

        dream = matrix.get("primary_dream_outcome", "")
        wow = matrix.get("wow_factor", "")
        passes = matrix.get("passes_quality", True)
        pairs = len(matrix.get("pain_to_joy_pairs", []))
        summary = f"joy matrix dream={dream[:60]} wow={wow[:40]} pairs={pairs} passes={passes}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(matrix, ensure_ascii=False)[:800],
            "keywords": ["joy", "gain", "dream_outcome", venture],
            "tags": ["bc14", "joy", "gain", "tron-vuong", venture],
            "venture": venture,
            "category": "profile",
            "context": f"Joy/Gain matrix venture={venture} dream={dream[:80]}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=matrix,
            emitted_memories=[memory_entry],
            escalation_required=not passes,
            escalation_reason=(
                "Joy matrix quality_check failed, review needed" if not passes else None
            ),
        )

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_joy_matrix":
                return block.input or {}
        return {"error": "No tool_use block"}
