"""E6 Market Demand Engine. BreakoutOS CHỌN module Engine 4/9.

Stack: DataForSEO (volume + competition) + YouTube Data API (discussion) +
Google Trends (growth) + Haiku narrative. Weight 25% trong tổng Opportunity Score.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from kernel.base_agent import (
    AgentResult, AutonomyLevel, BaseBC, EscalationTarget, ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

from .external_apis import (
    dataforseo_search_volume, youtube_search_count, google_trends_growth,
)

log = logging.getLogger("camas.e6_market_demand")
DEFAULT_MODEL = "claude-haiku-4-5"  # aggregate narrative
DEFAULT_MAX_TOKENS = 3000
DEFAULT_TIMEOUT = 60.0
EXPECTED_EVENTS = {"cohort.market_demand", "wizard.market_demand"}


def compute_demand_score(signals: dict) -> tuple[int, str, list[str]]:
    """Aggregate DataForSEO + YouTube + Google Trends → 0-100 score + verdict + flags."""
    score = 0
    flags = []

    # Volume signal (DataForSEO): 40 points max
    # NOTE: DataForSEO sometimes returns `null` cho volume (very low search), nên dùng `or 0`
    # để None → 0 (avoid TypeError int + None).
    vol_data = signals.get("volume_data", {})
    total_volume = sum((v.get("volume") or 0) for v in vol_data.values())
    if total_volume >= 5000:
        score += 40
    elif total_volume >= 1000:
        score += 30
    elif total_volume >= 300:
        score += 20
    elif total_volume >= 50:
        score += 10
    else:
        flags.append("VOLUME_TOO_LOW: tổng search volume <50/tháng, ngách quá nhỏ")

    # Competition signal: -10 if too HIGH
    avg_comp_idx = sum((v.get("competition_index") or 0) for v in vol_data.values()) / max(len(vol_data), 1)
    if avg_comp_idx > 80:
        score -= 10
        flags.append("COMPETITION_VERY_HIGH: avg competition >80, cần build moat hoặc niche down")

    # YouTube signal: 25 points max
    youtube_data = signals.get("youtube_data", {})
    total_youtube_results = sum(
        ((yt.get("total_results_estimated") or 0) if isinstance(yt, dict) and "_error" not in yt else 0)
        for yt in youtube_data.values()
    )
    if total_youtube_results >= 50000:
        score += 25
    elif total_youtube_results >= 10000:
        score += 20
    elif total_youtube_results >= 1000:
        score += 12
    elif total_youtube_results >= 100:
        score += 6
    else:
        flags.append("YOUTUBE_DISCUSSION_LOW: <100 video discussing, audience chưa có nhu cầu rõ")

    # Google Trends signal: 35 points max
    trends_data = signals.get("trends_data", {})
    growth_pcts = [
        (td.get("growth_pct_12m") or 0)
        for td in trends_data.values()
        if isinstance(td, dict) and "_error" not in td
    ]
    avg_growth = sum(growth_pcts) / max(len(growth_pcts), 1)
    if avg_growth >= 30:
        score += 35
    elif avg_growth >= 10:
        score += 25
    elif avg_growth >= 0:
        score += 15
    elif avg_growth >= -10:
        score += 8
    else:
        score += 0
        flags.append(f"TREND_DECLINING: trung bình {avg_growth:.0f}% growth 12m, ngách đang chết")

    score = max(0, min(100, score))
    if score >= 80:
        verdict = "STRONG_DEMAND"
    elif score >= 60:
        verdict = "MODERATE_DEMAND"
    elif score >= 40:
        verdict = "WEAK_DEMAND"
    elif score >= 20:
        verdict = "VERY_WEAK_DEMAND"
    else:
        verdict = "NO_DEMAND"

    return score, verdict, flags


def build_narrative_prompt(signals: dict, score: int, verdict: str, flags: list[str], keywords: list[str]) -> str:
    """Compose narrative prompt for Haiku."""
    return f"""Bạn là E6 Market Demand Engine narrative writer (BreakoutOS CHỌN module).

External API đã pull xong data. Viết báo cáo markdown 350-500 từ tiếng Việt giải thích cho founder.

# Keywords analyzed
{', '.join(keywords)}

# Raw signals
```json
{json.dumps(signals, ensure_ascii=False, indent=2)[:3500]}
```

# Aggregate result
Score: {score}/100
Verdict: {verdict}
Flags: {flags}

# Cấu trúc

## Tóm tắt
1-2 câu: tổng score + verdict + key takeaway.

## Search Volume (DataForSEO)
Phân tích từng keyword: volume cao/thấp + competition mức nào + ngụ ý gì cho founder.

## YouTube Discussion
Có nhiều video discussing không? Topic này audience đang quan tâm hay đã bão hoà?

## Google Trends Growth
Trend 12 tháng đang tăng/giảm/ổn định? Founder nên hành động NGAY hay nghiên cứu thêm?

## Cảnh báo
Nếu có flags, giải thích từng cái và recommend hành động.

## Verdict cuối
{verdict} score {score}/100. Founder NÊN/KHÔNG nên đầu tư vào ngách này.

# Rules

1. CHỈ dùng numbers từ signals object. KHÔNG bịa.
2. Tiếng Việt thuần, câu ngắn 5-15 từ, KHÔNG em-dash.
3. Trả về CHỈ markdown report, không kèm code block fence.
"""


class E6MarketDemand(BaseBC):
    name = "e6_market_demand"
    scope = (
        "Market Demand Engine. DataForSEO volume + YouTube discussion + Google Trends growth "
        "+ aggregate 0-100. BreakoutOS CHỌN module weight 25%."
    )
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
        self._db_pool: Optional[asyncpg.Pool] = None
        log.info("E6 init model=%s", model)

    async def _get_pool(self) -> Optional[asyncpg.Pool]:
        if self._db_pool is not None:
            return self._db_pool
        dsn = os.environ.get("DATABASE_URL") or os.environ.get("CDP_DATABASE_URL")
        if not dsn:
            return None
        try:
            self._db_pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3, command_timeout=10)
            return self._db_pool
        except Exception as e:
            log.warning("E6 db pool init fail: %r", e)
            return None

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(success=False, output_text=f"unsupported event {event}",
                               output_payload={"supported": sorted(EXPECTED_EVENTS)})
        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")
        venture = ctx.venture_context or "cohangai"

        raw = payload.get("market_demand_input")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                # treat as single keyword
                parsed = {"keywords": [raw[:100]]}
        else:
            parsed = payload

        keywords = parsed.get("keywords") or []
        if not keywords or not isinstance(keywords, list):
            return AgentResult(
                success=False,
                output_text="missing keywords (list)",
                output_payload={"error": "missing_keywords"},
            )
        keywords = [str(k).strip() for k in keywords if str(k).strip()][:10]  # max 10 keywords per run

        pool = await self._get_pool()

        # Fetch 3 signal sources in parallel
        import asyncio
        volume_task = dataforseo_search_volume(pool, keywords)
        youtube_tasks = {kw: youtube_search_count(pool, kw) for kw in keywords}
        trends_tasks = {kw: google_trends_growth(pool, kw) for kw in keywords}

        # Collect
        volume_data = await volume_task
        if "_error" in volume_data:
            log.warning("E6 volume fail: %s", volume_data)
            volume_data = {}

        youtube_data = {}
        for kw, task in youtube_tasks.items():
            try:
                youtube_data[kw] = await task
            except Exception as e:
                youtube_data[kw] = {"_error": str(e)[:100]}

        trends_data = {}
        for kw, task in trends_tasks.items():
            try:
                trends_data[kw] = await task
            except Exception as e:
                trends_data[kw] = {"_error": str(e)[:100]}

        signals = {
            "volume_data": volume_data,
            "youtube_data": youtube_data,
            "trends_data": trends_data,
        }
        score, verdict, flags = compute_demand_score(signals)

        # LLM narrative
        narrative = ""
        if self.llm.ready:
            try:
                response = await self.llm.client.messages.create(
                    model=self.model,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    messages=[{"role": "user", "content": build_narrative_prompt(signals, score, verdict, flags, keywords)}],
                    timeout=DEFAULT_TIMEOUT,
                )
                for block in response.content or []:
                    if getattr(block, "type", None) == "text":
                        narrative += getattr(block, "text", "")
            except Exception as e:
                log.warning("E6 narrative LLM fail: %r", e)
                narrative = f"## Tóm tắt\nDemand Score {score}/100 verdict {verdict}. Narrative LLM failed."

        output = {
            "market_demand_score": score,
            "verdict": verdict,
            "flags": flags,
            "keywords_analyzed": keywords,
            "signals": signals,
            "market_demand_report": narrative,
        }

        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        mem = {
            "agent_name": self.name,
            "content_summary": f"market_demand student={student_id} keywords={keywords[:3]} score={score} verdict={verdict}",
            "keywords": ["market_demand", "chon_module", student_id, f"score-{score}", *keywords[:3]],
            "tags": ["e6", "market_demand", "chon_module", "engine_4_of_9", verdict.lower(), date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"chon.market_demand {date_str} student={student_id} score={score} verdict={verdict}",
        }
        return AgentResult(
            success=True,
            output_text=f"e6_market_demand student={student_id} score={score}/100 verdict={verdict} keywords={len(keywords)}",
            output_payload=output,
            emitted_memories=[mem],
        )
