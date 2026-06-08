"""BC20 Copy Stack Builder agent, production-grade.

Framework encoder: Dan Lok 8 Tactical Secrets + Brunson Soap Opera + Hormozi Hook-Retain-Reward.
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
    SUBMIT_COPY_STACK_TOOL,
    build_copy_prompt,
    load_knowledge_base,
)

log = logging.getLogger("camas.bc20_copy_stack")

DEFAULT_MODEL = "claude-opus-4-7"  # Opus cho copy quality
DEFAULT_MAX_TOKENS = 8000
DEFAULT_TIMEOUT = 240.0


class BC20CopyStack(BaseBC):
    """BC20 Copy Stack Builder, encode Dan Lok + Brunson Soap Opera + Hormozi Hook-Retain-Reward."""

    name = "bc20_copy_stack"
    scope = "Generate copy variants per format (Dan Lok 8 secrets + Brunson Soap Opera + Hormozi Hook-Retain-Reward)"
    autonomy_level = AutonomyLevel.L2_APPROVE  # Anna review trước publish
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = True  # Send through BC2 Voice Guardian downstream
    requires_compliance_gate = True

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
        log.info("BC20 init model=%s knowledge_base_len=%d", model, len(self.knowledge_base))

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        persona = payload.get("persona", {})
        offer = payload.get("offer", {})
        funnel_phase = payload.get("funnel_phase", "frontend")
        formats = payload.get("formats", ["reel", "email_sequence", "landing", "ad"])
        venture = ctx.venture_context or "all"

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_copy_prompt(persona, offer, funnel_phase, formats, venture, self.knowledge_base)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_COPY_STACK_TOOL],
                tool_choice={"type": "tool", "name": "submit_copy_stack"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC20 LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        stack = self._parse_response(response)
        if "error" in stack:
            return AgentResult(success=False, output_text=stack["error"], output_payload=stack)

        reels = len(stack.get("reel_variants", []))
        posts = len(stack.get("fb_post_variants", []))
        emails = len(stack.get("email_sequence_soap_opera", []))
        ads = len(stack.get("ad_variants", []))
        dna_score = stack.get("voice_dna_match_score", 0)
        passes = stack.get("passes_quality", True)
        summary = f"copy stack reels={reels} posts={posts} emails={emails} ads={ads} dna_score={dna_score} passes={passes}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(stack, ensure_ascii=False)[:800],
            "keywords": ["copy_stack", "copywriting", venture, funnel_phase],
            "tags": ["bc20", "copy", "copy-stack", funnel_phase, venture],
            "venture": venture,
            "category": "venture_state",
            "context": f"Copy stack venture={venture} phase={funnel_phase} dna_score={dna_score}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=stack,
            emitted_memories=[memory_entry],
            escalation_required=not passes,
            escalation_reason=(
                f"Copy stack quality_check failed dna_score={dna_score}" if not passes else None
            ),
        )

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_copy_stack":
                return block.input or {}
        return {"error": "No tool_use block"}
