"""Phòng 08 Dữ liệu agent.

Analytics + ETL + daily digest 8am VN. Aggregate dữ liệu 3 venture Breakout +
Speakout + Cohangai từ 6 nguồn (GHL + Sepay + ZNS + WK + Postgres CDP + Telegram).
Memory: `reference-cdp-canonical.md` (public schema canonical).

Trigger events:
- `data.daily_digest`: 8am VN daily, KPI snapshot + anomaly + Telegram
- `data.adhoc_query`: manual query qua /kernel/execute, return JSON, không send

Autonomy L1 (read-only + report only). ZERO em-dash. Stub Sheets API Sprint 6+.
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

log = logging.getLogger("camas.pban_08_du_lieu")

DEFAULT_LLM_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 500
DEFAULT_LLM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"


class Pban08DuLieu(BaseBC):
    """Phòng 08 Dữ liệu, ETL + KPI + 8am VN digest cho Anna."""

    name = "pban_08_du_lieu"
    scope = "ETL 6 nguồn + 12 KPI + digest 8am VN + weekly Sheets"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = ["postgres", "google_sheets", "ghl_reporting"]
    requires_voice_gate = False  # internal report ops, BC2 voice cho narrative event riêng
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        model: str = DEFAULT_LLM_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""

        if event == "data.daily_digest":
            return await self._handle_daily_digest(ctx)
        if event == "data.adhoc_query":
            return await self._handle_adhoc_query(ctx)

        return AgentResult(
            success=False,
            output_text="Phòng 08 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "data.daily_digest",
                    "data.adhoc_query",
                ],
            },
        )

    # ============================================================
    # Event 1: daily digest (8am VN)
    # ============================================================
    async def _handle_daily_digest(self, ctx: ExecutionContext) -> AgentResult:
        """8am VN, 12 KPI snapshot + anomaly detect + Telegram + Phòng 10 input."""
        timestamp = self._now_perth_str()
        kpi = await self._collect_kpi_snapshot()
        anomalies = self._detect_anomalies(kpi)
        narrative = await self._llm_narrative(kpi, anomalies)

        digest = self._format_digest(
            timestamp=timestamp,
            kpi=kpi,
            anomalies=anomalies,
            narrative=narrative,
        )
        sent_ok = await self._maybe_send_telegram(digest)

        status = "alert" if anomalies else "ok"

        return AgentResult(
            success=True,
            output_text=digest,
            output_payload={
                "event": "data.daily_digest",
                "status": status,
                "kpi": kpi,
                "anomalies": anomalies,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"daily_digest revenue_24h={kpi.get('revenue_24h_vnd')} "
                        f"anomalies={len(anomalies)}"
                    ),
                    "keywords": ["digest", "kpi", timestamp[:10]],
                    "tags": ["pban_08", "daily_digest", status],
                    "venture": "all",
                    "context": (
                        f"data.daily_digest anomalies={len(anomalies)}"
                    ),
                }
            ],
        )

    # ============================================================
    # Event 2: adhoc query
    # ============================================================
    async def _handle_adhoc_query(self, ctx: ExecutionContext) -> AgentResult:
        """Manual query, KHÔNG send Telegram, return JSON."""
        payload = ctx.payload or {}
        query_name = payload.get("query_name", "kpi_snapshot")
        timestamp = self._now_perth_str()

        # TODO Sprint 6 wire Postgres adhoc query catalog
        result = await self._stub_adhoc_query(query_name)

        return AgentResult(
            success=True,
            output_text=json.dumps(
                result, ensure_ascii=False, default=str, indent=2
            ),
            output_payload={
                "event": "data.adhoc_query",
                "query_name": query_name,
                "result": result,
                "timestamp_perth": timestamp,
            },
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": f"adhoc_query name={query_name}",
                    "keywords": ["adhoc_query", query_name, timestamp[:10]],
                    "tags": ["pban_08", "adhoc_query"],
                    "venture": ctx.venture_context,
                    "context": f"data.adhoc_query name={query_name}",
                }
            ],
        )

    # ============================================================
    # KPI + anomaly
    # ============================================================
    async def _collect_kpi_snapshot(self) -> dict[str, Any]:
        """Query Postgres public schema cho 12 KPI core. Fail-soft."""
        kpi: dict[str, Any] = {
            "revenue_24h_vnd": None,
            "leads_24h": None,
            "active_customers": None,
            "churn_rate_pct": None,
            "activity_rate_pct": None,
            "funnel_conversion_pct": None,
            "roas": None,
            "cpl_vnd": None,
            "ltv_vnd": None,
            "email_open_rate_pct": None,
            "zns_success_rate_pct": None,
            "refund_rate_pct": None,
            "error": None,
        }

        if not self.memory.dsn:
            kpi["error"] = "DATABASE_URL chưa set, dùng stub"
            kpi.update(self._stub_kpi_values())
            return kpi

        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban08 get_pool fail: %r", exc)
            kpi["error"] = f"pool init fail: {exc}"
            kpi.update(self._stub_kpi_values())
            return kpi

        try:
            async with pool.acquire() as conn:
                # Combined query (TODO Sprint 6 mở rộng full 12 KPI)
                try:
                    row = await conn.fetchrow(
                        """
                        SELECT
                          (SELECT COUNT(*) FROM public.customers
                             WHERE created_at > now() - interval '24 hours')
                            AS leads_24h,
                          (SELECT COUNT(*) FROM public.customers)
                            AS active_customers,
                          (SELECT COUNT(*) FROM public.events
                             WHERE ts > now() - interval '24 hours'
                               AND event_type = 'payment.success')
                            AS payment_count_24h
                        """
                    )
                    if row:
                        kpi["leads_24h"] = int(row["leads_24h"] or 0)
                        kpi["active_customers"] = int(
                            row["active_customers"] or 0
                        )
                        # payment count proxy cho revenue (Sprint 6 join với amount)
                        kpi["revenue_24h_vnd"] = (
                            int(row["payment_count_24h"] or 0) * 3_000_000
                        )
                except Exception as exc:  # noqa: BLE001
                    log.warning("Pban08 KPI core query fail: %r", exc)
                    kpi["error"] = f"core query fail: {exc}"
                    kpi.update(self._stub_kpi_values())
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban08 KPI SQL fail: %r", exc)
            kpi["error"] = f"SQL fail: {exc}"
            kpi.update(self._stub_kpi_values())

        # Stub fill cho 8 KPI chưa wire
        if kpi.get("roas") is None:
            kpi.update(self._stub_kpi_secondary())
        return kpi

    def _stub_kpi_values(self) -> dict[str, Any]:
        """STUB. Sprint 6 wire Postgres full schema."""
        # TODO Sprint 6 wire Postgres
        return {
            "revenue_24h_vnd": 15_000_000,
            "leads_24h": 42,
            "active_customers": 770,
        }

    def _stub_kpi_secondary(self) -> dict[str, Any]:
        """STUB cho 8 KPI secondary."""
        # TODO Sprint 6 wire Postgres + GHL Reporting + Sepay
        return {
            "churn_rate_pct": 2.1,
            "activity_rate_pct": 38,
            "funnel_conversion_pct": 4.2,
            "roas": 2.4,
            "cpl_vnd": 62000,
            "ltv_vnd": 8_500_000,
            "email_open_rate_pct": 28,
            "zns_success_rate_pct": 97,
            "refund_rate_pct": 2.3,
        }

    def _detect_anomalies(self, kpi: dict[str, Any]) -> list[dict[str, Any]]:
        """6 rule core: Sepay drop > 30% + ZNS fail > 5% + churn spike etc."""
        anomalies: list[dict[str, Any]] = []
        if (kpi.get("zns_success_rate_pct") or 100) < 95:
            anomalies.append(
                {
                    "rule": "zns_fail_rate",
                    "value": kpi.get("zns_success_rate_pct"),
                    "severity": "warning",
                }
            )
        if (kpi.get("refund_rate_pct") or 0) > 5:
            anomalies.append(
                {
                    "rule": "refund_rate",
                    "value": kpi.get("refund_rate_pct"),
                    "severity": "critical",
                }
            )
        if (kpi.get("churn_rate_pct") or 0) > 5:
            anomalies.append(
                {
                    "rule": "churn_spike",
                    "value": kpi.get("churn_rate_pct"),
                    "severity": "warning",
                }
            )
        return anomalies

    async def _stub_adhoc_query(self, query_name: str) -> dict[str, Any]:
        """STUB. Sprint 6 wire Postgres query catalog."""
        # TODO Sprint 6 wire Postgres
        return {
            "query_name": query_name,
            "result": "STUB, Sprint 6 wire Postgres adhoc query catalog",
        }

    # ============================================================
    # LLM narrative
    # ============================================================
    async def _llm_narrative(
        self, kpi: dict[str, Any], anomalies: list[dict[str, Any]]
    ) -> str:
        """Haiku 4.5 sinh narrative 2-3 dòng tiếng Việt."""
        if not self.llm.ready:
            return "LLM chưa init, không có narrative"
        compact = json.dumps(kpi, ensure_ascii=False, default=str)[:600]
        anomaly_text = json.dumps(anomalies, ensure_ascii=False)
        prompt = (
            "You are Anna's analytics narrator. Given KPI snapshot + anomalies, "
            "viết 2-3 dòng tiếng Việt insight + 1 action item. Không preamble.\n\n"
            f"KPI: {compact}\nAnomalies: {anomaly_text}"
        )
        try:
            resp = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban08 LLM call fail: %r", exc)
            return "LLM call fail, không có narrative"
        parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))
        return ("".join(parts).strip()) or "Không có narrative"

    # ============================================================
    # Format helpers
    # ============================================================
    def _format_digest(
        self,
        *,
        timestamp: str,
        kpi: dict[str, Any],
        anomalies: list[dict[str, Any]],
        narrative: str,
    ) -> str:
        anomaly_block = (
            "\n".join(
                f"- {a['rule']} = {a['value']} ({a['severity']})"
                for a in anomalies
            )
            if anomalies
            else "- không có"
        )
        return (
            f"Phòng 08 Daily Digest {timestamp}\n\n"
            f"Revenue 24h: {kpi.get('revenue_24h_vnd', 0):,} VND\n"
            f"Leads 24h: {kpi.get('leads_24h')}\n"
            f"Active customers: {kpi.get('active_customers')}\n"
            f"Funnel conversion: {kpi.get('funnel_conversion_pct')}%\n"
            f"ROAS: {kpi.get('roas')}x, CPL: {kpi.get('cpl_vnd', 0):,} VND\n"
            f"Email open: {kpi.get('email_open_rate_pct')}%, "
            f"ZNS success: {kpi.get('zns_success_rate_pct')}%\n"
            f"Refund rate: {kpi.get('refund_rate_pct')}%\n\n"
            f"Anomalies:\n{anomaly_block}\n\n"
            f"Narrative:\n{narrative}"
        )

    # ============================================================
    # Telegram + utility
    # ============================================================
    async def _maybe_send_telegram(self, text: str) -> bool:
        dry_run = os.getenv("PBAN_DRY_RUN", "") == "1"
        if dry_run:
            log.info("Pban08 DRY_RUN, skip Telegram send")
            return True
        try:
            return await send_telegram(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban08 Telegram send fail: %r", exc)
            return False

    @staticmethod
    def _now_perth_str() -> str:
        now_perth = datetime.now(tz=timezone.utc) + timedelta(hours=8)
        return now_perth.strftime("%Y-%m-%d %H:%M")


async def send_telegram(text: str) -> bool:
    """Gửi Telegram Breakout Ops."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_OPS_GROUP_ID", DEFAULT_TELEGRAM_GROUP_ID)
    if not token:
        log.warning("Pban08 TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "Pban08 Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
