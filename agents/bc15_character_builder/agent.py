"""BC15 Attractive Character Builder agent, production-grade.

Framework encoder: Brunson Attractive Character 5 elements + Dan Lok Personal Brand + Anna 31 story pool.
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
    SUBMIT_CHARACTER_TOOL,
    build_character_prompt,
    load_knowledge_base,
)

log = logging.getLogger("camas.bc15_character_builder")

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 3500
DEFAULT_TIMEOUT = 120.0


class BC15CharacterBuilder(BaseBC):
    """BC15 Attractive Character Builder, production-grade."""

    name = "bc15_character_builder"
    scope = "Build Attractive Character profile 5 elements per founder (Brunson + Dan Lok + Anna 31 story pool)"
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
            "BC15 init model=%s knowledge_base_len=%d",
            model,
            len(self.knowledge_base),
        )

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        founder_data = payload.get("founder_data", {})
        venture = ctx.venture_context or "all"

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        story_pool: list[dict] = []
        if self.memory and self.memory.ready:
            try:
                results = await self.memory.retrieve(
                    query=f"founder story venture {venture}",
                    categories=["bio"],
                    venture=venture if venture != "all" else None,
                    k=20,
                )
                for r in results:
                    tier = "public_safe"
                    for t in r.tags or []:
                        if t.startswith("tier-"):
                            tier = t.replace("tier-", "")
                            break
                    story_pool.append({
                        "tier": tier,
                        "title": r.content[:150],
                        "content": r.content,
                    })
                log.info("BC15 retrieved %d stories venture=%s", len(story_pool), venture)
            except Exception as exc:  # noqa: BLE001
                log.warning("BC15 memory retrieve fail: %r", exc)

        prompt = build_character_prompt(founder_data, story_pool, venture, self.knowledge_base)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_CHARACTER_TOOL],
                tool_choice={"type": "tool", "name": "submit_character"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC15 LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        character = self._parse_response(response)
        if "error" in character:
            return AgentResult(success=False, output_text=character["error"], output_payload=character)

        identity = character.get("identity", "Reluctant Hero")
        founder = character.get("founder_name", "unknown")
        quality = character.get("quality_check", {}) or {}
        passes = quality.get("passes_quality", True)
        summary = f"character founder={founder} identity={identity} venture={venture} passes={passes}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(character, ensure_ascii=False)[:800],
            "keywords": ["character", identity.lower().replace(" ", "_"), founder, venture],
            "tags": ["bc15", "character", "attractive-character", identity.lower().replace(" ", "_"), venture],
            "venture": venture,
            "category": "profile",
            "context": f"Attractive Character founder={founder} venture={venture} identity={identity}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=character,
            emitted_memories=[memory_entry],
            escalation_required=not passes,
            escalation_reason=(
                "Character quality_check failed (story leak/forbidden term/missing element)" if not passes else None
            ),
        )

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_character":
                return block.input or {}
        return {"error": "No tool_use block"}
