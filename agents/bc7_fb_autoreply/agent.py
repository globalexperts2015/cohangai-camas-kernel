"""BC7 FB Autoreply agent.

Real-time FB Page Đào Thị Hằng (ID 112307003450690) Messenger + comment
auto-reply qua Claude Haiku 4.5. L1_AUTO confidence >= 70%, escalate Telegram
khi confidence thấp hoặc detect divorce/migration sensitive topic.

Architecture choice (1 LLM call vs 2 calls):
    Plan ban đầu split classify (Haiku) + reply (Sonnet) như BC6/BC3. Nhưng FB
    message thường rất ngắn (1-2 câu, < 200 char), latency yêu cầu < 30s end-to-end
    cho mobile UX. Gộp spam/troll/classify/reply vào 1 Haiku 4.5 call qua tool
    submit_fb_reply tiết kiệm 1 round-trip + đơn giản hoá parsing. Trade-off:
    reply quality giảm 5-10% so với Sonnet, nhưng FB reply ngắn 120-150 char
    không cần Sonnet nuance.

Char limit enforcement:
    LLM prompt instruct char limit nhưng KHÔNG đảm bảo tuân thủ. Layer
    truncation hard ở `_enforce_char_limit()` trim text + thêm "..." nếu vượt.
    DM cap 120 char, comment cap 150 char (FB mobile UX).

Trigger events:
    1. fb.message.in (DM) → AUTO_REPLY ≤120 char hoặc ESCALATE
    2. fb.comment.in (comment) → AUTO_REPLY ≤150 char, detect troll/spam
    3. fb.batch_audit (weekly) → sample 30 auto-replies cho Anna review
    4. unknown → success=False

Style: tiếng Việt cho prompt + comment + docstring. ZERO em-dash. Type hints +
async/await xuyên suốt.
"""
from __future__ import annotations

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

log = logging.getLogger("camas.bc7_fb_autoreply")

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 600
DEFAULT_TIMEOUT = 30.0

CONFIDENCE_AUTO_REPLY = 70
DM_CHAR_LIMIT = 120
COMMENT_CHAR_LIMIT = 150

RETRIEVE_K = 5
AUDIT_SAMPLE_SIZE = 30


# ============================================================
# Tool schema cho Claude Haiku 4.5
# ============================================================
FB_REPLY_TOOL = {
    "name": "submit_fb_reply",
    "description": (
        "Submit FB auto-reply decision: verdict + confidence + reply_text + "
        "topic + spam/troll detection. Reply text tiếng Việt ngắn ≤120 char "
        "cho DM, ≤150 char cho comment."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["AUTO_REPLY", "ESCALATE", "IGNORE"],
            },
            "confidence": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
            },
            "reply_text": {
                "type": "string",
                "description": (
                    "Vietnamese ≤150 chars cho comment, ≤120 chars cho DM. "
                    "Rỗng nếu verdict=IGNORE."
                ),
            },
            "topic": {
                "type": "string",
                "description": (
                    "Topic classification ngắn, vd 'pricing-breakout', "
                    "'feedback-thank', 'spam', 'troll', 'migration-question'."
                ),
            },
            "is_spam": {"type": "boolean"},
            "is_troll": {"type": "boolean"},
            "reason": {
                "type": "string",
                "description": "1-2 câu giải thích verdict cho Anna review.",
            },
        },
        "required": [
            "verdict",
            "confidence",
            "reply_text",
            "is_spam",
            "is_troll",
        ],
    },
}


# ============================================================
# System prompt builder
# ============================================================
def build_reply_prompt(
    *,
    message_text: str,
    channel: str,
    retrieved_context: str,
) -> str:
    """Build prompt cho Haiku 4.5 + tool submit_fb_reply.

    channel: 'fb_dm' hoặc 'fb_comment' để đặt char limit khác.
    retrieved_context: NL bullet list từ memory.retrieve(), rỗng nếu không có.
    """
    char_limit = DM_CHAR_LIMIT if channel == "fb_dm" else COMMENT_CHAR_LIMIT
    channel_label = "tin nhắn DM" if channel == "fb_dm" else "bình luận FB"

    context_block = retrieved_context.strip() or "(không có context liên quan)"

    return (
        f"Bạn là FB community manager của Đào Thị Hằng (Hằng). Trả lời ngắn, "
        f"ấm áp, tiếng Việt.\n\n"
        f"Context relevant:\n"
        f"{context_block}\n\n"
        f"Rules:\n"
        f"- Reply text ≤ {char_limit} chars (mobile UX, đây là {channel_label})\n"
        f"- Xưng \"Hằng\" hoặc \"mình\"\n"
        f"- KHÔNG hứa visa rate, KHÔNG mention \"mẹ đơn thân\" (per memory)\n"
        f"- KHÔNG mention city (Perth/Adelaide/Gold Coast), chỉ \"Úc\"\n"
        f"- Detect spam (promo link không liên quan, bán hàng giá rẻ) "
        f"→ is_spam=true, verdict=IGNORE, reply_text rỗng\n"
        f"- Detect troll (insult, lừa đảo, off-topic provoke) "
        f"→ is_troll=true, verdict=IGNORE, reply_text rỗng\n"
        f"- Câu hỏi pricing/khoá học rõ ràng → AUTO_REPLY confidence cao (≥80)\n"
        f"- Câu hỏi cá nhân nhạy cảm (divorce, gia đình, migration visa cụ thể) "
        f"→ ESCALATE confidence thấp (<50)\n"
        f"- Tin nhắn cảm xúc tích cực (thank you, motivation) "
        f"→ AUTO_REPLY reply ngắn 1-2 emoji + cảm ơn\n"
        f"- ZERO em-dash trong reply\n\n"
        f"Tin nhắn:\n"
        f"---\n"
        f"{message_text}\n"
        f"---\n\n"
        f"Sử dụng tool submit_fb_reply."
    )


class BC7FBAutoreply(BaseBC):
    """BC7 FB Autoreply agent, real-time Messenger + comment reply.

    Verdict: AUTO_REPLY (confidence >= 70) / ESCALATE / IGNORE (spam/troll).
    """

    name = "bc7_fb_autoreply"
    scope = (
        "FB message + comment auto-reply via Claude Haiku, "
        "escalate complex queries"
    )
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = True  # Output public, cần voice match
    requires_compliance_gate = True  # FB ads policy + sensitive info gate

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

        if event == "fb.message.in":
            return await self._handle_inbound(ctx, channel="fb_dm")
        if event == "fb.comment.in":
            return await self._handle_inbound(ctx, channel="fb_comment")
        if event == "fb.batch_audit":
            return await self._handle_batch_audit(ctx)

        return AgentResult(
            success=False,
            output_text="BC7 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "fb.message.in",
                    "fb.comment.in",
                    "fb.batch_audit",
                ],
            },
        )

    # ============================================================
    # Event 1+2: inbound message/comment
    # ============================================================
    async def _handle_inbound(
        self,
        ctx: ExecutionContext,
        *,
        channel: str,
    ) -> AgentResult:
        """Channel = 'fb_dm' hoặc 'fb_comment'. Logic giống nhau, khác char limit."""
        payload = ctx.payload or {}
        message_text = (payload.get("message_text") or "").strip()
        sender_id = payload.get("sender_id")
        page_id = payload.get("page_id")

        if not message_text:
            return AgentResult(
                success=False,
                output_text="payload.message_text thiếu hoặc rỗng",
                output_payload={
                    "channel": channel,
                    "sender_id": sender_id,
                    "page_id": page_id,
                },
            )

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM client chưa init",
                output_payload={"error": "ANTHROPIC_API_KEY chưa set"},
                escalation_required=True,
                escalation_reason="llm_not_ready",
            )

        # Retrieve context từ memory (best-effort, fail-soft)
        retrieved_nl = await self._retrieve_context_nl(
            query=message_text,
            venture=ctx.venture_context,
        )

        prompt = build_reply_prompt(
            message_text=message_text,
            channel=channel,
            retrieved_context=retrieved_nl,
        )

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[FB_REPLY_TOOL],
                tool_choice={"type": "tool", "name": "submit_fb_reply"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC7 LLM call fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM call fail: {exc}",
                output_payload={"error": str(exc)},
                escalation_required=True,
                escalation_reason="llm_call_fail",
            )

        decision = self._parse_tool_response(response)
        if decision.get("error"):
            return AgentResult(
                success=False,
                output_text=decision.get("error", "Parse fail"),
                output_payload=decision,
                escalation_required=True,
                escalation_reason="parse_fail",
            )

        # Force IGNORE nếu spam/troll detect, dù LLM trả verdict khác
        verdict = decision.get("verdict", "ESCALATE")
        confidence = int(decision.get("confidence", 0))
        is_spam = bool(decision.get("is_spam", False))
        is_troll = bool(decision.get("is_troll", False))
        reply_text = decision.get("reply_text", "") or ""
        topic = decision.get("topic", "unknown") or "unknown"

        if is_spam or is_troll:
            verdict = "IGNORE"
            confidence = 0
            reply_text = ""

        # Force ESCALATE nếu confidence < threshold dù LLM nói AUTO_REPLY
        if verdict == "AUTO_REPLY" and confidence < CONFIDENCE_AUTO_REPLY:
            verdict = "ESCALATE"

        # Hard truncate reply theo char limit
        char_limit = DM_CHAR_LIMIT if channel == "fb_dm" else COMMENT_CHAR_LIMIT
        reply_text = self._enforce_char_limit(reply_text, char_limit)

        # Publish target chỉ set khi AUTO_REPLY (kernel post-hook gửi qua FB API)
        publish_target: Optional[str] = None
        escalation_required = False
        escalation_reason: Optional[str] = None
        dry_run = os.getenv("BC7_DRY_RUN", "") == "1"

        if verdict == "AUTO_REPLY":
            publish_target = channel  # 'fb_dm' hoặc 'fb_comment'
        elif verdict == "ESCALATE":
            escalation_required = True
            escalation_reason = f"low_confidence_{channel}"
        # IGNORE: không publish, không escalate

        memory_entry = {
            "agent_name": self.name,
            "content": (
                f"FB {channel} from sender={sender_id} verdict={verdict} "
                f"confidence={confidence} topic={topic}: "
                f"\"{message_text[:160]}\""
            ),
            "content_summary": (
                f"verdict={verdict} confidence={confidence} topic={topic}"
            ),
            "keywords": [topic, channel, verdict][:5],
            "tags": [verdict, channel, topic],
            "venture": ctx.venture_context,
            "context": (
                f"page_id={page_id} sender_id={sender_id} "
                f"is_spam={is_spam} is_troll={is_troll} dry_run={dry_run}"
            ),
        }

        return AgentResult(
            success=True,
            output_text=reply_text or f"[{verdict}] {topic}",
            output_payload={
                "channel": channel,
                "verdict": verdict,
                "confidence": confidence,
                "reply_text": reply_text,
                "topic": topic,
                "is_spam": is_spam,
                "is_troll": is_troll,
                "reason": decision.get("reason", ""),
                "sender_id": sender_id,
                "page_id": page_id,
                "dry_run": dry_run,
            },
            emitted_memories=[memory_entry],
            publish_target=publish_target,
            escalation_required=escalation_required,
            escalation_reason=escalation_reason,
        )

    # ============================================================
    # Event 3: weekly batch audit
    # ============================================================
    async def _handle_batch_audit(self, ctx: ExecutionContext) -> AgentResult:
        """Sample 30 auto-reply gần nhất từ memory cho Anna review.

        Query agent_memory tags=['AUTO_REPLY'] agent_name='bc7_fb_autoreply'
        7 ngày gần nhất, return danh sách + thống kê verdict.
        """
        if not self.memory.dsn:
            return AgentResult(
                success=False,
                output_text="DATABASE_URL chưa set, skip audit",
                output_payload={"error": "no_dsn"},
            )

        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            log.warning("BC7 audit pool fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"Pool init fail: {exc}",
                output_payload={"error": str(exc)},
            )

        samples: list[dict[str, Any]] = []
        verdict_counts: dict[str, int] = {}
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT memory_id, content, tags, context, created_at
                    FROM public.agent_memory
                    WHERE agent_name = $1
                      AND 'AUTO_REPLY' = ANY(tags)
                      AND created_at > now() - interval '7 days'
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    self.name,
                    AUDIT_SAMPLE_SIZE,
                )
                for r in rows:
                    tags = list(r["tags"] or [])
                    samples.append(
                        {
                            "memory_id": str(r["memory_id"]),
                            "content": r["content"],
                            "tags": tags,
                            "created_at": (
                                r["created_at"].isoformat()
                                if r["created_at"]
                                else None
                            ),
                        }
                    )

                # Aggregate verdict counts 7 ngày
                count_rows = await conn.fetch(
                    """
                    SELECT tag, COUNT(*)::int AS cnt
                    FROM (
                        SELECT unnest(tags) AS tag
                        FROM public.agent_memory
                        WHERE agent_name = $1
                          AND created_at > now() - interval '7 days'
                    ) sub
                    WHERE tag IN ('AUTO_REPLY', 'ESCALATE', 'IGNORE')
                    GROUP BY tag
                    """,
                    self.name,
                )
                for r in count_rows:
                    verdict_counts[r["tag"]] = r["cnt"]
        except Exception as exc:  # noqa: BLE001
            log.warning("BC7 audit SQL fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"Audit SQL fail: {exc}",
                output_payload={"error": str(exc)},
            )

        summary = (
            f"BC7 audit 7d: AUTO_REPLY={verdict_counts.get('AUTO_REPLY', 0)} "
            f"ESCALATE={verdict_counts.get('ESCALATE', 0)} "
            f"IGNORE={verdict_counts.get('IGNORE', 0)} "
            f"sampled={len(samples)}"
        )

        memory_entry = {
            "agent_name": self.name,
            "content": summary,
            "content_summary": summary,
            "keywords": ["audit", "weekly"],
            "tags": ["audit", "weekly", "bc7_review"],
            "venture": ctx.venture_context or "all",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload={
                "verdict_counts": verdict_counts,
                "samples": samples,
                "sample_count": len(samples),
            },
            emitted_memories=[memory_entry],
        )

    # ============================================================
    # Helpers
    # ============================================================
    async def _retrieve_context_nl(
        self,
        *,
        query: str,
        venture: Optional[str],
    ) -> str:
        """Best-effort retrieve k=5 memories + render NL. Fail-soft trả rỗng."""
        if not self.memory.ready:
            return ""
        try:
            records = await self.memory.retrieve(
                query=query,
                k=RETRIEVE_K,
                venture=venture if venture and venture != "all" else None,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("BC7 memory retrieve fail: %r", exc)
            return ""
        if not records:
            return ""
        try:
            return await self.memory.to_natural_language(records)
        except Exception as exc:  # noqa: BLE001
            log.debug("BC7 to_natural_language fail: %r", exc)
            return ""

    def _enforce_char_limit(self, text: str, limit: int) -> str:
        """Hard truncate text về limit char, thêm '...' nếu cắt.

        ZERO em-dash check: nếu LLM lỡ output em-dash, replace bằng dấu phẩy.
        """
        if not text:
            return ""
        # Replace em-dash về dấu phẩy (memory rule)
        cleaned = text.replace("—", ",").replace("–", ",").strip()
        if len(cleaned) <= limit:
            return cleaned
        # Truncate + ellipsis (3 char) để vẫn dưới limit
        return cleaned[: max(0, limit - 3)].rstrip() + "..."

    def _parse_tool_response(self, response: Any) -> dict[str, Any]:
        """Extract submit_fb_reply tool_use input."""
        text_fallback = ""
        for block in response.content or []:
            block_type = getattr(block, "type", None)
            block_name = getattr(block, "name", None)
            if block_type == "tool_use" and block_name == "submit_fb_reply":
                return dict(block.input or {})
            if block_type == "text":
                text_fallback += getattr(block, "text", "")
        return {
            "error": "No submit_fb_reply tool_use in response",
            "raw_response": text_fallback[:500],
        }
