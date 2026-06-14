"""C1 Content Engine agent (BreakoutOS v3 Week 5).

Generates the full content pack per student:
- 7 pillars
- 100 reel ideas
- 30 FB posts
- 30 emails
- 30 blog topics
- 12 webinar topics
- 4 lead magnets
- 30-day calendar
- CTA matrix by 5 awareness levels

Inputs (ctx.payload):
- student_id: str
- customer_profile: dict
- offer: dict
- voice_register: str
- story_pool: list[str]

Output: AgentResult with full pack in output_payload + memory entry emitted.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

from .prompt_template import SUBMIT_CONTENT_PACK_TOOL, build_content_prompt
from .quality_lint import lint_content_pack

log = logging.getLogger("camas.c1_content_engine")

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 16384
DEFAULT_TIMEOUT = 600.0


class C1ContentEngine(BaseBC):
    """C1 Content Engine, BreakoutOS v3 Week 5 subagent."""

    name = "c1_content_engine"
    scope = (
        "Generate 100 Reel + 30 FB + 30 email + 30 blog + 12 webinar + 4 lead magnet "
        "+ 30-day calendar from customer profile + offer + voice. BreakoutOS v3 Week 5."
    )
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    EXPECTED_EVENTS: set[str] = {"cohort.content_engine", "wizard.content_engine"}

    def __init__(
        self,
        llm: LLMLayer,
        memory: Optional[MemoryLayer] = None,
        model: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model or DEFAULT_MODEL
        log.info("C1 init model=%s", self.model)

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        # 1. Validate event
        if ctx.trigger_event not in self.EXPECTED_EVENTS:
            return AgentResult(
                success=False,
                output_text=f"Unexpected trigger_event {ctx.trigger_event}",
                output_payload={
                    "error": "unexpected_event",
                    "expected": sorted(self.EXPECTED_EVENTS),
                    "got": ctx.trigger_event,
                },
            )

        # 2. Extract payload
        payload = ctx.payload or {}
        student_id: str = payload.get("student_id") or ""

        # Bridge: support both structured payload (programmatic) + content_input string (wizard route)
        content_input = payload.get("content_input")
        if isinstance(content_input, str) and content_input.strip():
            # Parse JSON if string, else treat as raw text
            import json as _json
            try:
                parsed = _json.loads(content_input)
                if isinstance(parsed, dict):
                    customer_profile = parsed.get("customer_profile") or {}
                    offer = parsed.get("offer") or {}
                    voice_register = parsed.get("voice_register") or "hang_webinar"
                    story_pool = parsed.get("story_pool") or []
                else:
                    customer_profile = {"raw_description": content_input}
                    offer = {"name": "BreakoutOS Cohort 1", "promise": "Build doanh nghiệp một người với AI"}
                    voice_register = "hang_webinar"
                    story_pool = []
            except _json.JSONDecodeError:
                # Plain text — treat as customer description, use sane defaults
                customer_profile = {"raw_description": content_input}
                offer = {"name": "BreakoutOS Cohort 1", "promise": "Build doanh nghiệp một người với AI"}
                voice_register = "hang_webinar"
                story_pool = [content_input[:200]]
        else:
            customer_profile = payload.get("customer_profile") or {}
            offer = payload.get("offer") or {}
            voice_register = payload.get("voice_register") or "hang_webinar"
            story_pool = payload.get("story_pool") or []

        if not student_id:
            return AgentResult(
                success=False,
                output_text="missing student_id",
                output_payload={"error": "missing_student_id"},
            )
        if not customer_profile:
            return AgentResult(
                success=False,
                output_text="missing customer_profile",
                output_payload={"error": "missing_customer_profile"},
            )
        if not offer:
            return AgentResult(
                success=False,
                output_text="missing offer",
                output_payload={"error": "missing_offer"},
            )

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "llm_not_ready"},
            )

        # 3. Build prompt
        prompt = build_content_prompt(
            student_id=student_id,
            customer_profile=customer_profile,
            offer=offer,
            voice_register=voice_register,
            story_pool=story_pool,
        )

        # 4. LLM call with tool schema (forced tool_choice)
        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_CONTENT_PACK_TOOL],
                tool_choice={"type": "tool", "name": "submit_content_pack"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("C1 LLM fail student=%s err=%r", student_id, exc)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        # 5. Parse tool_use result
        pack = self._parse_response(response)
        stop_reason = str(getattr(response, "stop_reason", ""))
        usage = getattr(response, "usage", None)
        if "error" in pack:
            text_dump = ""
            for block in response.content or []:
                if getattr(block, "type", None) == "text":
                    text_dump += getattr(block, "text", "")
            log.warning(
                "C1 parse fail student=%s stop_reason=%s usage=%s",
                student_id,
                stop_reason,
                usage,
            )
            if stop_reason == "max_tokens":
                pack["error"] = (
                    "Output quá dài cho tool. Hãy giảm scope (vd: pillars only, "
                    f"hoặc tăng max_tokens). stop_reason={stop_reason}"
                )
            return AgentResult(
                success=False,
                output_text=pack["error"],
                output_payload={
                    **pack,
                    "stop_reason": str(getattr(response, "stop_reason", "")),
                    "text_fallback": text_dump[:500],
                },
            )

        # 6. Quality lint
        passed, violations = lint_content_pack(pack)
        if not passed:
            log.warning(
                "C1 lint fail student=%s violations=%d sample=%s",
                student_id,
                len(violations),
                violations[:3],
            )

        # 7. Emit memory + return
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        venture = ctx.venture_context or "cohangai"
        summary = self._summarize(student_id, pack, passed, violations)

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(pack, ensure_ascii=False)[:700],
            "keywords": ["content", "cohort_1", student_id],
            "tags": [
                "c1",
                "content_engine",
                "stage_growth",
                "cohort_1",
                date_str,
            ],
            "venture": venture,
            "category": "content",
            "context": f"cohort.content_engine {student_id} {date_str}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload={
                "pack": pack,
                "lint_passed": passed,
                "lint_violations": violations,
                "student_id": student_id,
            },
            emitted_memories=[memory_entry],
            escalation_required=not passed,
            escalation_reason=(
                f"quality_lint advisory: {len(violations)} violations" if not passed else None
            ),
        )

    @staticmethod
    def _parse_response(response: Any) -> dict[str, Any]:
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_content_pack"
            ):
                data = block.input or {}
                if not data:
                    return {"error": "LLM tool_use returned empty input"}
                return data
        return {"error": "No tool_use block returned"}

    @staticmethod
    def _summarize(
        student_id: str,
        pack: dict[str, Any],
        passed: bool,
        violations: list[str],
    ) -> str:
        return (
            f"c1_content_engine student={student_id} "
            f"pillars={len(pack.get('pillars', []))} "
            f"reels={len(pack.get('reel_ideas', []))} "
            f"fb={len(pack.get('fb_posts', []))} "
            f"emails={len(pack.get('emails', []))} "
            f"blogs={len(pack.get('blog_topics', []))} "
            f"webinars={len(pack.get('webinar_topics', []))} "
            f"lead_magnets={len(pack.get('lead_magnets', []))} "
            f"calendar={len(pack.get('calendar_30d', []))} "
            f"lint={'pass' if passed else f'fail({len(violations)})'}"
        )
