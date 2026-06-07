"""Phòng 03 Landing Webinar agent.

Maintain app.breakout.live (Railway `breakout-app`) + WebinarKit Live Pro
Lifetime. Sync WK ↔ GHL register/attended real-time. Memory:
- `reference-breakout-railway-projects.md` (app vs zns gotcha)
- `reference-webinarkit-subscription.md` (Live Pro Lifetime $1,623.05)
- `reference-breakout-app-gate.md` (whitelist gate, K2 register-email miss)

Trigger events:
- `webinar.room_check`: pre-webinar 30 phút check WK event + landing live
- `landing.health_5min`: every 5 phút uptime probe app.breakout.live + WK API

Autonomy L2 (Anna approve major UI change). L1 cho WK event config + sync +
uptime monitor + minor copy fix typo. Stub WK API + GHL API Sprint 6+.
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

log = logging.getLogger("camas.pban_03_landing_webinar")

DEFAULT_HEALTH_HTTP_TIMEOUT = 10.0
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"
DEFAULT_LANDING_URL = "https://app.breakout.live/"


class Pban03LandingWebinar(BaseBC):
    """Phòng 03 Landing Webinar, uptime + WK sync + GHL pipeline."""

    name = "pban_03_landing_webinar"
    scope = "app.breakout.live uptime + WebinarKit sync GHL real-time"
    autonomy_level = AutonomyLevel.L2_APPROVE
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = ["webinarkit_api", "ghl_api", "railway_cli"]
    requires_voice_gate = True  # landing copy change phải qua BC2
    requires_compliance_gate = True

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        landing_url: str = DEFAULT_LANDING_URL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.landing_url = landing_url

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""

        if event == "webinar.room_check":
            return await self._handle_room_check(ctx)
        if event == "landing.health_5min":
            return await self._handle_landing_health(ctx)

        return AgentResult(
            success=False,
            output_text="Phòng 03 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "webinar.room_check",
                    "landing.health_5min",
                ],
            },
        )

    # ============================================================
    # Event 1: webinar room check (pre-webinar 30 phút)
    # ============================================================
    async def _handle_room_check(self, ctx: ExecutionContext) -> AgentResult:
        """Check WK event config + registrant count + redirect URL."""
        payload = ctx.payload or {}
        event_id = payload.get("wk_event_id", "unknown")
        timestamp = self._now_perth_str()

        # TODO Sprint 6 wire webinarkit_api event.get + registrants.list
        wk_status = await self._stub_wk_event_status(event_id)
        # TODO Sprint 6 wire ghl_api contacts.search tag K2-register
        ghl_register_count = await self._stub_ghl_register_count(event_id)

        sync_gap = abs(
            (wk_status.get("registrants_count") or 0) - ghl_register_count
        )
        status = "ok"
        issues: list[str] = []
        if not wk_status.get("event_live"):
            status = "critical"
            issues.append("WK event chưa LIVE")
        if sync_gap > 5:
            status = "warning" if status == "ok" else status
            issues.append(f"WK vs GHL sync gap {sync_gap} contacts")

        text = self._format_room_check(
            timestamp=timestamp,
            event_id=event_id,
            wk_status=wk_status,
            ghl_count=ghl_register_count,
            issues=issues,
        )
        sent_ok = (
            await self._maybe_send_telegram(text)
            if status != "ok"
            else False
        )

        return AgentResult(
            success=True,
            output_text=text,
            output_payload={
                "event": "webinar.room_check",
                "wk_event_id": event_id,
                "status": status,
                "wk_status": wk_status,
                "ghl_register_count": ghl_register_count,
                "sync_gap": sync_gap,
                "issues": issues,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"room_check event={event_id} status={status} "
                        f"sync_gap={sync_gap}"
                    ),
                    "keywords": ["webinarkit", "room_check", event_id],
                    "tags": ["pban_03", "room_check", status],
                    "venture": "breakout",
                    "context": f"webinar.room_check status={status}",
                }
            ],
        )

    # ============================================================
    # Event 2: landing health (every 5 min)
    # ============================================================
    async def _handle_landing_health(
        self, ctx: ExecutionContext
    ) -> AgentResult:
        """5-min HTTP probe app.breakout.live + WK API health."""
        timestamp = self._now_perth_str()
        landing = await self._probe_url(self.landing_url)
        wk_api = await self._probe_url(
            os.getenv("WK_API_HEALTH_URL", "https://api.webinarkit.com/v1/ping")
        )

        status = "ok"
        if not landing.get("ok"):
            status = "critical"
        elif not wk_api.get("ok"):
            status = "warning"

        send_required = status in {"warning", "critical"}
        text: Optional[str] = None
        sent_ok = False
        if send_required:
            text = self._format_health_alert(
                timestamp=timestamp,
                landing=landing,
                wk_api=wk_api,
                status=status,
            )
            sent_ok = await self._maybe_send_telegram(text)

        return AgentResult(
            success=True,
            output_text=text or f"landing.health_5min status={status} silent",
            output_payload={
                "event": "landing.health_5min",
                "status": status,
                "landing": landing,
                "wk_api": wk_api,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"landing.health_5min status={status} "
                        f"landing_ok={landing.get('ok')}"
                    ),
                    "keywords": ["landing", "health_check", timestamp[:10]],
                    "tags": ["pban_03", "landing_health", status],
                    "venture": "breakout",
                    "context": f"landing.health_5min status={status}",
                }
            ],
        )

    # ============================================================
    # Stubs + probes
    # ============================================================
    async def _probe_url(self, url: str) -> dict[str, Any]:
        """HTTP GET probe, fail-soft."""
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
            log.warning("Pban03 probe %s fail: %r", url, exc)
            result["error"] = str(exc)
        return result

    async def _stub_wk_event_status(self, event_id: str) -> dict[str, Any]:
        """STUB. Sprint 6 wire webinarkit_api event.get + registrants.list."""
        # TODO Sprint 6 wire webinarkit_api
        return {
            "event_id": event_id,
            "event_live": True,
            "registrants_count": 412,
            "config_check": {
                "registration_form": "ok",
                "redirect_url": "ok",
                "email_auto": "ok",
            },
        }

    async def _stub_ghl_register_count(self, event_id: str) -> int:
        """STUB. Sprint 6 wire ghl_api contacts.search tag K2-register."""
        # TODO Sprint 6 wire ghl_api
        return 408

    # ============================================================
    # Format helpers
    # ============================================================
    def _format_room_check(
        self,
        *,
        timestamp: str,
        event_id: str,
        wk_status: dict[str, Any],
        ghl_count: int,
        issues: list[str],
    ) -> str:
        issue_block = (
            "\n".join(f"- {i}" for i in issues) if issues else "- không có"
        )
        return (
            f"WK Room Check {timestamp}\n\n"
            f"Event: {event_id}\n"
            f"WK live: {wk_status.get('event_live')}\n"
            f"WK registrants: {wk_status.get('registrants_count')}\n"
            f"GHL registrants tag K2-register: {ghl_count}\n\n"
            f"Issues:\n{issue_block}"
        )

    def _format_health_alert(
        self,
        *,
        timestamp: str,
        landing: dict[str, Any],
        wk_api: dict[str, Any],
        status: str,
    ) -> str:
        def _latency(d: dict[str, Any]) -> str:
            v = d.get("latency_ms")
            return f"{v:.0f}ms" if isinstance(v, (int, float)) else "n/a"

        def _status_code(d: dict[str, Any]) -> str:
            v = d.get("status_code")
            return str(v) if v is not None else (d.get("error") or "unreachable")

        return (
            f"Landing/WK Health {status.upper()} {timestamp}\n\n"
            f"app.breakout.live: HTTP {_status_code(landing)} "
            f"({_latency(landing)})\n"
            f"WK API: HTTP {_status_code(wk_api)} "
            f"({_latency(wk_api)})\n\n"
            f"URL: {self.landing_url}"
        )

    # ============================================================
    # Telegram + utility
    # ============================================================
    async def _maybe_send_telegram(self, text: str) -> bool:
        dry_run = os.getenv("PBAN_DRY_RUN", "") == "1"
        if dry_run:
            log.info("Pban03 DRY_RUN, skip Telegram send")
            return True
        try:
            return await send_telegram(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban03 Telegram send fail: %r", exc)
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
        log.warning("Pban03 TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "Pban03 Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
