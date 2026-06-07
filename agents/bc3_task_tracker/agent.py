"""BC3 Task Tracker agent (Cerebrum NAACL 2025 pattern, role Task).

Mục tiêu: maintain Customer Task state WHAT we're doing right now. Medium-term
mutable action items, current focus, next session focus. Update per-event:
sau coaching call, sau payment, sau feedback submit.

Split khỏi monolith bc3_feedback_loop để tách concern:
- bc3_profile_extractor: WHO (Profile, weekly, Opus 4.7 quality > cost).
- bc3_task_tracker: WHAT đang làm (Task, per-event, Haiku 4.5 cost-sensitive).
- bc10_coaching_delivery / pban customer-facing chỉ READ cả 2.

Cerebrum paper validate 40-60% accuracy improvement so với monolith single
agent re-analyze customer history every interaction.

Three trigger events:

1. `task.update_post_call` (sau coaching call, Fathom transcript)
   - ctx.payload.customer_id + transcript + session_id + session_type
   - Update Task: action items Anna + customer, current focus, next session
     focus.

2. `task.update_post_payment` (sau high-value payment Sepay)
   - ctx.payload.customer_id + tier purchased + amount_vnd
   - Update Task: tier mới mua, onboarding focus, watch_out (vd 'refund risk
     14 ngày').

3. `task.update_generic` (mọi feedback event)
   - ctx.payload.customer_id + feedback_id (hoặc raw text)
   - Update Task dựa trên latest customer_feedback record.

Architectural decision LRU cap 3:
    Mỗi customer giữ tối đa 3 Task records (latest 3 events). Trước khi
    insert mới, đếm count category=task cho customer_id; nếu >= 3 thì delete
    oldest. Lý do: Task là current state, không cần history dài, customer
    journey 6 tháng 24 events sẽ làm noisy retrieval. Profile chứa long-term,
    Task chỉ chứa 3 mốc gần nhất.

Style: tiếng Việt cho prompt + content_summary + docstring. ZERO em-dash.
Type hints + async/await xuyên suốt.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Optional

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer, MemoryRecord

log = logging.getLogger("camas.bc3_task_tracker")

DEFAULT_HAIKU_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS_TASK = 1500
DEFAULT_LLM_TIMEOUT = 120.0

TASK_LRU_CAP = 3
SESSION_TYPES_VALID = {
    "kickoff",
    "weekly",
    "biweekly",
    "midpoint",
    "final",
    "onboarding",
    "milestone",
    "post_payment",
    "generic",
}


# ============================================================
# Tool schema Claude Haiku 4.5 submit Task state
# ============================================================
SUBMIT_TASK_TOOL = {
    "name": "submit_task_state",
    "description": (
        "Submit current Task state WHAT customer + Anna đang làm right now. "
        "Output JSON qua tool này, KHÔNG free text."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "ID phiên trigger event này (Fathom recording, Sepay txn, feedback_id...)",
            },
            "session_type": {
                "type": "string",
                "description": "Loại event, vd post_call, post_payment, onboarding, milestone, generic",
            },
            "current_focus": {
                "type": "string",
                "description": "1-2 câu mô tả customer + Anna đang focus gì tuần này",
            },
            "open_action_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "actor": {
                            "type": "string",
                            "enum": ["customer", "anna"],
                        },
                        "action": {"type": "string"},
                        "deadline": {"type": "string"},
                    },
                    "required": ["actor", "action"],
                },
                "description": "Action items chưa done, gồm actor + action + deadline (nếu có)",
            },
            "watch_out": {
                "type": "array",
                "items": {"type": "string"},
                "description": "0-3 cảnh báo Anna nên để ý (refund risk, conflict, churn signal)",
            },
            "completed_action_items": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Action items vừa được hoàn thành trong event này",
            },
        },
        "required": ["current_focus", "open_action_items"],
    },
}


class BC3TaskTracker(BaseBC):
    """BC3 Task Tracker agent (Cerebrum Task role).

    Autonomy: L1_AUTO. Task state là background memory layer, customer-facing
    agent (BC10, pban) đọc để guide conversation, không publish content trực
    tiếp.
    """

    name = "bc3_task_tracker"
    scope = (
        "Maintain customer Task state (WHAT we're doing right now): "
        "per-session/event update, category=task"
    )
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        haiku_model: str = DEFAULT_HAIKU_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.haiku_model = haiku_model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""

        if event == "task.update_post_call":
            return await self._handle_post_call(ctx)
        if event == "task.update_post_payment":
            return await self._handle_post_payment(ctx)
        if event == "task.update_generic":
            return await self._handle_generic(ctx)

        return AgentResult(
            success=False,
            output_text="BC3-Task không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "task.update_post_call",
                    "task.update_post_payment",
                    "task.update_generic",
                ],
            },
        )

    # ============================================================
    # Event 1: task.update_post_call
    # ============================================================
    async def _handle_post_call(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        customer_id = self._coerce_int(payload.get("customer_id"))
        if customer_id is None:
            return AgentResult(
                success=False,
                output_text="task.update_post_call thiếu customer_id",
                output_payload={"payload": payload},
            )

        transcript = (payload.get("transcript") or "").strip()
        if not transcript:
            return AgentResult(
                success=False,
                output_text="task.update_post_call thiếu transcript",
                output_payload={"customer_id": customer_id},
            )

        session_context = {
            "session_id": str(payload.get("session_id") or ""),
            "session_type": (
                payload.get("session_type") or "post_call"
            ).lower().strip(),
            "raw_text": transcript[:6000],
            "context_label": "Coaching call transcript",
        }
        return await self._update_task(customer_id, session_context)

    # ============================================================
    # Event 2: task.update_post_payment
    # ============================================================
    async def _handle_post_payment(
        self, ctx: ExecutionContext
    ) -> AgentResult:
        payload = ctx.payload or {}
        customer_id = self._coerce_int(payload.get("customer_id"))
        if customer_id is None:
            return AgentResult(
                success=False,
                output_text="task.update_post_payment thiếu customer_id",
                output_payload={"payload": payload},
            )

        tier = payload.get("tier") or "unknown"
        amount_vnd = self._coerce_int(payload.get("amount_vnd")) or 0
        txn_id = payload.get("txn_id") or payload.get("transaction_id") or ""

        raw_text = (
            f"Khách vừa thanh toán tier {tier} với amount {amount_vnd:,} VND "
            f"(txn={txn_id}). Cần lập Task onboarding mới, focus 14 ngày đầu "
            "để giảm refund risk + đảm bảo activation. Action items Anna nên "
            "gồm: gửi welcome email, schedule kickoff call, share access "
            "link. Action items customer gồm: confirm receipt, complete "
            "onboarding form, attend kickoff."
        )

        session_context = {
            "session_id": str(txn_id),
            "session_type": "post_payment",
            "raw_text": raw_text,
            "context_label": (
                f"Sepay payment tier={tier} amount={amount_vnd:,}"
            ),
        }
        return await self._update_task(customer_id, session_context)

    # ============================================================
    # Event 3: task.update_generic
    # ============================================================
    async def _handle_generic(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        customer_id = self._coerce_int(payload.get("customer_id"))
        if customer_id is None:
            return AgentResult(
                success=False,
                output_text="task.update_generic thiếu customer_id",
                output_payload={"payload": payload},
            )

        feedback_id = self._coerce_int(payload.get("feedback_id"))
        raw_text = payload.get("raw_text") or ""

        # Nếu có feedback_id, fetch row làm context. Nếu không có, dùng raw_text.
        if feedback_id is not None:
            feedback = await self._fetch_feedback_by_id(feedback_id)
            if feedback is None:
                return AgentResult(
                    success=False,
                    output_text=f"feedback_id={feedback_id} không tồn tại",
                    output_payload={
                        "customer_id": customer_id,
                        "feedback_id": feedback_id,
                    },
                )
            raw_text = (
                f"[{feedback.get('feedback_type', '?')}] "
                f"{feedback.get('content_summary') or feedback.get('content_raw', '')}"
            )
            context_label = (
                f"Feedback id={feedback_id} "
                f"source={feedback.get('source', '?')}"
            )
        else:
            if not raw_text.strip():
                return AgentResult(
                    success=False,
                    output_text=(
                        "task.update_generic thiếu cả feedback_id và raw_text"
                    ),
                    output_payload={"customer_id": customer_id},
                )
            context_label = "Generic feedback event"

        session_context = {
            "session_id": str(feedback_id or ""),
            "session_type": "generic",
            "raw_text": raw_text[:6000],
            "context_label": context_label,
        }
        return await self._update_task(customer_id, session_context)

    # ============================================================
    # Core: build + store Task state cho 1 customer
    # ============================================================
    async def _update_task(
        self,
        customer_id: int,
        session_context: dict[str, Any],
    ) -> AgentResult:
        # Verify customer exists
        customer = await self._fetch_customer_basic(customer_id)
        if customer is None:
            return AgentResult(
                success=False,
                output_text=f"customer_id={customer_id} không tồn tại",
                output_payload={"customer_id": customer_id},
            )

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM client chưa init",
                output_payload={"error": "ANTHROPIC_API_KEY chưa set"},
                escalation_required=True,
                escalation_reason="llm_not_ready",
            )

        try:
            task_state = await self._build_and_store_task(
                customer_id=customer_id,
                customer=customer,
                session_context=session_context,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "BC3-Task build customer=%s fail: %r", customer_id, exc
            )
            return AgentResult(
                success=False,
                output_text=f"Build task fail: {exc}",
                output_payload={
                    "customer_id": customer_id,
                    "error": str(exc),
                },
                escalation_required=True,
                escalation_reason="build_task_fail",
            )

        if not task_state or task_state.get("error"):
            return AgentResult(
                success=False,
                output_text=(
                    task_state.get("error", "Build task fail")
                    if task_state
                    else "Build task fail"
                ),
                output_payload={
                    "customer_id": customer_id,
                    "task_state": task_state,
                },
                escalation_required=True,
                escalation_reason="build_task_fail",
            )

        return AgentResult(
            success=True,
            output_text=(
                f"Task state updated customer_id={customer_id} "
                f"session_type={session_context.get('session_type')} "
                f"open_actions={len(task_state.get('open_action_items') or [])}"
            ),
            output_payload={
                "customer_id": customer_id,
                "task_state": task_state,
                "session_type": session_context.get("session_type"),
            },
        )

    async def _build_and_store_task(
        self,
        *,
        customer_id: int,
        customer: dict[str, Any],
        session_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Build Task state qua Haiku 4.5 + UPSERT (LRU cap 3) vào agent_memory.

        Return dict task_state (error key nếu fail).
        """
        # Fetch existing Task records để Haiku có continuity
        existing_tasks = await self._fetch_existing_tasks(customer_id)

        prompt = self._build_task_prompt(
            customer=customer,
            existing_tasks=existing_tasks,
            session_context=session_context,
        )

        try:
            response = await self.llm.client.messages.create(
                model=self.haiku_model,
                max_tokens=DEFAULT_MAX_TOKENS_TASK,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_TASK_TOOL],
                tool_choice={"type": "tool", "name": "submit_task_state"},
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "BC3-Task haiku call customer=%s fail: %r", customer_id, exc
            )
            return {"error": f"LLM call fail: {exc}"}

        task_state = self._extract_tool_input(response, "submit_task_state")
        if task_state.get("error"):
            return task_state

        # Đảm bảo session_id + session_type fallback từ context nếu Haiku skip
        if not task_state.get("session_id"):
            task_state["session_id"] = session_context.get("session_id", "")
        if not task_state.get("session_type"):
            task_state["session_type"] = session_context.get(
                "session_type", "generic"
            )

        # LRU cap: nếu >= 3 record, delete oldest
        try:
            await self._enforce_lru_cap(customer_id, cap=TASK_LRU_CAP)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "BC3-Task LRU enforce customer=%s fail: %r",
                customer_id,
                exc,
            )

        # Insert task record (KHÔNG dùng UUID5 vì cần multiple Task records
        # per customer, để gen_random_uuid trong store).
        current_focus = (task_state.get("current_focus") or "").strip()[:120]
        session_type = task_state.get("session_type", "generic")

        record = MemoryRecord(
            agent_name=self.name,
            content=json.dumps(task_state, ensure_ascii=False),
            keywords=self._build_keywords(task_state),
            tags=["task", session_type],
            category="task",
            customer_id=customer_id,
            venture=self._infer_venture(customer),
            context=(
                f"task customer_id={customer_id} "
                f"session_type={session_type} "
                f"updated={date.today().isoformat()}"
            ),
        )

        try:
            await self.memory.store(record)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "BC3-Task store memory customer=%s fail: %r",
                customer_id,
                exc,
            )
            return {"error": f"Store memory fail: {exc}"}

        return task_state

    # ============================================================
    # DB helpers
    # ============================================================
    async def _fetch_customer_basic(
        self, customer_id: int
    ) -> Optional[dict[str, Any]]:
        if not self.memory.dsn:
            raise RuntimeError("DATABASE_URL chưa set")
        pool = await self.memory._get_pool()  # noqa: SLF001
        sql = """
            SELECT c.id, c.full_name, c.primary_email,
                   c360.ltv_vnd, c360.current_stage,
                   c360.ventures_active, c360.notes
            FROM public.customers c
            LEFT JOIN public.customer_360 c360 ON c360.customer_id = c.id
            WHERE c.id = $1
            LIMIT 1
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, customer_id)
        return dict(row) if row else None

    async def _fetch_existing_tasks(
        self, customer_id: int
    ) -> list[dict[str, Any]]:
        if not self.memory.dsn:
            return []
        pool = await self.memory._get_pool()  # noqa: SLF001
        sql = """
            SELECT content, tags, context, created_at
            FROM public.agent_memory
            WHERE customer_id = $1
              AND category = 'task'
              AND agent_name = $2
            ORDER BY created_at DESC
            LIMIT 5
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, customer_id, self.name)
        return [dict(r) for r in rows]

    async def _fetch_feedback_by_id(
        self, feedback_id: int
    ) -> Optional[dict[str, Any]]:
        if not self.memory.dsn:
            return None
        pool = await self.memory._get_pool()  # noqa: SLF001
        sql = """
            SELECT id, customer_id, source, feedback_type, content_summary,
                   content_raw, sentiment, theme_tags, created_at
            FROM public.customer_feedback
            WHERE id = $1
            LIMIT 1
        """
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, feedback_id)
        return dict(row) if row else None

    async def _enforce_lru_cap(self, customer_id: int, *, cap: int) -> None:
        """Nếu count Task records cho customer >= cap, delete oldest cho đủ
        cap - 1 (chừa slot mới sắp insert).
        """
        if not self.memory.dsn:
            return
        pool = await self.memory._get_pool()  # noqa: SLF001
        async with pool.acquire() as conn:
            count_row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS n
                FROM public.agent_memory
                WHERE customer_id = $1
                  AND category = 'task'
                  AND agent_name = $2
                """,
                customer_id,
                self.name,
            )
            n = int(count_row["n"]) if count_row else 0
            if n < cap:
                return
            to_delete = n - (cap - 1)
            if to_delete <= 0:
                return
            await conn.execute(
                """
                DELETE FROM public.agent_memory
                WHERE memory_id IN (
                    SELECT memory_id
                    FROM public.agent_memory
                    WHERE customer_id = $1
                      AND category = 'task'
                      AND agent_name = $2
                    ORDER BY created_at ASC
                    LIMIT $3
                )
                """,
                customer_id,
                self.name,
                to_delete,
            )

    # ============================================================
    # LLM helpers
    # ============================================================
    def _build_task_prompt(
        self,
        *,
        customer: dict[str, Any],
        existing_tasks: list[dict[str, Any]],
        session_context: dict[str, Any],
    ) -> str:
        cust_name = customer.get("full_name") or "?"
        cust_id = customer.get("id")
        stage = customer.get("current_stage") or "?"
        ventures = customer.get("ventures_active") or []

        existing_lines: list[str] = []
        for t in existing_tasks[:3]:
            ts = t.get("created_at")
            ts_str = ts.isoformat()[:10] if hasattr(ts, "isoformat") else "?"
            tags = ",".join((t.get("tags") or [])[:3])
            content = (t.get("content") or "").replace("\n", " ")[:300]
            existing_lines.append(f"- [{ts_str} tags={tags}] {content}")
        existing_block = (
            "\n".join(existing_lines) if existing_lines else "(không có)"
        )

        session_id = session_context.get("session_id", "")
        session_type = session_context.get("session_type", "generic")
        raw_text = session_context.get("raw_text", "")
        context_label = session_context.get("context_label", "")

        return (
            "Bạn là Customer Task Tracker cho Đào Thị Hằng (Hằng/Anna). "
            "Nhiệm vụ: cập nhật Task state (WHAT customer + Anna đang làm "
            "right now) dựa trên event mới nhất + 3 Task gần nhất. Task "
            "khác Profile, Task là medium-term mutable (1-4 tuần), Profile "
            "là long-term identity.\n\n"
            "Cerebrum pattern: Task agent maintain action items, Profile "
            "agent maintain identity. Bạn chỉ làm Task, KHÔNG xen vào "
            "Profile.\n\n"
            f"CUSTOMER: {cust_name} (id={cust_id})\n"
            f"Current stage (DB): {stage}\n"
            f"Ventures active: {', '.join(ventures) if ventures else '?'}\n\n"
            f"EVENT MỚI:\n"
            f"- session_id: {session_id}\n"
            f"- session_type: {session_type}\n"
            f"- context: {context_label}\n"
            f"- nội dung:\n---\n{raw_text}\n---\n\n"
            f"3 TASK STATE GẦN NHẤT (carry forward chưa done):\n"
            f"{existing_block}\n\n"
            "NGUYÊN TẮC:\n"
            "- Tiếng Việt thuần, không em-dash, không emoji.\n"
            "- current_focus: 1-2 câu cô đọng customer + Anna đang focus gì.\n"
            "- open_action_items: gồm cả action mới phát sinh trong event + "
            "action cũ còn open. Mỗi item gắn actor (customer/anna) + action "
            "(động từ rõ ràng) + deadline (nếu có nhắc).\n"
            "- completed_action_items: list action items vừa done trong "
            "event này (text ngắn).\n"
            "- watch_out: 0-3 cảnh báo (refund risk, churn signal, conflict).\n"
            "- KHÔNG bịa, chỉ dùng nội dung trong event + Task cũ.\n"
            "- KHÔNG mention 'team' / 'nhân viên' (Hằng solo).\n"
            "- session_id + session_type giữ nguyên từ event context.\n\n"
            "Gọi tool `submit_task_state`. KHÔNG output text khác."
        )

    def _extract_tool_input(
        self, response: Any, tool_name: str
    ) -> dict[str, Any]:
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == tool_name
            ):
                return dict(block.input or {})
        return {"error": f"No {tool_name} tool_use in response"}

    # ============================================================
    # Misc helpers
    # ============================================================
    def _build_keywords(self, task_state: dict[str, Any]) -> list[str]:
        kws: list[str] = ["task"]
        session_type = task_state.get("session_type")
        if session_type:
            kws.append(str(session_type))
        for item in (task_state.get("open_action_items") or [])[:3]:
            actor = item.get("actor") if isinstance(item, dict) else None
            if actor:
                kws.append(f"actor_{actor}")
        # Dedup giữ order
        seen: set[str] = set()
        deduped: list[str] = []
        for k in kws:
            if k not in seen:
                seen.add(k)
                deduped.append(k)
        return deduped

    @staticmethod
    def _infer_venture(customer: dict[str, Any]) -> str:
        """Pick venture chính từ ventures_active, default breakout."""
        ventures = customer.get("ventures_active") or []
        for v in ventures:
            if not v:
                continue
            v_lower = str(v).lower()
            for known in (
                "breakout",
                "speakout",
                "cohangai",
                "bmcorner",
                "dahafa",
            ):
                if known in v_lower:
                    return known
        return "breakout"

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
