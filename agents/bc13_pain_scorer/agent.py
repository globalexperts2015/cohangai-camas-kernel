"""BC13 Pain Severity Scorer agent, production-grade.

Framework encoder: Anna CIS Module 3 (4 loại Pain + 3 rào cản + 3 rủi ro + 10 PDQ + Severity 10/10)
+ Hormozi Effort & Sacrifice (Value Equation denominator)
+ Dan Lok Pain > Pleasure (Tactical Secret #6).
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
    SUBMIT_PAIN_MATRIX_TOOL,
    build_pain_prompt,
    load_knowledge_base,
)

log = logging.getLogger("camas.bc13_pain_scorer")

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 2500
DEFAULT_TIMEOUT = 90.0


class BC13PainScorer(BaseBC):
    """BC13 Pain Severity Scorer, production-grade encoder CIS M3 + Hormozi + Dan Lok."""

    name = "bc13_pain_scorer"
    scope = "Score customer pain severity 4 loại × 1-10/10 (CIS Module 3 + Hormozi VE + Dan Lok)"
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
            "BC13 init model=%s knowledge_base_len=%d",
            model,
            len(self.knowledge_base),
        )

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        pain_text = payload.get("pain_text", "")
        customer_meta = payload.get("meta", {})
        context_data = payload.get("context", {})
        customer_id = customer_meta.get("customer_id", "unknown")

        if not pain_text or len(pain_text) < 10:
            return AgentResult(
                success=False,
                output_text="Pain text too short",
                output_payload={"error": "payload.pain_text < 10 chars"},
            )

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_pain_prompt(pain_text, customer_meta, context_data, self.knowledge_base)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_PAIN_MATRIX_TOOL],
                tool_choice={"type": "tool", "name": "submit_pain_matrix"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC13 LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        matrix = self._parse_response(response)
        if "error" in matrix:
            return AgentResult(success=False, output_text=matrix["error"], output_payload=matrix)

        max_sev = matrix.get("max_severity", 0)
        urgency = matrix.get("urgency_rank", "COLD")
        avg_sev = matrix.get("average_severity", 0)
        summary = f"pain max={max_sev} avg={avg_sev} urgency={urgency} customer={customer_id}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(matrix, ensure_ascii=False)[:800],
            "keywords": ["pain", f"severity-{max_sev}", urgency.lower(), customer_id],
            "tags": ["bc13", "pain", urgency.lower(), f"severity-{max_sev}"],
            "venture": ctx.venture_context or "all",
            "category": "task",
            "context": f"Pain matrix customer={customer_id} max_sev={max_sev} urgency={urgency}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=matrix,
            emitted_memories=[memory_entry],
            escalation_required=(urgency == "URGENT" and max_sev >= 9),
            escalation_reason=(
                f"Hot lead URGENT severity={max_sev}, alert Anna ngay"
                if urgency == "URGENT" and max_sev >= 9
                else None
            ),
        )

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_pain_matrix":
                return block.input or {}
        return {"error": "No tool_use block"}
