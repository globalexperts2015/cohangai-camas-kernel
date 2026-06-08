"""BC12 8 Levels Consciousness Tracker agent, production-grade.

Framework encoder: Eagle Camp 8 cấp ý thức khách hàng (Phạm Thành Long).

Input: customer_id + recent_messages (list of text) + meta
Output: consciousness level 1-8 + secondary + confidence + recommended register + sample headline

Trigger event: `consciousness.classify`
Output category: `task` (per-customer state)
Autonomy L1.
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
    SUBMIT_CLASSIFICATION_TOOL,
    build_classify_prompt,
    load_knowledge_base,
)

log = logging.getLogger("camas.bc12_consciousness_tracker")

DEFAULT_MODEL = "claude-haiku-4-5"  # Batch classify, không cần Opus
DEFAULT_MAX_TOKENS = 1500
DEFAULT_TIMEOUT = 60.0


class BC12ConsciousnessTracker(BaseBC):
    """BC12 8 Levels Consciousness Tracker, production-grade encoder Eagle Camp."""

    name = "bc12_consciousness_tracker"
    scope = "Classify customer consciousness level 1-8 (Eagle Camp 8 cấp ý thức)"
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
            "BC12 init model=%s knowledge_base_len=%d",
            model,
            len(self.knowledge_base),
        )

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        customer_id = payload.get("customer_id", "unknown")
        messages = payload.get("messages", [])
        customer_meta = payload.get("meta", {})

        if not messages or not isinstance(messages, list):
            return AgentResult(
                success=False,
                output_text="Missing messages",
                output_payload={"error": "payload.messages list rỗng"},
            )

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "ANTHROPIC_API_KEY chưa set"},
            )

        prompt = build_classify_prompt(messages, customer_meta, self.knowledge_base)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_CLASSIFICATION_TOOL],
                tool_choice={"type": "tool", "name": "submit_classification"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC12 LLM fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        level = result.get("primary_level", 0)
        confidence = result.get("confidence", 0)
        cluster = result.get("language_cluster", "unknown")
        summary = f"consciousness level={level} confidence={confidence} cluster={cluster} customer={customer_id}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:500],
            "keywords": ["consciousness", f"level-{level}", cluster, customer_id],
            "tags": ["bc12", "consciousness", f"level-{level}", cluster, f"confidence-{confidence}"],
            "venture": ctx.venture_context or "all",
            "category": "task",
            "context": f"Consciousness customer={customer_id} level={level} cluster={cluster}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=result,
            emitted_memories=[memory_entry],
        )

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_classification":
                return block.input or {}
        return {"error": "No tool_use block in response"}
