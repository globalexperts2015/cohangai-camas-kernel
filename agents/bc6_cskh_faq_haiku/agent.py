"""BC6 CSKH FAQ Haiku agent.

Customer support tier 1 auto-reply dùng Claude Haiku 4.5 cho 3 ventures
Breakout + Speakout + Cohangai qua 4 channel (GHL Conversations + FB Messenger
+ Zalo OA + Email). Mục tiêu: trả 80% FAQ < 60 giây, giảm tải inbox Anna còn
case L2/L3 thật sự.

Three trigger events:

1. `cskh.message.in` (GHL webhook hoặc breakout-zns relay)
   - Extract message_text + customer_id + channel từ payload
   - Retrieve memory (past BC6 reply + FAQ kb) semantic search
   - Haiku 4.5 với tool submit_faq_reply: verdict + confidence + reply_text
   - confidence >= 60 + AUTO_REPLY -> publish_target ghl_customer_reply
     (kernel Voice+Compliance gate sẽ chạy trước khi gửi thật)
   - confidence < 60 hoặc ESCALATE -> escalation_required=True, Anna xử lý tay

2. `cskh.batch_audit` (weekly cron)
   - Sample 50 auto-reply gần nhất từ agent_memory
   - Tóm tắt stats: theo verdict, top topic, avg confidence
   - Emit memory + return summary (Phòng 08 Dữ liệu pick up cho digest)

3. unknown event -> success=False

Architecture notes:
    - requires_voice_gate = True vì reply gửi tới khách hàng, kernel chạy BC2
      style review trước khi publish thật (memory feedback-display-name-dao-thi-hang
      + voice rule Hằng).
    - requires_compliance_gate = True vì content public chạm khách hàng, BC9 MARA
      + Privacy check bắt buộc.
    - LLM Haiku 4.5 (memory feedback-claude-not-openrouter-automation): rẻ + nhanh
      đủ cho FAQ pattern lặp, < 2s typical, $0.80/1M input.
    - Confidence threshold 60% trong brief gốc đã được Anna chốt cho phase 1
      (brief nói 70%, nhưng spec hiện tại đặt 60% để promote thêm L1 case, sau
      14 case L2 success liên tiếp tăng threshold xuống ngược lại).
    - BC6 KHÔNG gửi reply thật trong run(): chỉ set publish_target để kernel
      Scheduler chạy gate + send. Cô lập producer khỏi sender, dễ test + dry-run.
"""
from __future__ import annotations

import json
import logging
import os
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

log = logging.getLogger("camas.bc6_cskh_faq_haiku")

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 800
DEFAULT_LLM_TIMEOUT = 30.0

CONFIDENCE_AUTO_REPLY_THRESHOLD = 60
RETRIEVE_TOP_K = 6
PUBLISH_TARGET_GHL_REPLY = "ghl_customer_reply"


# ============================================================
# Tool schema cho Claude Haiku submit FAQ reply / escalation
# ============================================================
FAQ_REPLY_TOOL: dict[str, Any] = {
    "name": "submit_faq_reply",
    "description": (
        "Submit FAQ auto-reply hoặc escalation decision cho 1 inbound message "
        "khách hàng. Verdict AUTO_REPLY nếu chắc chắn (confidence >= 60), "
        "ESCALATE nếu không chắc hoặc case phức tạp cần Anna xử lý tay."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["AUTO_REPLY", "ESCALATE"],
                "description": "AUTO_REPLY tự trả lời, ESCALATE Anna xử lý",
            },
            "confidence": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "Mức tự tin trả lời đúng, 0-100",
            },
            "reply_text": {
                "type": "string",
                "description": (
                    "Reply tiếng Việt, <=200 từ, giọng Hằng (ngắn gọn, ấm áp, "
                    "action-oriented). Nếu ESCALATE thì viết draft Anna có thể "
                    "edit nhanh."
                ),
            },
            "reason": {
                "type": "string",
                "description": "Lý do verdict, 1-2 câu",
            },
            "topic": {
                "type": "string",
                "description": (
                    "Chủ đề câu hỏi: pricing | refund | technical | schedule | "
                    "content | login | other"
                ),
            },
        },
        "required": ["verdict", "confidence", "reply_text", "reason"],
    },
}


SYSTEM_PROMPT_TEMPLATE = """Bạn là CSKH tier 1 của Đào Thị Hằng (Hằng). Trả lời ngắn gọn, ấm áp, action-oriented bằng tiếng Việt.

Context relevant từ knowledge base:
{retrieved_context}

Style rules:
- Câu ngắn 5-15 từ
- Xưng "Hằng" không "tôi"
- KHÔNG hứa visa rate, KHÔNG dùng dấu ,
- Nếu không chắc thì escalate Anna, không bịa
- Confidence >= 80 chắc chắn trả lời; 60-79 trả lời + flag check; < 60 escalate

Câu hỏi khách:
{message_text}

Sử dụng tool submit_faq_reply."""


class BC6CSKHFAQHaiku(BaseBC):
    """BC6 CSKH FAQ tier 1 auto-reply Haiku 4.5.

    Workflow run():
        1. Match trigger_event (cskh.message.in | cskh.batch_audit | unknown)
        2. cskh.message.in:
           - extract message + customer + channel
           - retrieve memory semantic
           - Haiku tool-call submit_faq_reply
           - decide publish_target hoặc escalate
        3. cskh.batch_audit:
           - sample 50 recent auto-reply
           - aggregate stats verdict + topic + avg confidence
        4. emit memory với agent_name = bc6_cskh_faq_haiku
    """

    name = "bc6_cskh_faq_haiku"
    scope = "Customer support tier 1, FAQ auto-reply via Claude Haiku 4.5"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = True
    requires_compliance_gate = True

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        model: str = DEFAULT_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""

        if event == "cskh.message.in":
            return await self._handle_message_in(ctx)
        if event == "cskh.batch_audit":
            return await self._handle_batch_audit(ctx)

        return AgentResult(
            success=False,
            output_text="BC6 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": ["cskh.message.in", "cskh.batch_audit"],
            },
        )

    # ============================================================
    # Event 1: cskh.message.in
    # ============================================================
    async def _handle_message_in(self, ctx: ExecutionContext) -> AgentResult:
        payload = ctx.payload or {}
        message_text = str(payload.get("message_text", "") or "").strip()
        customer_id = payload.get("customer_id")
        channel = str(payload.get("channel", "unknown") or "unknown")

        if not message_text:
            return AgentResult(
                success=False,
                output_text="Missing message_text",
                output_payload={
                    "verdict": "ERROR",
                    "error": "payload.message_text thiếu hoặc rỗng",
                },
            )

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM client chưa init",
                output_payload={
                    "verdict": "ERROR",
                    "error": "ANTHROPIC_API_KEY chưa set",
                },
            )

        # FAST PATH: nếu kernel pre-inject Profile + Task, dùng trực tiếp,
        # skip Voyage retrieve call. Canonical tier vẫn dùng nếu có.
        profile_nl = self._extract_from_injected(ctx, "profile")
        task_nl = self._extract_from_injected(ctx, "task")
        canonical_nl = self._extract_from_injected(ctx, "canonical")

        if profile_nl or task_nl or canonical_nl:
            log.info(
                "BC6 fast path message_in customer=%s (pre-injected: "
                "profile=%s task=%s canonical=%s)",
                customer_id,
                bool(profile_nl),
                bool(task_nl),
                bool(canonical_nl),
            )
            retrieved_context = self._build_fast_path_context(
                profile_nl=profile_nl,
                task_nl=task_nl,
                canonical_nl=canonical_nl,
            )
        else:
            log.warning(
                "BC6 slow path message_in customer=%s, fallback semantic retrieve",
                customer_id,
            )
            retrieved_context = await self._retrieve_context(
                query=message_text,
                venture=ctx.venture_context,
            )

        # 2. Build prompt + call Haiku tool-use
        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            retrieved_context=retrieved_context or "Không có context retrieved",
            message_text=message_text,
        )

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[FAQ_REPLY_TOOL],
                tool_choice={"type": "tool", "name": "submit_faq_reply"},
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC6 LLM call fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM call fail: {exc}",
                output_payload={
                    "verdict": "ERROR",
                    "error": str(exc),
                },
                escalation_required=True,
                escalation_reason="LLM call exception, Anna review",
            )

        decision = self._parse_tool_response(response)
        if decision.get("verdict") == "ERROR":
            return AgentResult(
                success=False,
                output_text=decision.get("error", "Parse fail"),
                output_payload=decision,
                escalation_required=True,
                escalation_reason="Tool parse fail, Anna review",
            )

        verdict = decision.get("verdict", "ESCALATE")
        confidence = int(decision.get("confidence", 0))
        reply_text = decision.get("reply_text", "")
        topic = decision.get("topic", "other") or "other"
        reason = decision.get("reason", "")

        dry_run = os.getenv("BC6_DRY_RUN", "") == "1"

        # 3. Decision: AUTO_REPLY + confidence >= threshold -> publish, else escalate
        publish_target: Optional[str] = None
        escalation_required = False
        escalation_reason: Optional[str] = None

        if (
            verdict == "AUTO_REPLY"
            and confidence >= CONFIDENCE_AUTO_REPLY_THRESHOLD
        ):
            # Kernel sẽ chạy Voice+Compliance gate trước khi send thật qua channel
            publish_target = PUBLISH_TARGET_GHL_REPLY if not dry_run else None
            summary = (
                f"AUTO_REPLY confidence={confidence} topic={topic} "
                f"channel={channel}"
            )
        else:
            escalation_required = True
            if verdict != "AUTO_REPLY":
                escalation_reason = (
                    f"LLM verdict ESCALATE, topic={topic}, reason={reason}"
                )
            else:
                escalation_reason = (
                    f"Low confidence ({confidence} < "
                    f"{CONFIDENCE_AUTO_REPLY_THRESHOLD}), Anna review"
                )
            summary = (
                f"ESCALATE confidence={confidence} topic={topic} "
                f"channel={channel}"
            )

        # 4. Emit memory record
        keywords = [topic] + self._extract_keywords(message_text, limit=4)
        memory_entry = {
            "agent_name": self.name,
            "content_summary": (
                f"verdict={verdict} confidence={confidence} topic={topic}"
            ),
            "keywords": keywords[:6],
            "tags": [
                verdict,
                channel,
                topic,
            ],
            "venture": ctx.venture_context,
            "context": (
                f"channel={channel} customer_id={customer_id} "
                f"message_preview={message_text[:120]}"
            ),
        }

        output_payload = {
            "verdict": verdict,
            "confidence": confidence,
            "reply_text": reply_text,
            "reason": reason,
            "topic": topic,
            "channel": channel,
            "customer_id": customer_id,
            "dry_run": dry_run,
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=output_payload,
            emitted_memories=[memory_entry],
            publish_target=publish_target,
            escalation_required=escalation_required,
            escalation_reason=escalation_reason,
        )

    @staticmethod
    def _extract_from_injected(
        ctx: ExecutionContext, source: str
    ) -> Optional[str]:
        """Extract pre-processed NL content từ ctx.injected_memories theo tier.

        Scheduler._auto_inject populate 4 tier: profile / task / conversation /
        canonical. Consumer agent đọc trực tiếp.
        """
        for grp in ctx.injected_memories or []:
            if grp.get("source") == source:
                content = grp.get("content")
                if isinstance(content, str) and content.strip():
                    return content
        return None

    @staticmethod
    def _build_fast_path_context(
        *,
        profile_nl: Optional[str],
        task_nl: Optional[str],
        canonical_nl: Optional[str],
    ) -> str:
        """Compose retrieved_context block từ pre-processed tier.

        Order: Profile (identity) → Task (recent state) → Canonical (facts).
        """
        sections: list[str] = []
        if profile_nl:
            sections.append(f"CUSTOMER PROFILE:\n{profile_nl}")
        if task_nl:
            sections.append(f"CURRENT TASK STATE:\n{task_nl}")
        if canonical_nl:
            sections.append(f"CANONICAL FACTS:\n{canonical_nl}")
        return "\n\n".join(sections)

    async def _retrieve_context(
        self,
        *,
        query: str,
        venture: Optional[str],
    ) -> str:
        """Retrieve top-k semantic match từ agent_memory + render NL.

        Filter venture nếu khác 'all' để giảm noise cross-venture. Fail-soft:
        nếu memory layer chưa ready hoặc Postgres down thì trả str rỗng,
        không crash BC6.
        """
        if not self.memory or not self.memory.ready:
            log.debug("BC6 memory layer chưa ready, skip retrieve")
            return ""

        venture_filter: Optional[str] = None
        if venture and venture not in ("", "all"):
            venture_filter = venture

        try:
            records = await self.memory.retrieve(
                query,
                k=RETRIEVE_TOP_K,
                agent_name=None,  # cross-agent, lấy FAQ + BC2 voice rule
                venture=venture_filter,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC6 memory retrieve fail: %r", exc)
            return ""

        if not records:
            return ""

        try:
            return await self.memory.to_natural_language(records)
        except Exception as exc:  # noqa: BLE001
            log.warning("BC6 memory to_natural_language fail: %r", exc)
            return ""

    # ============================================================
    # Event 2: cskh.batch_audit (weekly)
    # ============================================================
    async def _handle_batch_audit(self, ctx: ExecutionContext) -> AgentResult:
        """Sample 50 auto-reply gần nhất, aggregate stats verdict + topic.

        Không gửi Telegram trực tiếp, để Phòng 08 Dữ liệu pick up qua memory
        weekly digest hoặc BC1 morning brief.
        """
        stats: dict[str, Any] = {
            "sample_size": 0,
            "verdicts": {"AUTO_REPLY": 0, "ESCALATE": 0},
            "by_topic": {},
            "by_channel": {},
            "error": None,
        }

        if not self.memory or not self.memory.dsn:
            stats["error"] = "DATABASE_URL chưa set, skip audit"
            return AgentResult(
                success=True,
                output_text="audit skipped, no DB",
                output_payload=stats,
            )

        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            log.warning("BC6 audit pool init fail: %r", exc)
            stats["error"] = f"pool init fail: {exc}"
            return AgentResult(
                success=True,
                output_text="audit pool fail",
                output_payload=stats,
            )

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT tags, content, created_at
                    FROM public.agent_memory
                    WHERE agent_name = $1
                      AND created_at > now() - interval '7 days'
                    ORDER BY created_at DESC
                    LIMIT 50
                    """,
                    self.name,
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC6 audit SQL fail: %r", exc)
            stats["error"] = f"SQL fail: {exc}"
            return AgentResult(
                success=True,
                output_text="audit SQL fail",
                output_payload=stats,
            )

        stats["sample_size"] = len(rows)
        for r in rows:
            tags = list(r["tags"] or [])
            verdict = next(
                (t for t in tags if t in ("AUTO_REPLY", "ESCALATE")),
                None,
            )
            if verdict:
                stats["verdicts"][verdict] = stats["verdicts"].get(verdict, 0) + 1
            # tag order = [verdict, channel, topic] per emit
            if len(tags) >= 3:
                channel = tags[1]
                topic = tags[2]
                stats["by_channel"][channel] = (
                    stats["by_channel"].get(channel, 0) + 1
                )
                stats["by_topic"][topic] = stats["by_topic"].get(topic, 0) + 1

        memory_entry = {
            "agent_name": self.name,
            "content_summary": (
                f"batch_audit sample={stats['sample_size']} "
                f"auto={stats['verdicts'].get('AUTO_REPLY', 0)} "
                f"escalate={stats['verdicts'].get('ESCALATE', 0)}"
            ),
            "keywords": ["batch_audit", "weekly", "stats"],
            "tags": ["audit", "weekly"],
            "venture": ctx.venture_context,
        }

        return AgentResult(
            success=True,
            output_text=(
                f"audit sample={stats['sample_size']} "
                f"AUTO_REPLY={stats['verdicts'].get('AUTO_REPLY', 0)} "
                f"ESCALATE={stats['verdicts'].get('ESCALATE', 0)}"
            ),
            output_payload=stats,
            emitted_memories=[memory_entry],
        )

    # ============================================================
    # Helpers
    # ============================================================
    def _parse_tool_response(self, response) -> dict:
        """Extract submit_faq_reply tool_use block. Schema-validated by Anthropic."""
        tool_block = None
        text_fallback = ""
        for block in response.content or []:
            block_type = getattr(block, "type", None)
            block_name = getattr(block, "name", None)
            if block_type == "tool_use" and block_name == "submit_faq_reply":
                tool_block = block
                break
            if block_type == "text":
                text_fallback += getattr(block, "text", "")

        if tool_block is None:
            return {
                "verdict": "ERROR",
                "confidence": 0,
                "reply_text": "",
                "error": "No submit_faq_reply tool_use block in response",
                "raw_response": text_fallback[:500],
            }

        data = tool_block.input or {}
        return {
            "verdict": data.get("verdict", "ESCALATE"),
            "confidence": int(data.get("confidence", 0)),
            "reply_text": data.get("reply_text", ""),
            "reason": data.get("reason", ""),
            "topic": data.get("topic", "other"),
            "raw_response": json.dumps(data, ensure_ascii=False),
        }

    @staticmethod
    def _extract_keywords(text: str, *, limit: int = 4) -> list[str]:
        """Quick keyword extract VN, lowercase, len > 3, dedupe, cap limit.

        Không phải NLP đầy đủ, chỉ giúp tag memory dễ retrieve sau. Bỏ stopword
        tiếng Việt phổ biến.
        """
        stop = {
            "khoá", "khoa", "bao", "nhieu", "nhiêu", "duoc", "được",
            "lam", "làm", "sao", "the", "thế", "nao", "nào", "khi",
            "minh", "mình", "ban", "bạn", "toi", "tôi", "hang", "hằng",
            "anh", "chi", "chị", "em", "co", "có", "khong", "không",
            "voi", "với", "cho", "tu", "từ", "den", "đến", "the", "vay", "vậy",
        }
        words = []
        for w in (text or "").lower().split():
            w_clean = "".join(c for c in w if c.isalnum() or c in ".-_")
            if len(w_clean) > 3 and w_clean not in stop:
                words.append(w_clean)
        # dedupe preserve order
        seen: set[str] = set()
        out: list[str] = []
        for w in words:
            if w in seen:
                continue
            seen.add(w)
            out.append(w)
            if len(out) >= limit:
                break
        return out
