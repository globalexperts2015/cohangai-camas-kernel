"""BC11 Tròn Vuông VPC Builder agent, production-grade.

Framework encoder: Eagle Camp Tròn Vuông VPC (Phạm Thành Long) + Anna CIS Module 2 JTBD.

Input: customer_id + venture_context + persona_name (+ customer_data optional)
Output: Tròn Vuông canvas 6 component JSON (schema-validated)

Architecture notes:
- Knowledge base loaded từ knowledge_base.md tại constructor (giảm I/O per-run)
- Prompt template + tool schema isolated trong prompt_template.py (testable)
- requires_voice_gate=False (VPC = strategic doc, không phải customer-facing content)
- requires_compliance_gate=False (VPC = internal artifact)
- Memory retrieve canonical fact venture (target/audience/bio/venture_state) làm context
- Emit memory category=profile (persona-level canonical, queryable downstream BC14/BC16)

Trigger event: `vpc.build_canvas`
Autonomy L1 (auto, persona-level artifact).
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
    SUBMIT_CANVAS_TOOL,
    build_canvas_prompt,
    load_knowledge_base,
)

log = logging.getLogger("camas.bc11_vpc_builder")

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 3500
DEFAULT_TIMEOUT = 120.0


class BC11VPCBuilder(BaseBC):
    """BC11 Tròn Vuông VPC Builder, production-grade encoder Eagle Camp + CIS Module 2."""

    name = "bc11_vpc_builder"
    scope = "Build Tròn Vuông VPC canvas 6 component per persona (Eagle Camp VPC + CIS Module 2 JTBD)"
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
            "BC11 init model=%s knowledge_base_len=%d memory_ready=%s",
            model,
            len(self.knowledge_base),
            bool(memory and memory.ready),
        )

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        venture = ctx.venture_context or "all"
        payload = ctx.payload or {}
        persona_name = payload.get("persona_name", "Default persona")
        customer_data = payload.get("customer_data", {})

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM client chưa init",
                output_payload={"error": "ANTHROPIC_API_KEY chưa set"},
            )

        canonical_facts: list[dict] = []
        if self.memory and self.memory.ready:
            try:
                results = await self.memory.retrieve(
                    query=f"persona {persona_name} target audience venture {venture}",
                    categories=["target", "audience", "bio", "venture_state", "compliance_audit"],
                    venture=venture if venture != "all" else None,
                    k=10,
                )
                canonical_facts = [
                    {"category": r.category, "content": r.content}
                    for r in results
                ]
                log.info("BC11 retrieved %d canonical facts venture=%s", len(canonical_facts), venture)
            except Exception as exc:  # noqa: BLE001
                log.warning("BC11 memory retrieve fail: %r", exc)

        prompt = build_canvas_prompt(
            venture=venture,
            persona_name=persona_name,
            customer_data=customer_data,
            canonical_facts=canonical_facts,
            knowledge_base=self.knowledge_base,
        )

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_CANVAS_TOOL],
                tool_choice={"type": "tool", "name": "submit_canvas"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC11 LLM call fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM call fail: {exc}",
                output_payload={"error": str(exc)},
            )

        canvas = self._parse_canvas(response)
        if "error" in canvas:
            return AgentResult(
                success=False,
                output_text=canvas["error"],
                output_payload=canvas,
            )

        fit_score = canvas.get("fit_score", 0)
        orphan_pains = canvas.get("orphan_pains", []) or []
        orphan_gains = canvas.get("orphan_gains", []) or []
        anna_match = canvas.get("anna_persona_match", "none")

        summary = (
            f"VPC canvas {persona_name} ({venture}) "
            f"fit={fit_score} orphans={len(orphan_pains)+len(orphan_gains)} "
            f"anna_match={anna_match}"
        )

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(canvas, ensure_ascii=False)[:800],
            "keywords": ["vpc", "canvas", persona_name, f"fit-{fit_score}"],
            "tags": ["bc11", "vpc", "tron-vuong", "persona", venture, f"fit-{fit_score}"],
            "venture": venture,
            "category": "profile",
            "context": f"VPC canvas persona={persona_name} venture={venture} fit={fit_score}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=canvas,
            emitted_memories=[memory_entry],
            escalation_required=fit_score < 60,
            escalation_reason=(
                f"VPC fit score {fit_score} < 60, persona-product mismatch, Anna review"
                if fit_score < 60
                else None
            ),
        )

    def _parse_canvas(self, response) -> dict:
        tool_block = None
        text_fallback = ""
        for block in response.content or []:
            block_type = getattr(block, "type", None)
            block_name = getattr(block, "name", None)
            if block_type == "tool_use" and block_name == "submit_canvas":
                tool_block = block
                break
            if block_type == "text":
                text_fallback += getattr(block, "text", "")

        if tool_block is None:
            return {
                "error": "No submit_canvas tool_use block",
                "raw_response": text_fallback[:500],
            }

        return tool_block.input or {}
