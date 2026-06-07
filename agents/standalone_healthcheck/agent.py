"""Standalone Healthcheck agent.

Meta monitor cho infra Railway của Anna, khác BC5 (CDP specific) ở chỗ
quét toàn bộ service Railway + Postgres + external endpoint, alert Telegram
khi critical hoặc 3 consecutive warning.

Three trigger events:

1. `healthcheck.system_5min` (cron-job.org every 5 min)
   - HTTP GET 8 service health endpoint (parallel asyncio.gather)
   - Postgres SELECT 1 ping
   - Total budget < 10s
   - Decision 3-state ok | warning | critical (per probe + overall rollup)
   - Suppress repeated WARNING: chỉ alert khi ≥3 consecutive memory record
     trong 15 phút gần nhất (reuse pattern BC5)
   - CRITICAL bypass suppress, send Telegram ngay

2. `healthcheck.deep_audit` (cron-job.org daily 5am Perth)
   - Mọi shallow check + Postgres table growth + Voyage + Anthropic quota probe
   - Generate weekly stats digest Telegram + emit memory

3. `healthcheck.on_demand` (manual qua /kernel/execute)
   - Full check, return JSON, KHÔNG send Telegram

Architectural choice (expect_status flexibility):
    Một số endpoint Anna có auth gate (vd app.breakout.live trả 401/403
    cho unauthenticated GET, bfos-web có thể trả 404 ở root). Nếu treat
    non-2xx = warning, agent sẽ FP liên tục. Solution: mỗi service config
    list expect_status = [200, 401, 403, 404] để accept "alive nhưng có
    auth/route gate". Chỉ 5xx = critical, timeout = critical.

Architectural choice (self-check inclusion):
    Agent self-probe camas-kernel/kernel/status. Nếu kernel chính nó down,
    agent này cũng không chạy nổi (chicken-and-egg). Nhưng nếu chạy được
    thì self-check cho phép verify route /kernel/status còn alive, hữu ích
    cho diff giữa worker chạy vs route chết.

Style: tiếng Việt cho Telegram. ZERO em-dash. Type hints + async/await.
Idempotent: chỉ READ + emit memory, KHÔNG mutate DB ngoài auto extract.
"""
from __future__ import annotations

import asyncio
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

log = logging.getLogger("camas.standalone_healthcheck")

DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"  # Breakout Ops
DEFAULT_HTTP_TIMEOUT = 10.0

# Suppression giống BC5
WARNING_SUPPRESS_WINDOW_MIN = 15
WARNING_THRESHOLD_TO_ALERT = 3


# Danh sách service infra Anna đang chạy.
# expect_status flexibility: services có auth gate trả 401/403/404 vẫn coi là alive.
SERVICES_TO_CHECK: list[dict[str, Any]] = [
    {
        "name": "camas-kernel",
        "url": "https://camas-kernel-production.up.railway.app/kernel/status",
        "expect_status": [200],
        "critical": True,
    },
    {
        "name": "vault-mcp",
        "url": "https://vault-mcp-production-fdcc.up.railway.app/healthz",
        "expect_status": [200],
        "critical": True,
    },
    {
        "name": "cdp-webhook",
        "url": "https://cdp-webhook-production.up.railway.app/",
        "expect_status": [200],
        "critical": True,
    },
    {
        "name": "bfos-web",
        "url": "https://bfos-web-production.up.railway.app/",
        "expect_status": [200, 401, 403, 404],
        "critical": False,
    },
    {
        "name": "app.breakout.live",
        "url": "https://app.breakout.live/",
        "expect_status": [200, 401, 403, 404],
        "critical": False,
    },
    {
        "name": "breakout-zns",
        "url": "https://breakout-zns-production.up.railway.app/",
        "expect_status": [200, 401, 403, 404],
        "critical": False,
    },
    {
        "name": "result.breakout.live",
        "url": "https://result.breakout.live/",
        "expect_status": [200, 401, 403, 404],
        "critical": False,
    },
    {
        "name": "breakout.live",
        "url": "https://breakout.live/",
        "expect_status": [200, 401, 403, 404],
        "critical": False,
    },
]


class StandaloneHealthcheck(BaseBC):
    """Meta healthcheck cho mọi Railway service + Postgres của Anna.

    Verdict autonomy: L1_AUTO vì health check deterministic, không sinh
    content public. Anna chỉ nhận alert khi CRITICAL hoặc 3 consecutive
    WARNING.
    """

    name = "standalone_healthcheck"
    scope = (
        "System-wide health check across Railway services + Postgres "
        "+ external endpoints"
    )
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        services: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        super().__init__()
        self.llm = llm  # symmetry, không gọi LLM
        self.memory = memory
        self.services = services if services is not None else SERVICES_TO_CHECK

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""

        if event == "healthcheck.system_5min":
            return await self._handle_system_5min()
        if event == "healthcheck.deep_audit":
            return await self._handle_deep_audit()
        if event == "healthcheck.on_demand":
            return await self._handle_on_demand()

        return AgentResult(
            success=False,
            output_text="StandaloneHealthcheck không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "healthcheck.system_5min",
                    "healthcheck.deep_audit",
                    "healthcheck.on_demand",
                ],
            },
        )

    # ============================================================
    # Event 1: system 5 min
    # ============================================================
    async def _handle_system_5min(self) -> AgentResult:
        """Shallow check, chạy 288 lần/ngày, suppress repeated warning."""
        dry_run = os.getenv("HEALTHCHECK_DRY_RUN", "") == "1"
        timestamp = self._now_perth_str()

        probes = await self._probe_all_services()
        pg = await self._probe_postgres()
        overall = self._decide_overall_status(probes=probes, pg=pg)

        send_required = False
        telegram_text: Optional[str] = None
        alert_kind: Optional[str] = None
        consecutive_warnings = 0

        if overall == "critical":
            send_required = True
            alert_kind = "critical"
            telegram_text = self._format_critical_alert(
                probes=probes, pg=pg, timestamp=timestamp
            )
        elif overall == "warning":
            consecutive_warnings = await self._count_recent_warnings()
            if consecutive_warnings + 1 >= WARNING_THRESHOLD_TO_ALERT:
                send_required = True
                alert_kind = "warning_streak"
                telegram_text = self._format_warning_alert(
                    probes=probes,
                    pg=pg,
                    timestamp=timestamp,
                    streak=consecutive_warnings + 1,
                )

        sent_ok = False
        if send_required and telegram_text:
            if dry_run:
                log.info("Healthcheck DRY_RUN, skip Telegram (%s)", alert_kind)
                sent_ok = True
            else:
                try:
                    sent_ok = await send_telegram(telegram_text)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Healthcheck Telegram send fail: %r", exc)
                    sent_ok = False

        memory_tags = ["healthcheck", overall, "system_5min"]
        if send_required:
            memory_tags.append("alerted" if sent_ok else "alert_failed")

        emitted_memories = [
            {
                "agent_name": self.name,
                "content_summary": (
                    f"system_check healthcheck.system_5min status={overall}"
                ),
                "content": (
                    f"Healthcheck system_5min {timestamp} status={overall} "
                    f"probes={json.dumps(probes, ensure_ascii=False)[:400]} "
                    f"pg={json.dumps(pg, ensure_ascii=False)[:200]}"
                ),
                "keywords": ["healthcheck", overall, timestamp[:10]],
                "tags": memory_tags,
                "venture": "all",
                "context": f"healthcheck.system_5min status={overall}",
            }
        ]

        return AgentResult(
            success=True,
            output_text=(
                telegram_text
                if telegram_text
                else f"Healthcheck system_5min status={overall} (silent)"
            ),
            output_payload={
                "event": "healthcheck.system_5min",
                "status": overall,
                "probes": probes,
                "postgres": pg,
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
    # Event 2: deep audit
    # ============================================================
    async def _handle_deep_audit(self) -> AgentResult:
        """Deep audit daily 5am Perth, send digest Telegram."""
        dry_run = os.getenv("HEALTHCHECK_DRY_RUN", "") == "1"
        timestamp = self._now_perth_str()

        probes = await self._probe_all_services()
        pg = await self._probe_postgres()
        pg_growth = await self._probe_postgres_table_growth()
        voyage = await self._probe_voyage_quota()
        anthropic_q = await self._probe_anthropic_quota()
        overall = self._decide_overall_status(probes=probes, pg=pg)

        digest = self._format_deep_audit_digest(
            probes=probes,
            pg=pg,
            pg_growth=pg_growth,
            voyage=voyage,
            anthropic_quota=anthropic_q,
            timestamp=timestamp,
            overall=overall,
        )

        sent_ok = False
        if dry_run:
            log.info("Healthcheck DRY_RUN, skip Telegram (deep_audit)")
            sent_ok = True
        else:
            try:
                sent_ok = await send_telegram(digest)
            except Exception as exc:  # noqa: BLE001
                log.warning("Healthcheck deep_audit send fail: %r", exc)
                sent_ok = False

        emitted_memories = [
            {
                "agent_name": self.name,
                "content_summary": (
                    f"system_check healthcheck.deep_audit status={overall}"
                ),
                "content": (
                    f"Healthcheck deep_audit {timestamp} status={overall} "
                    f"pg_growth={json.dumps(pg_growth, ensure_ascii=False, default=str)[:400]} "
                    f"voyage={json.dumps(voyage, ensure_ascii=False)[:200]} "
                    f"anthropic={json.dumps(anthropic_q, ensure_ascii=False)[:200]}"
                ),
                "keywords": ["healthcheck", "deep_audit", timestamp[:10]],
                "tags": [
                    "healthcheck",
                    overall,
                    "deep_audit",
                    "sent" if sent_ok else "send_failed",
                ],
                "venture": "all",
                "context": f"healthcheck.deep_audit status={overall}",
            }
        ]

        return AgentResult(
            success=True,
            output_text=digest,
            output_payload={
                "event": "healthcheck.deep_audit",
                "status": overall,
                "probes": probes,
                "postgres": pg,
                "postgres_growth": pg_growth,
                "voyage": voyage,
                "anthropic": anthropic_q,
                "sent_ok": sent_ok,
                "dry_run": dry_run,
                "timestamp_perth": timestamp,
            },
            emitted_memories=emitted_memories,
        )

    # ============================================================
    # Event 3: on demand
    # ============================================================
    async def _handle_on_demand(self) -> AgentResult:
        """Manual check, KHÔNG send Telegram, return JSON."""
        timestamp = self._now_perth_str()
        probes = await self._probe_all_services()
        pg = await self._probe_postgres()
        overall = self._decide_overall_status(probes=probes, pg=pg)

        payload = {
            "event": "healthcheck.on_demand",
            "status": overall,
            "probes": probes,
            "postgres": pg,
            "timestamp_perth": timestamp,
        }

        emitted_memories = [
            {
                "agent_name": self.name,
                "content_summary": (
                    f"system_check healthcheck.on_demand status={overall}"
                ),
                "content": (
                    f"Healthcheck on_demand {timestamp} status={overall} probe-only"
                ),
                "keywords": ["healthcheck", "on_demand", timestamp[:10]],
                "tags": ["healthcheck", overall, "on_demand"],
                "venture": "all",
                "context": f"healthcheck.on_demand status={overall}",
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
    # Probes
    # ============================================================
    async def _probe_service(
        self, client: httpx.AsyncClient, svc: dict[str, Any]
    ) -> dict[str, Any]:
        """Probe 1 service. Fail-soft, return cấu trúc đầy đủ."""
        name = svc["name"]
        url = svc["url"]
        expect_status: list[int] = svc.get("expect_status", [200])
        try:
            resp = await client.get(url, timeout=DEFAULT_HTTP_TIMEOUT)
            status_code = resp.status_code
            latency_ms = resp.elapsed.total_seconds() * 1000.0
            if status_code in expect_status:
                return {
                    "name": name,
                    "status": "ok",
                    "code": status_code,
                    "ms": round(latency_ms, 1),
                    "url": url,
                }
            if 500 <= status_code < 600:
                return {
                    "name": name,
                    "status": "critical",
                    "code": status_code,
                    "ms": round(latency_ms, 1),
                    "url": url,
                }
            return {
                "name": name,
                "status": "warning",
                "code": status_code,
                "ms": round(latency_ms, 1),
                "url": url,
            }
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            return {
                "name": name,
                "status": "critical",
                "error": f"unreachable: {type(exc).__name__}",
                "url": url,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "name": name,
                "status": "warning",
                "error": str(exc)[:100],
                "url": url,
            }

    async def _probe_all_services(self) -> list[dict[str, Any]]:
        """Parallel probe mọi service trong self.services."""
        async with httpx.AsyncClient(
            timeout=DEFAULT_HTTP_TIMEOUT, follow_redirects=True
        ) as client:
            tasks = [self._probe_service(client, svc) for svc in self.services]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        normalized: list[dict[str, Any]] = []
        for svc, res in zip(self.services, results):
            if isinstance(res, dict):
                normalized.append(res)
            else:
                normalized.append(
                    {
                        "name": svc["name"],
                        "status": "critical",
                        "error": f"probe exception: {res!r}",
                        "url": svc.get("url"),
                    }
                )
        return normalized

    async def _probe_postgres(self) -> dict[str, Any]:
        """SELECT 1 ping Postgres."""
        result: dict[str, Any] = {
            "ok": False,
            "latency_ms": None,
            "error": None,
        }
        if not self.memory.dsn:
            result["error"] = "DATABASE_URL chưa set"
            return result
        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
            t0 = datetime.now(tz=timezone.utc)
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            t1 = datetime.now(tz=timezone.utc)
            result["ok"] = True
            result["latency_ms"] = round((t1 - t0).total_seconds() * 1000.0, 1)
        except Exception as exc:  # noqa: BLE001
            log.warning("Healthcheck postgres ping fail: %r", exc)
            result["error"] = str(exc)[:200]
        return result

    async def _probe_postgres_table_growth(self) -> dict[str, Any]:
        """Top 10 table size cho deep audit. Fail-soft."""
        result: dict[str, Any] = {"tables": [], "error": None}
        if not self.memory.dsn:
            result["error"] = "DATABASE_URL chưa set"
            return result
        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT
                      schemaname || '.' || relname AS table_name,
                      pg_total_relation_size(relid) AS bytes,
                      pg_size_pretty(pg_total_relation_size(relid)) AS pretty
                    FROM pg_catalog.pg_statio_user_tables
                    ORDER BY pg_total_relation_size(relid) DESC
                    LIMIT 10
                    """
                )
                result["tables"] = [
                    {
                        "name": r["table_name"],
                        "bytes": int(r["bytes"]) if r["bytes"] is not None else 0,
                        "pretty": r["pretty"],
                    }
                    for r in rows
                ]
        except Exception as exc:  # noqa: BLE001
            log.warning("Healthcheck pg table growth fail: %r", exc)
            result["error"] = str(exc)[:200]
        return result

    async def _probe_voyage_quota(self) -> dict[str, Any]:
        """Probe Voyage AI dashboard accessible. Best-effort (no public quota API).

        Trả về availability of dashboard endpoint chứ không phải quota number.
        """
        result: dict[str, Any] = {"reachable": False, "error": None}
        try:
            async with httpx.AsyncClient(
                timeout=DEFAULT_HTTP_TIMEOUT, follow_redirects=True
            ) as client:
                resp = await client.get("https://dash.voyageai.com/")
                result["reachable"] = resp.status_code < 500
                result["code"] = resp.status_code
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)[:100]
        return result

    async def _probe_anthropic_quota(self) -> dict[str, Any]:
        """Probe Anthropic API alive. Best-effort.

        Không gọi /v1/messages thật để tránh tốn token. Chỉ GET status page.
        """
        result: dict[str, Any] = {"reachable": False, "error": None}
        try:
            async with httpx.AsyncClient(
                timeout=DEFAULT_HTTP_TIMEOUT, follow_redirects=True
            ) as client:
                resp = await client.get("https://status.anthropic.com/")
                result["reachable"] = resp.status_code < 500
                result["code"] = resp.status_code
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)[:100]
        return result

    # ============================================================
    # Decision logic
    # ============================================================
    def _decide_overall_status(
        self,
        *,
        probes: list[dict[str, Any]],
        pg: dict[str, Any],
    ) -> str:
        """Rollup individual probe status sang overall ok | warning | critical."""
        if not pg.get("ok"):
            return "critical"

        any_critical = False
        any_warning = False
        for p in probes:
            status = p.get("status")
            critical_flag = False
            for svc in self.services:
                if svc["name"] == p.get("name"):
                    critical_flag = svc.get("critical", False)
                    break
            if status == "critical":
                if critical_flag:
                    return "critical"
                any_critical = True  # non-critical service down chỉ là warning
            elif status == "warning":
                any_warning = True

        if any_critical:
            return "warning"
        if any_warning:
            return "warning"
        return "ok"

    async def _count_recent_warnings(self) -> int:
        """Đếm WARNING memory trong WARNING_SUPPRESS_WINDOW_MIN gần nhất."""
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
                      AND tags @> ARRAY['healthcheck']::text[]
                      AND created_at > now() - ($2::int * interval '1 minute')
                    """,
                    self.name,
                    WARNING_SUPPRESS_WINDOW_MIN,
                )
                return int(count or 0)
        except Exception as exc:  # noqa: BLE001
            log.debug("Healthcheck _count_recent_warnings fail: %r", exc)
            return 0

    # ============================================================
    # Format helpers
    # ============================================================
    def _format_critical_alert(
        self,
        *,
        probes: list[dict[str, Any]],
        pg: dict[str, Any],
        timestamp: str,
    ) -> str:
        """CRITICAL Telegram tiếng Việt."""
        lines = [
            f"🚨 *Infra CRITICAL Alert {timestamp}*",
            "",
        ]
        if not pg.get("ok"):
            lines.append(f"- Postgres: DOWN, {pg.get('error', 'unknown')}")
        for p in probes:
            if p.get("status") == "critical":
                if "code" in p:
                    lines.append(
                        f"- {p['name']}: HTTP {p['code']} ({p.get('url')})"
                    )
                else:
                    lines.append(
                        f"- {p['name']}: {p.get('error', 'unreachable')} "
                        f"({p.get('url')})"
                    )
        lines.append("")
        lines.append(
            "Action: vào Railway dashboard check service down, "
            "restart nếu cần."
        )
        return "\n".join(lines)

    def _format_warning_alert(
        self,
        *,
        probes: list[dict[str, Any]],
        pg: dict[str, Any],
        timestamp: str,
        streak: int,
    ) -> str:
        """WARNING streak Telegram tiếng Việt."""
        lines = [
            f"⚠️ *Infra WARNING streak {timestamp}*",
            "",
            f"Streak: {streak} cảnh báo liên tiếp 15 phút qua",
            "",
        ]
        for p in probes:
            if p.get("status") == "warning":
                if "code" in p:
                    lines.append(
                        f"- {p['name']}: HTTP {p['code']}"
                    )
                else:
                    lines.append(
                        f"- {p['name']}: {p.get('error', 'unknown')}"
                    )
            elif p.get("status") == "critical":
                lines.append(
                    f"- {p['name']}: critical, {p.get('error') or p.get('code')}"
                )
        lines.append("")
        lines.append("Action: verify từng service Railway, check logs.")
        return "\n".join(lines)

    def _format_deep_audit_digest(
        self,
        *,
        probes: list[dict[str, Any]],
        pg: dict[str, Any],
        pg_growth: dict[str, Any],
        voyage: dict[str, Any],
        anthropic_quota: dict[str, Any],
        timestamp: str,
        overall: str,
    ) -> str:
        """Daily deep audit digest tiếng Việt."""
        status_icon = {
            "ok": "✅",
            "warning": "⚠️",
            "critical": "🚨",
        }.get(overall, "ℹ️")

        lines = [
            f"{status_icon} *Infra Deep Audit {timestamp}*",
            "",
            "_Service status:_",
        ]
        for p in probes:
            icon = {
                "ok": "✓",
                "warning": "⚠",
                "critical": "✗",
            }.get(p.get("status", ""), "?")
            if "code" in p:
                lines.append(
                    f"- {icon} {p['name']}: {p['code']} ({p.get('ms', 0):.0f}ms)"
                )
            else:
                lines.append(
                    f"- {icon} {p['name']}: {p.get('error', 'unknown')}"
                )

        lines += ["", "_Postgres:_"]
        if pg.get("ok"):
            lines.append(f"- Ping OK ({pg.get('latency_ms', 0):.0f}ms)")
        else:
            lines.append(f"- FAIL: {pg.get('error', 'unknown')}")

        tables = pg_growth.get("tables") or []
        if tables:
            lines.append("- Top tables:")
            for t in tables[:5]:
                lines.append(f"  · {t['name']}: {t['pretty']}")

        lines += ["", "_External quota probes:_"]
        voyage_label = (
            f"reachable ({voyage.get('code', '?')})"
            if voyage.get("reachable")
            else f"FAIL ({voyage.get('error', 'unknown')})"
        )
        anth_label = (
            f"reachable ({anthropic_quota.get('code', '?')})"
            if anthropic_quota.get("reachable")
            else f"FAIL ({anthropic_quota.get('error', 'unknown')})"
        )
        lines.append(f"- Voyage dashboard: {voyage_label}")
        lines.append(f"- Anthropic status: {anth_label}")

        if pg_growth.get("error"):
            lines += ["", f"_Stats error:_ {pg_growth['error']}"]

        return "\n".join(lines)

    # ============================================================
    # Utility
    # ============================================================
    @staticmethod
    def _now_perth_str() -> str:
        """Timestamp Perth AWST UTC+8, format YYYY-MM-DD HH:MM."""
        now_perth = datetime.now(tz=timezone.utc) + timedelta(hours=8)
        return now_perth.strftime("%Y-%m-%d %H:%M")


# ============================================================
# Telegram (reuse pattern BC1/BC3/BC5)
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
        log.warning("Healthcheck TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "Healthcheck Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
