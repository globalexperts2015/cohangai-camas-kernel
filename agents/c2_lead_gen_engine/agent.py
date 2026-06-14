"""C2 Lead Gen Engine subagent (BreakoutOS v3 Week 6).

Generate 30-day Lead Generation plan from customer profile (B1 output),
content engine output (C1 output), and student advantages.

Output: 1-3 primary channels chosen from {fb_personal, community, tiktok_reels,
youtube, seo_blog} + 30-day daily plan + 4 lead magnets final spec + Tally form
specs + tag logic + referral strategy + 4-stage funnel map.

Trigger events: cohort.lead_gen, wizard.lead_gen_engine
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
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
    SUBMIT_LEAD_GEN_TOOL,
    build_lead_gen_prompt,
    load_channel_strategies,
    load_lead_magnet_templates,
)

log = logging.getLogger("camas.c2_lead_gen_engine")

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 16384
DEFAULT_TIMEOUT = 480.0

EXPECTED_EVENTS = {"cohort.lead_gen", "wizard.lead_gen_engine"}


class C2LeadGenEngine(BaseBC):
    """C2 Lead Gen Engine, Cohort 1 BreakoutOS v3 Week 6.

    Inputs (qua ctx.payload):
        - student_id: str
        - customer_profile: dict (B1 output)
        - content_engine_output: dict (C1 output, gồm 4 lead magnet ideas)
        - student_advantages: dict (audience đã có ở đâu, FB friends, mailing list ...)
        - budget_monthly_vnd: int (default 0 nếu organic-only)

    Output: lead gen plan đầy đủ 30 ngày + tagging + funnel map.
    """

    name = "c2_lead_gen_engine"
    scope = (
        "Lead Generation plan 30 days + 5 channel strategy + 4 lead magnets + "
        "tagging logic + funnel map. BreakoutOS v3 Week 6."
    )
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    DEFAULT_MODEL = DEFAULT_MODEL
    EXPECTED_EVENTS = EXPECTED_EVENTS

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
        self.channel_kb = load_channel_strategies()
        self.magnet_kb = load_lead_magnet_templates()
        log.info(
            "C2 init model=%s channels=%d magnets=%d",
            model,
            len(self.channel_kb),
            len(self.magnet_kb),
        )

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(
                success=False,
                output_text=f"unsupported event {event}",
                output_payload={"supported": list(EXPECTED_EVENTS)},
            )

        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")

        # Bridge: support lead_gen_input string from /run-wizard route
        lead_gen_input = payload.get("lead_gen_input")
        if isinstance(lead_gen_input, str) and lead_gen_input.strip():
            import json as _json
            try:
                parsed = _json.loads(lead_gen_input)
                customer_profile = parsed.get("customer_profile", {}) or {}
                content_engine_output = parsed.get("content_engine_output", {}) or {}
                student_advantages = parsed.get("student_advantages", {}) or {}
                budget_monthly_vnd = int(parsed.get("budget_monthly_vnd", 0) or 0)
            except _json.JSONDecodeError:
                customer_profile = {"raw_description": lead_gen_input[:500]}
                content_engine_output = {}
                student_advantages = {"raw_description": lead_gen_input[:500]}
                budget_monthly_vnd = 0
        else:
            customer_profile = payload.get("customer_profile", {}) or {}
            content_engine_output = payload.get("content_engine_output", {}) or {}
            student_advantages = payload.get("student_advantages", {}) or {}
            budget_monthly_vnd = int(payload.get("budget_monthly_vnd", 0) or 0)
        venture = ctx.venture_context or "cohangai"

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "LLM not ready"},
            )

        prompt = build_lead_gen_prompt(
            student_id=student_id,
            customer_profile=customer_profile,
            content_engine_output=content_engine_output,
            student_advantages=student_advantages,
            budget_monthly_vnd=budget_monthly_vnd,
            channel_kb=self.channel_kb,
            magnet_kb=self.magnet_kb,
        )

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_LEAD_GEN_TOOL],
                tool_choice={"type": "tool", "name": "submit_lead_gen_plan"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("C2 LLM fail student=%s: %r", student_id, exc)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        plan = self._parse_response(response)
        if "error" in plan:
            return AgentResult(
                success=False, output_text=plan["error"], output_payload=plan
            )

        validation_err = self._validate_plan(plan)
        if validation_err:
            log.warning(
                "C2 validation fail student=%s err=%s", student_id, validation_err
            )
            return AgentResult(
                success=False,
                output_text=f"validation fail: {validation_err}",
                output_payload={"error": validation_err, "raw": plan},
            )

        primary_channels = plan.get("primary_channels", [])
        magnets = plan.get("lead_magnets_final", [])
        funnel = plan.get("funnel_map", {}) or {}
        awareness_target = (funnel.get("awareness") or {}).get("target_volume", 0)
        action_target = (funnel.get("action") or {}).get("target_volume", 0)

        summary = (
            f"c2_lead_gen student={student_id} "
            f"channels={','.join(primary_channels)} "
            f"magnets={len(magnets)} "
            f"funnel={awareness_target}->{action_target}"
        )

        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(plan, ensure_ascii=False)[:800],
            "keywords": [
                "lead_gen",
                "cohort_1",
                student_id,
                *primary_channels,
            ],
            "tags": [
                "c2",
                "lead_gen_engine",
                "breakoutos_v3",
                "week_6",
                "cohort_1",
                date_str,
            ],
            "venture": venture,
            "category": "venture_state",
            "context": (
                f"cohort.lead_gen {date_str} student={student_id} "
                f"channels={','.join(primary_channels)} magnets={len(magnets)}"
            ),
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=plan,
            emitted_memories=[memory_entry],
        )

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_lead_gen_plan"
            ):
                return block.input or {}
        return {"error": "No tool_use block submit_lead_gen_plan"}

    def _validate_plan(self, plan: dict) -> Optional[str]:
        """Light validation beyond JSON schema (count + non-empty)."""
        daily = plan.get("daily_plan_30d", [])
        if len(daily) != 30:
            return f"daily_plan_30d must have 30 items, got {len(daily)}"
        days = [d.get("day") for d in daily]
        if sorted(days) != list(range(1, 31)):
            return "daily_plan_30d days must cover 1..30 exactly once"
        magnets = plan.get("lead_magnets_final", [])
        if len(magnets) != 4:
            return f"lead_magnets_final must have 4 items, got {len(magnets)}"
        channels = plan.get("primary_channels", [])
        if not channels or len(channels) > 3:
            return f"primary_channels must be 1..3, got {len(channels)}"
        return None
