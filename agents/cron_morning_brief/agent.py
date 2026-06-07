"""Cron Morning Brief, 6am VN daily wrapper delegate BC1 rollup.morning.

Pattern: cron-job.org → POST /kernel/execute với agent=cron_morning_brief +
trigger_event=cron.morning_brief.tick. Agent này KHÔNG duplicate logic
BC1 mà delegate qua scheduler.execute(bc1_team_leader, rollup.morning).

Lý do delegate thay vì duplicate:
- BC1 đã wire xong Postgres pool + Voyage memory + LLM Haiku + Telegram
- Duplicate = 2 nguồn truth digest format (drift risk)
- Cron là dispatcher mỏng, source-of-truth là BC1

Fallback: nếu scheduler không inject vào constructor (test mode), emit memory
trống + return success=True để cron-job.org không retry storm.
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

log = logging.getLogger("camas.cron_morning_brief")

EXPECTED_EVENT = "cron.morning_brief.tick"
DELEGATE_AGENT_NAME = "bc1_team_leader"
DELEGATE_EVENT = "rollup.morning"


class CronMorningBrief(BaseBC):
    """Cron wrapper, 6am VN daily, delegate BC1 Team Leader rollup.morning.

    Anna chốt Morning Brief 6am VN = BC1 rollup window 24h. Cron job
    cron-job.org POST /kernel/execute, agent dispatch trigger BC1 đúng event.
    """

    name = "cron_morning_brief"
    scope = "Cron 6am VN daily, delegate BC1 rollup morning Telegram Anna"
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
        # Scheduler optional, inject sau register, tránh circular import lúc init
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

        date_vn = self._date_vn_str()
        delegate_status = "skipped"
        delegate_payload: dict[str, Any] = {}

        # Delegate to BC1 nếu scheduler đã inject (production path).
        if self.scheduler is not None:
            try:
                new_ctx = ExecutionContext(
                    run_id=str(uuid.uuid4()),
                    venture_context="all",
                    trigger_event=DELEGATE_EVENT,
                    payload={},
                )
                delegate_result = await self.scheduler.execute(
                    DELEGATE_AGENT_NAME, new_ctx
                )
                delegate_status = "delegated_ok" if delegate_result.success else "delegated_fail"
                delegate_payload = {
                    "success": delegate_result.success,
                    "error": delegate_result.error,
                    "bc1_sent_ok": (delegate_result.output_payload or {}).get(
                        "sent_ok"
                    ),
                }
            except Exception as exc:  # noqa: BLE001
                log.warning("cron_morning_brief delegate fail: %r", exc)
                delegate_status = "delegate_exception"
                delegate_payload = {"error": repr(exc)}
        else:
            log.info(
                "cron_morning_brief scheduler chưa inject, skip delegate"
            )

        emitted_memories = [
            {
                "agent_name": self.name,
                "content_summary": (
                    f"Morning Brief 6am VN executed status={delegate_status}"
                ),
                "keywords": ["morning_brief", date_vn, "cron"],
                "tags": ["cron", "morning_brief", "daily", delegate_status],
                "venture": "all",
                "context": f"{EXPECTED_EVENT} {date_vn}",
            }
        ]

        return AgentResult(
            success=True,
            output_text=(
                f"Morning Brief tick {date_vn}, delegate BC1={delegate_status}"
            ),
            output_payload={
                "event": EXPECTED_EVENT,
                "delegate_agent": DELEGATE_AGENT_NAME,
                "delegate_event": DELEGATE_EVENT,
                "delegate_status": delegate_status,
                "delegate_payload": delegate_payload,
                "date_vn": date_vn,
            },
            emitted_memories=emitted_memories,
        )

    @staticmethod
    def _date_vn_str() -> str:
        now_vn = datetime.now(tz=timezone.utc) + timedelta(hours=7)
        return now_vn.strftime("%Y-%m-%d")
