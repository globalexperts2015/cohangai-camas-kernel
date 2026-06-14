"""BC3 Feedback Loop agent.

Aggregate Tally onboarding/milestone + Tally refund + Fathom transcript +
community feedback từ `public.customer_feedback` thành Customer Voice Digest
weekly Monday 7am Perth. Reuse logic phân tích Claude opus-4-7 với tool
`submit_digest` (giống `breakout-cdp/customer_voice/main.py`) nhưng adapt vào
CAMAS BaseBC contract.

Three trigger events:

1. `feedback.weekly_digest` (Monday 7am Perth cron)
   - Query `customer_feedback` 7 ngày gần nhất (processed_at IS NOT NULL)
   - Claude opus-4-7 phân tích: 5 pain themes, 5 wins, 3 objections, 3 feature
     requests, sentiment trend, suggestions
   - Output markdown digest tiếng Việt + Telegram Breakout Ops
   - Emit memory records với tags ["research_backlog" | "objection_bank" |
     "case_study"] cho Mac-local cron pick up + write vault files (Architecture
     choice, xem dưới).

2. `feedback.tally.submitted` (Tally webhook forward)
   - Map form_name → feedback_type (onboarding/milestone_30/60/90/refund)
   - Claude Haiku 4.5 summarize + classify + theme_tags + sentiment
   - INSERT vào `customer_feedback` với processed_at = now()

3. `feedback.fathom.transcript` (Fathom webhook forward)
   - Extract 3-5 key quotes + feedback_type + tags + sentiment
   - INSERT vào `customer_feedback` với processed_at = now()

Architectural choice (auto-feed Research Engine):
    Plan brief gốc yêu cầu BC3 append vào `wiki/projects/breakout/*.md`. Tuy
    nhiên BC3 deploy trên Railway, không mount vault Mac. Giải pháp: BC3 emit
    memory records với agent_name="bc3_feedback_loop" + tags trong
    {"research_backlog", "objection_bank", "case_study"}, để 1 cron Mac-local
    riêng pick up qua `agent_memory` query và write vào vault file. Tách concern
    Cloud (analyze) + Local (vault write) clean hơn.

DB:
    Reuse `MemoryLayer._pool` asyncpg pool (CDP và CAMAS chung Postgres
    `breakout-funnel-os-staging`). Fail-soft graceful nếu pool init lỗi.

Style: tiếng Việt cho Telegram + digest + docstring + comment trong file. ZERO
em-dash `,`. Type hints + async/await xuyên suốt.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
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

log = logging.getLogger("camas.bc3_feedback_loop")

DEFAULT_OPUS_MODEL = "claude-haiku-4-5"
DEFAULT_HAIKU_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS_DIGEST = 4000
DEFAULT_MAX_TOKENS_CLASSIFY = 800
DEFAULT_LLM_TIMEOUT = 120.0
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"  # Breakout Ops

FEEDBACK_QUERY_LIMIT = 200
WEEKLY_WINDOW_DAYS = 7

# Map Tally form_name → (feedback_source, default_feedback_type)
TALLY_FORM_MAP: dict[str, tuple[str, Optional[str]]] = {
    "onboarding": ("tally_onboarding", None),
    "milestone_30": ("tally_milestone_30", None),
    "milestone_30d": ("tally_milestone_30", None),
    "milestone_60": ("tally_milestone_60", None),
    "milestone_60d": ("tally_milestone_60", None),
    "milestone_90": ("tally_milestone_90", None),
    "milestone_90d": ("tally_milestone_90", None),
    "refund": ("tally_refund", "objection"),
    "refund_interview": ("tally_refund", "objection"),
}


# ============================================================
# Tool schema cho Claude opus-4-7 phân tích weekly digest
# ============================================================
SUBMIT_DIGEST_TOOL = {
    "name": "submit_digest",
    "description": (
        "Submit customer voice digest weekly với pain themes, wins, "
        "objections, feature requests, sentiment trend + actionable suggestions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pain_themes": {
                "type": "array",
                "minItems": 0,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "theme": {"type": "string"},
                        "frequency": {"type": "integer"},
                        "quote": {"type": "string"},
                    },
                    "required": ["theme", "frequency", "quote"],
                },
            },
            "wins": {
                "type": "array",
                "minItems": 0,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "win": {"type": "string"},
                        "customer_signal": {"type": "string"},
                        "case_study_potential": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                    },
                    "required": ["win", "customer_signal", "case_study_potential"],
                },
            },
            "objections": {
                "type": "array",
                "minItems": 0,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "objection": {"type": "string"},
                        "frequency": {"type": "integer"},
                        "quote": {"type": "string"},
                    },
                    "required": ["objection", "frequency", "quote"],
                },
            },
            "feature_requests": {
                "type": "array",
                "minItems": 0,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "request": {"type": "string"},
                        "frequency": {"type": "integer"},
                    },
                    "required": ["request", "frequency"],
                },
            },
            "sentiment_trend": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "stable"],
                    },
                    "avg_current": {"type": "number"},
                    "avg_prior": {"type": "number"},
                    "summary": {"type": "string"},
                },
                "required": ["direction", "summary"],
            },
            "suggestions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {"type": "string"},
            },
            "notes": {"type": "string"},
        },
        "required": [
            "pain_themes",
            "wins",
            "objections",
            "feature_requests",
            "sentiment_trend",
            "suggestions",
        ],
    },
}


# ============================================================
# Tool schema cho Claude Haiku 4.5 classify 1 feedback item
# ============================================================
SUBMIT_CLASSIFICATION_TOOL = {
    "name": "submit_classification",
    "description": (
        "Submit classification cho 1 feedback item: summary + feedback_type "
        "+ theme_tags + sentiment score."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content_summary": {
                "type": "string",
                "description": "Tóm tắt 1-3 câu tiếng Việt, tối đa 100 từ",
            },
            "feedback_type": {
                "type": "string",
                "enum": [
                    "pain",
                    "gain",
                    "win",
                    "objection",
                    "feature_request",
                    "complaint",
                    "praise",
                ],
            },
            "theme_tags": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {"type": "string"},
                "description": "3-5 short tag, vd ['gia-cao', 'thoi-gian', 'niem-tin']",
            },
            "sentiment": {
                "type": "number",
                "minimum": -1.0,
                "maximum": 1.0,
                "description": "-1.0 rat tieu cuc, 1.0 rat tich cuc",
            },
            "key_quotes": {
                "type": "array",
                "maxItems": 5,
                "items": {"type": "string"},
                "description": "3-5 quote nguyên văn từ transcript/form (chỉ cho Fathom)",
            },
        },
        "required": ["content_summary", "feedback_type", "theme_tags", "sentiment"],
    },
}


class BC3FeedbackLoop(BaseBC):
    """BC3 Feedback Loop agent.

    Verdict autonomy: L2_APPROVE vì digest preview cần Anna xem trước khi auto
    feed Research Engine downstream. Telegram message là preview, Anna /approve
    qua reply hoặc downstream cron pick up tags trong vault.
    """

    name = "bc3_feedback_loop"
    scope = (
        "Aggregate Tally + Fathom + community feedback "
        "→ Customer Voice digest weekly Monday"
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

        if event == "feedback.weekly_digest":
            return await self._handle_weekly_digest(ctx)
        if event == "feedback.tally.submitted":
            return await self._handle_tally_submitted(ctx)
        if event == "feedback.fathom.transcript":
            return await self._handle_fathom_transcript(ctx)

        return AgentResult(
            success=False,
            output_text="BC3 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "feedback.weekly_digest",
                    "feedback.tally.submitted",
                    "feedback.fathom.transcript",
                ],
            },
        )

    # ============================================================
    # Event 1: weekly digest
    # ============================================================
    async def _handle_weekly_digest(self, ctx: ExecutionContext) -> AgentResult:
        dry_run = os.getenv("BC3_DRY_RUN", "") == "1"

        # Query current week + prior week to compute sentiment delta
        try:
            current_rows = await self._fetch_feedback_window(
                days_back=WEEKLY_WINDOW_DAYS, offset_days=0
            )
            prior_rows = await self._fetch_feedback_window(
                days_back=WEEKLY_WINDOW_DAYS, offset_days=WEEKLY_WINDOW_DAYS
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC3 fetch feedback fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"Query customer_feedback fail: {exc}",
                output_payload={"error": str(exc)},
                escalation_required=True,
                escalation_reason="db_query_fail",
            )

        if not current_rows:
            log.info("BC3 không có feedback tuần này, skip digest")
            return AgentResult(
                success=True,
                output_text="Không có feedback tuần này",
                output_payload={
                    "events_count": 0,
                    "days_back": WEEKLY_WINDOW_DAYS,
                    "dry_run": dry_run,
                },
            )

        # Compute sentiment stats
        cur_sentiments = [
            float(r["sentiment"]) for r in current_rows if r.get("sentiment") is not None
        ]
        prior_sentiments = [
            float(r["sentiment"]) for r in prior_rows if r.get("sentiment") is not None
        ]
        avg_current = (
            sum(cur_sentiments) / len(cur_sentiments) if cur_sentiments else 0.0
        )
        avg_prior = (
            sum(prior_sentiments) / len(prior_sentiments) if prior_sentiments else 0.0
        )
        delta_pct = (
            ((len(current_rows) - len(prior_rows)) / max(len(prior_rows), 1)) * 100.0
            if prior_rows
            else 0.0
        )

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM client chưa init",
                output_payload={"error": "ANTHROPIC_API_KEY chưa set"},
                escalation_required=True,
                escalation_reason="llm_not_ready",
            )

        # Call Claude opus-4-7 với tool submit_digest
        prompt = self._build_digest_prompt(
            rows=current_rows,
            avg_current=avg_current,
            avg_prior=avg_prior,
            count_current=len(current_rows),
            count_prior=len(prior_rows),
        )

        try:
            response = await self.llm.client.messages.create(
                model=self.opus_model,
                max_tokens=DEFAULT_MAX_TOKENS_DIGEST,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_DIGEST_TOOL],
                tool_choice={"type": "tool", "name": "submit_digest"},
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC3 opus call fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM call fail: {exc}",
                output_payload={"error": str(exc)},
                escalation_required=True,
                escalation_reason="llm_call_fail",
            )

        digest = self._parse_digest_response(response)
        if digest.get("error"):
            return AgentResult(
                success=False,
                output_text=digest.get("error", "Parse fail"),
                output_payload=digest,
                escalation_required=True,
                escalation_reason="digest_parse_fail",
            )

        # Format markdown digest
        today_iso = date.today().isoformat()
        week_dates = self._week_dates_label()
        markdown = self._format_digest_markdown(
            digest=digest,
            week_dates=week_dates,
            events_count=len(current_rows),
            prior_count=len(prior_rows),
            avg_current=avg_current,
            avg_prior=avg_prior,
            delta_pct=delta_pct,
        )

        # Send Telegram
        sent_ok = False
        if dry_run:
            log.info("BC3 DRY_RUN, skip Telegram send")
            sent_ok = True
        else:
            # Telegram DISABLED 2026-06-11 (Anna chốt im lặng feedback loop digest)
            # Em vẫn lưu DB memory + log, KHÔNG send Telegram noise.
            sent_ok = False
            # Original: sent_ok = await send_telegram(markdown)

        # Emit memories: 1 digest summary + N auto-feed records cho Mac cron
        emitted_memories: list[dict[str, Any]] = [
            {
                "agent_name": self.name,
                "content": (
                    f"Customer Voice Digest {today_iso}: "
                    f"{len(current_rows)} feedback items, "
                    f"sentiment {avg_current:+.2f} vs {avg_prior:+.2f}"
                ),
                "keywords": ["digest", "weekly", today_iso],
                "tags": ["digest", "weekly", "sent" if sent_ok else "send_failed"],
                "venture": "breakout",
                "context": f"week={week_dates} window={WEEKLY_WINDOW_DAYS}d",
            }
        ]

        # Auto-feed: emit research_backlog (pain), objection_bank, case_study (win)
        for pain in digest.get("pain_themes", []) or []:
            emitted_memories.append(
                {
                    "agent_name": self.name,
                    "content": (
                        f"{pain.get('theme', '?')} (xuất hiện "
                        f"{pain.get('frequency', 0)} lần): "
                        f"\"{pain.get('quote', '')[:200]}\""
                    ),
                    "keywords": ["pain", "research_backlog", today_iso],
                    "tags": ["research_backlog", "pain", "auto_fed"],
                    "venture": "breakout",
                    "context": (
                        f"pain_theme week={week_dates} "
                        f"frequency={pain.get('frequency', 0)}"
                    ),
                }
            )

        for obj in digest.get("objections", []) or []:
            emitted_memories.append(
                {
                    "agent_name": self.name,
                    "content": (
                        f"{obj.get('objection', '?')} (xuất hiện "
                        f"{obj.get('frequency', 0)} lần): "
                        f"\"{obj.get('quote', '')[:200]}\""
                    ),
                    "keywords": ["objection", "objection_bank", today_iso],
                    "tags": ["objection_bank", "objection", "auto_fed"],
                    "venture": "breakout",
                    "context": (
                        f"objection week={week_dates} "
                        f"frequency={obj.get('frequency', 0)}"
                    ),
                }
            )

        for win in digest.get("wins", []) or []:
            potential = win.get("case_study_potential", "low")
            emitted_memories.append(
                {
                    "agent_name": self.name,
                    "content": (
                        f"[{potential}] {win.get('win', '?')} "
                        f"-> {win.get('customer_signal', '')[:200]}"
                    ),
                    "keywords": ["win", "case_study", today_iso, potential],
                    "tags": ["case_study", "win", "auto_fed", potential],
                    "venture": "breakout",
                    "context": f"win week={week_dates} potential={potential}",
                }
            )

        return AgentResult(
            success=True,
            output_text=markdown,
            output_payload={
                "events_count": len(current_rows),
                "prior_count": len(prior_rows),
                "avg_sentiment": avg_current,
                "avg_sentiment_prior": avg_prior,
                "delta_pct": delta_pct,
                "digest": digest,
                "sent_ok": sent_ok,
                "dry_run": dry_run,
                "week_dates": week_dates,
            },
            emitted_memories=emitted_memories,
        )

    # ============================================================
    # Event 2: Tally submitted
    # ============================================================
    async def _handle_tally_submitted(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        form_name = (payload.get("form_name") or "").lower().strip()
        customer_id = payload.get("customer_id")
        fields = payload.get("fields") or {}

        source, default_type = TALLY_FORM_MAP.get(
            form_name, ("tally_onboarding", None)
        )

        # Build content_raw từ fields dict
        content_raw = self._fields_to_raw_text(fields)
        if not content_raw.strip():
            return AgentResult(
                success=False,
                output_text="Tally payload không có fields có nội dung",
                output_payload={"form_name": form_name, "fields": fields},
            )

        # Haiku 4.5 classify
        classification = await self._classify_with_haiku(
            content_raw=content_raw,
            context_hint=f"Tally form {form_name}",
            default_type=default_type,
        )
        if classification.get("error"):
            return AgentResult(
                success=False,
                output_text=classification.get("error", "Classify fail"),
                output_payload=classification,
                escalation_required=True,
                escalation_reason="classify_fail",
            )

        # Insert customer_feedback
        dry_run = os.getenv("BC3_DRY_RUN", "") == "1"
        feedback_id: Optional[int] = None
        if dry_run:
            log.info("BC3 DRY_RUN, skip customer_feedback insert (tally)")
        else:
            try:
                feedback_id = await self._insert_feedback(
                    customer_id=customer_id,
                    source=source,
                    feedback_type=classification.get("feedback_type"),
                    content_raw=content_raw,
                    content_summary=classification.get("content_summary"),
                    sentiment=classification.get("sentiment"),
                    theme_tags=classification.get("theme_tags") or [],
                    event_id=payload.get("event_id"),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("BC3 insert feedback (tally) fail: %r", exc)
                return AgentResult(
                    success=False,
                    output_text=f"DB insert fail: {exc}",
                    output_payload={"error": str(exc)},
                    escalation_required=True,
                    escalation_reason="db_insert_fail",
                )

        memory = {
            "agent_name": self.name,
            "content": (
                f"Tally {form_name} feedback "
                f"type={classification.get('feedback_type')} "
                f"sentiment={classification.get('sentiment')}: "
                f"{(classification.get('content_summary') or '')[:200]}"
            ),
            "keywords": (classification.get("theme_tags") or [])[:5],
            "tags": [
                "tally",
                form_name or "unknown",
                classification.get("feedback_type") or "unclassified",
            ],
            "venture": "breakout",
            "customer_id": customer_id if isinstance(customer_id, int) else None,
        }

        return AgentResult(
            success=True,
            output_text=(
                f"Tally {form_name} classified type="
                f"{classification.get('feedback_type')} "
                f"feedback_id={feedback_id} dry_run={dry_run}"
            ),
            output_payload={
                "form_name": form_name,
                "source": source,
                "feedback_id": feedback_id,
                "classification": classification,
                "dry_run": dry_run,
            },
            emitted_memories=[memory],
        )

    # ============================================================
    # Event 3: Fathom transcript
    # ============================================================
    async def _handle_fathom_transcript(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        recording_id = payload.get("recording_id")
        transcript = payload.get("transcript") or ""
        participants = payload.get("participants") or []

        if not transcript.strip():
            return AgentResult(
                success=False,
                output_text="Fathom payload thiếu transcript",
                output_payload={"recording_id": recording_id},
            )

        # Resolve customer_id từ participants email (best effort)
        customer_id = await self._resolve_customer_from_participants(participants)

        # Haiku 4.5 extract quotes + classify
        classification = await self._classify_with_haiku(
            content_raw=transcript[:6000],  # cap để Haiku khỏi nuốt context
            context_hint=f"Fathom call recording_id={recording_id}",
            default_type=None,
            extract_quotes=True,
        )
        if classification.get("error"):
            return AgentResult(
                success=False,
                output_text=classification.get("error", "Classify fail"),
                output_payload=classification,
                escalation_required=True,
                escalation_reason="classify_fail",
            )

        # Build content_summary combine summary + quotes
        quotes = classification.get("key_quotes") or []
        summary_with_quotes = classification.get("content_summary") or ""
        if quotes:
            quote_block = " | ".join(f'"{q[:120]}"' for q in quotes[:3])
            summary_with_quotes = (
                f"{summary_with_quotes}\n\nKey quotes: {quote_block}"
            )

        dry_run = os.getenv("BC3_DRY_RUN", "") == "1"
        feedback_id: Optional[int] = None
        if dry_run:
            log.info("BC3 DRY_RUN, skip customer_feedback insert (fathom)")
        else:
            try:
                feedback_id = await self._insert_feedback(
                    customer_id=customer_id,
                    source="fathom_transcript",
                    feedback_type=classification.get("feedback_type"),
                    content_raw=transcript[:10000],
                    content_summary=summary_with_quotes,
                    sentiment=classification.get("sentiment"),
                    theme_tags=classification.get("theme_tags") or [],
                    event_id=payload.get("event_id"),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("BC3 insert feedback (fathom) fail: %r", exc)
                return AgentResult(
                    success=False,
                    output_text=f"DB insert fail: {exc}",
                    output_payload={"error": str(exc)},
                    escalation_required=True,
                    escalation_reason="db_insert_fail",
                )

        memory = {
            "agent_name": self.name,
            "content": (
                f"Fathom call recording={recording_id} "
                f"type={classification.get('feedback_type')} "
                f"sentiment={classification.get('sentiment')}: "
                f"{(classification.get('content_summary') or '')[:200]}"
            ),
            "keywords": (classification.get("theme_tags") or [])[:5],
            "tags": [
                "fathom",
                "call",
                classification.get("feedback_type") or "unclassified",
            ],
            "venture": "breakout",
            "customer_id": customer_id if isinstance(customer_id, int) else None,
        }

        return AgentResult(
            success=True,
            output_text=(
                f"Fathom recording={recording_id} classified type="
                f"{classification.get('feedback_type')} "
                f"customer_id={customer_id} feedback_id={feedback_id} "
                f"dry_run={dry_run}"
            ),
            output_payload={
                "recording_id": recording_id,
                "customer_id": customer_id,
                "feedback_id": feedback_id,
                "classification": classification,
                "key_quotes": quotes,
                "dry_run": dry_run,
            },
            emitted_memories=[memory],
        )

    # ============================================================
    # DB helpers (reuse MemoryLayer._pool)
    # ============================================================
    async def _fetch_feedback_window(
        self, *, days_back: int, offset_days: int = 0
    ) -> list[dict[str, Any]]:
        """Query `customer_feedback` window [now - (offset+days_back), now - offset]."""
        if not self.memory.dsn:
            raise RuntimeError("DATABASE_URL chưa set")

        pool = await self.memory._get_pool()  # noqa: SLF001
        sql = """
            SELECT id, customer_id, source, feedback_type, content_summary,
                   content_raw, sentiment, theme_tags, created_at
            FROM public.customer_feedback
            WHERE processed_at IS NOT NULL
              AND created_at <= now() - ($1::int * interval '1 day')
              AND created_at > now() - (($1::int + $2::int) * interval '1 day')
            ORDER BY created_at DESC
            LIMIT $3
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, offset_days, days_back, FEEDBACK_QUERY_LIMIT)
        return [dict(r) for r in rows]

    async def _insert_feedback(
        self,
        *,
        customer_id: Optional[Any],
        source: str,
        feedback_type: Optional[str],
        content_raw: str,
        content_summary: Optional[str],
        sentiment: Optional[float],
        theme_tags: list[str],
        event_id: Optional[Any],
    ) -> int:
        """INSERT vào customer_feedback. Return id."""
        if not self.memory.dsn:
            raise RuntimeError("DATABASE_URL chưa set")
        pool = await self.memory._get_pool()  # noqa: SLF001

        cust_id = customer_id if isinstance(customer_id, int) else None
        ev_id = event_id if isinstance(event_id, int) else None

        sql = """
            INSERT INTO public.customer_feedback (
                customer_id, source, feedback_type, content_raw,
                content_summary, sentiment, theme_tags, actionable,
                processed_at, event_id
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, now(), $9
            )
            RETURNING id
        """
        # actionable = True nếu là pain/objection/feature_request hoặc sentiment < -0.3
        actionable = False
        if feedback_type in ("pain", "objection", "feature_request", "complaint"):
            actionable = True
        if sentiment is not None and float(sentiment) < -0.3:
            actionable = True

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                sql,
                cust_id,
                source,
                feedback_type,
                content_raw,
                content_summary,
                float(sentiment) if sentiment is not None else None,
                theme_tags,
                actionable,
                ev_id,
            )
        return int(row["id"])

    async def _resolve_customer_from_participants(
        self, participants: list[Any]
    ) -> Optional[int]:
        """Best-effort: match email trong participants → customers.id."""
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
            log.debug("BC3 resolve customer fail: %r", exc)
        return None

    # ============================================================
    # LLM helpers
    # ============================================================
    async def _classify_with_haiku(
        self,
        *,
        content_raw: str,
        context_hint: str,
        default_type: Optional[str],
        extract_quotes: bool = False,
    ) -> dict[str, Any]:
        """Gọi Haiku 4.5 với tool submit_classification."""
        if not self.llm.ready:
            return {"error": "ANTHROPIC_API_KEY chưa set"}

        quote_instruction = (
            "\n- Extract 3-5 quote nguyên văn từ transcript vào key_quotes."
            if extract_quotes
            else ""
        )
        hint_type = (
            f"\n- Gợi ý feedback_type mặc định: {default_type} "
            "(override nếu nội dung rõ ràng khác)."
            if default_type
            else ""
        )
        prompt = (
            "Bạn là Customer Feedback Classifier cho Đào Thị Hằng (Hằng/Anna), "
            "venture Breakout (training Shopify cho người Việt).\n\n"
            f"Context: {context_hint}\n\n"
            "Nhiệm vụ: phân loại 1 feedback item, output qua tool "
            "`submit_classification`.\n"
            "- content_summary: 1-3 câu tiếng Việt, tối đa 100 từ.\n"
            "- feedback_type: 1 trong [pain, gain, win, objection, feature_request, "
            "complaint, praise].\n"
            "- theme_tags: 3-5 short tag kebab-case tiếng Việt không dấu, vd "
            "['gia-cao', 'thoi-gian', 'niem-tin'].\n"
            "- sentiment: -1.0 (rất tiêu cực) đến 1.0 (rất tích cực)."
            f"{quote_instruction}"
            f"{hint_type}\n\n"
            "NỘI DUNG:\n"
            "---\n"
            f"{content_raw[:6000]}\n"
            "---\n"
        )

        try:
            response = await self.llm.client.messages.create(
                model=self.haiku_model,
                max_tokens=DEFAULT_MAX_TOKENS_CLASSIFY,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_CLASSIFICATION_TOOL],
                tool_choice={"type": "tool", "name": "submit_classification"},
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC3 haiku call fail: %r", exc)
            return {"error": f"LLM call fail: {exc}"}

        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_classification"
            ):
                data = dict(block.input or {})
                # Clamp sentiment
                sent = data.get("sentiment")
                if sent is not None:
                    try:
                        sent_f = float(sent)
                        data["sentiment"] = max(-1.0, min(1.0, sent_f))
                    except (TypeError, ValueError):
                        data["sentiment"] = None
                return data

        return {"error": "No submit_classification tool_use in response"}

    def _build_digest_prompt(
        self,
        *,
        rows: list[dict[str, Any]],
        avg_current: float,
        avg_prior: float,
        count_current: int,
        count_prior: int,
    ) -> str:
        """Build prompt cho opus-4-7 weekly digest analysis."""
        lines: list[str] = []
        for r in rows[:200]:
            ts = ""
            if r.get("created_at"):
                ts = r["created_at"].isoformat() if hasattr(
                    r["created_at"], "isoformat"
                ) else str(r["created_at"])
            source = r.get("source") or "?"
            ftype = r.get("feedback_type") or "?"
            sent = r.get("sentiment")
            sent_str = f"{float(sent):+.2f}" if sent is not None else "n/a"
            tags = r.get("theme_tags") or []
            tag_str = ",".join(tags[:5]) if tags else ""
            summary = (r.get("content_summary") or r.get("content_raw") or "").replace(
                "\n", " "
            )[:400]
            lines.append(
                f"[{ts}] {source} type={ftype} sent={sent_str} tags=[{tag_str}]: "
                f"{summary}"
            )

        rows_text = "\n".join(lines) if lines else "(no feedback)"

        return (
            "Bạn là Customer Voice Analyst cho Đào Thị Hằng (Hằng/Anna), "
            "venture Breakout (training Shopify cho người Việt).\n\n"
            f"Phân tích {count_current} feedback items tuần qua "
            f"(prior week: {count_prior} items). "
            f"Sentiment trung bình hiện tại: {avg_current:+.2f}, tuần trước: "
            f"{avg_prior:+.2f}. Output JSON qua tool `submit_digest`.\n\n"
            "NHIỆM VỤ:\n"
            "1. Top 5 pain themes: nỗi đau cụ thể khách nói lặp lại (gộp tương đồng).\n"
            "2. Top 5 wins: thành công khách kể (case study candidate).\n"
            "3. Top 3 objections: phản đối khi sale/onboard (giá, thời gian, niềm "
            "tin, etc.) hoặc lý do refund.\n"
            "4. Top 3 feature requests: yêu cầu tính năng/khoá học mới.\n"
            "5. Sentiment trend: up/down/stable, kèm avg_current và avg_prior "
            f"({avg_current:+.2f} vs {avg_prior:+.2f}).\n"
            "6. Suggestions: 3-5 hành động Anna nên làm tuần này (actionable, "
            "làm ngay, không phải 'cần xem xét').\n\n"
            "NGUYÊN TẮC:\n"
            "- Mỗi item dẫn 1-2 quote thật từ rows (KHÔNG bịa).\n"
            "- Pain theme phải concrete (KHÔNG 'khó khăn chung chung').\n"
            "- Objection phải nguyên văn ngôn ngữ khách.\n"
            "- Tiếng Việt, không emoji, không dấu em-dash.\n\n"
            "DỮ LIỆU FEEDBACK:\n"
            "---\n"
            f"{rows_text}\n"
            "---\n\n"
            "Gọi tool `submit_digest` với đầy đủ fields. KHÔNG output text khác."
        )

    def _parse_digest_response(self, response: Any) -> dict[str, Any]:
        """Extract submit_digest tool_use input."""
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_digest"
            ):
                return dict(block.input or {})
        return {"error": "No submit_digest tool_use in response"}

    # ============================================================
    # Format + utility
    # ============================================================
    def _week_dates_label(self) -> str:
        """Trả về label tuần, vd '2026-06-01..2026-06-07'."""
        today = date.today()
        start = today - timedelta(days=WEEKLY_WINDOW_DAYS - 1)
        return f"{start.isoformat()}..{today.isoformat()}"

    def _fields_to_raw_text(self, fields: Any) -> str:
        """Convert Tally fields dict/list thành text raw."""
        if isinstance(fields, dict):
            parts = [
                f"{k}: {v}"
                for k, v in fields.items()
                if v not in (None, "", [])
            ]
            return " | ".join(parts)
        if isinstance(fields, list):
            parts: list[str] = []
            for f in fields:
                if isinstance(f, dict):
                    label = f.get("label") or f.get("key") or ""
                    value = f.get("value") or ""
                    if value:
                        parts.append(f"{label}: {value}")
            return " | ".join(parts)
        return str(fields) if fields else ""

    def _format_digest_markdown(
        self,
        *,
        digest: dict[str, Any],
        week_dates: str,
        events_count: int,
        prior_count: int,
        avg_current: float,
        avg_prior: float,
        delta_pct: float,
    ) -> str:
        """Render Telegram-friendly digest markdown tiếng Việt."""
        sentiment = digest.get("sentiment_trend") or {}
        direction = sentiment.get("direction", "stable")
        sent_icon = {"up": "📈", "down": "📉", "stable": "➡️"}.get(direction, "➡️")

        delta_sign = "+" if delta_pct >= 0 else ""
        lines = [
            f"📊 *Customer Voice Digest {week_dates}*",
            "",
            f"Tổng: {events_count} feedback items "
            f"(vs tuần trước: {prior_count}, {delta_sign}{delta_pct:.0f}%)",
            f"Sentiment {sent_icon}: {avg_current:+.2f} "
            f"(vs {avg_prior:+.2f}, hướng {direction.upper()})",
            "",
            "🔴 *Top Pain Themes:*",
        ]

        pain_themes = digest.get("pain_themes") or []
        if pain_themes:
            for i, p in enumerate(pain_themes, 1):
                lines.append(
                    f"{i}. {p.get('theme', '?')} (xuất hiện "
                    f"{p.get('frequency', 0)} lần)"
                )
                quote = (p.get("quote") or "").replace("\n", " ")[:160]
                if quote:
                    lines.append(f"   _{quote}_")
        else:
            lines.append("- Không có")

        lines += ["", "✅ *Top Wins:*"]
        wins = digest.get("wins") or []
        if wins:
            for i, w in enumerate(wins, 1):
                cs = w.get("case_study_potential", "low")
                icon = {"high": "⭐", "medium": "✨", "low": "·"}.get(cs, "·")
                lines.append(f"{i}. {icon} {w.get('win', '?')}")
                signal = (w.get("customer_signal") or "").replace("\n", " ")[:160]
                if signal:
                    lines.append(f"   _{signal}_")
        else:
            lines.append("- Không có")

        lines += ["", "⚠️ *Top Objections (Refund/Complaint):*"]
        objections = digest.get("objections") or []
        if objections:
            for i, o in enumerate(objections, 1):
                lines.append(
                    f"{i}. {o.get('objection', '?')} "
                    f"({o.get('frequency', 0)} lần)"
                )
                quote = (o.get("quote") or "").replace("\n", " ")[:160]
                if quote:
                    lines.append(f"   _{quote}_")
        else:
            lines.append("- Không có")

        lines += ["", "💡 *Top Feature Requests:*"]
        feature_requests = digest.get("feature_requests") or []
        if feature_requests:
            for i, f in enumerate(feature_requests, 1):
                lines.append(
                    f"{i}. {f.get('request', '?')} ({f.get('frequency', 0)} lần)"
                )
        else:
            lines.append("- Không có")

        lines += ["", "📌 *Actionable insights:*"]
        for i, s in enumerate(digest.get("suggestions") or [], 1):
            lines.append(f"{i}. {s}")

        notes = digest.get("notes")
        if notes:
            lines += ["", f"_Notes: {notes}_"]

        return "\n".join(lines)


# ============================================================
# Telegram (reuse pattern BC1)
# ============================================================
async def send_telegram(text: str) -> bool:
    """Gửi message tới Telegram group Breakout Ops.

    Env vars:
        TELEGRAM_BOT_TOKEN: bot token
        TELEGRAM_OPS_GROUP_ID: chat id (default -1003813280155)

    Return True nếu HTTP 200, False nếu thiếu token hoặc non-200.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_OPS_GROUP_ID", DEFAULT_TELEGRAM_GROUP_ID)
    if not token:
        log.warning("BC3 TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "BC3 Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
