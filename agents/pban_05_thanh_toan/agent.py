"""Phòng 05 Thanh toán agent.

Sepay payment webhook + ZNS Zalo OA notification + GHL trigger sync. Wrap
Railway service `breakout-zns` (production K2 đang chạy live từ 9/6). Memory:
- `reference-sepay-credentials.md` (merchant SP-LIVE-DTA46658)
- `reference-zns-breakout-config.md` (template 586303 ZBS)
- `reference-zalo-token-rotation.md` (rotate mỗi call, env ZALO_*)
- `feedback-zns-fail-no-remove.md` (ZNS fail KHÔNG remove contact)

Trigger events:
- `payment.health_check`: 5-min Sepay webhook + Zalo token freshness probe
- `payment.refund_request`: incoming refund request → handoff Phòng 07

Autonomy L1 (production K2 đang chạy). Refund handoff Phòng 07 L3 mãi.

Escalate Telegram direct (CRITICAL fail). ZERO em-dash. Stub APIs Sprint 6+.
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

log = logging.getLogger("camas.pban_05_thanh_toan")

DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"
DEFAULT_HEALTH_HTTP_TIMEOUT = 10.0
DEFAULT_BREAKOUT_ZNS_URL = "https://breakout-zns.up.railway.app/"

ZALO_TOKEN_REFRESH_DAYS_WARN = 14  # 2 tuần trước expire


class Pban05ThanhToan(BaseBC):
    """Phòng 05 Thanh toán, Sepay + ZNS + GHL real-time payment ops."""

    name = "pban_05_thanh_toan"
    scope = "Sepay webhook + ZNS Zalo + GHL trigger 24/7 production K2"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = ["sepay_api", "zalo_zns", "ghl_api"]
    requires_voice_gate = False  # internal ops, ZNS template fixed bởi BC9
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        breakout_zns_url: str = DEFAULT_BREAKOUT_ZNS_URL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.breakout_zns_url = breakout_zns_url

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""

        if event == "payment.health_check":
            return await self._handle_health_check(ctx)
        if event == "payment.refund_request":
            return await self._handle_refund_request(ctx)

        return AgentResult(
            success=False,
            output_text="Phòng 05 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "payment.health_check",
                    "payment.refund_request",
                ],
            },
        )

    # ============================================================
    # Event 1: payment health check (5 min)
    # ============================================================
    async def _handle_health_check(self, ctx: ExecutionContext) -> AgentResult:
        """5-min probe Sepay webhook service + Zalo token freshness."""
        timestamp = self._now_perth_str()
        zns_service = await self._probe_url(self.breakout_zns_url)
        # TODO Sprint 6 wire sepay_api transactions.last
        sepay_status = await self._stub_sepay_status()
        # TODO Sprint 6 wire zalo_zns token expiry check
        zalo_token = await self._stub_zalo_token_status()

        status = "ok"
        issues: list[str] = []
        if not zns_service.get("ok"):
            status = "critical"
            issues.append("breakout-zns service down")
        if sepay_status.get("fail_rate_pct", 0) > 5:
            status = "critical" if status == "ok" else status
            issues.append(
                f"Sepay fail rate {sepay_status.get('fail_rate_pct')}%"
            )
        if zalo_token.get("days_remaining", 99) < ZALO_TOKEN_REFRESH_DAYS_WARN:
            status = "warning" if status == "ok" else status
            issues.append(
                f"Zalo token expire trong {zalo_token.get('days_remaining')} ngày"
            )

        send_required = status != "ok"
        text: Optional[str] = None
        sent_ok = False
        if send_required:
            text = self._format_health_alert(
                timestamp=timestamp,
                zns_service=zns_service,
                sepay_status=sepay_status,
                zalo_token=zalo_token,
                status=status,
                issues=issues,
            )
            sent_ok = await self._maybe_send_telegram(text)

        return AgentResult(
            success=True,
            output_text=text or f"payment.health_check status={status} silent",
            output_payload={
                "event": "payment.health_check",
                "status": status,
                "zns_service": zns_service,
                "sepay_status": sepay_status,
                "zalo_token": zalo_token,
                "issues": issues,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"payment.health_check status={status} "
                        f"issues={len(issues)}"
                    ),
                    "keywords": ["sepay", "zns", "health_check", timestamp[:10]],
                    "tags": ["pban_05", "health_check", status],
                    "venture": "breakout",
                    "context": f"payment.health_check status={status}",
                }
            ],
        )

    # ============================================================
    # Event 2: refund request (handoff Phòng 07)
    # ============================================================
    async def _handle_refund_request(
        self, ctx: ExecutionContext
    ) -> AgentResult:
        """Incoming refund request, handoff Phòng 07 (L3 mãi)."""
        payload = ctx.payload or {}
        order_id = payload.get("order_id", "unknown")
        customer_id = payload.get("customer_id", "unknown")
        amount_vnd = payload.get("amount_vnd", 0)
        timestamp = self._now_perth_str()

        handoff_text = self._format_refund_handoff(
            timestamp=timestamp,
            order_id=order_id,
            customer_id=customer_id,
            amount_vnd=amount_vnd,
        )
        # KHÔNG send Telegram trực tiếp, Phòng 07 sẽ L3 escalate
        # Chỉ emit memory để Phòng 07 ingest event

        return AgentResult(
            success=True,
            output_text=handoff_text,
            output_payload={
                "event": "payment.refund_request",
                "order_id": order_id,
                "customer_id": customer_id,
                "amount_vnd": amount_vnd,
                "handoff_to": "pban_07_hoan_tien",
                "timestamp_perth": timestamp,
            },
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"refund_request order={order_id} amount={amount_vnd}"
                    ),
                    "keywords": ["refund", "handoff", order_id],
                    "tags": ["pban_05", "refund_handoff", "pban_07"],
                    "venture": "breakout",
                    "customer_id": (
                        int(customer_id)
                        if str(customer_id).isdigit()
                        else None
                    ),
                    "context": (
                        f"payment.refund_request handoff pban_07 amount={amount_vnd}"
                    ),
                }
            ],
        )

    # ============================================================
    # Stubs + probes
    # ============================================================
    async def _probe_url(self, url: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "url": url,
            "ok": False,
            "status_code": None,
            "latency_ms": None,
            "error": None,
        }
        try:
            t0 = datetime.now(tz=timezone.utc)
            async with httpx.AsyncClient(
                timeout=DEFAULT_HEALTH_HTTP_TIMEOUT
            ) as client:
                resp = await client.get(url)
            t1 = datetime.now(tz=timezone.utc)
            result["status_code"] = resp.status_code
            result["latency_ms"] = (t1 - t0).total_seconds() * 1000.0
            result["ok"] = 200 <= resp.status_code < 400
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban05 probe %s fail: %r", url, exc)
            result["error"] = str(exc)
        return result

    async def _stub_sepay_status(self) -> dict[str, Any]:
        """STUB. Sprint 6 wire sepay_api transactions.last + fail metrics."""
        # TODO Sprint 6 wire sepay_api
        return {
            "transactions_24h": 18,
            "fail_count_24h": 0,
            "fail_rate_pct": 0.0,
            "last_success_at": "stub",
        }

    async def _stub_zalo_token_status(self) -> dict[str, Any]:
        """STUB. Sprint 6 wire zalo_zns token expiry probe."""
        # TODO Sprint 6 wire zalo_zns
        return {
            "token_set": bool(os.getenv("ZALO_ACCESS_TOKEN")),
            "days_remaining": 60,
        }

    # ============================================================
    # Format helpers
    # ============================================================
    def _format_health_alert(
        self,
        *,
        timestamp: str,
        zns_service: dict[str, Any],
        sepay_status: dict[str, Any],
        zalo_token: dict[str, Any],
        status: str,
        issues: list[str],
    ) -> str:
        def _latency(d: dict[str, Any]) -> str:
            v = d.get("latency_ms")
            return f"{v:.0f}ms" if isinstance(v, (int, float)) else "n/a"

        def _status_code(d: dict[str, Any]) -> str:
            v = d.get("status_code")
            return str(v) if v is not None else (d.get("error") or "unreachable")

        issue_block = "\n".join(f"- {i}" for i in issues) if issues else "- không có"
        return (
            f"Payment Health {status.upper()} {timestamp}\n\n"
            f"breakout-zns: HTTP {_status_code(zns_service)} "
            f"({_latency(zns_service)})\n"
            f"Sepay 24h: {sepay_status.get('transactions_24h')} txn, "
            f"fail {sepay_status.get('fail_rate_pct')}%\n"
            f"Zalo token: {zalo_token.get('days_remaining')} ngày tới expire\n\n"
            f"Issues:\n{issue_block}"
        )

    def _format_refund_handoff(
        self,
        *,
        timestamp: str,
        order_id: str,
        customer_id: str,
        amount_vnd: int,
    ) -> str:
        return (
            f"Refund Request Handoff {timestamp}\n\n"
            f"Order: {order_id}\n"
            f"Customer: {customer_id}\n"
            f"Amount: {amount_vnd:,} VND\n\n"
            f"Handoff Phòng 07 Hoàn tiền (L3 mãi, Anna duyệt mỗi case)"
        )

    # ============================================================
    # Telegram + utility
    # ============================================================
    async def _maybe_send_telegram(self, text: str) -> bool:
        dry_run = os.getenv("PBAN_DRY_RUN", "") == "1"
        if dry_run:
            log.info("Pban05 DRY_RUN, skip Telegram send")
            return True
        try:
            return await send_telegram(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban05 Telegram send fail: %r", exc)
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
        log.warning("Pban05 TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "Pban05 Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
