"""Competitor Intelligence agent.

Stage 3 framework v2 Competitor Research. Analyze competitor offers + pricing +
funnel + ads strategy. Identify differentiation opportunities.

Tools (limited by no scrape API, mainly LLM knowledge + URL fetch):
- Meta Ads Library URL (manual review)
- TikTok Creative Center (manual review)
- SimilarWeb basic info via httpx
- LLM synthesize known competitor knowledge

Trigger event: competitor.intel_research
Autonomy L1.
Output: competitor matrix + differentiation matrix + gaps to exploit.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus

import httpx

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

log = logging.getLogger("camas.competitor_intelligence")

EXPECTED_EVENTS = {"competitor.intel_research"}

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 5500
DEFAULT_TIMEOUT = 180.0


SUBMIT_COMPETITOR_TOOL = {
    "name": "submit_competitor_intel",
    "description": "Submit competitor intelligence matrix",
    "input_schema": {
        "type": "object",
        "properties": {
            "venture": {"type": "string"},
            "niche": {"type": "string"},
            "competitor_count_analyzed": {"type": "integer"},
            "competitors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "url": {"type": "string"},
                        "positioning": {"type": "string"},
                        "price_range_vnd": {"type": "string"},
                        "core_offer": {"type": "string"},
                        "funnel_type": {"type": "string", "description": "tripwire | webinar | sales_call | direct"},
                        "strength": {"type": "string"},
                        "weakness": {"type": "string"},
                        "audience_size_estimate": {"type": "string"},
                        "ads_running": {"type": "boolean"},
                        "differentiation_angle": {"type": "string"},
                    },
                },
            },
            "differentiation_opportunities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "angle": {"type": "string"},
                        "competitors_missing_this": {"type": "array", "items": {"type": "string"}},
                        "evidence": {"type": "string"},
                        "estimated_market_advantage": {"type": "string"},
                    },
                },
            },
            "pricing_gap_analysis": {
                "type": "object",
                "properties": {
                    "underpriced_segment": {"type": "string"},
                    "overpriced_segment": {"type": "string"},
                    "recommended_anna_price_vnd": {"type": "integer"},
                    "reasoning": {"type": "string"},
                },
            },
            "ads_intelligence": {
                "type": "object",
                "properties": {
                    "common_hooks": {"type": "array", "items": {"type": "string"}},
                    "common_creatives": {"type": "string"},
                    "platforms_used": {"type": "array", "items": {"type": "string"}},
                    "estimated_spend_range": {"type": "string"},
                },
            },
            "manual_research_links": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "platform": {"type": "string"},
                        "url": {"type": "string"},
                        "what_to_check": {"type": "string"},
                    },
                },
                "description": "Links to manually review (Meta Ads Library, TikTok Creative, etc.)",
            },
            "summary": {"type": "string"},
        },
        "required": [
            "venture",
            "niche",
            "competitors",
            "differentiation_opportunities",
            "manual_research_links",
            "summary",
        ],
    },
}


def build_competitor_prompt(niche: str, venture: str, market: str, known_competitors: list[str]) -> str:
    competitors_hint = ", ".join(known_competitors) if known_competitors else "(discover từ knowledge)"
    return f"""Bạn là Competitor Intelligence analyst theo Stage 3 framework v2 Solo Business Growth System.

# Niche
"{niche}"

# Venture
{venture}

# Market
{market}

# Known competitors hint
{competitors_hint}

# Task

Analyze competitor landscape:

## 1. Competitors (5-10)
Mỗi competitor:
- name + url (nếu biết)
- positioning (1 dòng)
- price_range_vnd
- core_offer
- funnel_type (tripwire/webinar/sales_call/direct)
- strength + weakness
- audience_size_estimate
- ads_running (boolean)
- differentiation_angle

Reference Vietnamese market competitors nếu nichề local (vd: Hieu.tv, Phạm Thành Long, Tony Buổi Sáng, Đặng Lê Nguyên Vũ, etc.).

## 2. Differentiation opportunities (3-5)
Angles competitors KHÔNG cover, Anna có thể own:
- angle (1 câu)
- competitors_missing_this (list)
- evidence (vì sao biết competitors miss)
- estimated_market_advantage

## 3. Pricing gap analysis
- underpriced_segment (cheap competitors, low margin)
- overpriced_segment (premium, possibly inflated)
- recommended_anna_price_vnd
- reasoning

## 4. Ads intelligence
- common_hooks (3-5 hook angles competitors dùng)
- common_creatives (description)
- platforms_used
- estimated_spend_range

## 5. Manual research links
Anna cần review thủ công những URL nào:
- Meta Ads Library: https://www.facebook.com/ads/library/?q={quote_plus(niche)}&country=VN
- TikTok Creative Center: https://ads.tiktok.com/business/creativecenter/inspiration/topads/
- Specific competitor pricing pages

# Quality requirements
- KHÔNG bịa competitor không biết
- Specific với Vietnamese market context
- Recommendations actionable
- KHÔNG em-dash

Output qua tool submit_competitor_intel.
"""


class CompetitorIntelligence(BaseBC):
    """Competitor Intelligence, Stage 3 framework v2."""

    name = "competitor_intelligence"
    scope = "Analyze competitor landscape per niche + identify differentiation (Stage 3 framework v2)"
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
                output_text=f"{self.name} không xử lý event này",
                output_payload={"trigger_event": event, "supported": list(EXPECTED_EVENTS)},
            )

        payload = ctx.payload or {}
        niche = payload.get("niche", "").strip()
        venture = ctx.venture_context or "breakout"
        market = payload.get("market", "Vietnam")
        known_competitors = payload.get("known_competitors", [])

        if not niche or len(niche) < 5:
            return AgentResult(
                success=False,
                output_text="Missing niche",
                output_payload={"error": "niche < 5 chars"},
            )

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_competitor_prompt(niche, venture, market, known_competitors)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_COMPETITOR_TOOL],
                tool_choice={"type": "tool", "name": "submit_competitor_intel"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("competitor_intel LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        intel = self._parse_response(response)
        if "error" in intel:
            return AgentResult(success=False, output_text=intel["error"], output_payload=intel)

        comp_count = len(intel.get("competitors", []))
        diff_count = len(intel.get("differentiation_opportunities", []))
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = f"competitor intel venture={venture} niche='{niche[:40]}' competitors={comp_count} diff_opps={diff_count}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(intel, ensure_ascii=False)[:800],
            "keywords": ["competitor_intel", venture, niche[:50]],
            "tags": ["competitor_intelligence", "stage_3", venture, date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"competitor.intel_research {date_str} niche='{niche[:60]}' competitors={comp_count}",
        }

        return AgentResult(success=True, output_text=summary, output_payload=intel, emitted_memories=[memory_entry])

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_competitor_intel":
                return block.input or {}
        return {"error": "No tool_use block"}
