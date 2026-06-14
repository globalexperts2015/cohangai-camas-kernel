"""Phòng 07 Hoàn tiền agent.

Refund agent xử Breakout K2/K3+ theo policy 14 ngày chốt 5/6/2026 (memory
`project-breakout-k2-launch-state.md`). Anna duyệt mỗi case (L3 mãi). Memory:
- `agent-inventory-complete.md` (L3 forever rule)
- `reference-sepay-credentials.md` (Sepay refund execute)
- `reference-zns-breakout-config.md` (ZNS confirmation downstream)
- `feedback-no-change-facts-without-asking.md` (verify facts before propose)

Trigger events:
- `refund.request_received`: intake refund + eligibility check + propose verdict
- `refund.batch_audit`: weekly Monday refund pattern review

Autonomy L3 mãi (KHÔNG upgrade). Escalate Anna direct (mỗi case, email + Telegram
full evidence pack).

LLM Opus 4.7 cho propose verdict (high stakes refund decision).

ZERO em-dash. Stub Sepay refund + GHL update + WK activity Sprint 6+.
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

log = logging.getLogger("camas.pban_07_hoan_tien")

DEFAULT_LLM_MODEL = "claude-haiku-4-5"  # high stakes refund
DEFAULT_MAX_TOKENS = 1200
DEFAULT_LLM_TIMEOUT = 90.0
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"

REFUND_POLICY_DAYS = 14


class Pban07HoanTien(BaseBC):
    """Phòng 07 Hoàn tiền, propose verdict L3 mỗi case + execute sau Anna decide."""

    name = "pban_07_hoan_tien"
    scope = "Refund 14 ngày + điều kiện, propose verdict L3 Anna duyệt mỗi case"
    autonomy_level = AutonomyLevel.L3_PROPOSE
    escalate_to = EscalationTarget.EMAIL_ANNA  # Anna direct mỗi case
    tools: list[str] = ["sepay_refund_api", "ghl_api", "zalo_zns", "wk_api"]
    requires_voice_gate = True  # propose reply BC2 voice
    requires_compliance_gate = True  # refund disclosure + Privacy

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

        if event == "refund.request_received":
            return await self._handle_request_received(ctx)
        if event == "refund.batch_audit":
            return await self._handle_batch_audit(ctx)

        return AgentResult(
            success=False,
            output_text="Phòng 07 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "refund.request_received",
                    "refund.batch_audit",
                ],
            },
        )

    # ============================================================
    # Event 1: refund request received
    # ============================================================
    async def _handle_request_received(
        self, ctx: ExecutionContext
    ) -> AgentResult:
        """Intake + eligibility + propose verdict + escalate Anna L3."""
        payload = ctx.payload or {}
        order_id = payload.get("order_id", "unknown")
        customer_id = payload.get("customer_id", "unknown")
        customer_message = payload.get("customer_message", "")
        amount_vnd = payload.get("amount_vnd", 0)
        timestamp = self._now_perth_str()

        # Eligibility checks (TODO Sprint 6 wire WK + app.breakout.live + Sepay)
        eligibility = await self._stub_check_eligibility(
            order_id=order_id, customer_id=customer_id
        )

        # LLM Opus propose verdict
        proposal = await self._llm_propose_verdict(
            eligibility=eligibility,
            customer_message=customer_message,
            amount_vnd=amount_vnd,
        )

        # L3 escalate Anna với evidence pack
        escalation_text = self._format_escalation(
            timestamp=timestamp,
            order_id=order_id,
            customer_id=customer_id,
            amount_vnd=amount_vnd,
            eligibility=eligibility,
            customer_message=customer_message,
            proposal=proposal,
        )
        sent_ok = await self._maybe_send_telegram(escalation_text)

        return AgentResult(
            success=True,
            output_text=escalation_text,
            output_payload={
                "event": "refund.request_received",
                "order_id": order_id,
                "customer_id": customer_id,
                "amount_vnd": amount_vnd,
                "eligibility": eligibility,
                "proposal": proposal,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            escalation_required=True,
            escalation_reason="L3 refund decision Anna duyệt mỗi case",
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"refund.request order={order_id} amount={amount_vnd} "
                        f"verdict={proposal.get('verdict')}"
                    ),
                    "keywords": ["refund", "propose", order_id, customer_id],
                    "tags": [
                        "pban_07",
                        "refund_propose",
                        "l3_anna",
                        proposal.get("verdict", "UNKNOWN").lower(),
                    ],
                    "venture": "breakout",
                    "customer_id": (
                        int(customer_id)
                        if str(customer_id).isdigit()
                        else None
                    ),
                    "context": (
                        f"refund.request_received eligible={eligibility.get('eligible')} "
                        f"verdict={proposal.get('verdict')}"
                    ),
                }
            ],
        )

    # ============================================================
    # Event 2: batch audit (weekly Monday)
    # ============================================================
    async def _handle_batch_audit(self, ctx: ExecutionContext) -> AgentResult:
        """Weekly Monday refund pattern review, propose CSKH FAQ update."""
        # TODO Sprint 6 wire Postgres refund_log
        stats = await self._stub_refund_batch_stats()
        timestamp = self._now_perth_str()

        digest = self._format_batch_digest(timestamp=timestamp, stats=stats)
        sent_ok = await self._maybe_send_telegram(digest)

        return AgentResult(
            success=True,
            output_text=digest,
            output_payload={
                "event": "refund.batch_audit",
                "stats": stats,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"refund.batch_audit rate={stats.get('refund_rate_pct')}% "
                        f"count={stats.get('refund_count_7d')}"
                    ),
                    "keywords": ["refund", "batch_audit", timestamp[:10]],
                    "tags": ["pban_07", "batch_audit", "weekly"],
                    "venture": "breakout",
                    "context": "refund.batch_audit weekly pattern review",
                }
            ],
        )

    # ============================================================
    # Stubs + LLM
    # ============================================================
    async def _stub_check_eligibility(
        self, *, order_id: str, customer_id: str
    ) -> dict[str, Any]:
        """STUB. Sprint 6 wire WK + app.breakout.live + Sepay cross-check."""
        # TODO Sprint 6 wire wk_api + sepay_api + app.breakout.live
        return {
            "order_id": order_id,
            "customer_id": customer_id,
            "days_since_payment": 7,
            "within_14d_policy": True,
            "watched_content_pct": 12,
            "downloaded_master_doc": False,
            "eligible": True,
            "policy_threshold_watched_pct": 25,
        }

    async def _llm_propose_verdict(
        self,
        *,
        eligibility: dict[str, Any],
        customer_message: str,
        amount_vnd: int,
    ) -> dict[str, Any]:
        """Opus 4.7 sinh propose verdict + reasoning + reply tiếng Việt."""
        if not self.llm.ready:
            return {
                "verdict": "NEED_MORE_INFO",
                "reasoning": "LLM chưa init",
                "reply_text": "",
            }
        eligibility_block = json.dumps(eligibility, ensure_ascii=False)
        prompt = (
            "You are Anna's refund advisor. Policy: 14 ngày từ payment + watched < "
            f"{eligibility.get('policy_threshold_watched_pct')}% + chưa download "
            "tài liệu master. Anna duyệt mỗi case (L3 mãi).\n\n"
            f"Eligibility: {eligibility_block}\n"
            f"Customer message: {customer_message}\n"
            f"Amount: {amount_vnd} VND\n\n"
            "Output JSON với 3 field:\n"
            "- verdict: 'APPROVE' | 'REJECT' | 'NEED_MORE_INFO'\n"
            "- reasoning: 1-3 câu tiếng Việt rõ căn cứ policy\n"
            "- reply_text: bản nháp tiếng Việt giọng Hằng gửi khách (3-5 câu, "
            "lịch sự, không hứa thêm). KHÔNG dùng em-dash.\n\n"
            "Trả raw JSON, không kèm markdown fence."
        )
        try:
            resp = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban07 LLM call fail: %r", exc)
            return {
                "verdict": "NEED_MORE_INFO",
                "reasoning": f"LLM call fail: {exc}",
                "reply_text": "",
            }
        parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))
        text = "".join(parts).strip()
        try:
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("LLM response không phải dict")
            return {
                "verdict": parsed.get("verdict", "NEED_MORE_INFO"),
                "reasoning": parsed.get("reasoning", ""),
                "reply_text": parsed.get("reply_text", ""),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban07 parse JSON fail: %r raw=%s", exc, text[:300])
            return {
                "verdict": "NEED_MORE_INFO",
                "reasoning": f"Parse fail: {exc}",
                "reply_text": text[:300],
            }

    async def _stub_refund_batch_stats(self) -> dict[str, Any]:
        """STUB. Sprint 6 wire Postgres refund_log."""
        # TODO Sprint 6 wire Postgres refund_log
        return {
            "refund_count_7d": 4,
            "refund_rate_pct": 2.3,
            "approved_count": 3,
            "rejected_count": 1,
            "anna_agreement_rate_pct": 100,
            "top_reason": "Khách chưa start học, đổi ý",
        }

    # ============================================================
    # Format helpers
    # ============================================================
    def _format_escalation(
        self,
        *,
        timestamp: str,
        order_id: str,
        customer_id: str,
        amount_vnd: int,
        eligibility: dict[str, Any],
        customer_message: str,
        proposal: dict[str, Any],
    ) -> str:
        return (
            f"Refund L3 Anna Duyệt {timestamp}\n\n"
            f"Order: {order_id}\n"
            f"Customer: {customer_id}\n"
            f"Amount: {amount_vnd:,} VND\n\n"
            f"Eligibility:\n"
            f"- Days since payment: {eligibility.get('days_since_payment')}\n"
            f"- Within 14d policy: {eligibility.get('within_14d_policy')}\n"
            f"- Watched %: {eligibility.get('watched_content_pct')}%\n"
            f"- Downloaded master: {eligibility.get('downloaded_master_doc')}\n\n"
            f"Khách nói: {customer_message[:200]}\n\n"
            f"Propose verdict: {proposal.get('verdict')}\n"
            f"Reasoning: {proposal.get('reasoning')}\n\n"
            f"Reply draft:\n{proposal.get('reply_text')}\n\n"
            f"Anna 1-click: APPROVE / REJECT / EDIT"
        )

    def _format_batch_digest(
        self, *, timestamp: str, stats: dict[str, Any]
    ) -> str:
        return (
            f"Refund Weekly Audit {timestamp}\n\n"
            f"Refund 7d: {stats.get('refund_count_7d')} case\n"
            f"Refund rate: {stats.get('refund_rate_pct')}%\n"
            f"Approved: {stats.get('approved_count')}, "
            f"Rejected: {stats.get('rejected_count')}\n"
            f"Anna agreement rate: {stats.get('anna_agreement_rate_pct')}%\n\n"
            f"Top reason: {stats.get('top_reason')}\n\n"
            f"Propose: CSKH FAQ update theo top reason."
        )

    # ============================================================
    # Telegram + utility
    # ============================================================
    async def _maybe_send_telegram(self, text: str) -> bool:
        dry_run = os.getenv("PBAN_DRY_RUN", "") == "1"
        if dry_run:
            log.info("Pban07 DRY_RUN, skip Telegram send")
            return True
        try:
            return await send_telegram(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban07 Telegram send fail: %r", exc)
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
        log.warning("Pban07 TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "Pban07 Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
