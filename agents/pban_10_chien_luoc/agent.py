"""Phòng 10 Chiến lược agent.

Weekly LangGraph 3-node debate (Pro/Con/Synthesizer) propose strategy cho 6
ventures. L3 mãi forever (memory `agent-inventory-complete.md`). Anna decide,
KHÔNG auto-execute. Memory:
- `project-anna-thought-leader.md` (PURE TRUST 12 tháng)
- `aios-master-spec-v1` (500k AUD vision, 12 tháng roadmap)
- `feedback-just-do-no-suggestions.md` (just propose action, không hỏi suggest)

Trigger events:
- `strategy.weekly_debate`: thứ 7 chiều VN debate 30-60 phút, ship propose pack
  Telegram + email Anna Sunday 8am VN
- `strategy.decision_propose`: ad-hoc single decision propose (critical opportunity
  hoặc critical risk bypass weekly cycle)

Autonomy L3 mãi (KHÔNG upgrade). Propose only, không execute.

LLM Opus 4.7 cho Synthesizer node (high stakes strategic decision). Sonnet 4.6
cho Pro + Con (deferred Sprint 6 wire LangGraph thật, hiện tại Phòng 10 simulate
3-node bằng 3 LLM call tuần tự).

ZERO em-dash.
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

log = logging.getLogger("camas.pban_10_chien_luoc")

DEFAULT_DEBATE_PRO_MODEL = "claude-sonnet-4-6"
DEFAULT_DEBATE_CON_MODEL = "claude-sonnet-4-6"
DEFAULT_SYNTHESIZER_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 1500
DEFAULT_LLM_TIMEOUT = 90.0
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"


class Pban10ChienLuoc(BaseBC):
    """Phòng 10 Chiến lược, LangGraph 3-node debate weekly propose Anna."""

    name = "pban_10_chien_luoc"
    scope = "Weekly Pro/Con/Synthesizer debate 6 ventures, L3 propose Anna"
    autonomy_level = AutonomyLevel.L3_PROPOSE
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = ["langgraph", "vault_mcp", "postgres"]
    requires_voice_gate = True  # final brief BC2 voice gate
    requires_compliance_gate = True  # MARA + sensitive info

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        pro_model: str = DEFAULT_DEBATE_PRO_MODEL,
        con_model: str = DEFAULT_DEBATE_CON_MODEL,
        synth_model: str = DEFAULT_SYNTHESIZER_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.pro_model = pro_model
        self.con_model = con_model
        self.synth_model = synth_model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""

        if event == "strategy.weekly_debate":
            return await self._handle_weekly_debate(ctx)
        if event == "strategy.decision_propose":
            return await self._handle_decision_propose(ctx)

        return AgentResult(
            success=False,
            output_text="Phòng 10 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "strategy.weekly_debate",
                    "strategy.decision_propose",
                ],
            },
        )

    # ============================================================
    # Event 1: weekly debate
    # ============================================================
    async def _handle_weekly_debate(
        self, ctx: ExecutionContext
    ) -> AgentResult:
        """Saturday VN debate 3-node Pro/Con/Synthesizer, ship Sunday 8am."""
        timestamp = self._now_perth_str()

        # 1. Build context pack từ Phòng 08 + memory layer
        context_pack = await self._build_context_pack(ctx)

        # 2. Run 3-node debate (Sprint 6 wire LangGraph; hiện tại 3 LLM call tuần tự)
        pro = await self._debate_node(
            role="Pro",
            model=self.pro_model,
            context_pack=context_pack,
        )
        con = await self._debate_node(
            role="Con",
            model=self.con_model,
            context_pack=context_pack,
        )
        synthesis = await self._synthesizer_node(
            context_pack=context_pack, pro=pro, con=con
        )

        brief = self._format_brief(
            timestamp=timestamp,
            context_pack=context_pack,
            pro=pro,
            con=con,
            synthesis=synthesis,
        )
        sent_ok = await self._maybe_send_telegram(brief)

        return AgentResult(
            success=True,
            output_text=brief,
            output_payload={
                "event": "strategy.weekly_debate",
                "context_pack": context_pack,
                "pro": pro,
                "con": con,
                "synthesis": synthesis,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            escalation_required=True,
            escalation_reason="L3 propose Anna decide weekly",
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"weekly_debate propose_count={len(synthesis.get('items', []))}"
                    ),
                    "keywords": ["strategy", "debate", "weekly", timestamp[:10]],
                    "tags": ["pban_10", "weekly_debate", "l3_propose"],
                    "venture": "all",
                    "context": (
                        f"strategy.weekly_debate items={len(synthesis.get('items', []))}"
                    ),
                }
            ],
        )

    # ============================================================
    # Event 2: ad-hoc decision propose
    # ============================================================
    async def _handle_decision_propose(
        self, ctx: ExecutionContext
    ) -> AgentResult:
        """Ad-hoc decision (critical opportunity/risk), single Synthesizer call."""
        payload = ctx.payload or {}
        question = payload.get("question", "(no question)")
        context_data = payload.get("context", {})
        timestamp = self._now_perth_str()

        synthesis = await self._adhoc_synth(
            question=question, context_data=context_data
        )

        text = self._format_adhoc_propose(
            timestamp=timestamp, question=question, synthesis=synthesis
        )
        sent_ok = await self._maybe_send_telegram(text)

        return AgentResult(
            success=True,
            output_text=text,
            output_payload={
                "event": "strategy.decision_propose",
                "question": question,
                "synthesis": synthesis,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            escalation_required=True,
            escalation_reason="L3 ad-hoc decision Anna",
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"decision_propose q={question[:80]}"
                    ),
                    "keywords": ["strategy", "decision_propose", timestamp[:10]],
                    "tags": ["pban_10", "decision_propose", "l3_propose"],
                    "venture": ctx.venture_context,
                    "context": "strategy.decision_propose ad-hoc",
                }
            ],
        )

    # ============================================================
    # Context pack builder
    # ============================================================
    async def _build_context_pack(
        self, ctx: ExecutionContext
    ) -> dict[str, Any]:
        """Aggregate Phòng 08 KPI + retrieve memory cho 4-week trend."""
        pack: dict[str, Any] = {
            "ventures": [
                "speakout",
                "breakout",
                "cohangai",
                "migration",
                "bmcorner",
                "dat_gia_nghia",
            ],
            "window": "weekly",
            "kpi_summary": "STUB Sprint 6 wire Phòng 08 weekly aggregate",
            "memory_themes": [],
            "anomalies": [],
        }
        try:
            retrieved = await self.memory.retrieve(
                "strategy week opportunity risk", k=20, max_age_days=14
            )
            pack["memory_themes"] = [
                {
                    "agent": getattr(r, "agent_name", "?"),
                    "snippet": (getattr(r, "content", "") or "")[:120],
                }
                for r in retrieved[:6]
            ]
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban10 memory retrieve fail: %r", exc)
            pack["memory_themes"] = []
        return pack

    # ============================================================
    # Debate nodes (Sprint 6 wire LangGraph thật)
    # ============================================================
    async def _debate_node(
        self,
        *,
        role: str,
        model: str,
        context_pack: dict[str, Any],
    ) -> dict[str, Any]:
        """Pro hoặc Con node, single LLM call."""
        if not self.llm.ready:
            return {"role": role, "argument": f"LLM chưa init, {role} skip"}
        side = (
            "lập luận LÀM, list 3-5 lý do + evidence"
            if role == "Pro"
            else "lập luận KHÔNG LÀM, list 3-5 counter-evidence + risk"
        )
        prompt = (
            f"You are {role} debater cho Anna's portfolio strategy. {side}. "
            "Output 5-8 dòng tiếng Việt, không em-dash, không preamble.\n\n"
            f"Context: {json.dumps(context_pack, ensure_ascii=False)[:1500]}"
        )
        try:
            resp = await self.llm.client.messages.create(
                model=model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban10 %s debate fail: %r", role, exc)
            return {"role": role, "argument": f"{role} call fail: {exc}"}
        parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))
        return {"role": role, "argument": "".join(parts).strip() or "(empty)"}

    async def _synthesizer_node(
        self,
        *,
        context_pack: dict[str, Any],
        pro: dict[str, Any],
        con: dict[str, Any],
    ) -> dict[str, Any]:
        """Opus Synthesizer, propose 5-7 action item rank by impact × confidence."""
        if not self.llm.ready:
            return {
                "items": [],
                "dissent_note": "LLM chưa init",
                "confidence_score": 0,
            }
        prompt = (
            "You are Anna's Synthesizer, output 5-7 propose action item rank by "
            "impact × confidence × cost. Mỗi item: {action, venture, impact_1to5, "
            "confidence_1to5, cost_vnd, reasoning_1_line}. Kèm dissent_note ngắn "
            "(điểm Pro/Con chưa giải quyết) + confidence_score 0-100.\n\n"
            "Output raw JSON {items: [...], dissent_note: '...', "
            "confidence_score: int}, không markdown fence, tiếng Việt cho text. "
            "KHÔNG em-dash.\n\n"
            f"Context: {json.dumps(context_pack, ensure_ascii=False)[:1500]}\n"
            f"Pro: {pro.get('argument', '')[:1200]}\n"
            f"Con: {con.get('argument', '')[:1200]}"
        )
        try:
            resp = await self.llm.client.messages.create(
                model=self.synth_model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban10 synthesizer fail: %r", exc)
            return {
                "items": [],
                "dissent_note": f"Synthesizer fail: {exc}",
                "confidence_score": 0,
            }
        parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))
        text = "".join(parts).strip()
        try:
            parsed = json.loads(text)
            return {
                "items": parsed.get("items", []),
                "dissent_note": parsed.get("dissent_note", ""),
                "confidence_score": int(parsed.get("confidence_score", 0)),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban10 synth parse fail: %r raw=%s", exc, text[:300])
            return {
                "items": [],
                "dissent_note": f"Parse fail, raw output preserved",
                "confidence_score": 0,
                "raw_text": text[:1500],
            }

    async def _adhoc_synth(
        self, *, question: str, context_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Ad-hoc single Synthesizer call cho critical decision."""
        if not self.llm.ready:
            return {"recommendation": "LLM chưa init", "confidence": 0}
        prompt = (
            "You are Anna's strategic Synthesizer ad-hoc. Một câu hỏi critical. "
            "Output JSON {recommendation: '...', reasoning: '...', "
            "confidence: 0-100, risk_note: '...'} tiếng Việt no em-dash.\n\n"
            f"Câu hỏi: {question}\n"
            f"Context: {json.dumps(context_data, ensure_ascii=False)[:1200]}"
        )
        try:
            resp = await self.llm.client.messages.create(
                model=self.synth_model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban10 adhoc fail: %r", exc)
            return {"recommendation": f"LLM fail: {exc}", "confidence": 0}
        parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))
        text = "".join(parts).strip()
        try:
            return json.loads(text)
        except Exception:  # noqa: BLE001
            return {"recommendation": text[:500], "confidence": 0}

    # ============================================================
    # Format helpers
    # ============================================================
    def _format_brief(
        self,
        *,
        timestamp: str,
        context_pack: dict[str, Any],
        pro: dict[str, Any],
        con: dict[str, Any],
        synthesis: dict[str, Any],
    ) -> str:
        items_block: list[str] = []
        for idx, item in enumerate(synthesis.get("items", []), 1):
            if isinstance(item, dict):
                items_block.append(
                    f"{idx}. [{item.get('venture', '?')}] "
                    f"{item.get('action', '?')} | "
                    f"impact={item.get('impact_1to5', '?')} "
                    f"conf={item.get('confidence_1to5', '?')}"
                )
            else:
                items_block.append(f"{idx}. {item}")
        items_text = "\n".join(items_block) if items_block else "- không có"

        return (
            f"Phòng 10 Weekly Brief {timestamp}\n\n"
            f"Confidence: {synthesis.get('confidence_score', 0)}/100\n\n"
            f"PROPOSE 5-7 items:\n{items_text}\n\n"
            f"Dissent note:\n{synthesis.get('dissent_note', '(none)')}\n\n"
            f"Anna decide qua Telegram inline button hoặc email reply."
        )

    def _format_adhoc_propose(
        self,
        *,
        timestamp: str,
        question: str,
        synthesis: dict[str, Any],
    ) -> str:
        return (
            f"Phòng 10 Ad-hoc Propose {timestamp}\n\n"
            f"Q: {question}\n\n"
            f"Recommendation: {synthesis.get('recommendation', '')}\n"
            f"Reasoning: {synthesis.get('reasoning', '')}\n"
            f"Confidence: {synthesis.get('confidence', 0)}/100\n"
            f"Risk note: {synthesis.get('risk_note', '')}\n\n"
            f"Anna decide ngay (critical bypass weekly cycle)."
        )

    # ============================================================
    # Telegram + utility
    # ============================================================
    async def _maybe_send_telegram(self, text: str) -> bool:
        dry_run = os.getenv("PBAN_DRY_RUN", "") == "1"
        if dry_run:
            log.info("Pban10 DRY_RUN, skip Telegram send")
            return True
        try:
            return await send_telegram(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban10 Telegram send fail: %r", exc)
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
        log.warning("Pban10 TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "Pban10 Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
