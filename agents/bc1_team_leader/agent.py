"""BC1 Team Leader agent.

Orchestrator agent CAMAS Kernel. KHÔNG produce content như BC2, mà:
- Đọc shared memory (agent_memory) qua MemoryLayer + asyncpg pool
- Aggregate stats 22 agent khác (BC2..BC10 + Phong 01..10 + cron)
- Gửi 2 rollup digest mỗi ngày (7am + 9pm VN = 8am + 10pm Perth AWST)
  vào Telegram group Breakout Ops `-1003813280155`

Trigger event:
- `rollup.morning` (7am VN cron-job.org → /kernel/execute bc1_team_leader)
- `rollup.evening` (9pm VN cron-job.org)

Khác BC khác (BC2 producer, BC9 gate, BC8 audit):
- BC1 là consumer + orchestrator, không emit content public
- requires_voice_gate = False, requires_compliance_gate = False vì output chỉ
  vào Telegram nội bộ team, không public
- Reuse MemoryLayer asyncpg pool thay vì tạo pool riêng (tiết kiệm connection)
- LLM Haiku 4.5 cho recommendation (fast + cheap + đủ cho 1-2 dòng tiếng Việt)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
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

log = logging.getLogger("camas.bc1_team_leader")

DEFAULT_LLM_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 300
DEFAULT_LLM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"  # Breakout Ops


class BC1TeamLeader(BaseBC):
    """BC1 Team Leader, orchestrate 22 CAMAS agent + rollup 2x/ngày Telegram.

    Pipeline run():
        1. Match trigger_event → rollup.morning | rollup.evening | unknown
        2. Query agent_memory table 24h/12h window cho stats
        3. Query memory layer top retrieval candidates
        4. Build digest markdown tiếng Việt
        5. LLM Haiku đề xuất 1-2 action items
        6. Send Telegram (skip nếu BC1_DRY_RUN=1)
        7. Return AgentResult + emit memory entry rollup.{morning|evening}.sent
    """

    name = "bc1_team_leader"
    scope = "Orchestrate 22 agent + rollup Anna 2x/ngày Telegram"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = False
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

        if event == "rollup.morning":
            return await self._handle_rollup(window_hours=24, kind="morning")
        if event == "rollup.evening":
            return await self._handle_rollup(window_hours=12, kind="evening")

        return AgentResult(
            success=False,
            output_text="BC1 không xử lý event này",
            output_payload={"trigger_event": event, "supported": [
                "rollup.morning",
                "rollup.evening",
            ]},
        )

    async def _handle_rollup(
        self,
        *,
        window_hours: int,
        kind: str,
    ) -> AgentResult:
        """Build + gửi 1 rollup digest. kind in {'morning', 'evening'}."""
        # Date string giờ VN (UTC+7)
        now_vn = datetime.now(tz=timezone.utc) + timedelta(hours=7)
        date_vn = now_vn.strftime("%Y-%m-%d")

        # 1. Stats từ Postgres
        stats = await self._collect_stats(window_hours=window_hours)

        # 2. Top retrieved từ memory layer (semantic retrieve fallback nếu fail)
        try:
            retrieved = await self.memory.retrieve(
                "overnight events", k=50, max_age_days=1
            )
            top_retrieval_summary = self._summarize_top_retrieval(retrieved)
        except Exception as exc:  # noqa: BLE001
            log.warning("BC1 memory retrieve fail: %r", exc)
            top_retrieval_summary = "không lấy được"

        # 3. LLM recommendation
        recommendation = await self._llm_recommendation(stats, top_retrieval_summary)

        # 4. Build digest markdown
        digest = self._build_digest(
            kind=kind,
            date_vn=date_vn,
            window_hours=window_hours,
            stats=stats,
            top_retrieval=top_retrieval_summary,
            recommendation=recommendation,
        )

        # 5. Send Telegram
        dry_run = os.getenv("BC1_DRY_RUN", "") == "1"
        sent_ok = False
        if dry_run:
            log.info("BC1 DRY_RUN, skip Telegram send")
            sent_ok = True
        else:
            try:
                sent_ok = await send_telegram(digest)
            except Exception as exc:  # noqa: BLE001
                log.warning("BC1 Telegram send fail: %r", exc)
                sent_ok = False

        # 6. Emit memory entry (graceful, kernel auto_extract sẽ persist)
        memory_entry = {
            "agent_name": self.name,
            "content_summary": f"rollup.{kind} sent",
            "keywords": [kind, "rollup", date_vn],
            "tags": ["rollup", kind, "sent" if sent_ok else "send_failed"],
            "venture": "all",
            "context": f"rollup.{kind} {date_vn} window={window_hours}h",
        }

        return AgentResult(
            success=True,
            output_text=digest,
            output_payload={
                "kind": kind,
                "date_vn": date_vn,
                "window_hours": window_hours,
                "stats": stats,
                "sent_ok": sent_ok,
                "dry_run": dry_run,
            },
            emitted_memories=[memory_entry],
        )

    async def _collect_stats(self, *, window_hours: int) -> dict[str, Any]:
        """Query Postgres agent_memory 3 queries qua memory pool.

        Reuse MemoryLayer pool, fail-soft graceful nếu pool/asyncpg lỗi.
        """
        stats: dict[str, Any] = {
            "window_hours": window_hours,
            "by_agent": {},
            "bc2_verdicts": {"APPROVE": 0, "FLAG": 0, "REJECT": 0},
            "total_memories": 0,
            "top_retrieved": [],
            "error": None,
        }

        if not self.memory.dsn:
            stats["error"] = "DATABASE_URL chưa set"
            return stats

        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            log.warning("BC1 get_pool fail: %r", exc)
            stats["error"] = f"pool init fail: {exc}"
            return stats

        try:
            async with pool.acquire() as conn:
                # Query 1: by_agent counts within window
                rows = await conn.fetch(
                    """
                    SELECT agent_name, COUNT(*)::int AS cnt
                    FROM public.agent_memory
                    WHERE created_at > now() - ($1::int * interval '1 hour')
                    GROUP BY agent_name
                    ORDER BY cnt DESC
                    """,
                    window_hours,
                )
                by_agent = {r["agent_name"]: r["cnt"] for r in rows}
                stats["by_agent"] = by_agent
                stats["total_memories"] = sum(by_agent.values())

                # Query 2: BC2 verdict breakdown qua tags
                rows = await conn.fetch(
                    """
                    SELECT tag, COUNT(*)::int AS cnt
                    FROM (
                        SELECT unnest(tags) AS tag
                        FROM public.agent_memory
                        WHERE agent_name = 'bc2_voice_guardian'
                          AND created_at > now() - ($1::int * interval '1 hour')
                    ) sub
                    WHERE tag IN ('APPROVE', 'FLAG', 'REJECT')
                    GROUP BY tag
                    """,
                    window_hours,
                )
                for r in rows:
                    stats["bc2_verdicts"][r["tag"]] = r["cnt"]

                # Query 3: top 5 retrieved memories overall
                rows = await conn.fetch(
                    """
                    SELECT LEFT(content, 100) AS snippet,
                           retrieval_count,
                           agent_name
                    FROM public.agent_memory
                    WHERE retrieval_count > 0
                    ORDER BY retrieval_count DESC
                    LIMIT 5
                    """
                )
                stats["top_retrieved"] = [
                    {
                        "snippet": r["snippet"],
                        "retrieval_count": r["retrieval_count"],
                        "agent_name": r["agent_name"],
                    }
                    for r in rows
                ]
        except Exception as exc:  # noqa: BLE001
            log.warning("BC1 stats SQL fail: %r", exc)
            stats["error"] = f"SQL fail: {exc}"

        return stats

    def _summarize_top_retrieval(self, records: list) -> str:
        """Tóm tắt top retrieval list[MemoryRecord] thành 1 dòng."""
        if not records:
            return "Không có"
        first = records[0]
        content = (getattr(first, "content", "") or "").replace("\n", " ").strip()
        if len(content) > 80:
            content = content[:77] + "..."
        return f"[{first.agent_name}] {content}"

    async def _llm_recommendation(
        self,
        stats: dict[str, Any],
        top_issues: str,
    ) -> str:
        """Call Haiku 4.5 sinh 1-2 action item tiếng Việt."""
        if not self.llm.ready:
            return "LLM chưa init, không có khuyến nghị"

        # Trim stats để khỏi nuốt context
        compact = {
            "by_agent_top5": dict(
                sorted(
                    stats.get("by_agent", {}).items(),
                    key=lambda kv: kv[1],
                    reverse=True,
                )[:5]
            ),
            "bc2_verdicts": stats.get("bc2_verdicts", {}),
            "total_memories": stats.get("total_memories", 0),
            "window_hours": stats.get("window_hours", 24),
        }
        prompt = (
            "You are Anna's operations advisor. Given these overnight stats, "
            "suggest 1-2 short concrete actions Anna should take today. "
            "Output 1-2 lines tiếng Việt only, no preamble.\n\n"
            f"Stats: {json.dumps(compact, ensure_ascii=False)}\n"
            f"Top issues: {top_issues}"
        )

        try:
            resp = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC1 LLM call fail: %r", exc)
            return "LLM call fail, không có khuyến nghị"

        text_parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        text = "".join(text_parts).strip()
        return text or "Không có khuyến nghị"

    def _build_digest(
        self,
        *,
        kind: str,
        date_vn: str,
        window_hours: int,
        stats: dict[str, Any],
        top_retrieval: str,
        recommendation: str,
    ) -> str:
        """Render markdown digest. Telegram parse_mode=Markdown."""
        header_emoji = "Morning Brief" if kind == "morning" else "Evening Brief"
        prefix = "🌅" if kind == "morning" else "🌙"
        window_label = "24h qua" if kind == "morning" else "12h qua"

        verdicts = stats.get("bc2_verdicts", {})
        approve = verdicts.get("APPROVE", 0)
        flag = verdicts.get("FLAG", 0)
        reject = verdicts.get("REJECT", 0)

        total = stats.get("total_memories", 0)
        by_agent = stats.get("by_agent", {})
        top3_agents = sorted(
            by_agent.items(), key=lambda kv: kv[1], reverse=True
        )[:3]
        top_agents_line = (
            ", ".join(f"{name}={cnt}" for name, cnt in top3_agents)
            if top3_agents
            else "không có activity"
        )

        # Hot items: nếu BC2 có FLAG hoặc REJECT trong window thì flag, else không
        hot_lines: list[str] = []
        if flag > 0:
            hot_lines.append(f"- {flag} content FLAG cần Anna review (BC2 queue)")
        if reject > 0:
            hot_lines.append(f"- {reject} content REJECT, kiểm tra root cause")
        if stats.get("error"):
            hot_lines.append(f"- DB error: {stats['error']}")
        if not hot_lines:
            hot_lines.append("- Không có")

        lines = [
            f"{prefix} *{header_emoji} {date_vn}*",
            "",
            f"_{window_label.capitalize()} ({window_hours}h window):_",
            f"- BC2 Voice Guardian: {approve} APPROVE / {flag} FLAG / {reject} REJECT",
            f"- Total memories: {total}",
            f"- Top agents: {top_agents_line}",
            f"- Top retrieval: {top_retrieval}",
            "",
            "*Hot items cần Anna:*",
            *hot_lines,
            "",
            "*Recommended actions:*",
            f"- {recommendation}",
        ]
        return "\n".join(lines)


async def send_telegram(text: str) -> bool:
    """Gửi message tới Telegram group Breakout Ops.

    Env vars:
        TELEGRAM_BOT_TOKEN: bot token
        TELEGRAM_OPS_GROUP_ID: chat id (default -1003813280155)

    Return True nếu HTTP 200, False nếu thiếu token hoặc HTTP != 200.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_OPS_GROUP_ID", DEFAULT_TELEGRAM_GROUP_ID)
    if not token:
        log.warning("BC1 TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "BC1 Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
