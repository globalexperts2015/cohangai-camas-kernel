"""Cron WK Sync, every 15min backup WebinarKit → GHL safety net.

Pattern: cron-job.org → POST /kernel/execute, event=cron.wk_sync.tick.

Real-time webhook K2 đã miss 1,151 contact 6/6 (memory reference-breakout-app-gate).
Cron này = belt-and-suspenders: gọi cdp-webhook sync endpoint, idempotent qua
GHL tag-based dedupe đã có trong CDP service.

Lý do delegate HTTP thay vì query WK + push GHL trực tiếp:
- WK + GHL credentials đã wire trong cdp-webhook service Railway
- Duplicate = drift credentials, sync schema, watermark logic
- Cron agent chỉ trigger, CDP service làm việc thật
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
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

log = logging.getLogger("camas.cron_wk_sync")

EXPECTED_EVENT = "cron.wk_sync.tick"
DEFAULT_WK_SYNC_URL = "https://cdp-webhook-production.up.railway.app/api/wk-sync-status"
DEFAULT_HTTP_TIMEOUT = 30.0


class CronWkSync(BaseBC):
    """Cron 15min, trigger CDP WK sync endpoint, log result + emit memory."""

    name = "cron_wk_sync"
    scope = "Cron mỗi 15 phút, backup sync WK → GHL qua cdp-webhook endpoint"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        sync_url: str = DEFAULT_WK_SYNC_URL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.sync_url = sync_url

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

        dry_run = os.getenv("CRON_DRY_RUN", "") == "1"
        ts = datetime.now(tz=timezone.utc).isoformat()

        http_status: Optional[int] = None
        http_error: Optional[str] = None
        response_body: Optional[dict[str, Any]] = None
        status_tag = "ok"

        if dry_run:
            log.info("cron_wk_sync DRY_RUN, skip HTTP call")
            status_tag = "dry_run"
        else:
            secret = os.getenv("CRON_SECRET", "")
            url = (
                f"{self.sync_url}?secret={secret}" if secret else self.sync_url
            )
            try:
                async with httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT) as client:
                    resp = await client.get(url)
                http_status = resp.status_code
                if 200 <= resp.status_code < 300:
                    try:
                        response_body = resp.json()
                    except Exception:  # noqa: BLE001
                        response_body = {"raw": resp.text[:200]}
                    status_tag = "ok"
                else:
                    status_tag = "fail"
                    http_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except Exception as exc:  # noqa: BLE001
                log.warning("cron_wk_sync HTTP fail: %r", exc)
                status_tag = "fail"
                http_error = repr(exc)

        emitted_memories = [
            {
                "agent_name": self.name,
                "content_summary": (
                    f"WK sync 15min tick status={status_tag} "
                    f"http={http_status}"
                ),
                "keywords": ["wk_sync", "every_15min", status_tag],
                "tags": ["cron", "wk_sync", "every_15min", status_tag],
                "venture": "breakout",
                "context": f"{EXPECTED_EVENT} ts={ts}",
            }
        ]

        return AgentResult(
            success=True,
            output_text=f"WK sync tick status={status_tag} http={http_status}",
            output_payload={
                "event": EXPECTED_EVENT,
                "sync_url": self.sync_url,
                "status_tag": status_tag,
                "http_status": http_status,
                "http_error": http_error,
                "response": response_body,
                "dry_run": dry_run,
                "ts_utc": ts,
            },
            emitted_memories=emitted_memories,
        )
