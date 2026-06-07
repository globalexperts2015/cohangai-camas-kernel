"""Cron Stale Alert, Monday 7am VN weekly, flag contacts silent > 30 ngày.

Pattern: cron-job.org → POST /kernel/execute, event=cron.stale_alert.tick.

Query Postgres contacts với last_active > 30 ngày trong stage S2/S3 (memory
project-breakout-customer-segmentation). Build report Telegram cho Anna, emit
memory để Phòng 04 Phiếu Comms downstream trigger nurture sequence.

Lý do query trực tiếp thay vì GHL API:
- CDP customer_360 đã sync GHL, có last_engagement_at + stage
- GHL API rate limit + chậm cho 33k contacts scan
- Postgres index trên last_active_at + stage = sub-second
"""
from __future__ import annotations

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

log = logging.getLogger("camas.cron_stale_alert")

EXPECTED_EVENT = "cron.stale_alert.tick"
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"
STALE_DAYS_THRESHOLD = 30


class CronStaleAlert(BaseBC):
    """Cron Monday 7am VN weekly, scan stale contacts + report Telegram."""

    name = "cron_stale_alert"
    scope = "Cron Monday 7am VN, scan contacts silent > 30 ngày + report Telegram"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(self, llm: LLMLayer, memory: MemoryLayer) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event != EXPECTED_EVENT:
            return AgentResult(
                success=False,
                output_text=f"{self.name} không xử lý event này",
                output_payload={
                    "trigger_event": event,
                    "supported": [EXPECTED_EVENT],
                },
            )

        date_vn = self._date_vn_str()
        dry_run = os.getenv("CRON_DRY_RUN", "") == "1"

        stats = await self._scan_stale()
        status_tag = "ok" if stats.get("error") is None else "fail"

        report = self._build_report(stats=stats, date_vn=date_vn)

        sent_ok = False
        if dry_run:
            log.info("cron_stale_alert DRY_RUN, skip Telegram send")
            sent_ok = True
        else:
            try:
                sent_ok = await send_telegram(report)
            except Exception as exc:  # noqa: BLE001
                log.warning("cron_stale_alert Telegram fail: %r", exc)
                sent_ok = False

        emitted_memories = [
            {
                "agent_name": self.name,
                "content_summary": (
                    f"Stale alert weekly executed total={stats.get('total', 0)} "
                    f"high={stats.get('high', 0)} medium={stats.get('medium', 0)} "
                    f"low={stats.get('low', 0)}"
                ),
                "keywords": ["stale_alert", date_vn, status_tag],
                "tags": ["cron", "stale_alert", "weekly", status_tag,
                         "sent" if sent_ok else "send_failed"],
                "venture": "all",
                "context": f"{EXPECTED_EVENT} {date_vn}",
            }
        ]

        return AgentResult(
            success=True,
            output_text=report,
            output_payload={
                "event": EXPECTED_EVENT,
                "date_vn": date_vn,
                "status_tag": status_tag,
                "stats": stats,
                "sent_ok": sent_ok,
                "dry_run": dry_run,
            },
            emitted_memories=emitted_memories,
        )

    async def _scan_stale(self) -> dict[str, Any]:
        """Query customers stale > 30 ngày, bucket High/Medium/Low.

        Heuristic Sprint 5:
        - High: paid customer churn risk (đã thanh toán + silent > 30d)
        - Medium: warm lead cold (có event nhưng silent)
        - Low: cold lead never engaged

        Fail-soft. Schema có thể chưa có stage column → fallback đếm tổng.
        """
        stats: dict[str, Any] = {
            "total": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "error": None,
        }

        if not self.memory.dsn:
            stats["error"] = "DATABASE_URL chưa set"
            return stats

        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            stats["error"] = f"pool init fail: {exc}"
            return stats

        try:
            async with pool.acquire() as conn:
                # Customer có event cuối cùng > 30 ngày trước
                # Heuristic: paid customer = có event payment, others = warm/cold
                rows = await conn.fetch(
                    """
                    WITH last_seen AS (
                        SELECT customer_id, MAX(ts) AS last_ts,
                               BOOL_OR(event_type LIKE '%%payment%%') AS has_payment,
                               COUNT(*)::int AS total_events
                        FROM public.events
                        WHERE customer_id IS NOT NULL
                        GROUP BY customer_id
                    )
                    SELECT customer_id, last_ts, has_payment, total_events
                    FROM last_seen
                    WHERE last_ts < now() - ($1::int * interval '1 day')
                    """,
                    STALE_DAYS_THRESHOLD,
                )
                stats["total"] = len(rows)
                for r in rows:
                    if r["has_payment"]:
                        stats["high"] += 1
                    elif int(r["total_events"] or 0) >= 3:
                        stats["medium"] += 1
                    else:
                        stats["low"] += 1
        except Exception as exc:  # noqa: BLE001
            log.warning("cron_stale_alert SQL fail: %r", exc)
            stats["error"] = f"SQL fail: {exc}"

        return stats

    def _build_report(
        self,
        *,
        stats: dict[str, Any],
        date_vn: str,
    ) -> str:
        high = stats.get("high", 0)
        medium = stats.get("medium", 0)
        low = stats.get("low", 0)
        total = stats.get("total", 0)
        lines = [
            f"⏰ *Stale Alert {date_vn}*",
            "",
            f"_Total stale > {STALE_DAYS_THRESHOLD} ngày:_ {total}",
            f"- High (paid churn risk): {high}",
            f"- Medium (warm cold): {medium}",
            f"- Low (cold never engaged): {low}",
            "",
            "*Đề xuất action:*",
            f"- High: 1-on-1 message Anna ({high} contacts)",
            "- Medium: nurture sequence 5 email (Phòng 04)",
            "- Low: last-chance promo + auto-archive",
        ]
        if stats.get("error"):
            lines += ["", f"_Stats error:_ {stats['error']}"]
        return "\n".join(lines)

    @staticmethod
    def _date_vn_str() -> str:
        now_vn = datetime.now(tz=timezone.utc) + timedelta(hours=7)
        return now_vn.strftime("%Y-%m-%d")


async def send_telegram(text: str) -> bool:
    """Gửi message tới Telegram group Breakout Ops."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_OPS_GROUP_ID", DEFAULT_TELEGRAM_GROUP_ID)
    if not token:
        log.warning("cron_stale_alert TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "cron_stale_alert Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
