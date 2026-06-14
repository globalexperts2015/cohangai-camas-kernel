"""E11 Recommendation Engine. BreakoutOS CHỌN module Engine 9/9.

Generate Value Ladder + first offer + Lead Magnet + Workshop + Foundation + Growth +
Coaching + Action Plan 30 ngày. LLM Opus 4.7.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from kernel.base_agent import (
    AgentResult, AutonomyLevel, BaseBC, EscalationTarget, ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

log = logging.getLogger("camas.e11_recommendation")
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 8000
DEFAULT_TIMEOUT = 240.0
EXPECTED_EVENTS = {"cohort.recommendation", "wizard.recommendation"}


SUBMIT_RECOMMENDATION_TOOL: dict[str, Any] = {
    "name": "submit_breakout_recommendation",
    "description": (
        "Submit Value Ladder + first offer + 30-day Action Plan dựa trên Opportunity Score + "
        "5 engines outputs. Cụ thể, có giá, có tuần triển khai."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "value_ladder": {
                "type": "object",
                "properties": {
                    "lead_magnet": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "format": {"type": "string", "enum": ["pdf_guide", "mini_course", "template_pack", "quiz", "free_call"]},
                            "promise": {"type": "string"},
                            "expected_optin_rate": {"type": "string"},
                        },
                        "required": ["title", "format", "promise"],
                    },
                    "workshop": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "price_vnd": {"type": "integer"},
                            "format": {"type": "string"},
                            "duration_hours": {"type": "number"},
                        },
                        "required": ["title", "price_vnd", "format"],
                    },
                    "foundation": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "price_vnd": {"type": "integer"},
                            "delivery_format": {"type": "string"},
                            "duration_weeks": {"type": "integer"},
                            "target_customers": {"type": "integer"},
                        },
                        "required": ["title", "price_vnd", "delivery_format", "duration_weeks"],
                    },
                    "growth": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "price_vnd": {"type": "integer"},
                            "delivery_format": {"type": "string"},
                        },
                        "required": ["title", "price_vnd", "delivery_format"],
                    },
                    "coaching": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "price_vnd": {"type": "integer"},
                            "duration_months": {"type": "integer"},
                            "format": {"type": "string"},
                        },
                        "required": ["title", "price_vnd", "duration_months", "format"],
                    },
                },
                "required": ["lead_magnet", "workshop", "foundation", "growth", "coaching"],
            },
            "first_offer_to_launch": {
                "type": "object",
                "properties": {
                    "tier": {"type": "string", "enum": ["lead_magnet", "workshop", "foundation", "growth", "coaching"]},
                    "rationale": {"type": "string", "description": "Tại sao tier này LAUNCH FIRST cho founder"},
                    "expected_revenue_30d_vnd": {"type": "integer"},
                    "expected_customers_30d": {"type": "integer"},
                },
                "required": ["tier", "rationale", "expected_revenue_30d_vnd", "expected_customers_30d"],
            },
            "action_plan_30_days": {
                "type": "array",
                "minItems": 4,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "properties": {
                        "week": {"type": "integer", "minimum": 1, "maximum": 4},
                        "focus": {"type": "string"},
                        "actions": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 7},
                        "deliverable": {"type": "string"},
                        "success_metric": {"type": "string"},
                    },
                    "required": ["week", "focus", "actions", "deliverable", "success_metric"],
                },
            },
            "first_3_customers_acquisition_plan": {
                "type": "object",
                "properties": {
                    "channels": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
                    "outreach_script_subject": {"type": "string", "description": "1 subject line cho email/DM outreach"},
                    "outreach_script_body": {"type": "string", "description": "1 paragraph 80-150 từ tiếng Việt"},
                    "target_first_3_customers_by_day": {"type": "integer", "minimum": 7, "maximum": 30},
                },
                "required": ["channels", "outreach_script_subject", "outreach_script_body", "target_first_3_customers_by_day"],
            },
            "recommendation_report": {
                "type": "string",
                "description": (
                    "Báo cáo markdown 500-800 từ tiếng Việt. ## Value Ladder 5 tier + "
                    "## First offer to launch + ## Action plan 30 ngày + "
                    "## First 3 customers acquisition + ## Pitfalls cần tránh. KHÔNG em-dash."
                ),
            },
        },
        "required": [
            "value_ladder", "first_offer_to_launch", "action_plan_30_days",
            "first_3_customers_acquisition_plan", "recommendation_report",
        ],
    },
}


def build_recommendation_prompt(payload: dict) -> str:
    inputs_json = json.dumps(payload, ensure_ascii=False, indent=2)[:5000]
    return f"""Bạn là E11 Breakout Recommendation Engine trong BreakoutOS CHỌN module.

Đây là Engine 9 (cuối cùng). Sau khi 8 engines trước chạy xong, nhiệm vụ của bạn là tổng hợp toàn bộ data và đề xuất:
1. Value Ladder 5 tier (Lead Magnet → Workshop → Foundation → Growth → Coaching)
2. First Offer to launch (chọn 1 tier khởi đầu)
3. Action Plan 30 ngày (4 tuần)
4. Plan acquisition 3 khách đầu tiên

# Full data 8 engines trước
```json
{inputs_json}
```

# Framework

1. Value Ladder pricing logic:
   - Lead Magnet: 0đ
   - Workshop: 200k-500k (low ticket)
   - Foundation: 1.5M-5M (mid ticket, core offer)
   - Growth: 10M-20M (scale + group)
   - Coaching: 30M-100M (1-1 high touch)

2. First Offer to launch CHỌN dựa trên Opportunity Score + Founder Fit:
   - Founder Fit 80+: launch Foundation NGAY (skip lead magnet)
   - Founder Fit 60-79: launch Workshop để validate (test pricing + audience)
   - Founder Fit <60: launch Lead Magnet để build list trước

3. Action Plan 30 ngày phải có DELIVERABLE và SUCCESS METRIC mỗi tuần.

4. First 3 customers từ warm network (friends, ex-colleagues, mailing list, FB group). KHÔNG nói "chạy ads tốn 50tr".

5. Outreach script subject + body PHẢI cụ thể, dùng được luôn copy-paste.

# Rules

1. KHÔNG generic. Tham chiếu Founder Fit + Problem Map + Desire Map + Solution Design cụ thể.
2. Pricing realistic theo market VN (nếu lifestyle=solo_ai) hoặc AU (nếu opportunity scale ra Úc).
3. Tiếng Việt thuần, câu ngắn 5-15 từ, KHÔNG em-dash.

Output qua tool submit_breakout_recommendation đầy đủ 5 fields.
"""


class E11Recommendation(BaseBC):
    name = "e11_recommendation"
    scope = "Recommendation Engine. Value Ladder 5 tier + first offer + 30-day action plan + first 3 customers acquisition."
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(self, llm: LLMLayer, memory: Optional[MemoryLayer] = None, model: str = DEFAULT_MODEL):
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(success=False, output_text=f"unsupported event {event}",
                               output_payload={"supported": sorted(EXPECTED_EVENTS)})
        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")
        venture = ctx.venture_context or "cohangai"

        raw = payload.get("recommendation_input")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return AgentResult(success=False, output_text="recommendation_input must be JSON",
                                   output_payload={"error": "invalid_json"})
        else:
            parsed = payload

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready",
                               output_payload={"error": "llm_not_ready"})

        prompt = build_recommendation_prompt(parsed)
        try:
            response = await self.llm.client.messages.create(
                model=self.model, max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_RECOMMENDATION_TOOL],
                tool_choice={"type": "tool", "name": "submit_breakout_recommendation"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:
            log.warning("E11 LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}",
                               output_payload={"error": str(exc)})

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        first_tier = (result.get("first_offer_to_launch") or {}).get("tier", "?")
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        mem = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:700],
            "keywords": ["recommendation", "chon_module", student_id, first_tier],
            "tags": ["e11", "recommendation", "chon_module", "engine_9_of_9", first_tier, date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"chon.recommendation {date_str} student={student_id} first_tier={first_tier}",
        }
        return AgentResult(
            success=True,
            output_text=f"e11_recommendation student={student_id} first_tier={first_tier}",
            output_payload=result,
            emitted_memories=[mem],
        )

    @staticmethod
    def _parse_response(response: Any) -> dict[str, Any]:
        for block in response.content or []:
            if (getattr(block, "type", None) == "tool_use"
                    and getattr(block, "name", None) == "submit_breakout_recommendation"):
                data = block.input or {}
                if not data:
                    return {"error": "LLM tool_use returned empty input"}
                return data
        return {"error": "No tool_use block submit_breakout_recommendation in response"}
