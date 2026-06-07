"""Cron Ads Pull, 5am Perth daily wrapper delegate Pban01 ads.performance_review.

Pattern: cron-job.org → POST /kernel/execute với agent=cron_ads_pull +
trigger_event=cron.ads_pull.tick. Agent delegate qua scheduler.execute(
pban_01_quang_cao, ads.performance_review).

Lý do delegate thay vì duplicate:
- Pban01 đã wire FB Marketing client + LLM Haiku recommendation + Telegram digest
- Pban01 emit canonical fact per-campaign cho RAG retrieve (Sprint 11 enhance)
- Cron là dispatcher mỏng, source-of-truth là Pban01

Lý do 5am Perth (= 6am Hà Nội đêm hôm trước UTC+7 → 22:00 UTC):
- Chạy TRƯỚC BC1 Morning Brief 6am VN (= 5am Perth + 30 phút buffer voyage embed)
- Canonical fact ads_insights sẵn sàng khi BC1 rollup query "ads spend hôm qua"
- BC8 Night Audit 11pm Perth sẽ thấy fact của 5am sáng nay = same-day RAG hit

Fallback: nếu scheduler không inject vào constructor (test mode), emit memory
trống + return success=True để cron-job.org không retry storm.

Style: tiếng Việt docstring, ZERO em-dash, type hints, async/await.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

log = logging.getLogger("camas.cron_ads_pull")

EXPECTED_EVENT = "cron.ads_pull.tick"
DELEGATE_AGENT_NAME = "pban_01_quang_cao"
DELEGATE_EVENT = "ads.performance_review"


class CronAdsPull(BaseBC):
    """Cron wrapper, 5am Perth daily, delegate Pban01 ads.performance_review.

    Pull FB Ads insights per campaign last 24h, emit canonical memory facts cho
    BC1 + BC8 + Pban10 RAG retrieve. Google Ads insights wire ở Sprint 12 sau
    khi Anna apply developer token + complete OAuth refresh dance.
    """

    name = "cron_ads_pull"
    scope = "Cron 5am Perth daily, delegate Pban01 ads.performance_review canonical fact"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        scheduler: Optional[Any] = None,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.scheduler = scheduler

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

        date_perth = self._date_perth_str()
        delegate_status = "skipped"
        delegate_payload: dict[str, Any] = {}

        # Delegate Pban01 nếu scheduler đã inject (production path).
        if self.scheduler is not None:
            try:
                # Use venture_context "breakout" since K2 + sales pages live there.
                # Pban01 fetch_insights gom toàn account, không bị venture filter.
                new_ctx = ExecutionContext(
                    run_id=str(uuid.uuid4()),
                    venture_context=ctx.venture_context or "breakout",
                    trigger_event=DELEGATE_EVENT,
                    payload={
                        "triggered_by": self.name,
                        "cron_tick_at": date_perth,
                    },
                )
                delegate_result = await self.scheduler.execute(
                    DELEGATE_AGENT_NAME, new_ctx
                )
                delegate_status = (
                    "delegated_ok" if delegate_result.success else "delegated_fail"
                )
                delegate_payload = {
                    "success": delegate_result.success,
                    "error": delegate_result.error,
                    "pban01_sent_ok": (
                        delegate_result.output_payload or {}
                    ).get("sent_ok"),
                    "fb_metrics_keys": list(
                        (delegate_result.output_payload or {})
                        .get("metrics", {})
                        .keys()
                    ),
                }
            except Exception as exc:  # noqa: BLE001
                log.warning("cron_ads_pull delegate fail: %r", exc)
                delegate_status = "delegate_exception"
                delegate_payload = {"error": repr(exc)}
        else:
            log.info("cron_ads_pull scheduler chưa inject, skip delegate")

        emitted_memories = [
            {
                "agent_name": self.name,
                "content_summary": (
                    f"Ads pull 5am Perth executed status={delegate_status} "
                    f"date={date_perth}"
                ),
                "keywords": ["ads_pull", date_perth, "cron", "fb_ads"],
                "tags": ["cron", "ads_pull", "daily", delegate_status],
                "venture": "all",
                "context": f"{EXPECTED_EVENT} {date_perth}",
                "category": "ads_pull_audit",
            }
        ]

        return AgentResult(
            success=True,
            output_text=(
                f"Ads pull tick {date_perth}, delegate Pban01={delegate_status}"
            ),
            output_payload={
                "event": EXPECTED_EVENT,
                "date_perth": date_perth,
                "delegate_status": delegate_status,
                "delegate_payload": delegate_payload,
                "delegate_agent": DELEGATE_AGENT_NAME,
                "delegate_event": DELEGATE_EVENT,
            },
            emitted_memories=emitted_memories,
        )

    @staticmethod
    def _date_perth_str() -> str:
        """Date YYYY-MM-DD theo timezone Perth (UTC+8)."""
        perth_tz = timezone(timedelta(hours=8))
        return datetime.now(tz=perth_tz).strftime("%Y-%m-%d")
