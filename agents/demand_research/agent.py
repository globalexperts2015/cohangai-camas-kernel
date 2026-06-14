"""Demand Research agent.

Apply Stage 5 framework v2: research customer demand via LLM synthesize hoặc
web scrape (Reddit + Quora + Google Trends + Meta Ads Library).

Trigger events:
- demand.research, with depth=quick (LLM only) hoặc depth=deep (scrape + LLM)

Quick depth (5 min): LLM synthesize from knowledge (training data)
Deep depth (1 hour): httpx scrape Reddit search API + Meta Ads Library + Google Trends

Output:
- 50-100 search queries người ta gõ
- 20-30 câu hỏi recurring
- 5 competitor matrix
- 3 top buying trigger
- Willingness-to-pay range estimate

Emit canonical fact category=venture_state tags=demand_research+stage_5.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

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

log = logging.getLogger("camas.demand_research")

EXPECTED_EVENTS = {"demand.research"}

DEFAULT_MODEL = "claude-haiku-4-5"  # Opus cho deep research synthesis
DEFAULT_MAX_TOKENS = 6000
DEFAULT_TIMEOUT = 240.0


SUBMIT_RESEARCH_TOOL = {
    "name": "submit_demand_research",
    "description": "Submit demand research output (flat schema)",
    "input_schema": {
        "type": "object",
        "properties": {
            "niche": {"type": "string"},
            "venture": {"type": "string"},
            "language": {"type": "string", "description": "vi | en"},
            "depth": {"type": "string", "description": "quick | deep"},
            "search_queries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "50-100 search queries người ta gõ Google",
            },
            "recurring_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "20-30 câu hỏi recurring (Reddit/Quora/FB group)",
            },
            "competitors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "positioning": {"type": "string"},
                        "price_range": {"type": "string"},
                        "strength": {"type": "string"},
                        "weakness": {"type": "string"},
                    },
                },
                "description": "5 competitor matrix",
            },
            "buying_triggers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "trigger": {"type": "string"},
                        "context": {"type": "string"},
                        "frequency": {"type": "string", "description": "high | medium | low"},
                    },
                },
                "description": "3 top buying triggers",
            },
            "willingness_to_pay_low_vnd": {"type": "integer"},
            "willingness_to_pay_mid_vnd": {"type": "integer"},
            "willingness_to_pay_high_vnd": {"type": "integer"},
            "wtp_reasoning": {"type": "string"},
            "underserved_segments": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Segments thị trường chưa được serve tốt",
            },
            "summary": {"type": "string"},
        },
        "required": [
            "niche",
            "venture",
            "depth",
            "search_queries",
            "recurring_questions",
            "competitors",
            "buying_triggers",
            "willingness_to_pay_mid_vnd",
            "summary",
        ],
    },
}


async def scrape_reddit(client: httpx.AsyncClient, niche: str, limit: int = 25) -> list[dict]:
    """Scrape Reddit search (no auth) for niche-related posts."""
    try:
        resp = await client.get(
            f"https://www.reddit.com/search.json",
            params={"q": niche, "limit": limit, "sort": "relevance"},
            headers={"User-Agent": "camas-kernel-demand-research/1.0"},
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
        posts: list[dict] = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            posts.append({
                "title": d.get("title", "")[:200],
                "subreddit": d.get("subreddit", ""),
                "score": d.get("score", 0),
                "num_comments": d.get("num_comments", 0),
                "selftext": (d.get("selftext", "") or "")[:300],
            })
        return posts
    except Exception as exc:  # noqa: BLE001
        log.warning("scrape_reddit fail: %r", exc)
        return []


def build_research_prompt(
    niche: str,
    language: str,
    depth: str,
    venture: str,
    reddit_posts: list[dict],
) -> str:
    reddit_summary = ""
    if reddit_posts:
        reddit_summary = "\n# Reddit posts retrieved (top 25)\n"
        for p in reddit_posts[:25]:
            reddit_summary += (
                f"- r/{p.get('subreddit', '?')} score={p.get('score', 0)} "
                f"comments={p.get('num_comments', 0)}: "
                f"{p.get('title', '')[:120]}\n"
            )

    return f"""Bạn là chuyên gia Demand Research theo framework Solo Business Growth System v2 Stage 5.

# Niche
"{niche}"

# Venture
{venture}

# Language target
{language}

# Depth
{depth}
{reddit_summary}

# Task

Research demand cho niche này. Output 5 phần:

## 1. Search queries (50-100)
Liệt kê 50-100 search queries người Việt gõ Google liên quan niche. Mix:
- Long-tail: "cách [verb] [niche] cho [persona]"
- Question: "có nên [niche] không?"
- Comparison: "[option A] vs [option B]"
- Pain-driven: "[pain] thì làm sao?"
- Tutorial: "hướng dẫn [niche] step by step"

## 2. Recurring questions (20-30)
Câu hỏi recurring trong Reddit/Quora/FB group/community Việt.
{f"Tham khảo Reddit posts retrieved ở trên." if reddit_posts else "Synthesize từ knowledge."}

## 3. Competitor matrix (5)
5 competitor trong niche với:
- name + positioning + price_range + strength + weakness

## 4. Buying triggers (3 top)
3 trigger chính khiến khách quyết định MUA:
- trigger statement + context + frequency (high/medium/low)

## 5. Willingness to pay (Vietnam market)
- Low: budget audience giá thấp nhất
- Mid: average willing to pay
- High: premium audience willing top
+ Reasoning

## 6. Underserved segments
Segments thị trường Việt chưa được serve tốt cho niche này.

# Quality requirements
- KHÔNG bịa số, estimate honest dựa Vietnamese market knowledge
- KHÔNG generic ("nhiều người"), MUST cụ thể
- Reference Reddit data nếu có
- KHÔNG em-dash, no forbidden term

Output qua tool submit_demand_research.
"""


class DemandResearch(BaseBC):
    """BC Demand Research, Stage 5 framework v2."""

    name = "demand_research"
    scope = "Research demand niche via LLM + optional scrape (Stage 5 framework v2)"
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
                output_payload={
                    "trigger_event": event,
                    "supported": list(EXPECTED_EVENTS),
                },
            )

        payload = ctx.payload or {}
        niche = payload.get("niche", "").strip()
        language = payload.get("language", "vi")
        depth = payload.get("depth", "quick")
        venture = ctx.venture_context or "all"

        if not niche or len(niche) < 5:
            return AgentResult(
                success=False,
                output_text="Missing niche",
                output_payload={"error": "payload.niche < 5 chars"},
            )

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "ANTHROPIC_API_KEY chưa set"},
            )

        reddit_posts: list[dict] = []
        if depth == "deep":
            async with httpx.AsyncClient() as client:
                reddit_posts = await scrape_reddit(client, niche, limit=25)
            log.info(
                "demand_research deep niche=%s reddit_posts=%d", niche, len(reddit_posts)
            )

        prompt = build_research_prompt(niche, language, depth, venture, reddit_posts)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_RESEARCH_TOOL],
                tool_choice={"type": "tool", "name": "submit_demand_research"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("demand_research LLM fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        queries_count = len(result.get("search_queries", []))
        questions_count = len(result.get("recurring_questions", []))
        competitors_count = len(result.get("competitors", []))
        triggers_count = len(result.get("buying_triggers", []))
        wtp_mid = result.get("willingness_to_pay_mid_vnd", 0)
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        summary = (
            f"demand research depth={depth} niche='{niche[:50]}' "
            f"queries={queries_count} questions={questions_count} "
            f"competitors={competitors_count} triggers={triggers_count} "
            f"WTP_mid={wtp_mid:,}VND"
        )

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:800],
            "keywords": ["demand_research", venture, niche[:50], depth],
            "tags": ["demand_research", "stage_5", venture, depth, date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"demand.research {date_str} niche='{niche[:60]}' depth={depth}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=result,
            emitted_memories=[memory_entry],
        )

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_demand_research"
            ):
                return block.input or {}
        return {"error": "No tool_use block"}
