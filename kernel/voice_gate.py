"""BC2 Voice Guardian hook entry point.

Score content match Anna voice profile (vault wiki/synthesis/anna-spoken-voice-profile.md).
Verdict: APPROVE / FLAG / REJECT.

VoiceGate là 1 thin facade trên BC2VoiceGuardian. Scheduler inject bc2_agent
sau khi BC2 register, để Q3 swap implementation BC2 (vd thay model, thêm
cache) không phải đụng vào Scheduler.
"""
from __future__ import annotations

import logging
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
