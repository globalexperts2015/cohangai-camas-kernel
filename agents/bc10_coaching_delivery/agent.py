"""BC10 Coaching Delivery agent.

Mục tiêu: support Anna (Đào Thị Hằng) deliver 1on1 coaching tier 50tr (6 tháng)
cho Breakout + Cohangai + Speakout. BC10 chuẩn bị brief trước call, tổng kết sau
call và đẩy accountability check-in hàng tuần để tiết kiệm thời gian Anna trên
mỗi coachee về dưới 6h/tháng.

Four trigger events:

1. `coaching.pre_call` (30 phút trước session theo cron coaching)
   - Build customer context từ customer_360 + customer_feedback 30 ngày +
     agent_memory past coaching + Voyage semantic search.
   - Opus 4.7 sinh pre-call brief (5-sentence summary + top wins/challenges +
     agenda 60 phút + 3-5 question Anna hỏi).
   - Send Telegram Anna 30 phút trước.
   - Emit memory tags ["coaching", "pre_call", session_type].

2. `coaching.post_call` (Fathom webhook forward transcript)
   - Match customer_id từ participants email.
   - Opus 4.7 phân tích: action items Anna + customer, wins, concerns,
     next focus.
   - APPEND vào customer_360.notes (giữ history, KHÔNG replace).
   - Emit memory tags ["coaching", "post_call", "action_items"].
   - Telegram Anna preview confirm.

3. `coaching.weekly_checkin` (Sunday 6pm Perth cron per active customer)
   - Query last session action items → Haiku 4.5 sinh 1-2 câu accountability
     check-in.
   - Default ship qua email tới `hang.dao.bbb@gmail.com` (Anna's primary
     inbox) để Anna forward, opt-out qua opt_in flag trong customer_360.notes.
   - Emit memory tags ["coaching", "weekly_checkin"].

4. Unknown event → success=False.

Architectural decisions:
    - Opus 4.7 cho pre_call + post_call: customer tier 50tr/6 tháng = ROI cao,
      chất lượng > tốc độ (1 brief sai ý có thể làm Anna mất 90 phút call).
      Haiku 4.5 chỉ dùng cho weekly check-in (1-2 câu, cost-sensitive nhân số
      coachee active 5-10 người).
    - Send pre-call brief 30 phút trước (KHÔNG 1h hay 15p): đủ thời gian Anna
      đọc + tweak agenda nhưng đủ gần để context còn fresh, khớp Anna time
      budget brief 15 phút review trong brief.
    - customer_360.notes append-only với timestamp prefix: giữ history toàn
      bộ trajectory coaching 6 tháng để Anna lookback, không bao giờ overwrite.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
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

log = logging.getLogger("camas.bc10_coaching_delivery")

DEFAULT_OPUS_MODEL = "claude-haiku-4-5"
DEFAULT_HAIKU_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS_BRIEF = 2000
DEFAULT_MAX_TOKENS_POSTCALL = 2500
DEFAULT_MAX_TOKENS_CHECKIN = 400
DEFAULT_LLM_TIMEOUT = 120.0
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"  # Breakout Ops

VALID_SESSION_TYPES = {"kickoff", "weekly", "biweekly", "midpoint", "final"}
COACHING_LTV_THRESHOLD_VND = 50_000_000
ANNA_PRIMARY_INBOX = "hang.dao.bbb@gmail.com"


# ============================================================
# Tool schema cho Opus 4.7 pre-call brief
# ============================================================
SUBMIT_PRE_CALL_BRIEF_TOOL = {
    "name": "submit_pre_call_brief",
    "description": (
        "Submit pre-call coaching brief cho Anna 30 phút trước session, "
        "kèm summary + wins + challenges + agenda + questions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "customer_summary": {
                "type": "string",
                "description": (
                    "Tóm tắt 5 câu tiếng Việt: identity coachee, stage hiện "
                    "tại, big goal, momentum, key concern. Không em-dash."
                ),
            },
            "top_wins": {
                "type": "array",
                "minItems": 0,
                "maxItems": 3,
                "items": {"type": "string"},
                "description": "Top 3 win since last call (concrete, có quote nếu có).",
            },
            "top_challenges": {
                "type": "array",
                "minItems": 0,
                "maxItems": 3,
                "items": {"type": "string"},
                "description": "Top 3 challenge cần address buổi này.",
            },
            "suggested_agenda": {
                "type": "array",
                "minItems": 3,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "minutes": {"type": "integer"},
                        "block": {"type": "string"},
                    },
                    "required": ["minutes", "block"],
                },
                "description": (
                    "Agenda 60 phút, breakdown từng block, total ~60 phút."
                ),
            },
            "questions_for_anna": {
                "type": "array",
                "minItems": 3,
                "maxItems": 5,
                "items": {"type": "string"},
                "description": "3-5 câu Anna nên hỏi để dẫn buổi.",
            },
            "watch_out": {
                "type": "array",
                "maxItems": 3,
                "items": {"type": "string"},
                "description": "0-3 sensitive topic Anna nên tránh hoặc cẩn thận.",
            },
        },
        "required": [
            "customer_summary",
            "top_wins",
            "top_challenges",
            "suggested_agenda",
            "questions_for_anna",
        ],
    },
}


# ============================================================
# Tool schema cho Opus 4.7 post-call analysis
# ============================================================
SUBMIT_POST_CALL_ANALYSIS_TOOL = {
    "name": "submit_post_call_analysis",
    "description": (
        "Submit post-call coaching analysis: action items Anna + customer, "
        "wins, concerns, next session focus."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "anna_action_items": {
                "type": "array",
                "minItems": 0,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "deadline": {"type": "string"},
                    },
                    "required": ["action"],
                },
                "description": "Anna commitment tuần tới (max 3).",
            },
            "customer_action_items": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "deadline": {"type": "string"},
                    },
                    "required": ["action"],
                },
                "description": "Action items coachee tuần tới (max 5).",
            },
            "wins_captured": {
                "type": "array",
                "maxItems": 5,
                "items": {"type": "string"},
                "description": "Wins coachee kể trong call.",
            },
            "concerns_surfaced": {
                "type": "array",
                "maxItems": 5,
                "items": {"type": "string"},
                "description": "Block/concern xuất hiện trong call.",
            },
            "next_session_focus": {
                "type": "string",
                "description": "Focus chính buổi sau, 1-2 câu.",
            },
            "key_insight": {
                "type": "string",
                "description": "Insight dài hạn cho coachee, 1-2 câu.",
            },
        },
        "required": [
            "anna_action_items",
            "customer_action_items",
            "wins_captured",
            "concerns_surfaced",
            "next_session_focus",
        ],
    },
}


class BC10CoachingDelivery(BaseBC):
    """BC10 Coaching Delivery agent.

    Autonomy: L2_APPROVE vì pre-call brief gửi Anna 30 phút trước, Anna ack
    hoặc edit qua reply Telegram. Post-call analysis cũng gửi Anna confirm
    trước khi share với coachee.
    """

    name = "bc10_coaching_delivery"
    scope = (
        "1on1 50M tier coaching support, pre/post call brief, "
        "weekly check-in tracking"
    )
    autonomy_level = AutonomyLevel.L2_APPROVE
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        opus_model: str = DEFAULT_OPUS_MODEL,
        haiku_model: str = DEFAULT_HAIKU_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.opus_model = opus_model
        self.haiku_model = haiku_model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""

        if event == "coaching.pre_call":
            return await self._handle_pre_call(ctx)
        if event == "coaching.post_call":
            return await self._handle_post_call(ctx)
        if event == "coaching.weekly_checkin":
            return await self._handle_weekly_checkin(ctx)

        return AgentResult(
            success=False,
            output_text="BC10 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "coaching.pre_call",
                    "coaching.post_call",
                    "coaching.weekly_checkin",
                ],
            },
        )

    # ============================================================
    # Event 1: coaching.pre_call
    # ============================================================
    async def _handle_pre_call(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        customer_id = self._coerce_int(payload.get("customer_id"))
        session_id = payload.get("session_id")
        session_type = (payload.get("session_type") or "weekly").lower().strip()
        if session_type not in VALID_SESSION_TYPES:
            session_type = "weekly"

        if customer_id is None:
            return AgentResult(
                success=False,
                output_text="Pre-call brief thiếu customer_id (int)",
                output_payload={"payload": payload},
            )

        # FAST PATH: nếu kernel Scheduler đã pre-process Profile + Task,
        # dùng trực tiếp, skip 4 DB query + customer_feedback re-analysis.
        profile_nl = self._extract_from_injected(ctx, "profile")
        task_nl = self._extract_from_injected(ctx, "task")
        if profile_nl and task_nl and self.llm.ready:
            log.info(
                "BC10 fast path pre_call customer=%s (Profile+Task pre-injected)",
                customer_id,
            )
            return await self._pre_call_fast_path(
                ctx=ctx,
                customer_id=customer_id,
                session_id=session_id,
                session_type=session_type,
                profile_nl=profile_nl,
                task_nl=task_nl,
            )

        log.warning(
            "BC10 slow path pre_call customer=%s, no pre-processed Profile/Task, "
            "fallback re-analyze",
            customer_id,
        )

        # Build customer context
        try:
            customer_360 = await self._fetch_customer_360(customer_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("BC10 fetch customer_360 fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"Query customer_360 fail: {exc}",
                output_payload={"error": str(exc)},
                escalation_required=True,
                escalation_reason="db_query_fail",
            )

        if customer_360 is None:
            return AgentResult(
                success=False,
                output_text=f"Không tìm thấy customer_id={customer_id}",
                output_payload={"customer_id": customer_id},
            )

        try:
            feedback_rows = await self._fetch_customer_feedback(customer_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("BC10 fetch customer_feedback fail: %r", exc)
            feedback_rows = []

        try:
            past_memories = await self._fetch_coaching_memories(customer_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("BC10 fetch agent_memory fail: %r", exc)
            past_memories = []

        # Voyage semantic retrieve past similar coaching sessions
        retrieved_summary = "không lấy được"
        try:
            query = (
                f"coaching session {session_type} customer "
                f"{customer_360.get('full_name', '')} "
                f"stage={customer_360.get('current_stage', '')}"
            )
            retrieved = await self.memory.retrieve(
                query,
                k=5,
                agent_name=self.name,
                customer_id=customer_id,
                max_age_days=180,
            )
            retrieved_summary = self._summarize_retrieval(retrieved)
        except Exception as exc:  # noqa: BLE001
            log.debug("BC10 semantic retrieve fail: %r", exc)

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM client chưa init",
                output_payload={"error": "ANTHROPIC_API_KEY chưa set"},
                escalation_required=True,
                escalation_reason="llm_not_ready",
            )

        prompt = self._build_pre_call_prompt(
            customer_360=customer_360,
            feedback_rows=feedback_rows,
            past_memories=past_memories,
            retrieved_summary=retrieved_summary,
            session_type=session_type,
            session_id=session_id,
        )

        try:
            response = await self.llm.client.messages.create(
                model=self.opus_model,
                max_tokens=DEFAULT_MAX_TOKENS_BRIEF,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_PRE_CALL_BRIEF_TOOL],
                tool_choice={"type": "tool", "name": "submit_pre_call_brief"},
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC10 opus pre_call call fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM call fail: {exc}",
                output_payload={"error": str(exc)},
                escalation_required=True,
                escalation_reason="llm_call_fail",
            )

        brief = self._extract_tool_input(response, "submit_pre_call_brief")
        if brief.get("error"):
            return AgentResult(
                success=False,
                output_text=brief.get("error", "Parse fail"),
                output_payload=brief,
                escalation_required=True,
                escalation_reason="brief_parse_fail",
            )

        markdown = self._format_pre_call_markdown(
            customer_360=customer_360,
            brief=brief,
            session_type=session_type,
            session_id=session_id,
        )

        dry_run = os.getenv("BC10_DRY_RUN", "") == "1"
        sent_ok = False
        if dry_run:
            log.info("BC10 DRY_RUN, skip Telegram send pre_call")
            sent_ok = True
        else:
            try:
                sent_ok = await send_telegram(markdown)
            except Exception as exc:  # noqa: BLE001
                log.warning("BC10 Telegram send pre_call fail: %r", exc)
                sent_ok = False

        cust_name = customer_360.get("full_name") or f"#{customer_id}"
        memory = {
            "agent_name": self.name,
            "content": (
                f"Pre-call brief {session_type} customer={cust_name} "
                f"session_id={session_id}: "
                f"{(brief.get('customer_summary') or '')[:300]}"
            ),
            "keywords": ["coaching", "pre_call", session_type],
            "tags": ["coaching", "pre_call", session_type],
            "venture": "breakout",
            "customer_id": customer_id,
            "context": f"session_id={session_id} type={session_type}",
        }

        return AgentResult(
            success=True,
            output_text=markdown,
            output_payload={
                "customer_id": customer_id,
                "session_id": session_id,
                "session_type": session_type,
                "brief": brief,
                "sent_ok": sent_ok,
                "dry_run": dry_run,
            },
            emitted_memories=[memory],
        )

    # ============================================================
    # Event 2: coaching.post_call
    # ============================================================
    async def _handle_post_call(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        transcript = payload.get("transcript") or ""
        recording_id = payload.get("recording_id")
        participants = payload.get("participants") or []
        session_type = (payload.get("session_type") or "weekly").lower().strip()
        if session_type not in VALID_SESSION_TYPES:
            session_type = "weekly"

        if not transcript.strip():
            return AgentResult(
                success=False,
                output_text="Post-call thiếu transcript",
                output_payload={"recording_id": recording_id},
            )

        customer_id = self._coerce_int(payload.get("customer_id"))
        if customer_id is None:
            customer_id = await self._resolve_customer_from_participants(
                participants
            )
        if customer_id is None:
            return AgentResult(
                success=False,
                output_text="Không resolve được customer_id từ payload + participants",
                output_payload={"participants": participants},
                escalation_required=True,
                escalation_reason="customer_unresolved",
            )

        try:
            customer_360 = await self._fetch_customer_360(customer_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("BC10 fetch customer_360 (post_call) fail: %r", exc)
            customer_360 = None

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM client chưa init",
                output_payload={"error": "ANTHROPIC_API_KEY chưa set"},
                escalation_required=True,
                escalation_reason="llm_not_ready",
            )

        prompt = self._build_post_call_prompt(
            transcript=transcript,
            customer_360=customer_360 or {},
            session_type=session_type,
            recording_id=recording_id,
        )

        try:
            response = await self.llm.client.messages.create(
                model=self.opus_model,
                max_tokens=DEFAULT_MAX_TOKENS_POSTCALL,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_POST_CALL_ANALYSIS_TOOL],
                tool_choice={"type": "tool", "name": "submit_post_call_analysis"},
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC10 opus post_call call fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM call fail: {exc}",
                output_payload={"error": str(exc)},
                escalation_required=True,
                escalation_reason="llm_call_fail",
            )

        analysis = self._extract_tool_input(response, "submit_post_call_analysis")
        if analysis.get("error"):
            return AgentResult(
                success=False,
                output_text=analysis.get("error", "Parse fail"),
                output_payload=analysis,
                escalation_required=True,
                escalation_reason="analysis_parse_fail",
            )

        dry_run = os.getenv("BC10_DRY_RUN", "") == "1"

        # APPEND vào customer_360.notes (KHÔNG replace)
        notes_appended_ok = False
        if not dry_run:
            try:
                await self._append_customer_notes(
                    customer_id=customer_id,
                    session_type=session_type,
                    analysis=analysis,
                    recording_id=recording_id,
                )
                notes_appended_ok = True
            except Exception as exc:  # noqa: BLE001
                log.warning("BC10 append customer_360.notes fail: %r", exc)
                notes_appended_ok = False
        else:
            log.info("BC10 DRY_RUN, skip customer_360.notes append")
            notes_appended_ok = True

        markdown = self._format_post_call_markdown(
            customer_360=customer_360 or {},
            analysis=analysis,
            session_type=session_type,
            recording_id=recording_id,
        )

        sent_ok = False
        if dry_run:
            log.info("BC10 DRY_RUN, skip Telegram send post_call")
            sent_ok = True
        else:
            try:
                sent_ok = await send_telegram(markdown)
            except Exception as exc:  # noqa: BLE001
                log.warning("BC10 Telegram send post_call fail: %r", exc)
                sent_ok = False

        cust_name = (customer_360 or {}).get("full_name") or f"#{customer_id}"
        memory = {
            "agent_name": self.name,
            "content": (
                f"Post-call analysis {session_type} customer={cust_name} "
                f"recording={recording_id}: "
                f"{(analysis.get('next_session_focus') or '')[:300]}"
            ),
            "keywords": ["coaching", "post_call", "action_items"],
            "tags": ["coaching", "post_call", "action_items", session_type],
            "venture": "breakout",
            "customer_id": customer_id,
            "context": (
                f"recording_id={recording_id} type={session_type} "
                f"customer_actions={len(analysis.get('customer_action_items') or [])}"
            ),
        }

        return AgentResult(
            success=True,
            output_text=markdown,
            output_payload={
                "customer_id": customer_id,
                "recording_id": recording_id,
                "session_type": session_type,
                "analysis": analysis,
                "notes_appended_ok": notes_appended_ok,
                "sent_ok": sent_ok,
                "dry_run": dry_run,
            },
            emitted_memories=[memory],
        )

    # ============================================================
    # Event 3: coaching.weekly_checkin
    # ============================================================
    async def _handle_weekly_checkin(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        explicit_customer_id = self._coerce_int(payload.get("customer_id"))

        if explicit_customer_id is not None:
            customers = await self._fetch_single_coaching_customer(
                explicit_customer_id
            )
        else:
            try:
                customers = await self._fetch_active_coaching_customers()
            except Exception as exc:  # noqa: BLE001
                log.warning("BC10 fetch active coaching list fail: %r", exc)
                return AgentResult(
                    success=False,
                    output_text=f"Query coaching customers fail: {exc}",
                    output_payload={"error": str(exc)},
                    escalation_required=True,
                    escalation_reason="db_query_fail",
                )

        if not customers:
            return AgentResult(
                success=True,
                output_text="Không có coaching customer active tuần này",
                output_payload={"checkin_count": 0},
            )

        dry_run = os.getenv("BC10_DRY_RUN", "") == "1"
        emitted_memories: list[dict[str, Any]] = []
        sent_ok_total = 0
        checkin_outputs: list[dict[str, Any]] = []

        for cust in customers:
            cid = cust["id"]
            try:
                last_actions = await self._fetch_last_post_call_actions(cid)
            except Exception as exc:  # noqa: BLE001
                log.debug("BC10 fetch last actions fail c=%s: %r", cid, exc)
                last_actions = []

            question = await self._generate_checkin_question(
                customer=cust,
                last_actions=last_actions,
            )

            email_body = self._format_checkin_email(
                customer=cust,
                question=question,
                last_actions=last_actions,
            )

            sent_this = False
            if dry_run:
                log.info(
                    "BC10 DRY_RUN, skip email check-in customer=%s",
                    cid,
                )
                sent_this = True
            else:
                try:
                    sent_this = await send_email_to_anna(
                        subject=(
                            f"[Coaching check-in] {cust.get('full_name', f'#{cid}')}"
                        ),
                        body=email_body,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "BC10 send email check-in fail c=%s: %r", cid, exc
                    )
                    sent_this = False
            if sent_this:
                sent_ok_total += 1

            checkin_outputs.append(
                {
                    "customer_id": cid,
                    "name": cust.get("full_name"),
                    "question": question,
                    "sent_ok": sent_this,
                }
            )

            emitted_memories.append(
                {
                    "agent_name": self.name,
                    "content": (
                        f"Weekly check-in customer={cust.get('full_name') or cid}: "
                        f"{question[:300]}"
                    ),
                    "keywords": ["coaching", "weekly_checkin"],
                    "tags": ["coaching", "weekly_checkin"],
                    "venture": "breakout",
                    "customer_id": cid,
                    "context": (
                        f"week={date.today().isoformat()} "
                        f"actions_referenced={len(last_actions)}"
                    ),
                }
            )

        return AgentResult(
            success=True,
            output_text=(
                f"Weekly check-in {len(customers)} coaching customers, "
                f"{sent_ok_total} sent ok (dry_run={dry_run})"
            ),
            output_payload={
                "checkin_count": len(customers),
                "sent_ok_total": sent_ok_total,
                "dry_run": dry_run,
                "checkins": checkin_outputs,
            },
            emitted_memories=emitted_memories,
        )

    # ============================================================
    # DB helpers
    # ============================================================
    async def _fetch_customer_360(
        self, customer_id: int
    ) -> Optional[dict[str, Any]]:
        if not self.memory.dsn:
            raise RuntimeError("DATABASE_URL chưa set")
        pool = await self.memory._get_pool()  # noqa: SLF001
        sql = """
            SELECT c.id, c.full_name, c.primary_email, c.primary_phone_e164,
                   c360.ltv_vnd, c360.current_stage,
                   c360.ventures_active, c360.notes
            FROM public.customers c
            LEFT JOIN public.customer_360 c360 ON c360.customer_id = c.id
            WHERE c.id = $1
            LIMIT 1
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, customer_id)
        if not row:
            return None
        return dict(row)

    async def _fetch_customer_feedback(
        self, customer_id: int
    ) -> list[dict[str, Any]]:
        if not self.memory.dsn:
            return []
        pool = await self.memory._get_pool()  # noqa: SLF001
        sql = """
            SELECT feedback_type, content_summary, sentiment, theme_tags,
                   created_at
            FROM public.customer_feedback
            WHERE customer_id = $1
              AND created_at > now() - interval '30 days'
            ORDER BY created_at DESC
            LIMIT 20
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, customer_id)
        return [dict(r) for r in rows]

    async def _fetch_coaching_memories(
        self, customer_id: int
    ) -> list[dict[str, Any]]:
        if not self.memory.dsn:
            return []
        pool = await self.memory._get_pool()  # noqa: SLF001
        sql = """
            SELECT content, tags, created_at, retrieval_count
            FROM public.agent_memory
            WHERE customer_id = $1
              AND agent_name = 'bc10_coaching_delivery'
            ORDER BY created_at DESC
            LIMIT 10
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, customer_id)
        return [dict(r) for r in rows]

    async def _fetch_last_post_call_actions(
        self, customer_id: int
    ) -> list[dict[str, Any]]:
        """Lấy last post_call memory để extract action items reference."""
        if not self.memory.dsn:
            return []
        pool = await self.memory._get_pool()  # noqa: SLF001
        sql = """
            SELECT content, context, created_at
            FROM public.agent_memory
            WHERE customer_id = $1
              AND agent_name = 'bc10_coaching_delivery'
              AND 'post_call' = ANY(tags)
            ORDER BY created_at DESC
            LIMIT 1
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, customer_id)
        return [dict(r) for r in rows]

    async def _fetch_active_coaching_customers(self) -> list[dict[str, Any]]:
        """Active 50M tier coaching customers (Breakout coaching ladder).

        Filter c360.ltv_vnd >= 50tr AND 'breakout_coaching' trong
        ventures_active. Pattern follow brief.
        """
        if not self.memory.dsn:
            raise RuntimeError("DATABASE_URL chưa set")
        pool = await self.memory._get_pool()  # noqa: SLF001
        sql = """
            SELECT c.id, c.full_name, c.primary_email,
                   c360.ltv_vnd, c360.current_stage, c360.notes
            FROM public.customers c
            JOIN public.customer_360 c360 ON c360.customer_id = c.id
            WHERE c360.ltv_vnd >= $1
              AND 'breakout_coaching' = ANY(c360.ventures_active)
            ORDER BY c.id
            LIMIT 50
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, COACHING_LTV_THRESHOLD_VND)
        return [dict(r) for r in rows]

    async def _fetch_single_coaching_customer(
        self, customer_id: int
    ) -> list[dict[str, Any]]:
        if not self.memory.dsn:
            return []
        pool = await self.memory._get_pool()  # noqa: SLF001
        sql = """
            SELECT c.id, c.full_name, c.primary_email,
                   c360.ltv_vnd, c360.current_stage, c360.notes
            FROM public.customers c
            LEFT JOIN public.customer_360 c360 ON c360.customer_id = c.id
            WHERE c.id = $1
            LIMIT 1
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, customer_id)
        return [dict(row)] if row else []

    async def _append_customer_notes(
        self,
        *,
        customer_id: int,
        session_type: str,
        analysis: dict[str, Any],
        recording_id: Any,
    ) -> None:
        """APPEND post-call summary vào customer_360.notes, KHÔNG replace.

        Format prefix `[YYYY-MM-DD post_call type=...]` để Anna sau này dễ
        lookback theo timeline.
        """
        if not self.memory.dsn:
            raise RuntimeError("DATABASE_URL chưa set")
        pool = await self.memory._get_pool()  # noqa: SLF001

        ts = date.today().isoformat()
        wins = "; ".join((analysis.get("wins_captured") or [])[:3])
        concerns = "; ".join((analysis.get("concerns_surfaced") or [])[:3])
        next_focus = analysis.get("next_session_focus") or ""
        cust_actions = analysis.get("customer_action_items") or []
        cust_actions_str = "; ".join(
            f"{a.get('action', '?')}"
            + (f" (deadline {a.get('deadline')})" if a.get("deadline") else "")
            for a in cust_actions[:5]
        )

        append_block = (
            f"\n\n[{ts} post_call type={session_type} recording={recording_id}]\n"
            f"Wins: {wins}\n"
            f"Concerns: {concerns}\n"
            f"Customer actions: {cust_actions_str}\n"
            f"Next focus: {next_focus}"
        )

        sql = """
            UPDATE public.customer_360
            SET notes = COALESCE(notes, '') || $2,
                updated_at = now()
            WHERE customer_id = $1
        """
        async with pool.acquire() as conn:
            await conn.execute(sql, customer_id, append_block)

    async def _resolve_customer_from_participants(
        self, participants: list[Any]
    ) -> Optional[int]:
        if not participants or not self.memory.dsn:
            return None
        emails: list[str] = []
        for p in participants:
            if isinstance(p, dict):
                email = (p.get("email") or "").strip().lower()
                if email:
                    emails.append(email)
            elif isinstance(p, str) and "@" in p:
                emails.append(p.strip().lower())
        if not emails:
            return None
        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id FROM public.customers "
                    "WHERE LOWER(email) = ANY($1::text[]) LIMIT 1",
                    emails,
                )
                if row:
                    return int(row["id"])
        except Exception as exc:  # noqa: BLE001
            log.debug("BC10 resolve customer fail: %r", exc)
        return None

    # ============================================================
    # Fast path helpers (Sprint 5 System-Wide Personalization)
    # ============================================================
    @staticmethod
    def _extract_from_injected(
        ctx: ExecutionContext, source: str
    ) -> Optional[str]:
        """Extract pre-processed NL content từ ctx.injected_memories theo tier.

        Scheduler._auto_inject populate 4 tier: profile / task / conversation /
        canonical. Consumer agent đọc trực tiếp, không re-retrieve.
        """
        for grp in ctx.injected_memories or []:
            if grp.get("source") == source:
                content = grp.get("content")
                if isinstance(content, str) and content.strip():
                    return content
        return None

    async def _pre_call_fast_path(
        self,
        *,
        ctx: ExecutionContext,
        customer_id: int,
        session_id: Any,
        session_type: str,
        profile_nl: str,
        task_nl: str,
    ) -> AgentResult:
        """Pre-call brief dùng Profile + Task pre-processed.

        Tiết kiệm 4 DB query + bỏ customer_feedback re-analysis.
        Opus 4.7 vẫn chạy nhưng prompt ngắn hơn nhiều (~60% token saving).
        """
        # Conversation tier optional (recent context)
        conversation_nl = self._extract_from_injected(ctx, "conversation") or ""

        prompt = (
            "Bạn là Coaching Delivery Analyst cho Đào Thị Hằng (Hằng/Anna), "
            "venture Breakout (training Shopify cho người Việt). "
            "Coachee đang ở gói coaching 50tr/6 tháng, tier cao nhất ladder. "
            "Anna sẽ nhận brief này 30 phút trước call.\n\n"
            "NHIỆM VỤ: sinh pre-call brief qua tool `submit_pre_call_brief`.\n\n"
            f"CUSTOMER PROFILE (long-term identity):\n{profile_nl}\n\n"
            f"CURRENT TASK STATE (recent goals + actions):\n{task_nl}\n\n"
            f"RECENT CONVERSATION:\n{conversation_nl or '(không có)'}\n\n"
            f"Session type: {session_type} (session_id={session_id})\n\n"
            "NGUYÊN TẮC:\n"
            "- Tiếng Việt thuần, không em-dash, không emoji.\n"
            "- customer_summary 5 câu cô đọng identity + momentum + concern.\n"
            "- top_wins concrete (con số hoặc trải nghiệm cụ thể), KHÔNG bịa.\n"
            "- suggested_agenda total 60 phút, breakdown rõ minutes + block.\n"
            "- questions_for_anna là câu hỏi mở dẫn coachee tự reflect.\n"
            "- watch_out nhắc Anna về sensitive topic (nếu có) hoặc bài học cũ.\n"
            "- KHÔNG mention 'team' / 'nhân viên' (Anna solo).\n\n"
            "Gọi tool `submit_pre_call_brief`. KHÔNG output text khác."
        )

        try:
            response = await self.llm.client.messages.create(
                model=self.opus_model,
                max_tokens=DEFAULT_MAX_TOKENS_BRIEF,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_PRE_CALL_BRIEF_TOOL],
                tool_choice={"type": "tool", "name": "submit_pre_call_brief"},
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC10 fast path opus pre_call fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM call fail: {exc}",
                output_payload={"error": str(exc), "path": "fast"},
                escalation_required=True,
                escalation_reason="llm_call_fail",
            )

        brief = self._extract_tool_input(response, "submit_pre_call_brief")
        if brief.get("error"):
            return AgentResult(
                success=False,
                output_text=brief.get("error", "Parse fail"),
                output_payload={**brief, "path": "fast"},
                escalation_required=True,
                escalation_reason="brief_parse_fail",
            )

        cust_name = self._infer_customer_name_from_profile(profile_nl) or (
            f"#{customer_id}"
        )
        customer_360_min = {"full_name": cust_name}

        markdown = self._format_pre_call_markdown(
            customer_360=customer_360_min,
            brief=brief,
            session_type=session_type,
            session_id=session_id,
        )

        dry_run = os.getenv("BC10_DRY_RUN", "") == "1"
        sent_ok = False
        if dry_run:
            log.info("BC10 DRY_RUN, skip Telegram send pre_call (fast)")
            sent_ok = True
        else:
            try:
                sent_ok = await send_telegram(markdown)
            except Exception as exc:  # noqa: BLE001
                log.warning("BC10 Telegram send pre_call fast fail: %r", exc)
                sent_ok = False

        memory = {
            "agent_name": self.name,
            "content": (
                f"Pre-call brief {session_type} customer={cust_name} "
                f"session_id={session_id} (fast path): "
                f"{(brief.get('customer_summary') or '')[:300]}"
            ),
            "keywords": ["coaching", "pre_call", session_type, "fast_path"],
            "tags": ["coaching", "pre_call", session_type],
            "venture": "breakout",
            "customer_id": customer_id,
            "context": (
                f"session_id={session_id} type={session_type} path=fast"
            ),
        }

        return AgentResult(
            success=True,
            output_text=markdown,
            output_payload={
                "customer_id": customer_id,
                "session_id": session_id,
                "session_type": session_type,
                "brief": brief,
                "sent_ok": sent_ok,
                "dry_run": dry_run,
                "path": "fast",
            },
            emitted_memories=[memory],
        )

    @staticmethod
    def _infer_customer_name_from_profile(profile_nl: str) -> Optional[str]:
        """Best-effort extract tên coachee từ profile NL line.

        Profile NL format `- [agent | venture | date] content`. Tìm pattern
        "tên: X" hoặc "coachee X" để pretty-print Telegram.
        """
        if not profile_nl:
            return None
        lower = profile_nl.lower()
        for marker in ("coachee", "tên", "ten", "customer"):
            idx = lower.find(marker)
            if idx >= 0:
                tail = profile_nl[idx + len(marker):].strip(" :,").split("\n")[0]
                tail = tail.split(".")[0].strip()
                if 3 < len(tail) < 60:
                    return tail
        return None

    # ============================================================
    # LLM helpers
    # ============================================================
    def _build_pre_call_prompt(
        self,
        *,
        customer_360: dict[str, Any],
        feedback_rows: list[dict[str, Any]],
        past_memories: list[dict[str, Any]],
        retrieved_summary: str,
        session_type: str,
        session_id: Any,
    ) -> str:
        cust_name = customer_360.get("full_name") or "?"
        stage = customer_360.get("current_stage") or "?"
        ltv = customer_360.get("ltv_vnd") or 0
        ventures = customer_360.get("ventures_active") or []
        notes = (customer_360.get("notes") or "")[-2000:]

        # Pain themes top 5 từ feedback gần đây
        pain_lines: list[str] = []
        for r in feedback_rows[:10]:
            ftype = r.get("feedback_type") or "?"
            summary = (r.get("content_summary") or "").replace("\n", " ")[:200]
            sent = r.get("sentiment")
            sent_str = f"{float(sent):+.2f}" if sent is not None else "n/a"
            tags = ",".join((r.get("theme_tags") or [])[:5])
            pain_lines.append(
                f"- [{ftype} sent={sent_str} tags={tags}] {summary}"
            )
        feedback_block = "\n".join(pain_lines) if pain_lines else "(không có)"

        memory_lines: list[str] = []
        for m in past_memories[:8]:
            ts = m.get("created_at")
            ts_str = ts.isoformat()[:10] if hasattr(ts, "isoformat") else "?"
            tags = ",".join((m.get("tags") or [])[:3])
            content = (m.get("content") or "").replace("\n", " ")[:250]
            memory_lines.append(f"- [{ts_str} tags={tags}] {content}")
        memory_block = "\n".join(memory_lines) if memory_lines else "(không có)"

        return (
            "Bạn là Coaching Delivery Analyst cho Đào Thị Hằng (Hằng/Anna), "
            "venture Breakout (training Shopify cho người Việt). "
            "Coachee đang ở gói coaching 50tr/6 tháng, tier cao nhất ladder. "
            "Anna sẽ nhận brief này 30 phút trước call.\n\n"
            "NHIỆM VỤ: sinh pre-call brief qua tool `submit_pre_call_brief`.\n\n"
            f"COACHEE: {cust_name}\n"
            f"Stage hiện tại: {stage}\n"
            f"LTV VND: {ltv:,}\n"
            f"Ventures active: {', '.join(ventures) if ventures else '?'}\n"
            f"Session type: {session_type} (session_id={session_id})\n\n"
            f"CUSTOMER 360 NOTES (history append-only):\n---\n{notes}\n---\n\n"
            f"FEEDBACK 30 NGÀY QUA ({len(feedback_rows)} items):\n"
            f"{feedback_block}\n\n"
            f"COACHING MEMORIES PAST ({len(past_memories)} items):\n"
            f"{memory_block}\n\n"
            f"RETRIEVED SIMILAR SESSIONS: {retrieved_summary}\n\n"
            "NGUYÊN TẮC:\n"
            "- Tiếng Việt thuần, không em-dash, không emoji.\n"
            "- customer_summary 5 câu cô đọng identity + momentum + concern.\n"
            "- top_wins concrete (con số hoặc trải nghiệm cụ thể), KHÔNG bịa.\n"
            "- suggested_agenda total 60 phút, breakdown rõ minutes + block.\n"
            "- questions_for_anna là câu hỏi mở dẫn coachee tự reflect.\n"
            "- watch_out nhắc Anna về sensitive topic (nếu có) hoặc bài học cũ.\n"
            "- KHÔNG mention 'team' / 'nhân viên' (Anna solo).\n\n"
            "Gọi tool `submit_pre_call_brief`. KHÔNG output text khác."
        )

    def _build_post_call_prompt(
        self,
        *,
        transcript: str,
        customer_360: dict[str, Any],
        session_type: str,
        recording_id: Any,
    ) -> str:
        cust_name = customer_360.get("full_name") or "?"
        stage = customer_360.get("current_stage") or "?"
        trimmed = transcript[:12000]

        return (
            "Bạn là Coaching Delivery Analyst cho Đào Thị Hằng (Hằng/Anna). "
            "Đây là transcript buổi coaching 1on1 tier 50tr vừa kết thúc. "
            "Anna cần action items + insight để theo dõi accountability.\n\n"
            f"COACHEE: {cust_name} (stage={stage})\n"
            f"Session type: {session_type} (recording={recording_id})\n\n"
            f"TRANSCRIPT:\n---\n{trimmed}\n---\n\n"
            "NHIỆM VỤ: phân tích qua tool `submit_post_call_analysis`.\n"
            "- anna_action_items: Anna cam kết gì (review proposal, gửi link, "
            "follow up X) max 3.\n"
            "- customer_action_items: coachee commit gì tuần tới max 5, kèm "
            "deadline nếu có nhắc trong call.\n"
            "- wins_captured: thắng cụ thể coachee kể.\n"
            "- concerns_surfaced: lo lắng/block xuất hiện.\n"
            "- next_session_focus: 1-2 câu focus buổi sau.\n"
            "- key_insight: insight dài hạn cho coachee 1-2 câu.\n\n"
            "NGUYÊN TẮC:\n"
            "- Tiếng Việt, không em-dash, không emoji.\n"
            "- Action item phải SMART (specific, có verb hành động).\n"
            "- KHÔNG bịa, chỉ dùng nội dung trong transcript.\n"
            "- KHÔNG mention 'team' / 'nhân viên'.\n\n"
            "Gọi tool `submit_post_call_analysis`. KHÔNG output text khác."
        )

    async def _generate_checkin_question(
        self,
        *,
        customer: dict[str, Any],
        last_actions: list[dict[str, Any]],
    ) -> str:
        """Haiku 4.5 sinh 1-2 câu accountability check-in.

        Fallback nếu LLM chưa ready: dùng template generic.
        """
        cust_name = customer.get("full_name") or "?"
        last_actions_str = "(không có)"
        if last_actions:
            ctx_text = last_actions[0].get("context") or ""
            content = (last_actions[0].get("content") or "").replace("\n", " ")[:400]
            last_actions_str = f"context={ctx_text} | {content}"

        if not self.llm.ready:
            return (
                f"Tuần này {cust_name} đã tiến gần hơn mục tiêu chưa? "
                "Action item tuần trước đến đâu rồi?"
            )

        prompt = (
            "Bạn là Coaching Accountability Coach cho Đào Thị Hằng (Hằng). "
            "Sinh 1-2 câu tiếng Việt hỏi coachee về tiến độ action items "
            "tuần trước, giọng ấm áp + cụ thể. KHÔNG em-dash. KHÔNG emoji.\n\n"
            f"Coachee: {cust_name}\n"
            f"Last post-call: {last_actions_str}\n\n"
            "Output 1-2 câu duy nhất, không preamble."
        )
        try:
            resp = await self.llm.client.messages.create(
                model=self.haiku_model,
                max_tokens=DEFAULT_MAX_TOKENS_CHECKIN,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC10 haiku checkin fail: %r", exc)
            return (
                f"Tuần này {cust_name} đã tiến gần hơn mục tiêu chưa? "
                "Action item tuần trước đến đâu rồi?"
            )
        text_parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        text = "".join(text_parts).strip()
        return text or (
            f"Tuần này {cust_name} đã tiến gần hơn mục tiêu chưa? "
            "Action item tuần trước đến đâu rồi?"
        )

    def _extract_tool_input(self, response: Any, tool_name: str) -> dict[str, Any]:
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == tool_name
            ):
                return dict(block.input or {})
        return {"error": f"No {tool_name} tool_use in response"}

    # ============================================================
    # Format helpers
    # ============================================================
    def _format_pre_call_markdown(
        self,
        *,
        customer_360: dict[str, Any],
        brief: dict[str, Any],
        session_type: str,
        session_id: Any,
    ) -> str:
        cust_name = customer_360.get("full_name") or "?"
        lines = [
            f"🎯 *Pre-call brief, {cust_name}*",
            "",
            f"Session: {session_type} (id={session_id})",
            "",
            "*Customer summary:*",
            brief.get("customer_summary") or "(không có)",
            "",
            "*Top wins:*",
        ]
        for i, w in enumerate(brief.get("top_wins") or [], 1):
            lines.append(f"{i}. {w}")
        if not brief.get("top_wins"):
            lines.append("- Không có")

        lines += ["", "*Top challenges:*"]
        for i, c in enumerate(brief.get("top_challenges") or [], 1):
            lines.append(f"{i}. {c}")
        if not brief.get("top_challenges"):
            lines.append("- Không có")

        lines += ["", "*Suggested agenda (60 phút):*"]
        for block in brief.get("suggested_agenda") or []:
            m = block.get("minutes", 0)
            b = block.get("block", "?")
            lines.append(f"- {m}p: {b}")

        lines += ["", "*Câu hỏi Anna nên hỏi:*"]
        for i, q in enumerate(brief.get("questions_for_anna") or [], 1):
            lines.append(f"{i}. {q}")

        watch = brief.get("watch_out") or []
        if watch:
            lines += ["", "*Watch out:*"]
            for w in watch:
                lines.append(f"- {w}")

        return "\n".join(lines)

    def _format_post_call_markdown(
        self,
        *,
        customer_360: dict[str, Any],
        analysis: dict[str, Any],
        session_type: str,
        recording_id: Any,
    ) -> str:
        cust_name = customer_360.get("full_name") or "?"
        lines = [
            f"📝 *Post-call analysis, {cust_name}*",
            "",
            f"Session: {session_type} (recording={recording_id})",
            "",
            "*Anna action items:*",
        ]
        for i, a in enumerate(analysis.get("anna_action_items") or [], 1):
            deadline = a.get("deadline")
            line = f"{i}. {a.get('action', '?')}"
            if deadline:
                line += f" (deadline {deadline})"
            lines.append(line)
        if not analysis.get("anna_action_items"):
            lines.append("- Không có")

        lines += ["", "*Customer action items:*"]
        for i, a in enumerate(analysis.get("customer_action_items") or [], 1):
            deadline = a.get("deadline")
            line = f"{i}. {a.get('action', '?')}"
            if deadline:
                line += f" (deadline {deadline})"
            lines.append(line)

        wins = analysis.get("wins_captured") or []
        if wins:
            lines += ["", "*Wins captured:*"]
            for w in wins:
                lines.append(f"- {w}")

        concerns = analysis.get("concerns_surfaced") or []
        if concerns:
            lines += ["", "*Concerns surfaced:*"]
            for c in concerns:
                lines.append(f"- {c}")

        lines += [
            "",
            f"*Next session focus:* {analysis.get('next_session_focus', '?')}",
        ]
        insight = analysis.get("key_insight")
        if insight:
            lines += ["", f"*Key insight:* {insight}"]

        return "\n".join(lines)

    def _format_checkin_email(
        self,
        *,
        customer: dict[str, Any],
        question: str,
        last_actions: list[dict[str, Any]],
    ) -> str:
        cust_name = customer.get("full_name") or "?"
        cust_email = customer.get("primary_email") or "?"
        last_ref = ""
        if last_actions:
            content = (last_actions[0].get("content") or "")[:600]
            last_ref = f"\n\nReference last post-call:\n{content}"

        return (
            f"Hằng ơi, gửi accountability check-in tuần này cho {cust_name} "
            f"(email {cust_email}).\n\n"
            f"Câu Hằng có thể forward:\n---\n{question}\n---{last_ref}"
        )

    def _summarize_retrieval(self, records: list) -> str:
        if not records:
            return "Không có"
        first = records[0]
        content = (getattr(first, "content", "") or "").replace("\n", " ").strip()
        if len(content) > 120:
            content = content[:117] + "..."
        return f"[{first.agent_name}] {content}"

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None


# ============================================================
# Telegram (reuse pattern BC1/BC3)
# ============================================================
async def send_telegram(text: str) -> bool:
    """Gửi message tới Telegram group Breakout Ops.

    Env vars:
        TELEGRAM_BOT_TOKEN
        TELEGRAM_OPS_GROUP_ID (default -1003813280155)
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_OPS_GROUP_ID", DEFAULT_TELEGRAM_GROUP_ID)
    if not token:
        log.warning("BC10 TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "BC10 Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200


# ============================================================
# Email helper (cho weekly check-in tới Anna primary inbox)
# ============================================================
async def send_email_to_anna(*, subject: str, body: str) -> bool:
    """Gửi email check-in tới Anna's primary inbox hang.dao.bbb@gmail.com.

    Env vars cần (Resend hoặc SMTP wrapper). Fail-soft nếu thiếu config.
    Hiện reuse RESEND_API_KEY pattern; nếu chưa wire trả False + log warning.
    """
    resend_key = os.getenv("RESEND_API_KEY")
    from_addr = os.getenv("EMAIL_FROM", "Đào Thị Hằng <hang@daothihang.com>")
    to_addr = os.getenv("ALERT_EMAIL", ANNA_PRIMARY_INBOX)
    if not resend_key:
        log.warning("BC10 RESEND_API_KEY chưa set, skip email check-in")
        return False
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {resend_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "from": from_addr,
        "to": [to_addr],
        "subject": subject,
        "text": body,
    }
    async with httpx.AsyncClient(timeout=DEFAULT_TELEGRAM_TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 300:
            log.warning(
                "BC10 Resend non-2xx: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code < 300
