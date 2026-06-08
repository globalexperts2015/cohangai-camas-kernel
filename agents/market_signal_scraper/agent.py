"""Market Signal Scraper agent.

Stage 1.3 framework v2. "Thị trường đang hỏi mình điều gì?"
Aggregate inbox/comment/DM/email từ FB + Zalo + GHL + community → identify
recurring questions, sẵn-sàng-trả-tiền signals.

Triết lý: KHÔNG tạo nhu cầu. Tìm nhu cầu đã tồn tại.

Trigger event: market.signal_aggregate
Autonomy L1.
Output: top recurring questions + complaint clusters + pay-willingness signals.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
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

log = logging.getLogger("camas.market_signal_scraper")

EXPECTED_EVENTS = {"market.signal_aggregate"}

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 5000
DEFAULT_TIMEOUT = 150.0


SUBMIT_SIGNAL_TOOL = {
    "name": "submit_market_signal",
    "description": "Submit market signal aggregate output",
    "input_schema": {
        "type": "object",
        "properties": {
            "venture": {"type": "string"},
            "window_days": {"type": "integer"},
            "total_signals_analyzed": {"type": "integer"},
            "recurring_questions": {
                "type": "array",
                "description": "Câu hỏi recurring khách hỏi",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "frequency_count": {"type": "integer"},
                        "channels": {"type": "array", "items": {"type": "string"}},
                        "intent_type": {"type": "string", "description": "informational | comparison | objection | pay_intent"},
                    },
                },
            },
            "complaint_clusters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "complaint": {"type": "string"},
                        "frequency": {"type": "integer"},
                        "root_cause_stage": {"type": "string", "description": "framework v2 Stage caused"},
                    },
                },
            },
            "pay_willingness_signals": {
                "type": "array",
                "description": "Signals khách sẵn sàng trả tiền cho điều gì",
                "items": {
                    "type": "object",
                    "properties": {
                        "signal": {"type": "string"},
                        "evidence_quote": {"type": "string", "description": "Verbatim quote nếu có"},
                        "frequency": {"type": "integer"},
                        "estimated_market_size": {"type": "string"},
                    },
                },
            },
            "help_requests": {
                "type": "array",
                "description": "Người ta nhờ giúp gì",
                "items": {
                    "type": "object",
                    "properties": {
                        "request": {"type": "string"},
                        "frequency": {"type": "integer"},
                    },
                },
            },
            "untapped_demand_themes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Demand themes chưa có ai serve",
            },
            "top_3_product_opportunities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "opportunity": {"type": "string"},
                        "based_on_signals": {"type": "array", "items": {"type": "string"}},
                        "estimated_30d_revenue_vnd": {"type": "integer"},
                    },
                },
            },
            "summary": {"type": "string"},
        },
        "required": [
            "venture",
            "window_days",
            "total_signals_analyzed",
            "recurring_questions",
            "top_3_product_opportunities",
            "summary",
        ],
    },
}


def build_signal_prompt(venture: str, window_days: int, signals: list[dict]) -> str:
    signals_text = "\n".join(
        f"- [{s.get('channel', '?')}/{s.get('source', '?')}] {s.get('content', '')[:200]}"
        for s in signals[:80]
    )
    return f"""Bạn là Market Signal analyst theo Stage 1.3 framework v2 Solo Business Growth System.

Triết lý: "Không tạo nhu cầu. Tìm nhu cầu đã tồn tại."

# Venture
{venture}

# Window
Last {window_days} days

# Signals aggregated (top 80 từ inbox + comment + DM)
{signals_text}

# Task

Analyze signals + extract market intelligence:

## 1. Recurring questions
Group similar questions. Count frequency. Channel distribution. Classify intent:
- informational (just curious)
- comparison (evaluating options)
- objection (concerns about buying)
- pay_intent (ready to buy if X)

## 2. Complaint clusters
Group complaints. Map root_cause_stage to framework v2 (Stage 3 niche / Stage 9 offer / Stage 15 delivery / etc).

## 3. Pay willingness signals
Identify "Người sẵn sàng trả tiền cho điều gì?":
- Direct: "Em chấp nhận trả X triệu để giải pain Y"
- Indirect: nói về competitor pricing, sự bực bội với current solution
- Include verbatim quote nếu có

## 4. Help requests
"Người ta nhờ mình giúp gì?" = direct product opportunity.

## 5. Untapped demand themes
Themes chưa có ai serve well in Vietnamese market.

## 6. Top 3 product opportunities
Based on signals + untapped themes, đề xuất 3 product/service ideas với:
- opportunity name
- based_on_signals (cite signal nào support)
- estimated_30d_revenue_vnd (Vietnamese market realistic)

# Quality requirements
- KHÔNG bịa signal không có trong input
- Cite verbatim quote khi available
- Estimate honest dựa Vietnamese market knowledge
- KHÔNG em-dash

Output qua tool submit_market_signal.
"""


class MarketSignalScraper(BaseBC):
    """Market Signal Scraper, Stage 1.3 framework v2."""

    name = "market_signal_scraper"
    scope = "Aggregate inbox/comment/DM signals identify recurring questions + pay intent (Stage 1.3)"
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
        venture = ctx.venture_context or "breakout"
        window_days = payload.get("window_days", 14)
        signals = payload.get("signals", [])

        if not signals:
            # Auto-retrieve last N days từ memory (BC6/BC7/Tally/Fathom canonical)
            signals = await self._retrieve_signals(venture, window_days)

        if not signals:
            return AgentResult(
                success=False,
                output_text="No signals to analyze",
                output_payload={"error": "no signals retrieved", "window_days": window_days},
            )

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_signal_prompt(venture, window_days, signals)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_SIGNAL_TOOL],
                tool_choice={"type": "tool", "name": "submit_market_signal"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("market_signal LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        total = result.get("total_signals_analyzed", len(signals))
        questions = len(result.get("recurring_questions", []))
        opps = len(result.get("top_3_product_opportunities", []))
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = f"market signal venture={venture} window={window_days}d signals={total} questions={questions} opps={opps}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:800],
            "keywords": ["market_signal", venture, f"window-{window_days}d"],
            "tags": ["market_signal_scraper", "stage_1_3", venture, date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"market.signal_aggregate {date_str} venture={venture} signals={total}",
        }

        return AgentResult(success=True, output_text=summary, output_payload=result, emitted_memories=[memory_entry])

    async def _retrieve_signals(self, venture: str, window_days: int) -> list[dict]:
        """Auto-retrieve signals từ memory layer (BC6/BC7 reply log + Tally/Fathom)."""
        if not self.memory.ready:
            return []
        try:
            records = await self.memory.retrieve(
                query=f"customer question comment inquiry feedback {venture}",
                categories=["task", "conversation", "venture_state"],
                venture=venture if venture != "all" else None,
                k=80,
                max_age_days=window_days,
            )
            return [
                {"channel": "memory", "source": r.agent_name, "content": r.content[:300]}
                for r in records
            ]
        except Exception as exc:  # noqa: BLE001
            log.warning("retrieve signals fail: %r", exc)
            return []

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_market_signal":
                return block.input or {}
        return {"error": "No tool_use block"}
