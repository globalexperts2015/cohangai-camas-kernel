"""BC2 Voice Guardian hook + Anna voice rewriter.

Hai chức năng:
1. VoiceGate.review(): score content theo profile, verdict APPROVE/FLAG/REJECT (BC2 agent).
2. apply_voice_rewrite(): rewrite text AI-tone sang Anna voice qua Haiku 4.5 (Sprint 14 P0.3).

Voice profile source: vault wiki/synthesis/anna-spoken-voice-profile.md (5 ngày webinar Speakout, 6300+ dòng).
"""
from __future__ import annotations

import logging
import os
import uuid
from enum import Enum
from typing import TYPE_CHECKING, Optional

from kernel.llm_layer import LLMLayer

if TYPE_CHECKING:
    from agents.bc2_voice_guardian.agent import BC2VoiceGuardian

log = logging.getLogger("camas.voice_gate")


class VoiceVerdict(str, Enum):
    APPROVE = "approve"
    FLAG = "flag"
    REJECT = "reject"
    SKIP = "skip"


class VoiceGate:
    """Hook chạy pre-publish.

    Khi bc2_agent chưa inject → SKIP graceful (log warn 1 lần).
    Khi đã inject → build ExecutionContext tạm cho BC2, gọi run(), map verdict.
    """

    def __init__(
        self,
        llm: Optional[LLMLayer] = None,
        bc2_agent: Optional["BC2VoiceGuardian"] = None,
    ) -> None:
        self.llm = llm or LLMLayer()
        self.bc2_agent: Optional["BC2VoiceGuardian"] = bc2_agent

    async def review(
        self, text: str, venture_context: str = "all"
    ) -> VoiceVerdict:
        """Return verdict cho 1 đoạn content."""
        if not text or not text.strip():
            return VoiceVerdict.SKIP

        if self.bc2_agent is None:
            log.warning(
                "VoiceGate skip, BC2 agent chưa inject (venture=%s)",
                venture_context,
            )
            return VoiceVerdict.SKIP

        # Import tại runtime, tránh circular import với agents.bc2_voice_guardian
        from kernel.base_agent import ExecutionContext

        ctx = ExecutionContext(
            run_id=str(uuid.uuid4()),
            user_id=None,
            venture_context=venture_context,
            trigger_event="voice_gate.inline_review",
            payload={
                "content": text,
                "meta": {
                    "venture": venture_context,
                    "channel": "inline_gate",
                },
            },
        )

        result = await self.bc2_agent.run(ctx)
        if not result.success:
            log.info(
                "VoiceGate BC2 fail, skip (err=%s)", result.output_text
            )
            return VoiceVerdict.SKIP

        verdict_raw = (result.output_payload or {}).get("verdict", "")
        mapping = {
            "APPROVE": VoiceVerdict.APPROVE,
            "FLAG": VoiceVerdict.FLAG,
            "REJECT": VoiceVerdict.REJECT,
        }
        return mapping.get(verdict_raw, VoiceVerdict.SKIP)


# Sprint 14 P0.3 Anna voice rewriter
# Source: wiki/synthesis/anna-spoken-voice-profile.md

VOICE_REWRITE_MODEL = "claude-haiku-4-5-20251001"
VOICE_REWRITE_MAX_TOKENS = 6000
VOICE_REWRITE_TIMEOUT = 90.0
VOICE_REWRITE_SIGNATURE = "<!-- voice-rewritten-anna -->"
VOICE_REWRITE_MIN_INPUT = 30

ANNA_VOICE_REWRITE_SYSTEM = """Bạn là Đào Thị Hằng (Anna), founder người Quảng Trị sống ở Úc. Rewrite text AI tone sang giọng nói THẬT của bạn.

# VOICE ANNA

## Xưng hô
- Gọi mình: "Hằng" (ngôi 3, register webinar/dạy học)
- Gọi người nghe: "bạn", "các bạn"
- KHÔNG corporate "chúng tôi", KHÔNG "anh/chị"

## Câu + nhịp
- Câu ngắn 5-12 từ, đọc to nghe tự nhiên
- Pause "…" thay phẩy nặng khi chuyển ý
- Talk-it-out, không câu dài lê thê
- Không sub-clause nhiều tầng

## Từ ngữ mộc mạc miền Trung
- Dùng dân dã: "cùi bắp", "trầm trầy trầm trật", "lên bờ xuống ruộng", "té sấp mặt", "mừng húm", "thót tim", "khăn gói", "lật đật", "vắt tay lên trán nghĩ"
- Địa phương: "mạ", "ba", "mệ", "cậu", "dì", "răng mà", "chi"
- Không hoa mỹ, không corporate jargon

## Cấu trúc
- Why trước How trước What
- Đặt câu hỏi rồi tự trả lời: "Vì sao?", "Tại sao?", "Bằng cách nào?"
- Ẩn dụ dân dã: kiềng ba chân, bình trà rỗng, thai nghén đi đẻ, viên gạch xi măng
- Bộ ba: Đúng-Đủ-Đều, Sợ-Muốn-Yêu, Biết-Hiểu-Ngộ
- Câu chốt aphorism: "Hoàn thành hơn hoàn hảo", "Muốn nhanh cần phải từ từ"

## Dám yếu
- Thừa nhận lúc dở, lúc bế tắc
- Chuyển hoá: "Hằng nhận ra...", "Hằng hiểu ra..."

## TUYỆT ĐỐI KHÔNG
- KHÔNG dấu "—" em-dash, dùng "," hoặc "…"
- KHÔNG emoji
- KHÔNG mở đầu AI-style: "Tôi tin rằng", "Theo tôi", "Như chúng ta đã biết", "Có thể nói"
- KHÔNG formal connector "Hơn nữa", "Bên cạnh đó", "Tuy nhiên", "Do đó" → dùng "Nhưng", "Còn", "Vì vậy", "Nói thật"
- KHÔNG "Việt kiều" → dùng "người Việt"
- KHÔNG marital status: "mẹ đơn thân", "ly thân", "chồng cũ"
- KHÔNG city Perth/Adelaide/Gold Coast → chỉ "Úc"
- KHÔNG hứa "x100 doanh thu", outcome đảm bảo
- KHÔNG bịa số liệu mới (giữ nguyên số gốc)

## GIỮ NGUYÊN
- Structure Markdown (headers ##/###, lists, tables, code blocks, blockquotes)
- Số liệu, tên riêng, framework name (Hormozi, Brunson, VPC, JTBD, Eagle Camp)
- Tên thật trong text

# TASK

Rewrite text dưới đây sang voice Anna. Giữ NGUYÊN ý + structure Markdown, ĐỔI giọng từ AI sang voice thật của Hằng.

Output: CHỈ rewrite text Markdown. KHÔNG preamble. KHÔNG explain. KHÔNG meta-comment.
"""


def voice_rewrite_enabled() -> bool:
    """Check env flag, default True (Anna chốt 2026-06-08 Sprint 14 P0.3)."""
    return os.getenv("VOICE_REWRITE_ENABLED", "true").lower() in ("1", "true", "yes")


async def apply_voice_rewrite(
    llm: LLMLayer,
    text: str,
    venture_context: str = "all",
) -> str:
    """Rewrite Markdown text sang Anna voice qua Haiku 4.5.

    Idempotent: skip nếu text đã có VOICE_REWRITE_SIGNATURE.
    Fail-safe: return original nếu LLM lỗi, output ngắn, hoặc flag disable.

    Args:
        llm: LLMLayer instance (cần ready)
        text: Markdown text gốc từ wizard output
        venture_context: venture tag để log + future MCP voice register pick

    Returns:
        Rewritten Markdown với signature footer, OR original text on failure.
    """
    if not voice_rewrite_enabled():
        return text

    if not text or len(text.strip()) < VOICE_REWRITE_MIN_INPUT:
        return text

    if VOICE_REWRITE_SIGNATURE in text:
        return text

    if not llm.ready:
        log.warning("apply_voice_rewrite skip: LLM not ready (venture=%s)", venture_context)
        return text

    try:
        response = await llm.client.messages.create(
            model=VOICE_REWRITE_MODEL,
            max_tokens=VOICE_REWRITE_MAX_TOKENS,
            system=ANNA_VOICE_REWRITE_SYSTEM,
            messages=[{"role": "user", "content": f"Text gốc cần rewrite:\n\n{text}"}],
            timeout=VOICE_REWRITE_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("apply_voice_rewrite LLM fail: %r, return original (venture=%s)", exc, venture_context)
        return text

    rewritten_parts: list[str] = []
    for block in response.content or []:
        if getattr(block, "type", None) == "text":
            rewritten_parts.append(getattr(block, "text", ""))
    rewritten = "".join(rewritten_parts).strip()

    if len(rewritten) < len(text) * 0.4:
        log.warning(
            "apply_voice_rewrite output too short (%d vs %d), fall back (venture=%s)",
            len(rewritten),
            len(text),
            venture_context,
        )
        return text

    usage = getattr(response, "usage", None)
    if usage is not None:
        log.info(
            "voice_rewrite ok venture=%s input_tokens=%s output_tokens=%s",
            venture_context,
            getattr(usage, "input_tokens", 0),
            getattr(usage, "output_tokens", 0),
        )

    return f"{rewritten}\n\n{VOICE_REWRITE_SIGNATURE}"
