"""BC3 Profile Extractor agent (Cerebrum NAACL 2025 pattern, role Profile).

Mục tiêu: maintain Customer Profile WHO they are. Slow-changing identity
(personality, current phase, biggest obstacle, win pattern, communication
preference, venture focus, stage, ltv estimate, risk flags). Run weekly Sunday
6am Perth cron + on-demand khi customer high-value action (vd Sepay payment).

Split khỏi monolith bc3_feedback_loop để tách concern:
- bc3_profile_extractor: WHO (Profile, weekly, Opus 4.7 quality > cost).
- bc3_task_tracker: WHAT đang làm (Task, per-event, Haiku 4.5 cost-sensitive).
- bc10_coaching_delivery / pban customer-facing chỉ READ cả 2.

Cerebrum paper validate 40-60% accuracy improvement so với monolith single
agent re-analyze customer history every interaction.

Two trigger events:

1. `profile.refresh_weekly` (Sunday 6am Perth cron, cron-job.org hookup sau)
   - Fetch active customers 30d (có ít nhất 1 customer_feedback hoặc 1
     coaching memory).
   - Cap 100 customers/run, mỗi customer build Profile riêng.
   - Output: count profile_updated.

2. `profile.refresh_single` (per-customer on-demand)
   - ctx.payload.customer_id (int) → build Profile cho 1 customer ngay.
   - Dùng sau Sepay payment success hoặc khi Anna explicit trigger.

Architectural decision idempotency:
    agent_memory schema không có UNIQUE (customer_id, category=profile).
    Để 1 Profile / customer luôn UPSERT (KHÔNG append duplicate), dùng UUID5
    deterministic theo namespace + `profile_{customer_id}`. ON CONFLICT
    (memory_id) DO UPDATE trong MemoryLayer.store() sẽ tự thay vì append.

Style: tiếng Việt cho prompt + content_summary + docstring. ZERO em-dash.
Type hints + async/await xuyên suốt.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid5

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer, MemoryRecord

log = logging.getLogger("camas.bc3_profile_extractor")

DEFAULT_OPUS_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS_PROFILE = 1500
DEFAULT_LLM_TIMEOUT = 120.0

# Namespace UUID cố định để UUID5 deterministic per customer
# Bất kỳ UUID v4 cố định nào dùng làm namespace cũng OK, không cần secret.
PROFILE_NAMESPACE = UUID("12345678-1234-5678-1234-567812345678")

WEEKLY_CAP = 100
ACTIVE_WINDOW_DAYS = 30
FEEDBACK_FETCH_LIMIT = 20
MEMORY_FETCH_LIMIT = 15

VALID_VENTURES = {
    "breakout",
    "speakout",
    "cohangai",
    "bmcorner",
    "dahafa",
    "personal",
}


# ============================================================
# Tool schema Claude Opus 4.7 submit Profile
# ============================================================
SUBMIT_PROFILE_TOOL = {
    "name": "submit_profile",
    "description": (
        "Submit structured Customer Profile (WHO they are), slow-changing "
        "long-term identity. Output JSON qua tool này, KHÔNG free text."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "personality": {
                "type": "string",
                "description": "1-2 câu mô tả tính cách, vd 'cầu toàn nội tâm, sợ rủi ro tài chính'",
            },
            "current_phase": {
                "type": "string",
                "description": "Giai đoạn cuộc sống/kinh doanh hiện tại, vd 'đang ôm Shopee, muốn build store riêng nhưng chưa start'",
            },
            "biggest_obstacle": {
                "type": "string",
                "description": "Rào cản lớn nhất khách đang gặp, 1 câu cụ thể",
            },
            "win_pattern": {
                "type": "string",
                "description": "Pattern khách thắng trong quá khứ, vd 'bứt phá khi có deadline + bạn đồng hành'",
            },
            "communication_preference": {
                "type": "string",
                "description": "Cách khách thích giao tiếp, vd 'text dài, ít gọi điện, phản hồi đêm 9-11pm'",
            },
            "venture_focus": {
                "type": "string",
                "enum": list(VALID_VENTURES),
                "description": "Venture chính khách đang focus",
            },
            "stage": {
                "type": "string",
                "description": "Stage trong customer journey, vd 'foundation', 'customer', 'growth', 'coaching', 'lead'",
            },
            "ltv_estimate_vnd": {
                "type": "integer",
                "description": "LTV ước tính theo VND",
            },
            "risk_flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "0-5 risk flag, vd ['churn_risk', 'refund_request', 'low_engagement']",
            },
        },
        "required": [
            "personality",
            "current_phase",
            "biggest_obstacle",
            "communication_preference",
        ],
    },
}


class BC3ProfileExtractor(BaseBC):
    """BC3 Profile Extractor agent (Cerebrum Profile role).

    Autonomy: L1_AUTO. Profile là background memory layer, không publish
    content, không cần Anna approve từng record. Sai bias nhẹ qua tuần sau
    sẽ tự correct vì weekly refresh.
    """

    name = "bc3_profile_extractor"
    scope = (
        "Maintain customer Profile (WHO they are): scan past 30d feedback + "
        "events → structured profile JSON, write category=profile"
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
        opus_model: str = DEFAULT_OPUS_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.opus_model = opus_model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""

        if event == "profile.refresh_weekly":
            return await self._handle_refresh_weekly(ctx)
        if event == "profile.refresh_single":
            return await self._handle_refresh_single(ctx)

        return AgentResult(
            success=False,
            output_text="BC3-Profile không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "profile.refresh_weekly",
                    "profile.refresh_single",
                ],
            },
        )

    # ============================================================
    # Event 1: profile.refresh_weekly
    # ============================================================
    async def _handle_refresh_weekly(
        self, ctx: ExecutionContext
    ) -> AgentResult:
        try:
            customers = await self._fetch_active_customers(
                days=ACTIVE_WINDOW_DAYS
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC3-Profile fetch active customers fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"Query active customers fail: {exc}",
                output_payload={"error": str(exc)},
                escalation_required=True,
                escalation_reason="db_query_fail",
            )

        if not customers:
            return AgentResult(
                success=True,
                output_text="Không có customer active trong 30 ngày",
                output_payload={
                    "profiles_updated": 0,
                    "active_window_days": ACTIVE_WINDOW_DAYS,
                },
            )

        capped = customers[:WEEKLY_CAP]
        profiles_updated = 0
        failed: list[dict[str, Any]] = []

        for cust in capped:
            cid = cust["id"]
            try:
                profile = await self._build_and_store_profile(cid)
                if profile and not profile.get("error"):
                    profiles_updated += 1
                else:
                    failed.append(
                        {
                            "customer_id": cid,
                            "error": profile.get("error", "unknown")
                            if profile
                            else "none",
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "BC3-Profile build customer=%s fail: %r", cid, exc
                )
                failed.append({"customer_id": cid, "error": str(exc)})

        return AgentResult(
            success=True,
            output_text=(
                f"Weekly profile refresh: {profiles_updated} updated "
                f"(cap {WEEKLY_CAP}, candidates {len(customers)}, "
                f"failed {len(failed)})"
            ),
            output_payload={
                "profiles_updated": profiles_updated,
                "candidates": len(customers),
                "capped_at": WEEKLY_CAP,
                "failed_count": len(failed),
                "failed_sample": failed[:5],
            },
        )

    # ============================================================
    # Event 2: profile.refresh_single
    # ============================================================
    async def _handle_refresh_single(
        self, ctx: ExecutionContext
    ) -> AgentResult:
        customer_id = self._coerce_int(ctx.payload.get("customer_id"))
        if customer_id is None:
            return AgentResult(
                success=False,
                output_text="profile.refresh_single thiếu customer_id (int)",
                output_payload={"payload": ctx.payload},
            )

        try:
            profile = await self._build_and_store_profile(customer_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "BC3-Profile single build customer=%s fail: %r",
                customer_id,
                exc,
            )
            return AgentResult(
                success=False,
                output_text=f"Build profile fail: {exc}",
                output_payload={
                    "customer_id": customer_id,
                    "error": str(exc),
                },
                escalation_required=True,
                escalation_reason="build_profile_fail",
            )

        if not profile or profile.get("error"):
            return AgentResult(
                success=False,
                output_text=(
                    profile.get("error", "Build profile fail")
                    if profile
                    else "Build profile fail"
                ),
                output_payload={
                    "customer_id": customer_id,
                    "profile": profile,
                },
                escalation_required=True,
                escalation_reason="build_profile_fail",
            )

        return AgentResult(
            success=True,
            output_text=f"Profile refreshed customer_id={customer_id}",
            output_payload={
                "customer_id": customer_id,
                "profile": profile,
            },
        )

    # ============================================================
    # Core: build + store Profile cho 1 customer
    # ============================================================
    async def _build_and_store_profile(
        self, customer_id: int
    ) -> dict[str, Any]:
        """Build structured Profile cho 1 customer + UPSERT vào agent_memory.

        Return dict profile (đã có error key nếu fail).
        """
        # 1. Gather context từ DB
        customer = await self._fetch_customer_basic(customer_id)
        if customer is None:
            return {"error": f"customer_id={customer_id} không tồn tại"}

        feedback_rows = await self._fetch_customer_feedback(customer_id)
        past_memories = await self._fetch_customer_memories(customer_id)

        if not self.llm.ready:
            return {"error": "LLM client chưa init"}

        # 2. Build prompt + call Opus 4.7
        prompt = self._build_profile_prompt(
            customer=customer,
            feedback_rows=feedback_rows,
            past_memories=past_memories,
        )

        try:
            response = await self.llm.client.messages.create(
                model=self.opus_model,
                max_tokens=DEFAULT_MAX_TOKENS_PROFILE,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_PROFILE_TOOL],
                tool_choice={"type": "tool", "name": "submit_profile"},
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "BC3-Profile opus call customer=%s fail: %r",
                customer_id,
                exc,
            )
            return {"error": f"LLM call fail: {exc}"}

        profile = self._extract_tool_input(response, "submit_profile")
        if profile.get("error"):
            return profile

        # Sanitize venture_focus
        venture_focus = (profile.get("venture_focus") or "").strip().lower()
        if venture_focus not in VALID_VENTURES:
            venture_focus = "breakout"
            profile["venture_focus"] = venture_focus

        # 3. UPSERT vào agent_memory với UUID5 deterministic
        memory_id = uuid5(PROFILE_NAMESPACE, f"profile_{customer_id}")
        personality = (profile.get("personality") or "").strip()
        risk_flags = profile.get("risk_flags") or []
        stage = (profile.get("stage") or "").strip()

        record = MemoryRecord(
            memory_id=memory_id,
            agent_name=self.name,
            content=json.dumps(profile, ensure_ascii=False),
            keywords=self._build_keywords(
                venture_focus=venture_focus,
                stage=stage,
                risk_flags=risk_flags,
            ),
            tags=["profile", "weekly_refresh", venture_focus],
            category="profile",
            customer_id=customer_id,
            venture=venture_focus,
            context=(
                f"profile customer_id={customer_id} "
                f"updated={date.today().isoformat()}"
            ),
        )

        try:
            await self.memory.store(record)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "BC3-Profile store memory customer=%s fail: %r",
                customer_id,
                exc,
            )
            return {"error": f"Store memory fail: {exc}"}

        return profile

    # ============================================================
    # DB helpers
    # ============================================================
    async def _fetch_active_customers(
        self, *, days: int
    ) -> list[dict[str, Any]]:
        """Active = có ít nhất 1 customer_feedback hoặc 1 agent_memory trong
        N ngày qua.
        """
        if not self.memory.dsn:
            raise RuntimeError("DATABASE_URL chưa set")
        pool = await self.memory._get_pool()  # noqa: SLF001
        sql = """
            SELECT DISTINCT c.id, c.full_name, c.primary_email
            FROM public.customers c
            WHERE EXISTS (
                SELECT 1 FROM public.customer_feedback cf
                WHERE cf.customer_id = c.id
                  AND cf.created_at > now() - ($1::int * interval '1 day')
            ) OR EXISTS (
                SELECT 1 FROM public.agent_memory am
                WHERE am.customer_id = c.id
                  AND am.created_at > now() - ($1::int * interval '1 day')
            )
            ORDER BY c.id
            LIMIT 500
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, days)
        return [dict(r) for r in rows]

    async def _fetch_customer_basic(
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
        return dict(row) if row else None

    async def _fetch_customer_feedback(
        self, customer_id: int
    ) -> list[dict[str, Any]]:
        if not self.memory.dsn:
            return []
        pool = await self.memory._get_pool()  # noqa: SLF001
        sql = """
            SELECT feedback_type, content_summary, sentiment, theme_tags,
                   source, created_at
            FROM public.customer_feedback
            WHERE customer_id = $1
              AND created_at > now() - ($2::int * interval '1 day')
            ORDER BY created_at DESC
            LIMIT $3
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                sql, customer_id, ACTIVE_WINDOW_DAYS, FEEDBACK_FETCH_LIMIT
            )
        return [dict(r) for r in rows]

    async def _fetch_customer_memories(
        self, customer_id: int
    ) -> list[dict[str, Any]]:
        """Lấy past agent_memory category profile + conversation trong 30d.

        Profile cũ + conversation memory feed context giúp Opus continuity.
        """
        if not self.memory.dsn:
            return []
        pool = await self.memory._get_pool()  # noqa: SLF001
        sql = """
            SELECT content, category, tags, context, created_at
            FROM public.agent_memory
            WHERE customer_id = $1
              AND category IN ('profile', 'conversation')
              AND created_at > now() - ($2::int * interval '1 day')
            ORDER BY created_at DESC
            LIMIT $3
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                sql, customer_id, ACTIVE_WINDOW_DAYS, MEMORY_FETCH_LIMIT
            )
        return [dict(r) for r in rows]

    # ============================================================
    # LLM helpers
    # ============================================================
    def _build_profile_prompt(
        self,
        *,
        customer: dict[str, Any],
        feedback_rows: list[dict[str, Any]],
        past_memories: list[dict[str, Any]],
    ) -> str:
        cust_name = customer.get("full_name") or "?"
        cust_id = customer.get("id")
        stage = customer.get("current_stage") or "?"
        ltv = customer.get("ltv_vnd") or 0
        ventures = customer.get("ventures_active") or []
        notes = (customer.get("notes") or "")[-2000:]

        feedback_lines: list[str] = []
        for r in feedback_rows[:FEEDBACK_FETCH_LIMIT]:
            ftype = r.get("feedback_type") or "?"
            sent = r.get("sentiment")
            sent_str = f"{float(sent):+.2f}" if sent is not None else "n/a"
            tags = ",".join((r.get("theme_tags") or [])[:4])
            summary = (r.get("content_summary") or "").replace("\n", " ")[
                :300
            ]
            feedback_lines.append(
                f"- [{ftype} sent={sent_str} tags={tags}] {summary}"
            )
        feedback_block = (
            "\n".join(feedback_lines) if feedback_lines else "(không có)"
        )

        memory_lines: list[str] = []
        for m in past_memories[:MEMORY_FETCH_LIMIT]:
            ts = m.get("created_at")
            ts_str = ts.isoformat()[:10] if hasattr(ts, "isoformat") else "?"
            cat = m.get("category") or "?"
            content = (m.get("content") or "").replace("\n", " ")[:250]
            memory_lines.append(f"- [{ts_str} cat={cat}] {content}")
        memory_block = (
            "\n".join(memory_lines) if memory_lines else "(không có)"
        )

        return (
            "Bạn là Customer Profile Analyst cho Đào Thị Hằng (Hằng/Anna). "
            "Nhiệm vụ: xây dựng structured Profile WHO khách hàng này là, "
            "dựa trên 30 ngày feedback + past memories. Profile chậm thay đổi "
            "(personality, current phase, win pattern), KHÔNG phải task ngắn "
            "hạn.\n\n"
            "Cerebrum pattern: Profile agent maintain identity, Task agent "
            "maintain action items. Bạn chỉ làm Profile, KHÔNG xen vào Task.\n\n"
            f"CUSTOMER: {cust_name} (id={cust_id})\n"
            f"Current stage (DB): {stage}\n"
            f"LTV VND: {ltv:,}\n"
            f"Ventures active: {', '.join(ventures) if ventures else '?'}\n\n"
            f"CUSTOMER 360 NOTES (history append-only):\n---\n"
            f"{notes if notes else '(trống)'}\n---\n\n"
            f"FEEDBACK 30 NGÀY ({len(feedback_rows)} items):\n"
            f"{feedback_block}\n\n"
            f"PAST MEMORIES ({len(past_memories)} items):\n"
            f"{memory_block}\n\n"
            "NGUYÊN TẮC:\n"
            "- Tiếng Việt thuần, không em-dash, không emoji.\n"
            "- personality 1-2 câu cô đọng tính cách, KHÔNG bịa khi không có "
            "evidence (nếu data ít, ghi 'chưa đủ data, theo cảm nhận sơ bộ ...').\n"
            "- current_phase phải concrete (vd 'đang ôm Shopee, muốn build "
            "store riêng nhưng chưa start' chứ KHÔNG 'đang phát triển').\n"
            "- biggest_obstacle: 1 rào cản rõ ràng, KHÔNG list 5 rào cản.\n"
            "- win_pattern: pattern khách thắng quá khứ (nếu chưa có data ghi "
            "'chưa đủ data').\n"
            "- communication_preference: dùng dấu hiệu thật từ feedback "
            "(tone, độ dài, kênh).\n"
            "- venture_focus: 1 trong {breakout, speakout, cohangai, "
            "bmcorner, dahafa, personal}.\n"
            "- stage: lead, foundation, customer, growth, coaching, refund, "
            "churned.\n"
            "- ltv_estimate_vnd: ước tính tổng số tiền khách có thể chi 12 "
            "tháng tới, INT VND.\n"
            "- risk_flags: 0-5 flag, vd ['churn_risk', 'refund_request', "
            "'low_engagement', 'high_potential', 'evangelist'].\n"
            "- KHÔNG mention 'team' / 'nhân viên' (Hằng solo).\n\n"
            "Gọi tool `submit_profile`. KHÔNG output text khác."
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
    def _build_keywords(
        self,
        *,
        venture_focus: str,
        stage: str,
        risk_flags: list[str],
    ) -> list[str]:
        kws: list[str] = []
        if venture_focus:
            kws.append(venture_focus)
        if stage:
            kws.append(stage)
        for flag in (risk_flags or [])[:5]:
            if flag:
                kws.append(flag)
        # Dedup giữ order
        seen: set[str] = set()
        deduped: list[str] = []
        for k in kws:
            if k not in seen:
                seen.add(k)
                deduped.append(k)
        return deduped

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
