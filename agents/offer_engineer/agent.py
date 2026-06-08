"""Offer Engineer agent.

Apply Hormozi $100M Offers formula để engineer offer mới hoặc audit offer cũ
của Anna. Output Stack value visualization + Bonus generator + Guarantee picker
+ Optimization recommendations với expected lift %.

Triết lý:
- Offer Value = (Dream Outcome × Perceived Likelihood) ÷ (Time Delay × Effort)
- 4 lever maximize: Dream ↑ Likelihood ↑ Time ↓ Effort ↓
- Stack value 8-12 components, total = 5-10x giá thật
- Bonus 3-5 time-limited
- Guarantee: money-back + outcome (Hormozi advanced)

Trigger events:
- `offer.engineer`: design offer mới từ scratch
- `offer.audit`: review offer hiện tại + recommend optimization

Autonomy L2 PROPOSE: agent recommend nhưng Anna duyệt trước khi publish offer
(blast radius lớn, ảnh hưởng pricing + conversion + refund rate).

Style: tiếng Việt docstring + log, ZERO em-dash, type hints, async/await.
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

log = logging.getLogger("camas.offer_engineer")

DEFAULT_LLM_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 2000
DEFAULT_LLM_TIMEOUT = 60.0
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"

EXPECTED_EVENTS = {"offer.engineer", "offer.audit"}


class OfferEngineer(BaseBC):
    """Offer Engineer apply Hormozi formula optimize offer Anna.

    2 mode:
    - engineer: design offer mới từ product + audience + dream outcome
    - audit: review offer hiện tại + return optimization

    Emit canonical fact category=venture_state cho Pban10 Chiến lược RAG retrieve
    khi propose budget + pricing decision.
    """

    name = "offer_engineer"
    scope = "Hormozi Grand Slam Offer formula + Stack + Bonus + Guarantee + Optimization"
    autonomy_level = AutonomyLevel.L2_APPROVE
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = ["anthropic_haiku"]
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
        if event not in EXPECTED_EVENTS:
            return AgentResult(
                success=False,
                output_text=f"{self.name} không xử lý event này",
                output_payload={
                    "trigger_event": event,
                    "supported": sorted(EXPECTED_EVENTS),
                },
            )

        if event == "offer.engineer":
            return await self._handle_engineer(ctx)
        if event == "offer.audit":
            return await self._handle_audit(ctx)

        return AgentResult(
            success=False,
            output_text=f"Event {event} chưa implement",
        )

    # ============================================================
    # Event 1: design offer mới từ scratch
    # ============================================================
    async def _handle_engineer(self, ctx: ExecutionContext) -> AgentResult:
        """Design offer mới Hormozi Grand Slam Offer formula."""
        payload = ctx.payload or {}
        product_name = (payload.get("product_name") or "").strip()
        target_audience = (payload.get("target_audience") or "").strip()
        dream_outcome = (payload.get("dream_outcome") or "").strip()
        price_vnd = int(payload.get("price_vnd") or 0)
        venture = ctx.venture_context or "breakout"

        if not product_name or not target_audience or not dream_outcome:
            return AgentResult(
                success=False,
                output_text="offer.engineer cần product_name + target_audience + dream_outcome",
                output_payload={"missing": ["product_name", "target_audience", "dream_outcome"]},
            )

        analysis = await self._llm_engineer(
            product_name=product_name,
            target_audience=target_audience,
            dream_outcome=dream_outcome,
            price_vnd=price_vnd,
            venture=venture,
        )
        timestamp = self._now_perth_str()
        date_tag = timestamp[:10]

        digest = self._format_engineer_digest(
            timestamp=timestamp,
            product_name=product_name,
            price_vnd=price_vnd,
            analysis=analysis,
        )
        sent_ok = await self._maybe_send_telegram(digest)

        emitted_memories = self._build_emit_memories(
            event="offer.engineer",
            product_name=product_name,
            venture=venture,
            date_tag=date_tag,
            analysis=analysis,
            sent_ok=sent_ok,
        )

        return AgentResult(
            success=True,
            output_text=digest,
            output_payload={
                "event": "offer.engineer",
                "product_name": product_name,
                "venture": venture,
                "analysis": analysis,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            emitted_memories=emitted_memories,
        )

    # ============================================================
    # Event 2: audit offer hiện tại + recommend
    # ============================================================
    async def _handle_audit(self, ctx: ExecutionContext) -> AgentResult:
        """Audit offer hiện tại theo Hormozi formula + recommend optimization."""
        payload = ctx.payload or {}
        product_name = (payload.get("product_name") or "").strip()
        target_audience = (payload.get("target_audience") or "").strip()
        dream_outcome = (payload.get("dream_outcome") or "").strip()
        price_vnd = int(payload.get("current_price_vnd") or payload.get("price_vnd") or 0)
        current_components = list(payload.get("current_components") or [])
        current_bonus = list(payload.get("current_bonus") or [])
        current_guarantee = (payload.get("current_guarantee") or "").strip()
        venture = ctx.venture_context or "breakout"

        if not product_name or not price_vnd:
            return AgentResult(
                success=False,
                output_text="offer.audit cần product_name + current_price_vnd",
                output_payload={"missing": ["product_name", "current_price_vnd"]},
            )

        analysis = await self._llm_audit(
            product_name=product_name,
            target_audience=target_audience or "(chưa cung cấp)",
            dream_outcome=dream_outcome or "(chưa cung cấp)",
            price_vnd=price_vnd,
            components=current_components,
            bonus=current_bonus,
            guarantee=current_guarantee or "(chưa có)",
            venture=venture,
        )
        timestamp = self._now_perth_str()
        date_tag = timestamp[:10]

        digest = self._format_audit_digest(
            timestamp=timestamp,
            product_name=product_name,
            price_vnd=price_vnd,
            analysis=analysis,
        )
        sent_ok = await self._maybe_send_telegram(digest)

        emitted_memories = self._build_emit_memories(
            event="offer.audit",
            product_name=product_name,
            venture=venture,
            date_tag=date_tag,
            analysis=analysis,
            sent_ok=sent_ok,
        )

        return AgentResult(
            success=True,
            output_text=digest,
            output_payload={
                "event": "offer.audit",
                "product_name": product_name,
                "venture": venture,
                "current_price_vnd": price_vnd,
                "analysis": analysis,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            emitted_memories=emitted_memories,
        )

    # ============================================================
    # LLM Haiku 4.5 analysis
    # ============================================================
    async def _llm_engineer(
        self,
        product_name: str,
        target_audience: str,
        dream_outcome: str,
        price_vnd: int,
        venture: str,
    ) -> dict[str, Any]:
        """Haiku 4.5 design offer Hormozi formula. Fallback stub khi LLM fail."""
        if not self.llm.ready:
            return self._stub_engineer(product_name, price_vnd)

        prompt = (
            "Bạn là Hormozi $100M Offers expert. Design offer Grand Slam theo formula:\n"
            "Offer Value = (Dream Outcome × Perceived Likelihood) ÷ (Time Delay × Effort)\n\n"
            f"Product: {product_name}\n"
            f"Audience: {target_audience}\n"
            f"Dream outcome: {dream_outcome}\n"
            f"Price: {price_vnd:,} VND\n"
            f"Venture: {venture}\n\n"
            "Return JSON object EXACTLY shape sau (no preamble, no markdown fence):\n"
            "{\n"
            '  "dream_outcome_score": float 0-10,\n'
            '  "dream_outcome_reasoning": str ngắn,\n'
            '  "likelihood_score": float 0-10,\n'
            '  "likelihood_reasoning": str ngắn,\n'
            '  "time_delay_score": float 0-10,\n'
            '  "time_delay_reasoning": str ngắn,\n'
            '  "effort_score": float 0-10,\n'
            '  "effort_reasoning": str ngắn,\n'
            '  "overall_value_score": float 0-10,\n'
            '  "recommended_stack": [\n'
            '    {"component": str, "value_vnd": int, "reasoning": str}\n'
            "  ] (8-12 items),\n"
            '  "recommended_bonus": [\n'
            '    {"name": str, "value_vnd": int, "expire_hours": int, "reasoning": str}\n'
            "  ] (3-5 items),\n"
            '  "recommended_guarantee": {"type": "money_back|outcome|double_back", "terms": str},\n'
            '  "total_stack_value_vnd": int,\n'
            '  "stack_to_price_ratio": float,\n'
            '  "top_3_levers": [\n'
            '    {"lever": "dream|likelihood|time|effort", "change": str, "expected_lift_pct": int}\n'
            "  ],\n"
            '  "risk_notes": str\n'
            "}\n\n"
            "Tiếng Việt cho mọi reasoning + component name. JSON only."
        )

        try:
            resp = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
            text = resp.content[0].text if resp.content else ""
            return self._parse_json_safe(text, fallback=self._stub_engineer(product_name, price_vnd))
        except Exception as exc:  # noqa: BLE001
            log.warning("offer_engineer LLM engineer fail: %r", exc)
            return self._stub_engineer(product_name, price_vnd)

    async def _llm_audit(
        self,
        product_name: str,
        target_audience: str,
        dream_outcome: str,
        price_vnd: int,
        components: list,
        bonus: list,
        guarantee: str,
        venture: str,
    ) -> dict[str, Any]:
        """Haiku 4.5 audit offer hiện tại + recommend optimization."""
        if not self.llm.ready:
            return self._stub_audit(product_name, price_vnd)

        components_str = "\n".join(f"  - {c}" for c in components) or "  (chưa có)"
        bonus_str = "\n".join(f"  - {b}" for b in bonus) or "  (chưa có)"

        prompt = (
            "Bạn là Hormozi $100M Offers expert. Audit offer hiện tại theo formula:\n"
            "Offer Value = (Dream Outcome × Perceived Likelihood) ÷ (Time Delay × Effort)\n\n"
            f"Product: {product_name}\n"
            f"Audience: {target_audience}\n"
            f"Dream outcome: {dream_outcome}\n"
            f"Current price: {price_vnd:,} VND\n"
            f"Current components:\n{components_str}\n"
            f"Current bonus:\n{bonus_str}\n"
            f"Current guarantee: {guarantee}\n"
            f"Venture: {venture}\n\n"
            "Return JSON object EXACTLY shape sau (no preamble, no markdown fence):\n"
            "{\n"
            '  "current_value_score": float 0-10,\n'
            '  "current_stack_to_price_ratio": float (estimate value/price),\n'
            '  "dream_outcome_score": float 0-10,\n'
            '  "dream_outcome_reasoning": str,\n'
            '  "likelihood_score": float 0-10,\n'
            '  "likelihood_reasoning": str,\n'
            '  "time_delay_score": float 0-10,\n'
            '  "time_delay_reasoning": str,\n'
            '  "effort_score": float 0-10,\n'
            '  "effort_reasoning": str,\n'
            '  "top_3_levers": [\n'
            '    {"lever": "dream|likelihood|time|effort", "change": str, "expected_lift_pct": int}\n'
            "  ],\n"
            '  "recommended_add_stack": [\n'
            '    {"component": str, "value_vnd": int, "reasoning": str}\n'
            "  ] (optional 3-5 items add),\n"
            '  "recommended_add_bonus": [\n'
            '    {"name": str, "value_vnd": int, "expire_hours": int, "reasoning": str}\n'
            "  ] (optional 2-3 items),\n"
            '  "recommended_guarantee_upgrade": {"type": "money_back|outcome|double_back", "terms": str, "reasoning": str},\n'
            '  "projected_value_score_after": float 0-10,\n'
            '  "projected_stack_ratio_after": float,\n'
            '  "risk_notes": str\n'
            "}\n\n"
            "Tiếng Việt cho mọi reasoning. JSON only."
        )

        try:
            resp = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
            text = resp.content[0].text if resp.content else ""
            return self._parse_json_safe(text, fallback=self._stub_audit(product_name, price_vnd))
        except Exception as exc:  # noqa: BLE001
            log.warning("offer_engineer LLM audit fail: %r", exc)
            return self._stub_audit(product_name, price_vnd)

    @staticmethod
    def _parse_json_safe(text: str, fallback: dict[str, Any]) -> dict[str, Any]:
        """Parse JSON từ LLM response, fallback nếu invalid."""
        if not text:
            return fallback
        # Try strip markdown fence if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```", 2)[1] if "```" in cleaned[3:] else cleaned[3:]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.rstrip("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            log.warning("offer_engineer JSON parse fail, use fallback")
            return fallback

    # ============================================================
    # Stub fallback (LLM down or invalid)
    # ============================================================
    @staticmethod
    def _stub_engineer(product_name: str, price_vnd: int) -> dict[str, Any]:
        """Stub engineer output khi LLM unavailable."""
        return {
            "dream_outcome_score": 0,
            "dream_outcome_reasoning": "(stub - LLM unavailable)",
            "likelihood_score": 0,
            "likelihood_reasoning": "(stub)",
            "time_delay_score": 0,
            "time_delay_reasoning": "(stub)",
            "effort_score": 0,
            "effort_reasoning": "(stub)",
            "overall_value_score": 0,
            "recommended_stack": [],
            "recommended_bonus": [],
            "recommended_guarantee": {"type": "money_back", "terms": "14 ngày refund"},
            "total_stack_value_vnd": 0,
            "stack_to_price_ratio": 0,
            "top_3_levers": [],
            "risk_notes": "LLM unavailable, stub output. Rerun khi llm.ready=True.",
        }

    @staticmethod
    def _stub_audit(product_name: str, price_vnd: int) -> dict[str, Any]:
        """Stub audit output khi LLM unavailable."""
        return {
            "current_value_score": 0,
            "current_stack_to_price_ratio": 0,
            "dream_outcome_score": 0,
            "dream_outcome_reasoning": "(stub - LLM unavailable)",
            "likelihood_score": 0,
            "likelihood_reasoning": "(stub)",
            "time_delay_score": 0,
            "time_delay_reasoning": "(stub)",
            "effort_score": 0,
            "effort_reasoning": "(stub)",
            "top_3_levers": [],
            "recommended_add_stack": [],
            "recommended_add_bonus": [],
            "recommended_guarantee_upgrade": {"type": "money_back", "terms": "14 ngày", "reasoning": "(stub)"},
            "projected_value_score_after": 0,
            "projected_stack_ratio_after": 0,
            "risk_notes": "LLM unavailable, stub output. Rerun khi llm.ready=True.",
        }

    # ============================================================
    # Format digest cho Telegram
    # ============================================================
    @staticmethod
    def _format_engineer_digest(
        timestamp: str,
        product_name: str,
        price_vnd: int,
        analysis: dict[str, Any],
    ) -> str:
        ratio = analysis.get("stack_to_price_ratio", 0)
        total_value = analysis.get("total_stack_value_vnd", 0)
        levers = analysis.get("top_3_levers", []) or []
        stack = analysis.get("recommended_stack", []) or []
        bonus = analysis.get("recommended_bonus", []) or []
        guarantee = analysis.get("recommended_guarantee", {}) or {}

        lines = [
            f"🎯 Offer ENGINEER: {product_name}",
            f"Time: {timestamp}",
            f"Price: {price_vnd:,} VND",
            f"Stack value total: {total_value:,} VND",
            f"Stack/Price ratio: {ratio:.1f}x (target 5-10x)",
            f"Overall value score: {analysis.get('overall_value_score', 0):.1f}/10",
            "",
        ]

        if levers:
            lines.append("📈 Top 3 lever optimize:")
            for i, lv in enumerate(levers[:3], 1):
                lines.append(
                    f"  {i}. [{lv.get('lever','?')}] {lv.get('change','?')} → +{lv.get('expected_lift_pct',0)}%"
                )
            lines.append("")

        if stack:
            lines.append(f"🎁 Stack {len(stack)} components:")
            for s in stack[:8]:
                lines.append(f"  - {s.get('component','?')} ({s.get('value_vnd',0):,} VND)")
            if len(stack) > 8:
                lines.append(f"  ... và {len(stack) - 8} component khác")
            lines.append("")

        if bonus:
            lines.append(f"🎊 Bonus {len(bonus)} items:")
            for b in bonus[:5]:
                lines.append(
                    f"  - {b.get('name','?')} ({b.get('value_vnd',0):,} VND, expire {b.get('expire_hours',0)}h)"
                )
            lines.append("")

        if guarantee:
            lines.append(f"🛡 Guarantee: {guarantee.get('type','?')} - {guarantee.get('terms','?')}")
            lines.append("")

        risk = analysis.get("risk_notes", "")
        if risk:
            lines.append(f"⚠️ Risk: {risk}")

        return "\n".join(lines)

    @staticmethod
    def _format_audit_digest(
        timestamp: str,
        product_name: str,
        price_vnd: int,
        analysis: dict[str, Any],
    ) -> str:
        current_score = analysis.get("current_value_score", 0)
        current_ratio = analysis.get("current_stack_to_price_ratio", 0)
        projected_score = analysis.get("projected_value_score_after", 0)
        projected_ratio = analysis.get("projected_stack_ratio_after", 0)
        levers = analysis.get("top_3_levers", []) or []
        add_stack = analysis.get("recommended_add_stack", []) or []
        add_bonus = analysis.get("recommended_add_bonus", []) or []
        guarantee_up = analysis.get("recommended_guarantee_upgrade", {}) or {}

        lines = [
            f"🔍 Offer AUDIT: {product_name}",
            f"Time: {timestamp}",
            f"Current price: {price_vnd:,} VND",
            f"Current value score: {current_score:.1f}/10",
            f"Current Stack/Price ratio: {current_ratio:.1f}x",
            f"Projected after change: {projected_score:.1f}/10, ratio {projected_ratio:.1f}x",
            "",
        ]

        if levers:
            lines.append("📈 Top 3 lever optimize:")
            for i, lv in enumerate(levers[:3], 1):
                lines.append(
                    f"  {i}. [{lv.get('lever','?')}] {lv.get('change','?')} → +{lv.get('expected_lift_pct',0)}%"
                )
            lines.append("")

        if add_stack:
            lines.append(f"➕ Add stack ({len(add_stack)} items):")
            for s in add_stack[:5]:
                lines.append(f"  - {s.get('component','?')} ({s.get('value_vnd',0):,} VND)")
            lines.append("")

        if add_bonus:
            lines.append(f"➕ Add bonus ({len(add_bonus)} items):")
            for b in add_bonus[:3]:
                lines.append(
                    f"  - {b.get('name','?')} ({b.get('value_vnd',0):,} VND)"
                )
            lines.append("")

        if guarantee_up:
            lines.append(
                f"🛡 Guarantee upgrade: {guarantee_up.get('type','?')} - {guarantee_up.get('terms','?')}"
            )
            reason = guarantee_up.get("reasoning", "")
            if reason:
                lines.append(f"   Lý do: {reason}")
            lines.append("")

        risk = analysis.get("risk_notes", "")
        if risk:
            lines.append(f"⚠️ Risk: {risk}")

        return "\n".join(lines)

    # ============================================================
    # Build emit memories cho RAG canonical
    # ============================================================
    def _build_emit_memories(
        self,
        event: str,
        product_name: str,
        venture: str,
        date_tag: str,
        analysis: dict[str, Any],
        sent_ok: bool,
    ) -> list[dict[str, Any]]:
        """Build canonical facts cho Pban10 + BC1 RAG retrieve."""
        if event == "offer.engineer":
            value_score = analysis.get("overall_value_score", 0)
            ratio = analysis.get("stack_to_price_ratio", 0)
            total_value = analysis.get("total_stack_value_vnd", 0)
            stack_count = len(analysis.get("recommended_stack", []) or [])
            bonus_count = len(analysis.get("recommended_bonus", []) or [])
            top_lever = (analysis.get("top_3_levers", []) or [{}])[0]

            content_summary = (
                f"Offer ENGINEER '{product_name}' {date_tag} value_score {value_score:.1f}/10 "
                f"stack_ratio {ratio:.1f}x total_value {total_value:,} VND "
                f"stack {stack_count} items bonus {bonus_count} items. "
                f"Top lever: {top_lever.get('lever','?')} → +{top_lever.get('expected_lift_pct',0)}%."
            )
        else:  # offer.audit
            current_score = analysis.get("current_value_score", 0)
            current_ratio = analysis.get("current_stack_to_price_ratio", 0)
            projected_score = analysis.get("projected_value_score_after", 0)
            projected_ratio = analysis.get("projected_stack_ratio_after", 0)
            top_lever = (analysis.get("top_3_levers", []) or [{}])[0]

            content_summary = (
                f"Offer AUDIT '{product_name}' {date_tag} current_score {current_score:.1f}/10 "
                f"ratio {current_ratio:.1f}x → projected {projected_score:.1f}/10 ratio {projected_ratio:.1f}x. "
                f"Top lever: {top_lever.get('lever','?')} → +{top_lever.get('expected_lift_pct',0)}%."
            )

        return [
            {
                "agent_name": self.name,
                "content_summary": content_summary,
                "keywords": ["offer_engineer", product_name.lower().replace(" ", "_"), date_tag],
                "tags": [
                    "offer_engineer",
                    "stage_9",
                    "hormozi",
                    event.replace(".", "_"),
                    venture,
                    "sent" if sent_ok else "send_failed",
                ],
                "venture": venture,
                "context": f"{event} {product_name} {date_tag}",
                "category": "venture_state",
            }
        ]

    # ============================================================
    # Telegram + utility
    # ============================================================
    async def _maybe_send_telegram(self, text: str) -> bool:
        dry_run = os.getenv("OFFER_DRY_RUN", "") == "1"
        if dry_run:
            log.info("offer_engineer DRY_RUN, skip Telegram send")
            return True
        try:
            return await _send_telegram(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("offer_engineer Telegram send fail: %r", exc)
            return False

    @staticmethod
    def _now_perth_str() -> str:
        now_perth = datetime.now(tz=timezone.utc) + timedelta(hours=8)
        return now_perth.strftime("%Y-%m-%d %H:%M")


async def _send_telegram(text: str) -> bool:
    """Gửi Telegram Breakout Ops, fallback nếu thiếu token."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_OPS_GROUP_ID", DEFAULT_TELEGRAM_GROUP_ID)
    if not token:
        log.warning("offer_engineer TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "offer_engineer Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
