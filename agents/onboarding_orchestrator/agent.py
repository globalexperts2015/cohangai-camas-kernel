"""Onboarding Orchestrator agent.

Stage 10 enhance framework v2. Proactive 5-7 email onboarding sequence per
tier purchase + progress tracking dashboard. Trigger on customer payment
confirmed (event from breakout-zns or Sepay webhook).

Pre BC6/BC7 reactive answer FAQ. Onboarding orchestrator = PROACTIVE
welcome + setup + first action + check-in + completion celebrate.

Trigger events:
- onboarding.welcome_sequence (post-purchase Day 0)
- onboarding.progress_check (Day 3, 7, 14, 30 check-in)

Autonomy L1.
Output: 5-7 email sequence per tier + progress tracking JSON.
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

log = logging.getLogger("camas.onboarding_orchestrator")

EXPECTED_EVENTS = {"onboarding.welcome_sequence", "onboarding.progress_check"}

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 5500
DEFAULT_TIMEOUT = 180.0


SUBMIT_ONBOARDING_TOOL = {
    "name": "submit_onboarding_sequence",
    "description": "Submit proactive onboarding 5-7 email sequence + progress tracking",
    "input_schema": {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string"},
            "venture": {"type": "string"},
            "tier_purchased": {"type": "string", "description": "VIP/Foundation/Customer/Growth/Coaching"},
            "purchase_amount_vnd": {"type": "integer"},
            "email_sequence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "day": {"type": "integer"},
                        "subject": {"type": "string"},
                        "purpose": {"type": "string", "description": "welcome | setup | first_action | check_in | celebrate | upsell"},
                        "body_summary": {"type": "string"},
                        "cta": {"type": "string"},
                        "expected_action": {"type": "string"},
                    },
                },
                "description": "5-7 emails Day 0-30",
            },
            "first_quick_win_milestone": {
                "type": "object",
                "properties": {
                    "milestone": {"type": "string"},
                    "expected_day": {"type": "integer"},
                    "celebration_email_day": {"type": "integer"},
                },
            },
            "progress_tracking_metrics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string"},
                        "current_value": {"type": "string"},
                        "target_value": {"type": "string"},
                        "check_at_day": {"type": "integer"},
                    },
                },
            },
            "stuck_signals_to_alert_anna": {
                "type": "array",
                "items": {
                    "type": "string"
                },
                "description": "Signals that should escalate to Anna (low completion, no login 7d, etc.)",
            },
            "upsell_trigger_conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "condition": {"type": "string"},
                        "upsell_tier": {"type": "string"},
                        "trigger_day": {"type": "integer"},
                    },
                },
            },
            "summary": {"type": "string"},
        },
        "required": [
            "customer_id",
            "venture",
            "tier_purchased",
            "email_sequence",
            "first_quick_win_milestone",
            "progress_tracking_metrics",
            "summary",
        ],
    },
}


def build_onboarding_prompt(customer_id: str, venture: str, tier: str, purchase: dict, persona: dict) -> str:
    return f"""Bạn là Onboarding Orchestrator theo Stage 10 enhance framework v2.

Triết lý: BC6/BC7 reactive answer FAQ. Onboarding = PROACTIVE welcome + setup + first action + check-in + celebrate completion.

Mục đích:
1. Customer cảm thấy được care từ Day 0
2. Quick win Day 1-3 → engagement
3. First action Day 1 → momentum
4. Check-in Day 7+14 → catch stuck signals
5. Celebrate Day 14+30 → milestone unlock
6. Upsell opportunity Day 21+ nếu engagement cao

# Customer
ID: {customer_id}

# Venture
{venture}

# Tier purchased
{tier}

# Purchase details
{json.dumps(purchase, ensure_ascii=False, indent=2)[:1500]}

# Persona profile
{json.dumps(persona, ensure_ascii=False, indent=2)[:1500]}

# Task

Design 5-7 email proactive onboarding sequence Day 0-30:

## Email pattern per tier

### VIP 199k:
- Day 0: Welcome + access link
- Day 3: First action (watch buổi 1 replay)
- Day 7: Check-in
- Day 14: Upsell Foundation 3M nếu engaged

### Foundation 3M:
- Day 0: Welcome + login dashboard
- Day 1: Roadmap 30 ngày + first module unlock
- Day 3: First quick win check (template ready?)
- Day 7: Group call invite + accountability
- Day 14: Mid-checkpoint (50% done?)
- Day 21: Celebrate progress + Customer 6M soft pitch
- Day 30: Completion celebrate + testimonial ask

### Customer 6M / Growth 15M / Coaching 50M:
- Higher touch: 1on1 call invite Day 1
- Weekly check-in
- Quarterly retreat invite

## Output

1. **Email sequence** 5-7 emails Day 0-30 với:
   - day + subject + purpose + body_summary + cta + expected_action

2. **First Quick Win Milestone**:
   - Cụ thể (vd: "Build first Shopify product page")
   - Expected day (Day 1-3)
   - Celebration email day

3. **Progress tracking metrics** (3-5):
   - metric + current + target + check_at_day

4. **Stuck signals to alert Anna** (4-6):
   - "No login 7 days" / "Module completion < 20% Day 14" / etc.

5. **Upsell trigger conditions** (2-4):
   - Engagement-based (vd: completion >70% Day 14 → upsell Customer 6M)

# Quality requirements
- Pronoun "bạn"
- Email tone Anna voice (Hằng + bạn)
- Specific actions, KHÔNG generic
- Quick win achievable Day 1-3
- KHÔNG em-dash, no forbidden term

Output qua tool submit_onboarding_sequence.
"""


class OnboardingOrchestrator(BaseBC):
    """Onboarding Orchestrator, Stage 10 proactive enhance."""

    name = "onboarding_orchestrator"
    scope = "Proactive 5-7 email onboarding + progress tracking per tier (Stage 10 enhance)"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = True
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
                output_text=f"{self.name} không xử lý event này",
                output_payload={"trigger_event": event, "supported": list(EXPECTED_EVENTS)},
            )

        payload = ctx.payload or {}
        customer_id = payload.get("customer_id", "unknown")
        venture = ctx.venture_context or "breakout"
        tier = payload.get("tier_purchased", "Foundation")
        purchase = payload.get("purchase", {})
        persona = payload.get("persona", {})

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_onboarding_prompt(customer_id, venture, tier, purchase, persona)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_ONBOARDING_TOOL],
                tool_choice={"type": "tool", "name": "submit_onboarding_sequence"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("onboarding_orchestrator LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        plan = self._parse_response(response)
        if "error" in plan:
            return AgentResult(success=False, output_text=plan["error"], output_payload=plan)

        emails = len(plan.get("email_sequence", []))
        metrics = len(plan.get("progress_tracking_metrics", []))
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = f"onboarding customer={customer_id} tier={tier} emails={emails} metrics={metrics}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(plan, ensure_ascii=False)[:800],
            "keywords": ["onboarding", customer_id, tier, venture],
            "tags": ["onboarding_orchestrator", "stage_10", tier.lower(), venture, date_str],
            "venture": venture,
            "category": "task",
            "context": f"onboarding.{event.split('.')[-1]} {date_str} customer={customer_id} tier={tier}",
        }

        return AgentResult(success=True, output_text=summary, output_payload=plan, emitted_memories=[memory_entry])

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_onboarding_sequence":
                return block.input or {}
        return {"error": "No tool_use block"}
