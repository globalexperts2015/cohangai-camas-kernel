"""BC5 CDP Monitor agent.

Infra observer cho Breakout CDP service `cdp-webhook-production`
(Railway project `breakout-funnel-os-staging`). KHÔNG produce content public,
KHÔNG rebuild CDP service, chỉ verify health + alert Anna qua Telegram khi
critical.

Three trigger events:

1. `monitor.health_5min` (cron-job.org every 5 min)
   - Postgres SELECT 1 ping
   - Event ingestion rate trong 5 phút gần nhất
   - CDP webhook health endpoint (`GET https://cdp-webhook-production.up.railway.app/`)
   - Decision rule 3-state: ok | warning | critical
   - Suppress repeated warnings: chỉ send Telegram khi 3 consecutive WARNING
     (state đếm qua agent_memory query, không ghi state DB riêng để idempotent)
   - CRITICAL = send Telegram ngay

2. `monitor.daily_audit` (cron-job.org daily 7am Perth, sau BC1 morning brief)
   - Customers count 7d delta
   - Events 24h breakdown
   - agent_memory growth 24h
   - customer_360 freshness
   - Send Telegram daily digest tóm tắt cho Anna

3. `monitor.on_demand` (manual trigger qua /kernel/execute)
   - Full health check, return JSON, KHÔNG send Telegram
   - Dùng cho Anna debug local

Architectural choice (suppress repeated warnings):
    BC5 chạy mỗi 5 phút (288 lần/ngày). Nếu mỗi WARNING đều send Telegram,
    Anna sẽ ngập alert nhiễu khi K2 launch giờ thấp điểm (low event rate
    natural sau 22h Perth). Solution: count WARNING memory trong 15 phút gần
    nhất, chỉ send khi ≥3 consecutive. CRITICAL bypass suppress.

DB:
    Reuse `MemoryLayer._pool` asyncpg pool. Queries phải FAST (<100ms mỗi
    query) vì BC5 chạy 288 lần/ngày, mỗi run query 4 table.

Style: tiếng Việt cho Telegram + docstring. ZERO em-dash `,`. Type hints
+ async/await xuyên suốt. Idempotent: query 2 lần liên tiếp = state giống
nhau (KHÔNG mutate DB ngoài auto_extract memory).
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

log = logging.getLogger("camas.bc5_cdp_monitor")

DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"  # Breakout Ops
DEFAULT_HEALTH_HTTP_TIMEOUT = 10.0
DEFAULT_CDP_WEBHOOK_URL = "https://cdp-webhook-production.up.railway.app/"

# Decision thresholds
WORK_HOUR_START_PERTH = 8  # 8am Perth (AWST UTC+8)
WORK_HOUR_END_PERTH = 22  # 10pm Perth
MIN_EVENTS_IN_5MIN_WORK_HOURS = 1  # less than this = WARNING

# Consecutive warning suppression
WARNING_SUPPRESS_WINDOW_MIN = 15
WARNING_THRESHOLD_TO_ALERT = 3


class BC5CDPMonitor(BaseBC):
    """BC5 CDP Monitor, verify CDP health 5 phút, alert critical qua Telegram.

    Verdict autonomy: L1_AUTO vì health check là deterministic infra observer,
    không sinh content public, không quyết định business. Anna chỉ nhận alert
    khi CRITICAL hoặc 3 consecutive WARNING.
    """

    name = "bc5_cdp_monitor"
    scope = "Verify CDP health 5min, alert critical via Telegram direct"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        cdp_webhook_url: str = DEFAULT_CDP_WEBHOOK_URL,
    ) -> None:
        super().__init__()
        self.llm = llm  # giữ reference để symmetry với BC1/BC3, BC5 không gọi LLM
        self.memory = memory
        self.cdp_webhook_url = cdp_webhook_url

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""

        if event == "monitor.health_5min":
            return await self._handle_health_5min()
        if event == "monitor.daily_audit":
            return await self._handle_daily_audit()
        if event == "monitor.on_demand":
            return await self._handle_on_demand()

        return AgentResult(
            success=False,
            output_text="BC5 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "monitor.health_5min",
                    "monitor.daily_audit",
                    "monitor.on_demand",
                ],
            },
        )

    # ============================================================
    # Event 1: health 5 min
    # ============================================================
    async def _handle_health_5min(self) -> AgentResult:
        """Health check nhẹ, chạy 288 lần/ngày. Suppress repeated WARNING."""
        dry_run = os.getenv("BC5_DRY_RUN", "") == "1"
        checks = await self._run_health_checks()
        status = self._decide_status(checks)
        timestamp = self._now_perth_str()

        send_required = False
        telegram_text: Optional[str] = None
        alert_kind: Optional[str] = None
        consecutive_warnings = 0

        if status == "critical":
            send_required = True
            alert_kind = "critical"
            telegram_text = self._format_critical_alert(
                checks=checks, timestamp=timestamp
            )
        elif status == "warning":
            consecutive_warnings = await self._count_recent_warnings()
            # +1 vì memory tuần hiện tại chưa store xong
            if consecutive_warnings + 1 >= WARNING_THRESHOLD_TO_ALERT:
                send_required = True
                alert_kind = "warning_streak"
                telegram_text = self._format_warning_alert(
                    checks=checks,
                    timestamp=timestamp,
                    streak=consecutive_warnings + 1,
                )

        sent_ok = False
        if send_required and telegram_text:
            if dry_run:
                log.info("BC5 DRY_RUN, skip Telegram send (%s)", alert_kind)
                sent_ok = True
            else:
                try:
                    sent_ok = await send_telegram(telegram_text)
                except Exception as exc:  # noqa: BLE001
                    log.warning("BC5 Telegram send fail: %r", exc)
                    sent_ok = False

        memory_tags = [status, "health_check"]
        if send_required:
            memory_tags.append("alerted" if sent_ok else "alert_failed")

        emitted_memories = [
            {
                "agent_name": self.name,
                "content_summary": (
                    f"health check monitor.health_5min status={status}"
                ),
                "content": (
                    f"BC5 health_5min {timestamp} status={status} "
                    f"checks={json.dumps(checks, ensure_ascii=False)[:400]}"
                ),
                "keywords": ["health_check", status, timestamp[:10]],
                "tags": memory_tags,
                "venture": "all",
                "context": f"monitor.health_5min status={status}",
            }
        ]

        return AgentResult(
            success=True,
            output_text=(
                telegram_text
                if telegram_text
                else f"BC5 health_5min status={status} (silent)"
            ),
            output_payload={
                "event": "monitor.health_5min",
                "status": status,
                "checks": checks,
                "send_required": send_required,
                "alert_kind": alert_kind,
                "consecutive_warnings_prior": consecutive_warnings,
                "sent_ok": sent_ok,
                "dry_run": dry_run,
                "timestamp_perth": timestamp,
            },
            emitted_memories=emitted_memories,
        )

    # ============================================================
    # Event 2: daily audit
    # ============================================================
    async def _handle_daily_audit(self) -> AgentResult:
        """Audit comprehensive daily, send digest cho Anna mỗi 7am Perth."""
        dry_run = os.getenv("BC5_DRY_RUN", "") == "1"
        timestamp = self._now_perth_str()

        checks = await self._run_health_checks()
        audit_stats = await self._collect_daily_audit_stats()

        digest = self._format_daily_audit_digest(
            checks=checks, stats=audit_stats, timestamp=timestamp
        )

        sent_ok = False
        if dry_run:
            log.info("BC5 DRY_RUN, skip Telegram send (daily_audit)")
            sent_ok = True
        else:
            try:
                sent_ok = await send_telegram(digest)
            except Exception as exc:  # noqa: BLE001
                log.warning("BC5 Telegram daily_audit send fail: %r", exc)
                sent_ok = False

        status = self._decide_status(checks)

        emitted_memories = [
            {
                "agent_name": self.name,
                "content_summary": (
                    f"health check monitor.daily_audit status={status}"
                ),
                "content": (
                    f"BC5 daily_audit {timestamp} status={status} "
                    f"stats={json.dumps(audit_stats, ensure_ascii=False, default=str)[:600]}"
                ),
                "keywords": ["health_check", "daily_audit", timestamp[:10]],
                "tags": [status, "health_check", "daily_audit",
                         "sent" if sent_ok else "send_failed"],
                "venture": "all",
                "context": f"monitor.daily_audit status={status}",
            }
        ]

        return AgentResult(
            success=True,
            output_text=digest,
            output_payload={
                "event": "monitor.daily_audit",
                "status": status,
                "checks": checks,
                "stats": audit_stats,
                "sent_ok": sent_ok,
                "dry_run": dry_run,
                "timestamp_perth": timestamp,
            },
            emitted_memories=emitted_memories,
        )

    # ============================================================
    # Event 3: on-demand
    # ============================================================
    async def _handle_on_demand(self) -> AgentResult:
        """Manual health check, KHÔNG send Telegram, KHÔNG emit alert tag.

        Dùng cho Anna debug qua POST /kernel/execute.
        """
        timestamp = self._now_perth_str()
        checks = await self._run_health_checks()
        audit_stats = await self._collect_daily_audit_stats()
        status = self._decide_status(checks)

        payload = {
            "event": "monitor.on_demand",
            "status": status,
            "checks": checks,
            "stats": audit_stats,
            "timestamp_perth": timestamp,
        }

        # Emit memory dạng probe (không trigger alert)
        emitted_memories = [
            {
                "agent_name": self.name,
                "content_summary": (
                    f"health check monitor.on_demand status={status}"
                ),
                "content": (
                    f"BC5 on_demand {timestamp} status={status} probe-only"
                ),
                "keywords": ["health_check", "on_demand", timestamp[:10]],
                "tags": [status, "health_check", "on_demand"],
                "venture": "all",
                "context": f"monitor.on_demand status={status}",
            }
        ]

        return AgentResult(
            success=True,
            output_text=json.dumps(
                payload, ensure_ascii=False, default=str, indent=2
            ),
            output_payload=payload,
            emitted_memories=emitted_memories,
        )

    # ============================================================
    # Health probes
    # ============================================================
    async def _run_health_checks(self) -> dict[str, Any]:
        """Run 3 probe: Postgres ping, event rate, CDP webhook.

        Fail-soft: mỗi probe wrap try/except, return cấu trúc đầy đủ.
        """
        result: dict[str, Any] = {
            "postgres": {"ok": False, "latency_ms": None, "error": None},
            "event_rate_5min": {"count": None, "error": None},
            "cdp_webhook": {
                "ok": False,
                "status_code": None,
                "latency_ms": None,
                "error": None,
            },
            "in_work_hours": self._is_work_hours_perth(),
        }

        # Postgres ping + event rate (1 acquire 2 queries cho nhanh)
        if not self.memory.dsn:
            result["postgres"]["error"] = "DATABASE_URL chưa set"
            result["event_rate_5min"]["error"] = "DATABASE_URL chưa set"
        else:
            try:
                pool = await self.memory._get_pool()  # noqa: SLF001
                t0 = datetime.now(tz=timezone.utc)
                async with pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                    t1 = datetime.now(tz=timezone.utc)
                    result["postgres"]["ok"] = True
                    result["postgres"]["latency_ms"] = (
                        (t1 - t0).total_seconds() * 1000.0
                    )

                    try:
                        # events table dùng cột `ts` (legacy, không phải created_at)
                        rate = await conn.fetchval(
                            "SELECT COUNT(*) FROM public.events "
                            "WHERE ts > now() - interval '5 minutes'"
                        )
                        result["event_rate_5min"]["count"] = int(rate or 0)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("BC5 event rate query fail: %r", exc)
                        result["event_rate_5min"]["error"] = str(exc)
            except Exception as exc:  # noqa: BLE001
                log.warning("BC5 postgres ping fail: %r", exc)
                result["postgres"]["error"] = str(exc)

        # CDP webhook health
        try:
            t0 = datetime.now(tz=timezone.utc)
            async with httpx.AsyncClient(
                timeout=DEFAULT_HEALTH_HTTP_TIMEOUT
            ) as client:
                resp = await client.get(self.cdp_webhook_url)
            t1 = datetime.now(tz=timezone.utc)
            result["cdp_webhook"]["status_code"] = resp.status_code
            result["cdp_webhook"]["latency_ms"] = (
                (t1 - t0).total_seconds() * 1000.0
            )
            result["cdp_webhook"]["ok"] = 200 <= resp.status_code < 300
        except Exception as exc:  # noqa: BLE001
            log.warning("BC5 webhook probe fail: %r", exc)
            result["cdp_webhook"]["error"] = str(exc)

        return result

    def _decide_status(self, checks: dict[str, Any]) -> str:
        """3-state decision: ok | warning | critical."""
        pg = checks.get("postgres") or {}
        webhook = checks.get("cdp_webhook") or {}
        rate = checks.get("event_rate_5min") or {}

        # CRITICAL: Postgres down hoặc webhook 5xx hoặc unreachable
        if not pg.get("ok"):
            return "critical"
        status_code = webhook.get("status_code")
        if status_code is not None and status_code >= 500:
            return "critical"
        if webhook.get("error") and status_code is None:
            return "critical"

        # WARNING: webhook non-200 nhưng <500, hoặc event rate thấp giờ làm việc,
        # hoặc event rate query fail
        if status_code is not None and not (200 <= status_code < 300):
            return "warning"
        if rate.get("error"):
            return "warning"
        if checks.get("in_work_hours"):
            count = rate.get("count")
            if count is not None and count < MIN_EVENTS_IN_5MIN_WORK_HOURS:
                return "warning"

        return "ok"

    # ============================================================
    # Daily audit stats
    # ============================================================
    async def _collect_daily_audit_stats(self) -> dict[str, Any]:
        """Query 4 number set cho daily audit.

        Fail-soft từng query, return dict với None nếu fail.
        """
        stats: dict[str, Any] = {
            "new_customers_7d": None,
            "events_24h": None,
            "memories_24h": None,
            "last_c360_compute": None,
            "events_24h_by_type": [],
            "bc_recent_runs": {},
            "error": None,
        }

        if not self.memory.dsn:
            stats["error"] = "DATABASE_URL chưa set"
            return stats

        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            log.warning("BC5 daily audit get_pool fail: %r", exc)
            stats["error"] = f"pool init fail: {exc}"
            return stats

        try:
            async with pool.acquire() as conn:
                # 1 query combined cho core stats.
                # events table dùng `ts` (legacy); customers + agent_memory dùng created_at.
                try:
                    row = await conn.fetchrow(
                        """
                        SELECT
                          (SELECT COUNT(*) FROM public.customers
                             WHERE created_at > now() - interval '7 days')
                            AS new_customers_7d,
                          (SELECT COUNT(*) FROM public.events
                             WHERE ts > now() - interval '24 hours')
                            AS events_24h,
                          (SELECT COUNT(*) FROM public.agent_memory
                             WHERE created_at > now() - interval '24 hours')
                            AS memories_24h,
                          (SELECT MAX(computed_at) FROM public.customer_360)
                            AS last_c360_compute
                        """
                    )
                    if row:
                        stats["new_customers_7d"] = (
                            int(row["new_customers_7d"])
                            if row["new_customers_7d"] is not None
                            else 0
                        )
                        stats["events_24h"] = (
                            int(row["events_24h"])
                            if row["events_24h"] is not None
                            else 0
                        )
                        stats["memories_24h"] = (
                            int(row["memories_24h"])
                            if row["memories_24h"] is not None
                            else 0
                        )
                        last_c360 = row["last_c360_compute"]
                        stats["last_c360_compute"] = (
                            last_c360.isoformat()
                            if hasattr(last_c360, "isoformat")
                            else last_c360
                        )
                except Exception as exc:  # noqa: BLE001
                    log.warning("BC5 audit core query fail: %r", exc)
                    stats["error"] = f"core query fail: {exc}"

                # Event type breakdown 24h (events table cột `ts`)
                try:
                    rows = await conn.fetch(
                        """
                        SELECT event_type, COUNT(*)::int AS cnt
                        FROM public.events
                        WHERE ts > now() - interval '24 hours'
                        GROUP BY event_type
                        ORDER BY cnt DESC
                        LIMIT 8
                        """
                    )
                    stats["events_24h_by_type"] = [
                        {"event_type": r["event_type"], "count": r["cnt"]}
                        for r in rows
                    ]
                except Exception as exc:  # noqa: BLE001
                    log.warning("BC5 audit events_by_type fail: %r", exc)

                # BC1/BC2/BC3/BC9 last run
                try:
                    rows = await conn.fetch(
                        """
                        SELECT agent_name, MAX(created_at) AS last_run
                        FROM public.agent_memory
                        WHERE agent_name = ANY($1::text[])
                        GROUP BY agent_name
                        """,
                        [
                            "bc1_team_leader",
                            "bc2_voice_guardian",
                            "bc3_feedback_loop",
                            "bc9_compliance_officer",
                        ],
                    )
                    for r in rows:
                        last_run = r["last_run"]
                        stats["bc_recent_runs"][r["agent_name"]] = (
                            last_run.isoformat()
                            if hasattr(last_run, "isoformat")
                            else str(last_run)
                        )
                except Exception as exc:  # noqa: BLE001
                    log.warning("BC5 audit bc_recent_runs fail: %r", exc)
        except Exception as exc:  # noqa: BLE001
            log.warning("BC5 daily audit SQL fail: %r", exc)
            stats["error"] = f"SQL fail: {exc}"

        return stats

    # ============================================================
    # Warning streak detection
    # ============================================================
    async def _count_recent_warnings(self) -> int:
        """Đếm WARNING memory trong WARNING_SUPPRESS_WINDOW_MIN gần nhất.

        Idempotent: chỉ READ agent_memory, không mutate.
        """
        if not self.memory.dsn:
            return 0
        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
            async with pool.acquire() as conn:
                count = await conn.fetchval(
                    """
                    SELECT COUNT(*)::int
                    FROM public.agent_memory
                    WHERE agent_name = $1
                      AND tags @> ARRAY['warning']::text[]
                      AND tags @> ARRAY['health_check']::text[]
                      AND created_at > now() - ($2::int * interval '1 minute')
                    """,
                    self.name,
                    WARNING_SUPPRESS_WINDOW_MIN,
                )
                return int(count or 0)
        except Exception as exc:  # noqa: BLE001
            log.debug("BC5 _count_recent_warnings fail: %r", exc)
            return 0

    # ============================================================
    # Format helpers
    # ============================================================
    def _format_critical_alert(
        self, *, checks: dict[str, Any], timestamp: str
    ) -> str:
        """CRITICAL Telegram message tiếng Việt."""
        pg = checks.get("postgres") or {}
        webhook = checks.get("cdp_webhook") or {}

        if not pg.get("ok"):
            service_name = "Postgres CDP"
            status_code = "DOWN"
            error_message = pg.get("error") or "không phản hồi SELECT 1"
            action = (
                "Vào Railway breakout-funnel-os-staging check Postgres "
                "addon, restart nếu cần."
            )
            url = "https://railway.com/project/9337df05-da4f-406e-8df8-51373f733d76"
        else:
            service_name = "CDP Webhook"
            status_code = webhook.get("status_code") or "unreachable"
            error_message = (
                webhook.get("error") or f"HTTP {status_code}"
            )
            action = (
                "Vào Railway check service cdp-webhook-production logs, "
                "verify endpoint /api/event."
            )
            url = self.cdp_webhook_url

        return (
            f"🚨 CDP CRITICAL Alert {timestamp}\n\n"
            f"Service: {service_name}\n"
            f"Status: {status_code} {error_message}\n"
            f"Action required: {action}\n\n"
            f"URL: {url}"
        )

    def _format_warning_alert(
        self,
        *,
        checks: dict[str, Any],
        timestamp: str,
        streak: int,
    ) -> str:
        """WARNING streak (≥3 consecutive) Telegram message."""
        rate = (checks.get("event_rate_5min") or {}).get("count")
        webhook = checks.get("cdp_webhook") or {}
        status_code = webhook.get("status_code")

        reasons: list[str] = []
        if rate is not None and rate < MIN_EVENTS_IN_5MIN_WORK_HOURS:
            reasons.append(f"event ingestion thấp ({rate} events/5 phút)")
        if status_code is not None and not (200 <= status_code < 300):
            reasons.append(f"CDP webhook HTTP {status_code}")
        if (checks.get("event_rate_5min") or {}).get("error"):
            reasons.append("event rate query lỗi")
        reason_text = "; ".join(reasons) or "không xác định"

        return (
            f"⚠️ CDP WARNING streak {timestamp}\n\n"
            f"Service: Breakout CDP\n"
            f"Streak: {streak} cảnh báo liên tiếp 15 phút qua\n"
            f"Nguyên nhân: {reason_text}\n"
            f"Action required: Verify event flow Sepay/WK/GHL,"
            f" check dashboard breakout.live\n\n"
            f"URL: https://result.breakout.live/dashboard"
        )

    def _format_daily_audit_digest(
        self,
        *,
        checks: dict[str, Any],
        stats: dict[str, Any],
        timestamp: str,
    ) -> str:
        """Daily audit Telegram digest tiếng Việt."""
        status = self._decide_status(checks)
        status_icon = {
            "ok": "✅",
            "warning": "⚠️",
            "critical": "🚨",
        }.get(status, "ℹ️")

        pg = checks.get("postgres") or {}
        webhook = checks.get("cdp_webhook") or {}
        rate = checks.get("event_rate_5min") or {}

        pg_label = (
            f"OK ({pg.get('latency_ms', 0):.0f}ms)"
            if pg.get("ok")
            else f"FAIL ({pg.get('error', 'unknown')})"
        )
        webhook_label = (
            f"HTTP {webhook.get('status_code')} "
            f"({webhook.get('latency_ms', 0):.0f}ms)"
            if webhook.get("status_code") is not None
            else f"FAIL ({webhook.get('error', 'unknown')})"
        )
        rate_label = (
            f"{rate.get('count')} events/5min"
            if rate.get("count") is not None
            else f"FAIL ({rate.get('error', 'unknown')})"
        )

        new_cust = stats.get("new_customers_7d")
        events_24h = stats.get("events_24h")
        memories_24h = stats.get("memories_24h")
        last_c360 = stats.get("last_c360_compute") or "chưa compute"

        lines = [
            f"{status_icon} *CDP Daily Audit {timestamp}*",
            "",
            "_Health snapshot:_",
            f"- Postgres: {pg_label}",
            f"- CDP webhook: {webhook_label}",
            f"- Event rate (5min): {rate_label}",
            "",
            "_24h activity:_",
            f"- Customers mới (7d): {new_cust if new_cust is not None else 'n/a'}",
            f"- Events (24h): {events_24h if events_24h is not None else 'n/a'}",
            f"- Memories (24h): {memories_24h if memories_24h is not None else 'n/a'}",
            f"- customer_360 last compute: {last_c360}",
        ]

        events_by_type = stats.get("events_24h_by_type") or []
        if events_by_type:
            top = ", ".join(
                f"{e['event_type']}={e['count']}"
                for e in events_by_type[:5]
            )
            lines += ["", f"_Top event types 24h:_ {top}"]

        bc_runs = stats.get("bc_recent_runs") or {}
        if bc_runs:
            lines += ["", "_BC last run:_"]
            for agent in (
                "bc1_team_leader",
                "bc2_voice_guardian",
                "bc3_feedback_loop",
                "bc9_compliance_officer",
            ):
                last = bc_runs.get(agent, "chưa chạy")
                lines.append(f"- {agent}: {last}")

        if stats.get("error"):
            lines += ["", f"_Stats error:_ {stats['error']}"]

        return "\n".join(lines)

    # ============================================================
    # Utility
    # ============================================================
    @staticmethod
    def _now_perth_str() -> str:
        """Trả về timestamp giờ Perth (AWST UTC+8) format YYYY-MM-DD HH:MM."""
        now_perth = datetime.now(tz=timezone.utc) + timedelta(hours=8)
        return now_perth.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _is_work_hours_perth() -> bool:
        """Giờ làm việc Perth 8am-10pm (AWST)."""
        now_perth = datetime.now(tz=timezone.utc) + timedelta(hours=8)
        return WORK_HOUR_START_PERTH <= now_perth.hour < WORK_HOUR_END_PERTH


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
        log.warning("BC5 TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "BC5 Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
