"""E1 AI COO Dashboard agent (BreakoutOS v3, AIOS Sprint 16).

Đọc data từ Fan Hub (person) + Sepay (events.payment.completed) + content
engine output + Brevo email event + trust_score_log + GA4 fact. Generate
Daily 6am / Weekly Chủ Nhật 8pm / Monthly đầu tháng report kèm top 3 actions
+ red flags + pipeline snapshot. Push Telegram + lưu DB.

KHÔNG chỉ báo cáo: phải ĐỀ XUẤT hành động ưu tiên cụ thể.

Pipeline:
1. DataAggregator pull metric theo period (24h/7d/30d)
2. DecisionEngine rule-based → top 3 actions + red flags
3. Nếu weekly/monthly và có narrative case ambiguous, gọi LLM Opus 4.7
4. Format MD message qua telegram_formatter
5. Push Telegram (TELEGRAM_BOT_TOKEN + chat_id)
6. INSERT coo_report table (best-effort, fail-soft)
7. Emit memory entry

Style: tiếng Việt, câu ngắn, KHÔNG em-dash. Voice register `hang_webinar`.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

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

from .data_aggregator import DataAggregator
from .decision_engine import DecisionEngine
from .prompt_template import (
    SUBMIT_COO_NARRATIVE_TOOL,
    build_monthly_memo_prompt,
    build_weekly_narrative_prompt,
)
from .telegram_formatter import (
    format_daily_report,
    format_monthly_memo,
    format_weekly_report,
)

log = logging.getLogger("camas.e1_ai_coo")

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 1500
DEFAULT_LLM_TIMEOUT = 120.0
DEFAULT_HTTP_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"  # Breakout Ops fallback
TELEGRAM_MAX_LEN = 3800  # safety margin under 4096


class E1AICOO(BaseBC):
    """E1 AI COO Dashboard subagent.

    Events handled:
    - coo.daily      6am Perth, daily ops report
    - coo.weekly     Sunday 8pm Perth, weekly retro
    - coo.monthly    1st of month 9am Perth, strategic memo
    - wizard.ai_coo  on-demand from cohort widget UI
    """

    name = "e1_ai_coo"
    scope = (
        "AI COO Dashboard, daily 6am + weekly Sunday 8pm + monthly memo. "
        "Pull from Fan Hub, Content, Lead Gen, Sepay, GA4. Generate top 3 "
        "actions + red flags. Push Telegram."
    )
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS  # critical red flags escalate
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    EXPECTED_EVENTS: set[str] = {
        "coo.daily",
        "coo.weekly",
        "coo.monthly",
        "wizard.ai_coo",
    }

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        model: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model or DEFAULT_MODEL
        log.info("E1 AI COO init model=%s", self.model)

    # ----------------------------------------------------------------
    # Main entry
    # ----------------------------------------------------------------
    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in self.EXPECTED_EVENTS:
            return AgentResult(
                success=False,
                output_text=f"Event {event} not expected",
                output_payload={
                    "error": "unexpected_event",
                    "expected": sorted(self.EXPECTED_EVENTS),
                    "got": event,
                },
            )

        payload = ctx.payload or {}
        student_id: str = payload.get("student_id") or "anna"
        tenant_id: str = payload.get("tenant_id") or "anna"
        student_name: str = payload.get("student_name") or "Hằng"

        # Determine period from event (coo.daily / coo.weekly / coo.monthly)
        # wizard.ai_coo treats payload.period (daily default)
        if event == "wizard.ai_coo":
            period = (payload.get("period") or "daily").lower()
        else:
            period = event.split(".", 1)[1] if "." in event else "daily"

        if period not in {"daily", "weekly", "monthly"}:
            return AgentResult(
                success=False,
                output_text=f"Invalid period {period}",
                output_payload={"error": "invalid_period", "got": period},
            )

        # 1. Aggregate data
        agg = DataAggregator(self.memory)
        if period == "daily":
            data = await agg.collect_24h(student_id, tenant_id)
        elif period == "weekly":
            data = await agg.collect_7d(student_id, tenant_id)
        else:
            data = await agg.collect_30d(student_id, tenant_id)

        # 2. Decision engine
        engine = DecisionEngine()
        if period == "daily":
            analysis = engine.analyze_daily(data)
        elif period == "weekly":
            analysis = engine.analyze_weekly(data)
        else:
            analysis = engine.analyze_monthly(data)

        # 3. Narrative LLM (weekly/monthly only)
        narrative: Optional[dict[str, Any]] = None
        if period in {"weekly", "monthly"} and self.llm.ready:
            narrative = await self._llm_narrative(
                student_id, data, analysis, period
            )

        # 4. Format message
        now_perth = datetime.now(tz=timezone.utc) + timedelta(hours=8)
        if period == "daily":
            date_str = now_perth.strftime("%d/%m")
            msg = format_daily_report(student_name, date_str, analysis, data)
        elif period == "weekly":
            date_str = now_perth.strftime("%d/%m/%Y")
            msg = format_weekly_report(
                student_name, date_str, analysis, data, narrative
            )
        else:
            date_str = now_perth.strftime("%m/%Y")
            msg = format_monthly_memo(
                student_name, date_str, analysis, data, narrative
            )

        # 5. Push Telegram (skip if E1_DRY_RUN=1)
        dry_run = os.getenv("E1_DRY_RUN", "") == "1"
        telegram_sent = False
        if dry_run:
            log.info("E1 DRY_RUN, skip Telegram push")
            telegram_sent = True
        else:
            telegram_chat_id = (
                payload.get("telegram_chat_id")
                or os.environ.get("TELEGRAM_OPS_GROUP_ID")
                or DEFAULT_TELEGRAM_GROUP_ID
            )
            try:
                telegram_sent = await self._push_telegram(telegram_chat_id, msg)
            except Exception as exc:  # noqa: BLE001
                log.warning("E1 telegram push fail: %r", exc)
                telegram_sent = False

        # 6. Store DB (best-effort)
        stored = await self._store_report(
            student_id=student_id,
            tenant_id=tenant_id,
            period=period,
            analysis=analysis,
            data=data,
            msg=msg,
            narrative=narrative,
        )

        # 7. Emit memory
        date_label = now_perth.strftime("%Y-%m-%d")
        memory_entry = {
            "agent_name": self.name,
            "content_summary": msg[:700],
            "keywords": ["coo", period, student_id, date_label],
            "tags": ["e1", "ai_coo", period, "cohort_1", date_label],
            "venture": ctx.venture_context or "cohangai",
            "category": "operations",
            "context": (
                f"coo.{period} student={student_id} date={date_label} "
                f"telegram_sent={telegram_sent} stored={stored}"
            ),
        }

        # Escalation if critical red flag
        red_flags = analysis.get("red_flags", [])
        critical_count = sum(
            1 for rf in red_flags if rf.get("severity") == "critical"
        )
        escalation_required = critical_count > 0
        escalation_reason: Optional[str] = None
        if escalation_required:
            escalation_reason = (
                f"E1 phát hiện {critical_count} red flag CRITICAL trong "
                f"{period} report cho {student_id}"
            )

        return AgentResult(
            success=True,
            output_text=msg[:500],
            output_payload={
                "period": period,
                "analysis": analysis,
                "data": data,
                "narrative": narrative,
                "telegram_sent": telegram_sent,
                "stored": stored,
                "date_label": date_label,
            },
            emitted_memories=[memory_entry],
            escalation_required=escalation_required,
            escalation_reason=escalation_reason,
        )

    # ----------------------------------------------------------------
    # LLM narrative (weekly/monthly)
    # ----------------------------------------------------------------
    async def _llm_narrative(
        self,
        student_id: str,
        data: dict[str, Any],
        analysis: dict[str, Any],
        period: str,
    ) -> Optional[dict[str, Any]]:
        """Call Opus 4.7 cho narrative synthesis. Return dict hoặc None."""
        if period == "weekly":
            prompt = build_weekly_narrative_prompt(student_id, data, analysis)
        elif period == "monthly":
            prompt = build_monthly_memo_prompt(student_id, data, analysis)
        else:
            return None

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_COO_NARRATIVE_TOOL],
                tool_choice={"type": "tool", "name": "submit_coo_narrative"},
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("E1 LLM narrative fail student=%s err=%r", student_id, exc)
            return None

        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_coo_narrative"
            ):
                return block.input or {}
        log.warning(
            "E1 LLM narrative no tool_use student=%s stop=%s",
            student_id,
            getattr(response, "stop_reason", None),
        )
        return None

    # ----------------------------------------------------------------
    # Telegram push
    # ----------------------------------------------------------------
    async def _push_telegram(self, chat_id: str, msg: str) -> bool:
        """Push message tới Telegram chat. Return True nếu HTTP 200."""
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            log.warning("E1 TELEGRAM_BOT_TOKEN chưa set, skip")
            return False
        body = msg
        if len(body) > TELEGRAM_MAX_LEN:
            body = body[: TELEGRAM_MAX_LEN - 60] + "\n\n...(cắt bớt, xem dashboard)"
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        async with httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT) as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": body,
                    "disable_web_page_preview": True,
                },
            )
            if resp.status_code != 200:
                log.warning(
                    "E1 Telegram non-200: %s %s",
                    resp.status_code,
                    resp.text[:200],
                )
            return resp.status_code == 200

    # ----------------------------------------------------------------
    # Store report DB
    # ----------------------------------------------------------------
    async def _store_report(
        self,
        student_id: str,
        tenant_id: str,
        period: str,
        analysis: dict[str, Any],
        data: dict[str, Any],
        msg: str,
        narrative: Optional[dict[str, Any]],
    ) -> bool:
        """INSERT vào public.coo_report. Fail-soft, return False nếu lỗi.

        Schema expected (migration TBD):
            CREATE TABLE public.coo_report (
                id BIGSERIAL PRIMARY KEY,
                student_id TEXT NOT NULL,
                tenant_id TEXT,
                period TEXT NOT NULL,
                report_date DATE NOT NULL,
                data JSONB,
                analysis JSONB,
                narrative JSONB,
                msg TEXT,
                created_at TIMESTAMPTZ DEFAULT now()
            );
        """
        if not getattr(self.memory, "dsn", None):
            return False
        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            log.warning("E1 store_report pool fail: %r", exc)
            return False

        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO public.coo_report
                        (student_id, tenant_id, period, report_date,
                         data, analysis, narrative, msg)
                    VALUES ($1, $2, $3, CURRENT_DATE, $4::jsonb, $5::jsonb,
                            $6::jsonb, $7)
                    """,
                    student_id,
                    tenant_id,
                    period,
                    json.dumps(data, ensure_ascii=False, default=str),
                    json.dumps(analysis, ensure_ascii=False, default=str),
                    json.dumps(narrative or {}, ensure_ascii=False, default=str),
                    msg,
                )
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("E1 store_report INSERT fail: %r", exc)
            return False
