"""Cron Dedupe Contact, Sunday 2am VN weekly merge duplicate GHL contacts.

Pattern: cron-job.org → POST /kernel/execute, event=cron.dedupe_contact.tick.

Delegate HTTP POST cdp-webhook /admin/reconcile-daily?secret=$CRON_SECRET.
Reuse CDP service đã có dedupe logic (memory reference-cdp-canonical: public
schema canonical), tránh duplicate normalization + merge rule logic.

Lý do delegate thay vì viết merge logic trong agent:
- CDP service đã có /admin/reconcile-daily endpoint + Postgres reversibility log
- Merge cần GHL credential + email/phone normalization library trong CDP
- Cron là trigger, CDP service là worker
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

log = logging.getLogger("camas.cron_dedupe_contact")

EXPECTED_EVENT = "cron.dedupe_contact.tick"
DEFAULT_RECONCILE_URL = "https://cdp-webhook-production.up.railway.app/admin/reconcile-daily"
DEFAULT_HTTP_TIMEOUT = 120.0  # dedupe có thể chạy lâu


class CronDedupeContact(BaseBC):
    """Cron Sunday 2am VN weekly, trigger CDP reconcile endpoint."""

    name = "cron_dedupe_contact"
    scope = "Cron Sunday 2am VN, merge duplicate GHL contacts qua cdp-webhook"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        reconcile_url: str = DEFAULT_RECONCILE_URL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.reconcile_url = reconcile_url

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

        http_status: Optional[int] = None
        http_error: Optional[str] = None
        response_body: Optional[dict[str, Any]] = None
        status_tag = "ok"
        merged_count: Optional[int] = None

        if dry_run:
            log.info("cron_dedupe_contact DRY_RUN, skip HTTP call")
            status_tag = "dry_run"
        else:
            secret = os.getenv("CRON_SECRET", "")
            url = (
                f"{self.reconcile_url}?secret={secret}"
                if secret
                else self.reconcile_url
            )
            try:
                async with httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT) as client:
                    resp = await client.post(url)
                http_status = resp.status_code
                if 200 <= resp.status_code < 300:
                    try:
                        response_body = resp.json()
                        merged_count = (
                            response_body.get("merged")
                            or response_body.get("merged_count")
                            or 0
                        )
                    except Exception:  # noqa: BLE001
                        response_body = {"raw": resp.text[:200]}
                    status_tag = "ok"
                else:
                    status_tag = "fail"
                    http_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except Exception as exc:  # noqa: BLE001
                log.warning("cron_dedupe_contact HTTP fail: %r", exc)
                status_tag = "fail"
                http_error = repr(exc)

        emitted_memories = [
            {
                "agent_name": self.name,
                "content_summary": (
                    f"Dedupe contact weekly executed status={status_tag} "
                    f"merged={merged_count}"
                ),
                "keywords": ["dedupe_contact", date_vn, status_tag],
                "tags": ["cron", "dedupe_contact", "weekly", status_tag],
                "venture": "all",
                "context": f"{EXPECTED_EVENT} {date_vn}",
            }
        ]

        return AgentResult(
            success=True,
            output_text=(
                f"Dedupe contact {date_vn} status={status_tag} "
                f"merged={merged_count}"
            ),
            output_payload={
                "event": EXPECTED_EVENT,
                "date_vn": date_vn,
                "status_tag": status_tag,
                "http_status": http_status,
                "http_error": http_error,
                "merged_count": merged_count,
                "response": response_body,
                "dry_run": dry_run,
                "reconcile_url": self.reconcile_url,
            },
            emitted_memories=emitted_memories,
        )

    @staticmethod
    def _date_vn_str() -> str:
        now_vn = datetime.now(tz=timezone.utc) + timedelta(hours=7)
        return now_vn.strftime("%Y-%m-%d")
