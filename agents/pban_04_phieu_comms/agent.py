"""Phòng 04 Phiếu Comms agent.

GHL workflow + tag + custom field + email/SMS automation cho 3 ventures Breakout
+ Speakout + Cohangai (1 GHL location chung, tách bằng tag prefix sp:/bk:/cg:).
Memory: `feedback-speakout-not-breakout-audience.md` + `reference-lead-scoring.md`.

Trigger events:
- `comms.workflow_audit`: daily fail rate check + alert > 5%
- `comms.message_propose`: bulk email > 949 contacts request L2 Anna approve

Autonomy L1 (5 workflow existing) / L2 (bulk > 949 + new workflow).

ZERO em-dash. Stub GHL API Sprint 6+.
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

log = logging.getLogger("camas.pban_04_phieu_comms")

DEFAULT_LLM_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 400
DEFAULT_LLM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"

WORKFLOW_FAIL_RATE_L2_THRESHOLD = 5  # percent
BULK_EMAIL_L2_THRESHOLD = 949  # rule BC4


class Pban04PhieuComms(BaseBC):
    """Phòng 04 Phiếu Comms, GHL workflow trigger + tag + email/SMS orchestrator."""

    name = "pban_04_phieu_comms"
    scope = "GHL workflow + tag + email/SMS 3 venture, fail rate < 5%/ngày"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = ["ghl_api"]
    requires_voice_gate = False  # ops nội bộ, template BC2 review tại event khác
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

        if event == "comms.workflow_audit":
            return await self._handle_workflow_audit(ctx)
        if event == "comms.message_propose":
            return await self._handle_message_propose(ctx)

        return AgentResult(
            success=False,
            output_text="Phòng 04 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "comms.workflow_audit",
                    "comms.message_propose",
                ],
            },
        )

    # ============================================================
    # Event 1: workflow audit (daily)
    # ============================================================
    async def _handle_workflow_audit(
        self, ctx: ExecutionContext
    ) -> AgentResult:
        """Daily fail rate check, escalate L2 nếu > 5%/ngày."""
        # TODO Sprint 6 wire ghl_api workflows.list + executions.stats
        stats = await self._stub_workflow_stats(ctx)
        timestamp = self._now_perth_str()

        fail_rate = stats.get("fail_rate_pct", 0)
        status = "ok"
        if fail_rate >= WORKFLOW_FAIL_RATE_L2_THRESHOLD:
            status = "warning"

        send_required = status != "ok"
        digest = self._format_audit_digest(
            timestamp=timestamp, stats=stats, status=status
        )
        sent_ok = (
            await self._maybe_send_telegram(digest) if send_required else False
        )

        return AgentResult(
            success=True,
            output_text=digest,
            output_payload={
                "event": "comms.workflow_audit",
                "status": status,
                "stats": stats,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"workflow_audit fail_rate={fail_rate}% status={status}"
                    ),
                    "keywords": ["ghl", "workflow_audit", timestamp[:10]],
                    "tags": ["pban_04", "workflow_audit", status],
                    "venture": "all",
                    "context": f"comms.workflow_audit fail_rate={fail_rate}%",
                }
            ],
        )

    # ============================================================
    # Event 2: message propose (bulk email > 949)
    # ============================================================
    async def _handle_message_propose(
        self, ctx: ExecutionContext
    ) -> AgentResult:
        """Bulk email propose, L2 Anna approve nếu > 949 contacts."""
        payload = ctx.payload or {}
        recipients_count = int(payload.get("recipients_count", 0))
        subject = payload.get("subject", "(no subject)")
        venture = ctx.venture_context or "all"
        timestamp = self._now_perth_str()

        needs_l2 = recipients_count > BULK_EMAIL_L2_THRESHOLD

        proposal = {
            "subject": subject,
            "recipients_count": recipients_count,
            "venture": venture,
            "needs_l2_approval": needs_l2,
            "threshold": BULK_EMAIL_L2_THRESHOLD,
        }

        text = self._format_message_proposal(
            timestamp=timestamp, proposal=proposal
        )
        sent_ok = (
            await self._maybe_send_telegram(text) if needs_l2 else False
        )

        return AgentResult(
            success=True,
            output_text=text,
            output_payload={
                "event": "comms.message_propose",
                "proposal": proposal,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"message_propose recipients={recipients_count} "
                        f"needs_l2={needs_l2}"
                    ),
                    "keywords": ["ghl", "message_propose", venture],
                    "tags": [
                        "pban_04",
                        "message_propose",
                        "l2_propose" if needs_l2 else "l1_auto",
                    ],
                    "venture": venture,
                    "context": (
                        f"comms.message_propose recipients={recipients_count} "
                        f"subject={subject}"
                    ),
                }
            ],
        )

    # ============================================================
    # Stubs
    # ============================================================
    async def _stub_workflow_stats(
        self, ctx: ExecutionContext
    ) -> dict[str, Any]:
        """STUB. Sprint 6 wire ghl_api workflows.list + executions.stats."""
        # TODO Sprint 6 wire ghl_api
        return {
            "workflows_count": 5,
            "executions_24h": 2840,
            "fail_count_24h": 41,
            "fail_rate_pct": round(41 / 2840 * 100, 2),
            "top_failing_workflow": "25.2 Day 1 reminder K2",
            "venture_breakdown": {
                "breakout": 1200,
                "speakout": 1450,
                "cohangai": 190,
            },
        }

    # ============================================================
    # Format helpers
    # ============================================================
    def _format_audit_digest(
        self, *, timestamp: str, stats: dict[str, Any], status: str
    ) -> str:
        return (
            f"GHL Workflow Audit {status.upper()} {timestamp}\n\n"
            f"Workflows active: {stats.get('workflows_count')}\n"
            f"Executions 24h: {stats.get('executions_24h')}\n"
            f"Fail count 24h: {stats.get('fail_count_24h')}\n"
            f"Fail rate: {stats.get('fail_rate_pct')}%\n"
            f"Top failing: {stats.get('top_failing_workflow')}"
        )

    def _format_message_proposal(
        self, *, timestamp: str, proposal: dict[str, Any]
    ) -> str:
        l2_note = (
            "L2 Anna approve cần thiết (> 949 threshold rule BC4)"
            if proposal["needs_l2_approval"]
            else "L1 auto send (dưới threshold)"
        )
        return (
            f"GHL Bulk Email Propose {timestamp}\n\n"
            f"Subject: {proposal['subject']}\n"
            f"Recipients: {proposal['recipients_count']}\n"
            f"Venture: {proposal['venture']}\n"
            f"Threshold: {proposal['threshold']}\n\n"
            f"{l2_note}"
        )

    # ============================================================
    # Telegram + utility
    # ============================================================
    async def _maybe_send_telegram(self, text: str) -> bool:
        dry_run = os.getenv("PBAN_DRY_RUN", "") == "1"
        if dry_run:
            log.info("Pban04 DRY_RUN, skip Telegram send")
            return True
        try:
            return await send_telegram(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban04 Telegram send fail: %r", exc)
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
        log.warning("Pban04 TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "Pban04 Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
