"""BC2 Voice Guardian agent.

Migrate từ standalone `cohangai/agents/voice_guardian/main.py` vào CAMAS Kernel
như 1 BaseBC subclass. Đánh giá content match voice Hằng (APPROVE/FLAG/REJECT).

Architecture notes:
- requires_voice_gate = False vì BC2 CHÍNH LÀ voice gate (recursion guard).
- requires_compliance_gate = True vì output BC2 vẫn là content cần MARA check.
- LLM injection qua constructor để Scheduler share 1 client duy nhất, không
  mỗi BC tự tạo AsyncAnthropic riêng.
- Đọc knowledge_base.md + style_rules.md + story_pool.json từ folder cùng cấp
  (Path(__file__).parent) tại constructor để giảm I/O per-run.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer

from .prompt_template import (
    SUBMIT_REVIEW_TOOL,
    build_review_prompt,
    load_knowledge_base,
    load_story_pool,
    load_style_rules,
)

log = logging.getLogger("camas.bc2_voice_guardian")

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 2500
DEFAULT_TIMEOUT = 60.0


class BC2VoiceGuardian(BaseBC):
    """BC2 voice guardian, review content match voice Hằng.

    Verdict: APPROVE (>= 80) / FLAG (60-79) / REJECT (< 60 hoặc có red flag).
    """

    name = "bc2_voice_guardian"
    scope = "Đánh giá content match voice Hằng (APPROVE/FLAG/REJECT)"
    autonomy_level = AutonomyLevel.L2_APPROVE
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = False  # BC2 IS voice gate, tránh recursion
    requires_compliance_gate = True  # Output BC2 là content, vẫn cần MARA check

    def __init__(
        self,
        llm: LLMLayer,
        model: str = DEFAULT_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.model = model
        # Load knowledge base 1 lần khi khởi tạo, giảm I/O per run
        self.knowledge_base = load_knowledge_base()
        self.style_rules = load_style_rules()
        self.story_pool = load_story_pool()

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        """Review content trong ctx.payload["content"] với meta ctx.payload["meta"]."""
        content = ctx.payload.get("content", "") if ctx.payload else ""
        meta = ctx.payload.get("meta", {}) if ctx.payload else {}

        if not content or not str(content).strip():
            return AgentResult(
                success=False,
                output_text="Missing content",
                output_payload={
                    "verdict": "ERROR",
                    "error": "payload.content thiếu hoặc rỗng",
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

        prompt = build_review_prompt(
            content=content,
            meta=meta,
            knowledge_base=self.knowledge_base,
            style_rules=self.style_rules,
            story_pool=self.story_pool,
        )

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_REVIEW_TOOL],
                tool_choice={"type": "tool", "name": "submit_review"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC2 LLM call fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM call fail: {exc}",
                output_payload={
                    "verdict": "ERROR",
                    "error": str(exc),
                },
            )

        review = self._parse_tool_response(response)
        if review.get("verdict") == "ERROR":
            return AgentResult(
                success=False,
                output_text=review.get("error", "Parse fail"),
                output_payload=review,
            )

        verdict = review.get("verdict", "ERROR")
        total = int(review.get("total", 0))
        red_flags = review.get("red_flags", []) or []

        summary = f"verdict={verdict} total={total}"

        memory = {
            "agent_name": self.name,
            "content_summary": (
                f"verdict={verdict} channel={meta.get('channel')} "
                f"venture={meta.get('venture')}"
            ),
            "keywords": list(red_flags)[:5],
            "tags": [
                verdict,
                meta.get("channel", "unknown") or "unknown",
                meta.get("venture", "all") or "all",
            ],
            "venture": meta.get("venture"),
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=review,
            emitted_memories=[memory],
        )

    def _parse_tool_response(self, response) -> dict:
        """Extract submit_review tool input. Schema-validated by Anthropic."""
        tool_block = None
        text_fallback = ""
        for block in response.content or []:
            block_type = getattr(block, "type", None)
            block_name = getattr(block, "name", None)
            if block_type == "tool_use" and block_name == "submit_review":
                tool_block = block
                break
            if block_type == "text":
                text_fallback += getattr(block, "text", "")

        if tool_block is None:
            return {
                "verdict": "ERROR",
                "total": 0,
                "error": "No submit_review tool_use block in response",
                "raw_response": text_fallback[:500],
            }

        data = tool_block.input or {}
        return {
            "verdict": data.get("verdict", "ERROR"),
            "total": int(data.get("total", 0)),
            "scores": data.get("scores", {}),
            "red_flags": data.get("red_flags", []),
            "issues": data.get("issues", []),
            "fixes": data.get("fixes", []),
            "notes": data.get("notes", ""),
            "raw_response": json.dumps(data, ensure_ascii=False),
        }
