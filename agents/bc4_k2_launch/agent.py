"""BC4 K2 Launch agent.

Orchestrate pre-launch + launch week 72h critical cho cohort Breakout K2 (khai
giảng LIVE 22/6, access quay sẵn ngay sau khi mua). 5 trigger event:

1. `launch.t_minus_3` (3 ngày trước launch)
   - Check whitelist sync count (qua agent_memory bc5_cdp_monitor)
   - Check ads campaigns status (placeholder, FB Marketing API later)
   - Build T-3 reminder status report
   - Telegram + email (email TODO, hiện chỉ Telegram)

2. `launch.t_minus_1` (1 ngày trước launch)
   - Final readiness checklist: WK room + Sepay + ZNS + GHL + email queue
   - Telegram checklist Anna confirm trước go-live

3. `launch.live_day` (chạy mỗi giờ trong launch window)
   - Monitor 3 con số: registrations + payments + ZNS sent (window 1h gần nhất)
   - Alert nếu service down hoặc count dưới threshold
   - Hourly stats Telegram

4. `launch.post_24h` (24h sau launch)
   - Outcome report: tổng register/paid theo 5 tier giá
     (VIP 199k, Foundation 3M, Customer 6M, Growth 15M, Coaching 50M)
   - Conversion funnel + revenue VND + AUD
   - Telegram + emit memory tag launch_outcome cho cron Mac archive

5. Unknown event → success=False với output_text

Architectural choice (L3_PROPOSE default, downgrade L1 sau K2 settles):
    Brief yêu cầu L3 trong launch week (Anna cần preview message trước khi blast),
    nhưng sau K2 thì routine launch sau (K3/K4) downgrade L1_AUTO vì pattern đã
    proven. Override autonomy_level qua constructor `autonomy_level` arg sau K2.

LLM split:
    - Haiku 4.5: hourly stats summarization (cheap + fast cho 1-2 dòng)
    - Opus 4.7: post-24h outcome report (cần insight chiến lược + retro learnings)

DB queries:
    - Reuse MemoryLayer._pool asyncpg pool (CDP và CAMAS chung Postgres)
    - Fail-soft graceful nếu pool init lỗi, return stats empty + alert Telegram

Style: tiếng Việt cho Telegram + digest + docstring. ZERO em-dash. Type hints
async/await xuyên suốt. Idempotent: same event 2 lần = 2 message (dedup là job
của cron-job.org).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
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

log = logging.getLogger("camas.bc4_k2_launch")

DEFAULT_HAIKU_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_OPUS_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS_STATS = 400
DEFAULT_MAX_TOKENS_OUTCOME = 2500
DEFAULT_LLM_TIMEOUT = 60.0
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"  # Breakout Ops

# Hourly thresholds (Anna chốt: cảnh báo nếu rớt dưới)
HOURLY_REG_THRESHOLD = 5
HOURLY_PAY_THRESHOLD = 1
HOURLY_ZNS_THRESHOLD = 1

# Tỷ giá VND/AUD placeholder (chốt cứng, Anna tự cập nhật khi cần)
DEFAULT_VND_PER_AUD = 17000.0

# K2 pricing 5 tier (memory project-breakout-pricing) tính bằng VND
TIER_PRICING_VND: dict[str, int] = {
    "vip": 199_000,
    "foundation": 3_000_000,
    "customer": 6_000_000,
    "growth": 15_000_000,
    "coaching": 50_000_000,
}


class BC4K2Launch(BaseBC):
    """BC4 K2 Launch agent, orchestrate 72h critical + launch outcome report.

    Autonomy:
        - L3_PROPOSE default trong launch week (Anna preview trước blast).
        - Override L1_AUTO khi cohort K3/K4 routine sau K2 settles.

    Escalation: TELEGRAM_OPS (group Breakout Ops -1003813280155).
    """

    name = "bc4_k2_launch"
    scope = (
        "Pre-launch + launch week tactical 72h critical orchestration "
        "K2/K3/K4 cohorts"
    )
    autonomy_level = AutonomyLevel.L3_PROPOSE
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        haiku_model: str = DEFAULT_HAIKU_MODEL,
        opus_model: str = DEFAULT_OPUS_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.haiku_model = haiku_model
        self.opus_model = opus_model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""

        if event == "launch.t_minus_3":
            return await self._handle_t_minus_3(ctx)
        if event == "launch.t_minus_1":
            return await self._handle_t_minus_1(ctx)
        if event == "launch.live_day":
            return await self._handle_live_day(ctx)
        if event == "launch.post_24h":
            return await self._handle_post_24h(ctx)

        return AgentResult(
            success=False,
            output_text="BC4 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "launch.t_minus_3",
                    "launch.t_minus_1",
                    "launch.live_day",
                    "launch.post_24h",
                ],
            },
        )

    # ============================================================
    # Event 1: T-3 reminder
    # ============================================================
    async def _handle_t_minus_3(self, ctx: ExecutionContext) -> AgentResult:
        dry_run = self._dry_run()
        cohort = ctx.payload.get("cohort", "K2") if ctx.payload else "K2"

        whitelist_count = await self._fetch_whitelist_count()
        ads_status = await self._fetch_ads_status()

        report = self._build_t_minus_3_report(
            cohort=cohort,
            whitelist_count=whitelist_count,
            ads_status=ads_status,
        )

        sent_ok = await self._maybe_send_telegram(report, dry_run=dry_run)

        memory = {
            "agent_name": self.name,
            "content": (
                f"T-3 launch reminder {cohort}: "
                f"whitelist={whitelist_count} ads={ads_status.get('status')}"
            ),
            "keywords": ["t_minus_3", cohort, "reminder"],
            "tags": ["launch", "k2", "t_minus_3", "sent" if sent_ok else "send_failed"],
            "venture": "breakout",
            "context": f"T-3 reminder cohort={cohort}",
        }

        return AgentResult(
            success=True,
            output_text=report,
            output_payload={
                "event": "launch.t_minus_3",
                "cohort": cohort,
                "whitelist_count": whitelist_count,
                "ads_status": ads_status,
                "sent_ok": sent_ok,
                "dry_run": dry_run,
            },
            emitted_memories=[memory],
        )

    # ============================================================
    # Event 2: T-1 final readiness
    # ============================================================
    async def _handle_t_minus_1(self, ctx: ExecutionContext) -> AgentResult:
        dry_run = self._dry_run()
        cohort = ctx.payload.get("cohort", "K2") if ctx.payload else "K2"
        overrides = ctx.payload.get("checks", {}) if ctx.payload else {}

        # Default checklist: tất cả True nếu Anna chưa override
        # (cron-job sẽ POST overrides từ healthcheck endpoint)
        checklist = {
            "wk_room_ready": overrides.get("wk_room_ready", True),
            "sepay_healthy": overrides.get("sepay_healthy", True),
            "zns_templates_approved": overrides.get(
                "zns_templates_approved", True
            ),
            "ghl_workflows_enabled": overrides.get(
                "ghl_workflows_enabled", True
            ),
            "email_reminders_queued": overrides.get(
                "email_reminders_queued", True
            ),
        }

        all_green = all(checklist.values())
        report = self._build_t_minus_1_report(
            cohort=cohort, checklist=checklist, all_green=all_green
        )
        sent_ok = await self._maybe_send_telegram(report, dry_run=dry_run)

        memory = {
            "agent_name": self.name,
            "content": (
                f"T-1 readiness checklist {cohort}: "
                f"green={all_green} {json.dumps(checklist, ensure_ascii=False)}"
            ),
            "keywords": ["t_minus_1", cohort, "checklist"],
            "tags": [
                "launch",
                "k2",
                "t_minus_1",
                "ready" if all_green else "blocked",
                "sent" if sent_ok else "send_failed",
            ],
            "venture": "breakout",
            "context": f"T-1 checklist cohort={cohort}",
        }

        return AgentResult(
            success=True,
            output_text=report,
            output_payload={
                "event": "launch.t_minus_1",
                "cohort": cohort,
                "checklist": checklist,
                "all_green": all_green,
                "sent_ok": sent_ok,
                "dry_run": dry_run,
            },
            emitted_memories=[memory],
            escalation_required=not all_green,
            escalation_reason=(
                "T-1 readiness có item chưa green" if not all_green else None
            ),
        )

    # ============================================================
    # Event 3: live day hourly monitor
    # ============================================================
    async def _handle_live_day(self, ctx: ExecutionContext) -> AgentResult:
        dry_run = self._dry_run()
        cohort = ctx.payload.get("cohort", "K2") if ctx.payload else "K2"
        window_hours = ctx.payload.get("window_hours", 1) if ctx.payload else 1

        stats = await self._fetch_live_stats(window_hours=window_hours)

        # Detect alerts
        alerts: list[str] = []
        if stats.get("error"):
            alerts.append(f"DB error: {stats['error']}")
        if stats.get("registrations", 0) < HOURLY_REG_THRESHOLD:
            alerts.append(
                f"Registrations {stats.get('registrations', 0)} dưới ngưỡng "
                f"{HOURLY_REG_THRESHOLD}/h"
            )
        if stats.get("payments", 0) < HOURLY_PAY_THRESHOLD:
            alerts.append(
                f"Payments {stats.get('payments', 0)} dưới ngưỡng "
                f"{HOURLY_PAY_THRESHOLD}/h"
            )
        if stats.get("zns_sent", 0) < HOURLY_ZNS_THRESHOLD:
            alerts.append(
                f"ZNS sent {stats.get('zns_sent', 0)} dưới ngưỡng "
                f"{HOURLY_ZNS_THRESHOLD}/h"
            )

        # LLM Haiku narrate stats thành 1 dòng tiếng Việt
        narrative = await self._llm_narrate_hourly(stats, alerts)

        report = self._build_live_day_report(
            cohort=cohort,
            stats=stats,
            alerts=alerts,
            narrative=narrative,
            window_hours=window_hours,
        )

        sent_ok = await self._maybe_send_telegram(report, dry_run=dry_run)

        memory = {
            "agent_name": self.name,
            "content": (
                f"Live day hourly {cohort}: "
                f"reg={stats.get('registrations', 0)} "
                f"pay={stats.get('payments', 0)} "
                f"zns={stats.get('zns_sent', 0)} alerts={len(alerts)}"
            ),
            "keywords": ["live_day", cohort, "hourly"],
            "tags": [
                "launch",
                "k2",
                "live_day",
                "alert" if alerts else "ok",
                "sent" if sent_ok else "send_failed",
            ],
            "venture": "breakout",
            "context": f"hourly stats cohort={cohort} window={window_hours}h",
        }

        return AgentResult(
            success=True,
            output_text=report,
            output_payload={
                "event": "launch.live_day",
                "cohort": cohort,
                "stats": stats,
                "alerts": alerts,
                "window_hours": window_hours,
                "sent_ok": sent_ok,
                "dry_run": dry_run,
            },
            emitted_memories=[memory],
            escalation_required=bool(alerts),
            escalation_reason=(
                f"Live day alerts: {'; '.join(alerts[:2])}" if alerts else None
            ),
        )

    # ============================================================
    # Event 4: post-24h outcome report
    # ============================================================
    async def _handle_post_24h(self, ctx: ExecutionContext) -> AgentResult:
        dry_run = self._dry_run()
        cohort = ctx.payload.get("cohort", "K2") if ctx.payload else "K2"
        mock_stats = ctx.payload.get("mock_stats") if ctx.payload else None

        if mock_stats:
            # Test mode: dùng stats giả
            outcome = mock_stats
        else:
            outcome = await self._fetch_24h_outcome()

        revenue_vnd = int(outcome.get("revenue_vnd", 0))
        vnd_per_aud = float(
            os.getenv("VND_PER_AUD", str(DEFAULT_VND_PER_AUD))
        )
        revenue_aud = revenue_vnd / vnd_per_aud if vnd_per_aud > 0 else 0.0

        # LLM Opus phân tích outcome + retro learnings
        analysis = await self._llm_outcome_analysis(
            cohort=cohort,
            outcome=outcome,
            revenue_vnd=revenue_vnd,
            revenue_aud=revenue_aud,
        )

        report = self._build_outcome_report(
            cohort=cohort,
            outcome=outcome,
            revenue_vnd=revenue_vnd,
            revenue_aud=revenue_aud,
            analysis=analysis,
        )

        sent_ok = await self._maybe_send_telegram(report, dry_run=dry_run)

        memory = {
            "agent_name": self.name,
            "content": (
                f"Launch outcome {cohort}: "
                f"register={outcome.get('total_registered', 0)} "
                f"paid={outcome.get('total_paid', 0)} "
                f"revenue={revenue_vnd:,} VND ({revenue_aud:,.0f} AUD)"
            ),
            "keywords": ["launch_outcome", cohort, "post_24h"],
            "tags": [
                "launch",
                "k2",
                "launch_outcome",
                cohort.lower(),
                "sent" if sent_ok else "send_failed",
            ],
            "venture": "breakout",
            "context": f"launch outcome {cohort}",
        }

        return AgentResult(
            success=True,
            output_text=report,
            output_payload={
                "event": "launch.post_24h",
                "cohort": cohort,
                "outcome": outcome,
                "revenue_vnd": revenue_vnd,
                "revenue_aud": revenue_aud,
                "vnd_per_aud": vnd_per_aud,
                "sent_ok": sent_ok,
                "dry_run": dry_run,
            },
            emitted_memories=[memory],
        )

    # ============================================================
    # DB helpers (reuse MemoryLayer._pool)
    # ============================================================
    async def _fetch_whitelist_count(self) -> int:
        """Count customers created last 7 days (whitelist proxy)."""
        if not self.memory.dsn:
            return -1
        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(*)::int AS cnt
                    FROM public.customers
                    WHERE created_at > now() - interval '7 days'
                    """
                )
                return int(row["cnt"]) if row else 0
        except Exception as exc:  # noqa: BLE001
            log.warning("BC4 whitelist count fail: %r", exc)
            return -1

    async def _fetch_ads_status(self) -> dict[str, Any]:
        """Placeholder: FB Marketing API later. Hiện trả status synthetic."""
        # TODO: wire FB Marketing API qua tool layer khi BC10 publisher xong
        return {
            "status": "placeholder",
            "note": "FB Marketing API chưa wire, manual check Anna",
        }

    async def _fetch_live_stats(
        self, *, window_hours: int = 1
    ) -> dict[str, Any]:
        """Query events table cho registrations + payments + ZNS sent.

        Window = `window_hours` giờ gần nhất. Fail-soft nếu pool lỗi.
        """
        stats: dict[str, Any] = {
            "registrations": 0,
            "payments": 0,
            "payment_amount_vnd": 0,
            "zns_sent": 0,
            "window_hours": window_hours,
            "error": None,
        }
        if not self.memory.dsn:
            stats["error"] = "DATABASE_URL chưa set"
            return stats
        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            log.warning("BC4 get_pool fail: %r", exc)
            stats["error"] = f"pool init fail: {exc}"
            return stats

        try:
            async with pool.acquire() as conn:
                # Registrations: webinar register events
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(*)::int AS cnt
                    FROM public.events
                    WHERE event_type LIKE 'webinar%'
                      AND created_at > now() - ($1::int * interval '1 hour')
                    """,
                    window_hours,
                )
                stats["registrations"] = int(row["cnt"]) if row else 0

                # Payments: payment.completed
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(*)::int AS cnt,
                           COALESCE(SUM(
                               COALESCE(
                                   (properties->>'amount_vnd')::bigint,
                                   (properties->>'amount')::bigint,
                                   0
                               )
                           ), 0)::bigint AS total_amount
                    FROM public.events
                    WHERE event_type = 'payment.completed'
                      AND created_at > now() - ($1::int * interval '1 hour')
                    """,
                    window_hours,
                )
                if row:
                    stats["payments"] = int(row["cnt"] or 0)
                    stats["payment_amount_vnd"] = int(row["total_amount"] or 0)

                # ZNS sent: zns.sent / zns.success
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(*)::int AS cnt
                    FROM public.events
                    WHERE event_type IN ('zns.sent', 'zns.success')
                      AND created_at > now() - ($1::int * interval '1 hour')
                    """,
                    window_hours,
                )
                stats["zns_sent"] = int(row["cnt"]) if row else 0
        except Exception as exc:  # noqa: BLE001
            log.warning("BC4 live_stats SQL fail: %r", exc)
            stats["error"] = f"SQL fail: {exc}"

        return stats

    async def _fetch_24h_outcome(self) -> dict[str, Any]:
        """Aggregate 24h launch outcome: register count + paid breakdown 5 tier."""
        outcome: dict[str, Any] = {
            "total_registered": 0,
            "total_paid": 0,
            "revenue_vnd": 0,
            "by_tier": {tier: 0 for tier in TIER_PRICING_VND},
            "error": None,
        }
        if not self.memory.dsn:
            outcome["error"] = "DATABASE_URL chưa set"
            return outcome

        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            log.warning("BC4 get_pool fail: %r", exc)
            outcome["error"] = f"pool init fail: {exc}"
            return outcome

        try:
            async with pool.acquire() as conn:
                # Total register
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(*)::int AS cnt
                    FROM public.events
                    WHERE event_type LIKE 'webinar%'
                      AND created_at > now() - interval '24 hours'
                    """
                )
                outcome["total_registered"] = int(row["cnt"]) if row else 0

                # Paid + revenue
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(*)::int AS cnt,
                           COALESCE(SUM(
                               COALESCE(
                                   (properties->>'amount_vnd')::bigint,
                                   (properties->>'amount')::bigint,
                                   0
                               )
                           ), 0)::bigint AS total_amount
                    FROM public.events
                    WHERE event_type = 'payment.completed'
                      AND created_at > now() - interval '24 hours'
                    """
                )
                if row:
                    outcome["total_paid"] = int(row["cnt"] or 0)
                    outcome["revenue_vnd"] = int(row["total_amount"] or 0)

                # By tier: extract properties->>'tier' từ payment events
                rows = await conn.fetch(
                    """
                    SELECT COALESCE(properties->>'tier', 'unknown') AS tier,
                           COUNT(*)::int AS cnt
                    FROM public.events
                    WHERE event_type = 'payment.completed'
                      AND created_at > now() - interval '24 hours'
                    GROUP BY tier
                    """
                )
                for r in rows:
                    tier = (r["tier"] or "unknown").lower()
                    if tier in outcome["by_tier"]:
                        outcome["by_tier"][tier] = int(r["cnt"])
        except Exception as exc:  # noqa: BLE001
            log.warning("BC4 24h outcome SQL fail: %r", exc)
            outcome["error"] = f"SQL fail: {exc}"

        return outcome

    # ============================================================
    # LLM helpers
    # ============================================================
    async def _llm_narrate_hourly(
        self, stats: dict[str, Any], alerts: list[str]
    ) -> str:
        """Haiku 4.5 narrate hourly stats thành 1-2 dòng tiếng Việt."""
        if not self.llm.ready:
            return "LLM chưa init, skip narrative"

        compact = {
            "registrations": stats.get("registrations", 0),
            "payments": stats.get("payments", 0),
            "payment_amount_vnd": stats.get("payment_amount_vnd", 0),
            "zns_sent": stats.get("zns_sent", 0),
            "alerts_count": len(alerts),
        }
        prompt = (
            "Bạn là Launch Monitor cho Đào Thị Hằng (Hằng/Anna), venture Breakout. "
            "Tóm 1-2 dòng tiếng Việt hourly stats launch K2. KHÔNG preamble, "
            "KHÔNG markdown, KHÔNG dấu em-dash. Câu ngắn 5-12 từ.\n\n"
            f"Stats: {json.dumps(compact, ensure_ascii=False)}\n"
            f"Alerts: {alerts if alerts else 'không có'}"
        )
        try:
            resp = await self.llm.client.messages.create(
                model=self.haiku_model,
                max_tokens=DEFAULT_MAX_TOKENS_STATS,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC4 haiku narrate fail: %r", exc)
            return "LLM call fail, skip narrative"

        text_parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        return "".join(text_parts).strip() or "Không có narrative"

    async def _llm_outcome_analysis(
        self,
        *,
        cohort: str,
        outcome: dict[str, Any],
        revenue_vnd: int,
        revenue_aud: float,
    ) -> str:
        """Opus 4.7 phân tích outcome + retro learnings 4-6 dòng tiếng Việt."""
        if not self.llm.ready:
            return "LLM chưa init, skip analysis"

        total_reg = int(outcome.get("total_registered", 0))
        total_paid = int(outcome.get("total_paid", 0))
        conv = (total_paid / total_reg * 100.0) if total_reg > 0 else 0.0

        compact = {
            "cohort": cohort,
            "total_registered": total_reg,
            "total_paid": total_paid,
            "conversion_pct": round(conv, 2),
            "revenue_vnd": revenue_vnd,
            "revenue_aud": round(revenue_aud, 0),
            "by_tier": outcome.get("by_tier", {}),
            "tier_pricing_vnd": TIER_PRICING_VND,
        }

        prompt = (
            "Bạn là Launch Strategist cho Đào Thị Hằng (Hằng/Anna), venture "
            "Breakout (training Shopify cho người Việt).\n\n"
            "Phân tích outcome launch cohort K2 (24h gần nhất). Output 4-6 dòng "
            "tiếng Việt, mỗi dòng 1 insight actionable. Cấu trúc:\n"
            "- 1 dòng tóm số liệu chính (register, paid, revenue VND + AUD).\n"
            "- 1-2 dòng conversion funnel + tier mix winner/loser.\n"
            "- 1-2 dòng retro learnings (cái gì work, cái gì cần cải thiện K3).\n"
            "- 1 dòng next action Anna nên làm ngay.\n\n"
            "NGUYÊN TẮC:\n"
            "- KHÔNG em-dash, KHÔNG emoji.\n"
            "- KHÔNG hứa kết quả, KHÔNG bịa số.\n"
            "- Câu ngắn 5-15 từ.\n\n"
            f"Data: {json.dumps(compact, ensure_ascii=False)}"
        )

        try:
            resp = await self.llm.client.messages.create(
                model=self.opus_model,
                max_tokens=DEFAULT_MAX_TOKENS_OUTCOME,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC4 opus outcome fail: %r", exc)
            return "LLM call fail, skip analysis"

        text_parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        return "".join(text_parts).strip() or "Không có analysis"

    # ============================================================
    # Markdown formatters
    # ============================================================
    def _build_t_minus_3_report(
        self,
        *,
        cohort: str,
        whitelist_count: int,
        ads_status: dict[str, Any],
    ) -> str:
        whitelist_line = (
            f"{whitelist_count}" if whitelist_count >= 0 else "(query lỗi)"
        )
        ads_line = f"{ads_status.get('status', '?')} ({ads_status.get('note', '')})"

        lines = [
            f"🟡 *T-3 Launch Reminder, cohort {cohort}*",
            "",
            "_3 ngày nữa launch. Check pre-flight:_",
            f"- Whitelist sync (customers 7 ngày): {whitelist_line}",
            f"- Ads campaigns: {ads_line}",
            "",
            "*Anna cần làm hôm nay:*",
            "- Verify WK setup 3 sessions LIVE đúng timezone Asia/Ho_Chi_Minh",
            "- Save GHL workflow 25.1 (verify typo + Continue on Failure)",
            "- Verify số phone invalid trong GHL",
            "- Setup Gmail forwarding support@daothihang.com",
            "- Approve email reminder T-3 draft (BC4 soạn)",
            "",
            "_BC4 sẽ ping lại lúc T-1 với final readiness checklist._",
        ]
        return "\n".join(lines)

    def _build_t_minus_1_report(
        self,
        *,
        cohort: str,
        checklist: dict[str, bool],
        all_green: bool,
    ) -> str:
        icon = "🟢" if all_green else "🔴"
        status_label = "READY" if all_green else "BLOCKED"

        check_items = [
            ("wk_room_ready", "WebinarKit room ready"),
            ("sepay_healthy", "Sepay payment endpoints healthy"),
            ("zns_templates_approved", "ZNS Zalo templates approved"),
            ("ghl_workflows_enabled", "GHL workflows enabled"),
            ("email_reminders_queued", "Email reminders queued"),
        ]

        lines = [
            f"{icon} *T-1 Final Readiness, cohort {cohort}, {status_label}*",
            "",
            "_Mai 20:00 VN go-live. Final checklist:_",
        ]
        for key, label in check_items:
            mark = "✅" if checklist.get(key) else "❌"
            lines.append(f"- {mark} {label}")

        lines.append("")
        if all_green:
            lines.append("*Tất cả green. Sẵn sàng go-live mai 20:00 VN.*")
        else:
            blocked = [
                label for key, label in check_items if not checklist.get(key)
            ]
            lines.append(
                f"🚨 *NEED ANNA:* {len(blocked)} item chưa green, "
                "fix trước 18:00 hôm nay:"
            )
            for b in blocked:
                lines.append(f"- {b}")
        return "\n".join(lines)

    def _build_live_day_report(
        self,
        *,
        cohort: str,
        stats: dict[str, Any],
        alerts: list[str],
        narrative: str,
        window_hours: int,
    ) -> str:
        icon = "🟢" if not alerts else "🟡"
        now_vn = datetime.now(tz=timezone.utc) + timedelta(hours=7)
        ts = now_vn.strftime("%H:%M")

        reg = stats.get("registrations", 0)
        pay = stats.get("payments", 0)
        amount = int(stats.get("payment_amount_vnd", 0) or 0)
        zns = stats.get("zns_sent", 0)

        lines = [
            f"{icon} *Launch Live Hourly, cohort {cohort}, {ts} VN*",
            "",
            f"_Window {window_hours}h gần nhất:_",
            f"- Registrations: {reg}",
            f"- Payments: {pay} ({amount:,} VND)",
            f"- ZNS sent: {zns}",
            "",
            f"_Tóm: {narrative}_",
        ]
        if alerts:
            lines.append("")
            lines.append("🚨 *Alerts:*")
            for a in alerts:
                lines.append(f"- {a}")
        return "\n".join(lines)

    def _build_outcome_report(
        self,
        *,
        cohort: str,
        outcome: dict[str, Any],
        revenue_vnd: int,
        revenue_aud: float,
        analysis: str,
    ) -> str:
        total_reg = int(outcome.get("total_registered", 0))
        total_paid = int(outcome.get("total_paid", 0))
        conv = (total_paid / total_reg * 100.0) if total_reg > 0 else 0.0
        by_tier = outcome.get("by_tier", {}) or {}

        lines = [
            f"📊 *Launch Outcome 24h, cohort {cohort}*",
            "",
            f"- Total registered: {total_reg}",
            f"- Total paid: {total_paid} (conversion {conv:.1f}%)",
            f"- Revenue: {revenue_vnd:,} VND ({revenue_aud:,.0f} AUD)",
            "",
            "*Tier breakdown:*",
        ]
        tier_labels = [
            ("vip", "VIP 199k"),
            ("foundation", "Foundation 3M"),
            ("customer", "Customer 6M"),
            ("growth", "Growth 15M"),
            ("coaching", "Coaching 50M"),
        ]
        for key, label in tier_labels:
            cnt = int(by_tier.get(key, 0))
            tier_rev = cnt * TIER_PRICING_VND[key]
            lines.append(f"- {label}: {cnt} ({tier_rev:,} VND)")

        if outcome.get("error"):
            lines += ["", f"⚠️ DB error: {outcome['error']}"]

        lines += ["", "*Retro + next actions:*", analysis]
        return "\n".join(lines)

    # ============================================================
    # Utility
    # ============================================================
    def _dry_run(self) -> bool:
        return os.getenv("BC4_DRY_RUN", "") == "1"

    async def _maybe_send_telegram(
        self, text: str, *, dry_run: bool
    ) -> bool:
        if dry_run:
            log.info("BC4 DRY_RUN, skip Telegram send")
            return True
        try:
            return await send_telegram(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("BC4 Telegram send fail: %r", exc)
            return False


# ============================================================
# Telegram (reuse pattern BC1/BC3)
# ============================================================
async def send_telegram(text: str) -> bool:
    """Gửi message tới Telegram group Breakout Ops.

    Env vars:
        TELEGRAM_BOT_TOKEN: bot token
        TELEGRAM_OPS_GROUP_ID: chat id (default -1003813280155)

    Return True nếu HTTP 200, False nếu thiếu token hoặc non-200.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_OPS_GROUP_ID", DEFAULT_TELEGRAM_GROUP_ID)
    if not token:
        log.warning("BC4 TELEGRAM_BOT_TOKEN chưa set, skip send")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=DEFAULT_TELEGRAM_TIMEOUT) as client:
        resp = await client.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )
        if resp.status_code != 200:
            log.warning(
                "BC4 Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
