"""Cron Social Posts, Sunday 8pm VN weekly trigger Phòng 02 Nội dung batch.

Pattern: cron-job.org → POST /kernel/execute, event=cron.social_posts.tick.
Sprint 6 wired: delegate Phòng 02 Nội dung qua scheduler.execute() cho 3 topic.
Mỗi topic 1 reel render request → Vbee + Creatomate API.

Topic source Sprint 6 MVP: fixed list 3 topic. Sprint 7+ sẽ query BC3
customer voice top pain themes.

Fallback: nếu scheduler chưa inject (test mode) → emit memory + return success
để cron-job.org không retry storm.

Lý do delegate qua scheduler thay vì call API trực tiếp:
- Phòng 02 sở hữu Vbee + Creatomate credential + LLM script logic
- Cron là dispatcher mỏng, không duplicate logic
- Kernel scheduler auto inject/extract memory + voice/compliance gate
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

log = logging.getLogger("camas.cron_social_posts")

EXPECTED_EVENT = "cron.social_posts.tick"
DELEGATE_AGENT_NAME = "pban_02_noi_dung"
DELEGATE_EVENT = "content.reel_render_request"

# Sprint 6 MVP fixed topics. Sprint 7+ thay bằng query BC3 + customer voice.
SPRINT_6_TOPICS: list[dict[str, str]] = [
    {
        "name": "ai_solo_business",
        "story_id": "H7",
        "venture": "breakout",
    },
    {
        "name": "breakout_value_ladder",
        "story_id": "H3",
        "venture": "breakout",
    },
    {
        "name": "anna_quangtri_journey",
        "story_id": "H1",
        "venture": "personal",
    },
]


class CronSocialPosts(BaseBC):
    """Cron Sunday 8pm VN weekly, delegate Phòng 02 Nội dung batch 3 reel."""

    name = "cron_social_posts"
    scope = "Cron Sunday 8pm VN, delegate Phòng 02 Nội dung batch 3 reel/tuần"
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
        # Scheduler optional, inject sau register, tránh circular ref lúc init
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
        topics = await self._pick_weekly_topics()
        delegations: list[dict[str, Any]] = []

        if self.scheduler is None:
            log.info(
                "cron_social_posts scheduler chưa inject, skip delegate (Sprint 6 fallback)"
            )
            for topic in topics:
                delegations.append(
                    {
                        "topic": topic["name"],
                        "delegate_status": "no_scheduler",
                        "success": False,
                    }
                )
        else:
            for topic in topics:
                delegate_ctx = ExecutionContext(
                    run_id=str(uuid.uuid4()),
                    user_id=None,
                    venture_context=topic.get("venture", "breakout"),
                    trigger_event=DELEGATE_EVENT,
                    payload={
                        "topic": topic["name"],
                        "story_id": topic.get("story_id", "H1"),
                    },
                )
                try:
                    delegate_result = await self.scheduler.execute(
                        DELEGATE_AGENT_NAME, delegate_ctx
                    )
                    payload = delegate_result.output_payload or {}
                    delegations.append(
                        {
                            "topic": topic["name"],
                            "venture": topic.get("venture"),
                            "success": delegate_result.success,
                            "voice_job_id": payload.get("voice_job_id"),
                            "voice_source": payload.get("voice_source"),
                            "render_job_id": payload.get("render_job_id"),
                            "render_source": payload.get("render_source"),
                            "error": delegate_result.error,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "cron_social_posts delegate %s fail: %r",
                        topic["name"],
                        exc,
                    )
                    delegations.append(
                        {
                            "topic": topic["name"],
                            "venture": topic.get("venture"),
                            "success": False,
                            "error": repr(exc)[:200],
                        }
                    )

        ok_count = sum(1 for d in delegations if d.get("success"))
        summary = self._format_batch_summary(
            date_vn=date_vn, delegations=delegations, ok=ok_count
        )

        emitted_memories = [
            {
                "agent_name": self.name,
                "content_summary": (
                    f"Social posts weekly trigger {date_vn} "
                    f"delegated={ok_count}/{len(topics)}"
                ),
                "keywords": ["social_post", date_vn, "weekly_trigger"],
                "tags": ["cron", "social_post", "weekly_trigger"],
                "venture": "all",
                "context": f"{EXPECTED_EVENT} {date_vn}",
            }
        ]

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload={
                "event": EXPECTED_EVENT,
                "date_vn": date_vn,
                "delegate_agent": DELEGATE_AGENT_NAME,
                "delegate_event": DELEGATE_EVENT,
                "topic_count": len(topics),
                "delegated_ok": ok_count,
                "delegations": delegations,
            },
            emitted_memories=emitted_memories,
        )

    async def _pick_weekly_topics(self) -> list[dict[str, str]]:
        """Sprint 6 MVP: fixed list. Sprint 7+ query BC3 top pain themes."""
        return list(SPRINT_6_TOPICS)

    def _format_batch_summary(
        self,
        *,
        date_vn: str,
        delegations: list[dict[str, Any]],
        ok: int,
    ) -> str:
        lines: list[str] = [
            f"Cron Social Posts {date_vn}",
            f"Delegate Phòng 02 Nội dung: {ok}/{len(delegations)} reel ok",
            "",
        ]
        for d in delegations:
            tag = "ok" if d.get("success") else "fail"
            voice = d.get("voice_source") or "n/a"
            render = d.get("render_source") or "n/a"
            lines.append(
                f"- {d.get('topic')} [{tag}] voice={voice} render={render}"
            )
        return "\n".join(lines)

    @staticmethod
    def _date_vn_str() -> str:
        now_vn = datetime.now(tz=timezone.utc) + timedelta(hours=7)
        return now_vn.strftime("%Y-%m-%d")
