"""Niche Validator agent.

Apply 3-indicator test cho niche statement (Stage 3 framework v2):
1. Semantic clarity: 3 LLM prompts mô tả lại niche → check match score ≥ 0.85
2. Audience size: FB Group count fit niche ≥ 100 (LLM estimate)
3. Search demand: ≥ 5 keywords với monthly volume > 100 (LLM estimate)

Trigger event: niche.validate
Autonomy L1.
Output: pass/fail per indicator + overall score + recommendation if fail.
Emit canonical fact category=venture_state tags=niche_validator+stage_3.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
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

log = logging.getLogger("camas.niche_validator")

EXPECTED_EVENTS = {"niche.validate"}

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 2500
DEFAULT_TIMEOUT = 90.0


SUBMIT_VALIDATION_TOOL = {
    "name": "submit_niche_validation",
    "description": "Submit niche validation result 3-indicator test",
    "input_schema": {
        "type": "object",
        "properties": {
            "niche_statement": {"type": "string"},
            "venture": {"type": "string"},
            "indicator_1_semantic_clarity_score": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Semantic match score 3 LLM rephrase (0-1, pass ≥0.85)",
            },
            "indicator_1_paraphrases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3 LLM paraphrases of niche",
            },
            "indicator_1_pass": {"type": "boolean"},
            "indicator_2_fb_group_estimate": {
                "type": "integer",
                "description": "Estimated FB groups fit niche (LLM knowledge, pass ≥100)",
            },
            "indicator_2_pass": {"type": "boolean"},
            "indicator_2_sample_groups": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Sample group names",
            },
            "indicator_3_keywords": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string"},
                        "estimated_monthly_volume": {"type": "integer"},
                    },
                },
                "description": "Keywords + monthly volume (pass: ≥5 with vol >100)",
            },
            "indicator_3_pass": {"type": "boolean"},
            "indicator_3_pass_count": {
                "type": "integer",
                "description": "Số keywords có volume >100",
            },
            "overall_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 3,
                "description": "0-3 (count indicators passed)",
            },
            "overall_verdict": {
                "type": "string",
                "description": "STRONG | VIABLE | TOO_BROAD | TOO_NARROW | NO_DEMAND",
            },
            "recommendation": {
                "type": "string",
                "description": "Specific recommendation if not all pass",
            },
            "anna_persona_match": {
                "type": "string",
                "description": "nhan_vien_vp | me_bim_sua | chu_shop | custom | none",
            },
            "summary": {"type": "string"},
        },
        "required": [
            "niche_statement",
            "venture",
            "indicator_1_semantic_clarity_score",
            "indicator_1_pass",
            "indicator_2_fb_group_estimate",
            "indicator_2_pass",
            "indicator_3_pass_count",
            "indicator_3_pass",
            "overall_score",
            "overall_verdict",
            "summary",
        ],
    },
}


def build_niche_prompt(niche_statement: str, venture: str) -> str:
    return f"""Bạn là chuyên gia Niche Validation theo framework Solo Business Growth System v2 Stage 3.

# Niche statement cần validate
"{niche_statement}"

# Venture context
{venture}

# Task: 3-indicator validation

## Indicator 1: Semantic clarity
Rephrase niche statement 3 lần với 3 góc nhìn khác nhau. Score semantic match (0-1):
- 1.0: 3 paraphrase mô tả CÙNG nhóm khách + CÙNG nỗi đau + CÙNG giải pháp
- 0.85-0.99: Cùng nhóm khách, có thể khác cách phrase pain/solution
- 0.7-0.84: 2/3 paraphrase match, 1 lệch
- <0.7: paraphrase mô tả khác hoàn toàn → niche unclear

PASS nếu score ≥ 0.85.

## Indicator 2: Audience size (FB Group)
Estimate số FB groups Việt Nam fit niche này (knowledge-based, không thực scrape).
Liệt kê 3-5 sample group names có thể tồn tại.

PASS nếu estimate ≥ 100 groups.

## Indicator 3: Search demand
Estimate 5-10 keywords người ta sẽ search liên quan niche, mỗi keyword cho estimate monthly volume (Vietnamese market).

PASS nếu ≥ 5 keywords có volume > 100/month.

## Overall verdict
- STRONG (3/3 pass): proceed development
- VIABLE (2/3 pass): proceed với caveat về indicator fail
- TOO_BROAD: semantic >0.85 nhưng audience > 10K groups → quá rộng, narrow lại
- TOO_NARROW: semantic >0.85 nhưng audience <50 groups → quá hẹp, mở rộng
- NO_DEMAND: search volume thấp → consider khác niche

## Anna persona match
Match với 3 chân dung Anna canonical (Nhân viên VP / Mẹ bỉm sữa / Chủ shop) nếu có.

# Quality requirements
- KHÔNG bịa keyword volume, estimate honest dựa trên Vietnamese market knowledge
- KHÔNG generic, cụ thể với niche statement input
- KHÔNG em-dash, no forbidden term
- Recommendation MUST actionable nếu fail

Output qua tool submit_niche_validation.
"""


class NicheValidator(BaseBC):
    """BC Niche Validator, 3-indicator test for niche statement."""

    name = "niche_validator"
    scope = "Validate niche statement với 3-indicator test (Stage 3 framework v2)"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

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
        if event not in EXPECTED_EVENTS:
            return AgentResult(
                success=False,
                output_text=f"{self.name} không xử lý event này",
                output_payload={
                    "trigger_event": event,
                    "supported": list(EXPECTED_EVENTS),
                },
            )

        payload = ctx.payload or {}
        niche_statement = payload.get("niche_statement", "").strip()
        venture = ctx.venture_context or "all"

        if not niche_statement or len(niche_statement) < 10:
            return AgentResult(
                success=False,
                output_text="Missing niche_statement",
                output_payload={"error": "payload.niche_statement < 10 chars"},
            )

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "ANTHROPIC_API_KEY chưa set"},
            )

        prompt = build_niche_prompt(niche_statement, venture)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_VALIDATION_TOOL],
                tool_choice={"type": "tool", "name": "submit_niche_validation"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("niche_validator LLM fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        score = result.get("overall_score", 0)
        verdict = result.get("overall_verdict", "?")
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = f"niche validate score={score}/3 verdict={verdict} '{niche_statement[:60]}'"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:800],
            "keywords": ["niche_validator", venture, verdict.lower(), niche_statement[:50]],
            "tags": ["niche_validator", "stage_3", verdict.lower(), venture, date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"niche.validate {date_str} venture={venture} score={score}/3",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=result,
            emitted_memories=[memory_entry],
        )

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_niche_validation"
            ):
                return block.input or {}
        return {"error": "No tool_use block"}
