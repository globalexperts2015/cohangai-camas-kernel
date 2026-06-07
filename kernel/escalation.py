"""Escalation L1/L2/L3 → Telegram Breakout Ops group.

Group ID: -1003813280155 (Anna solo, memory feedback-anna-solo-no-team).
Email fallback: hang.dao.bbb@gmail.com (memory feedback-anna-primary-inbox).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from kernel.base_agent import AutonomyLevel

log = logging.getLogger("camas.escalation")

TELEGRAM_OPS_CHAT_ID = "-1003813280155"
ANNA_EMAIL = "hang.dao.bbb@gmail.com"


class EscalationService:
    """Send notification cho Anna khi agent gặp L2/L3 hoặc gate block.

    Format Telegram message:
        [AGENT] bc4_k2_launch
        [AUTONOMY] L2
        [REASON] compliance_block
        [RUN] run_id=...
        [SUMMARY] BC9 BLOCK reel X vì MARA layer
    """

    def __init__(self, bot_token: Optional[str] = None) -> None:
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.api_base = "https://api.telegram.org"

    async def notify(
        self,
        agent_name: str,
        autonomy_level: AutonomyLevel,
        reason: str,
        ctx_run_id: str,
        summary: str,
    ) -> None:
        message = (
            f"[AGENT] {agent_name}\n"
            f"[AUTONOMY] {autonomy_level.value}\n"
            f"[REASON] {reason}\n"
            f"[RUN] {ctx_run_id}\n"
            f"[SUMMARY] {summary[:500]}"
        )

        if not self.bot_token:
            log.warning(
                "TELEGRAM_BOT_TOKEN chưa set, skip notify agent=%s reason=%s",
                agent_name,
                reason,
            )
            raise NotImplementedError("Telegram bot token chưa wire trong env")

        url = f"{self.api_base}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_OPS_CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
        log.info("Escalation sent agent=%s reason=%s", agent_name, reason)
