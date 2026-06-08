"""L2.7 Referral Engine Template (wrap P0.2 breakout-referral service).

Generate referral engine template cho student's venture. NOT deploy a new service
per student (too complex), instead generate playbook + tier config + scripts
for student to manually implement on their stack OR use shared breakout-referral
service với multi-tenant venture filter.

Trigger event: cohort.referral_engine_design
Output: Markdown playbook + commission tier suggestion + share script copy.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

log = logging.getLogger("camas.l2_referral_engine_template")
EXPECTED_EVENTS = {"cohort.referral_engine_design"}
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 3500
DEFAULT_TIMEOUT = 90.0


SUBMIT_REFERRAL_TEMPLATE_TOOL = {
    "name": "submit_referral_template",
    "description": "Submit referral engine template student-friendly",
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "string"},
            "venture": {"type": "string"},
            "implementation_path": {
                "type": "string",
                "description": "shared_service | self_implement | manual_track",
            },
            "commission_tiers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "min_referrals_year": {"type": "integer"},
                        "commission_pct": {"type": "number"},
                    },
                },
            },
            "share_link_structure": {"type": "string", "description": "URL pattern student dùng"},
            "incentive_for_referrer": {"type": "string"},
            "incentive_for_referred": {"type": "string"},
            "share_script_email": {"type": "string", "description": "Email template student gửi ask referral"},
            "share_script_dm": {"type": "string", "description": "DM template casual share"},
            "share_script_post": {"type": "string", "description": "Public post template"},
            "tracking_method": {"type": "string", "description": "Cookie + UTM | manual code | Google Form"},
            "payout_frequency": {"type": "string", "description": "monthly typical, weekly for high volume"},
            "expected_30d_referrals": {"type": "integer"},
            "expected_30d_revenue_vnd": {"type": "integer"},
            "markdown_playbook": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": [
            "student_id",
            "venture",
            "implementation_path",
            "commission_tiers",
            "share_script_email",
            "share_script_dm",
            "share_script_post",
            "markdown_playbook",
            "summary",
        ],
    },
}


def build_referral_prompt(student_id: str, venture: str, offer: dict, persona: dict) -> str:
    return f"""Bạn là Referral Engine Coach Cohangai Cohort 1 week 8 (capstone), applying Stage 17.5 framework v2 5th scale lever.

# Student
{student_id}

# Venture
{venture}

# Offer designed (L2.6)
{json.dumps(offer, ensure_ascii=False, indent=2)[:1500]}

# Persona (L2.4)
{json.dumps(persona, ensure_ascii=False, indent=2)[:1500]}

# Task

Design referral engine cho student's venture. Reference breakout-referral service architecture.

## 1. Implementation path (chọn 1)
- **shared_service**: dùng breakout-referral service multi-tenant với venture filter (FAST setup)
- **self_implement**: student tự build mini system (Notion + Google Form + Sepay manual)
- **manual_track**: spreadsheet tracking đơn giản (first 30-90 days)

Recommend dựa volume expected. <20 referral/tháng → manual OK. 20+ → shared_service.

## 2. Commission tiers (4-tier mặc định Bronze/Silver/Gold/Platinum)
Adjust pct theo venture margin. Service venture margin thấp → giảm pct.

## 3. Share link structure
URL pattern student dùng.

## 4. Incentives
- Cho referrer (10-25% commission)
- Cho referred (5-10% discount hoặc bonus content)

## 5. Share scripts (3 channels)
- Email ask referral
- DM casual share
- Public post (FB/IG)

## 6. Tracking method (cookie + UTM / manual / Form)

## 7. Payout frequency (monthly recommend)

## 8. Forecast 30 ngày
- Expected referrals count
- Expected revenue VND

## 9. Markdown playbook full dashboard

# Quality requirements
- Pronoun "bạn"
- Concrete với venture context
- KHÔNG em-dash

Output qua tool submit_referral_template.
"""


class L2ReferralEngineTemplate(BaseBC):
    name = "l2_referral_engine_template"
    scope = "Referral engine template Stage 17.5 (wrap P0.2 breakout-referral)"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(self, llm: LLMLayer, memory: MemoryLayer, model: str = DEFAULT_MODEL) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(success=False, output_text=f"unsupported {event}", output_payload={"supported": list(EXPECTED_EVENTS)})
        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")
        venture = ctx.venture_context or "cohangai"
        offer = payload.get("offer", {})
        persona = payload.get("persona", {})

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_referral_prompt(student_id, venture, offer, persona)
        try:
            response = await self.llm.client.messages.create(
                model=self.model, max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_REFERRAL_TEMPLATE_TOOL],
                tool_choice={"type": "tool", "name": "submit_referral_template"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        path = result.get("implementation_path", "?")
        expected_revenue = result.get("expected_30d_revenue_vnd", 0)
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:700],
            "keywords": ["referral_template", "cohort_1", student_id, path],
            "tags": ["l2", "referral_engine_template", "stage_17_5", "cohort_1", date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"cohort.referral_engine_design {date_str} student={student_id} path={path}",
        }
        return AgentResult(success=True, output_text=f"l2_referral student={student_id} path={path} expected_revenue={expected_revenue:,}", output_payload=result, emitted_memories=[memory_entry])

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_referral_template":
                return block.input or {}
        return {"error": "No tool_use block"}
