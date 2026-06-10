"""E2 Scale Coach agent (BreakoutOS v3 Week 10).

Take state hiện tại student (customers, revenue, list size, NPS) → sinh 90-day
scale plan + recommended lever + templates + AI team structure + hire decision
tree.

Decision logic gate:
- current_customers < 15 → REJECT (Foundation lock), return static locked response
- 15-30 customers → recommended_lever = "webinar" (Brunson Perfect Webinar)
- 30-100 customers → recommended_lever = "referral" + membership combo
- 100+ customers → recommended_lever = "affiliate" + partnership

Trigger events: cohort.scale_coach, wizard.scale_coach
Autonomy L1 (auto, propose ready-to-execute plan, founder review).
Output: scale plan flat structure + 7 markdown templates available via filesystem.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

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
    SUBMIT_SCALE_PLAN_TOOL,
    build_locked_response,
    build_scale_plan_prompt,
    pick_lever_from_state,
)

log = logging.getLogger("camas.e2_scale_coach")

EXPECTED_EVENTS = {"cohort.scale_coach", "wizard.scale_coach"}

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 8192
DEFAULT_TIMEOUT = 240.0

FOUNDATION_LOCK_THRESHOLD = 15


class E2ScaleCoach(BaseBC):
    """Scale Coach 90-day plan từ 5-15 lên 50-100 khách."""

    name = "e2_scale_coach"
    scope = (
        "Scale Coach 90-day plan từ 5-15 lên 50-100 khách. "
        "Webinar + Membership + Referral + Affiliate + Upsell. BreakoutOS v3 Week 10."
    )
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        model: str = DEFAULT_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(
                success=False,
                output_text=f"unsupported event {event}",
                output_payload={"supported": sorted(EXPECTED_EVENTS)},
            )

        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")
        venture = ctx.venture_context or payload.get("venture", "cohangai")
        state = payload.get("state") or {}

        # Ensure state has required keys, default 0 if missing
        state.setdefault("current_customers", 0)
        state.setdefault("revenue_vnd_30d", 0)
        state.setdefault("list_size", 0)
        state.setdefault("nps", 0)

        current_customers = int(state.get("current_customers", 0) or 0)

        # Foundation lock gate (deterministic, không cần LLM)
        if current_customers < FOUNDATION_LOCK_THRESHOLD:
            locked = build_locked_response(state)
            date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            memory_entry = self._build_memory_entry(
                student_id=student_id,
                venture=venture,
                lever="LOCKED",
                result=locked,
                date_str=date_str,
                locked=True,
            )
            return AgentResult(
                success=True,
                output_text=(
                    f"e2_scale_coach student={student_id} LOCKED "
                    f"current_customers={current_customers} < {FOUNDATION_LOCK_THRESHOLD}"
                ),
                output_payload=locked,
                emitted_memories=[memory_entry],
            )

        # Unlocked → call LLM
        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "LLM not ready"},
            )

        prompt = build_scale_plan_prompt(student_id, venture, state)
        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_SCALE_PLAN_TOOL],
                tool_choice={"type": "tool", "name": "submit_scale_plan"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("e2_scale_coach LLM call failed student=%s", student_id)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(
                success=False,
                output_text=result["error"],
                output_payload=result,
            )

        # Post-process: enforce lever from state (anti-hallucination guard)
        rule_lever, _ = pick_lever_from_state(current_customers)
        if rule_lever != "LOCKED" and result.get("recommended_lever") not in {
            "webinar",
            "membership",
            "referral",
            "ads",
            "content_seo",
            "partnership",
        }:
            result["recommended_lever"] = rule_lever

        lever = result.get("recommended_lever", "?")
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        memory_entry = self._build_memory_entry(
            student_id=student_id,
            venture=venture,
            lever=lever,
            result=result,
            date_str=date_str,
            locked=False,
        )

        return AgentResult(
            success=True,
            output_text=(
                f"e2_scale_coach student={student_id} lever={lever} "
                f"customers={current_customers} venture={venture}"
            ),
            output_payload=result,
            emitted_memories=[memory_entry],
        )

    def _parse_response(self, response: Any) -> dict[str, Any]:
        """Extract tool_use block from Anthropic response."""
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_scale_plan"
            ):
                return block.input or {}
        return {"error": "No tool_use block submit_scale_plan in response"}

    def _build_memory_entry(
        self,
        *,
        student_id: str,
        venture: str,
        lever: str,
        result: dict[str, Any],
        date_str: str,
        locked: bool,
    ) -> dict[str, Any]:
        """Build CAMASMemoryMetadata-compatible dict for kernel auto-extract."""
        summary = json.dumps(result, ensure_ascii=False, default=str)[:700]
        tags = ["e2", "scale_coach", "breakoutos_v3_week_10", "cohort_1", date_str]
        if locked:
            tags.append("foundation_lock")
        return {
            "agent_name": self.name,
            "content_summary": summary,
            "keywords": ["scale_plan", "90day", student_id, lever],
            "tags": tags,
            "venture": venture,
            "category": "venture_state",
            "context": (
                f"cohort.scale_coach {date_str} student={student_id} "
                f"lever={lever} locked={locked}"
            ),
        }
