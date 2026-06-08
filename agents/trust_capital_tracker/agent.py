"""Trust Capital Tracker agent.

Apply Stage 13 framework v2 Trust Capital. Quarterly audit 4 indicator:
1. Authority signals: media mention + certification + years exp
2. Social proof: testimonial video + case study count
3. Expert positioning: publication (podcast guest, talk, book) count
4. Partnership/borrowed trust: collab + endorsement count

Trigger event: trust.quarterly_audit
Output: 4-quadrant dashboard + quarter-over-quarter delta + recommendation.
Emit canonical fact category=venture_state (sparse, 1 record per quarter).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

log = logging.getLogger("camas.trust_capital_tracker")

EXPECTED_EVENTS = {"trust.quarterly_audit"}

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 4000
DEFAULT_TIMEOUT = 120.0


SUBMIT_TRUST_AUDIT_TOOL = {
    "name": "submit_trust_audit",
    "description": "Submit Trust Capital quarterly audit 4-quadrant",
    "input_schema": {
        "type": "object",
        "properties": {
            "venture": {"type": "string"},
            "quarter": {"type": "string", "description": "Q1-2026, Q2-2026, etc."},
            "authority_signals_count": {"type": "integer"},
            "authority_signals_detail": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Media mention + certification + years exp",
            },
            "authority_score": {"type": "integer", "minimum": 0, "maximum": 10},
            "social_proof_count": {"type": "integer"},
            "social_proof_detail": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Testimonial video + case study",
            },
            "social_proof_score": {"type": "integer", "minimum": 0, "maximum": 10},
            "expert_positioning_count": {"type": "integer"},
            "expert_positioning_detail": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Podcast guest + talk + book + publication",
            },
            "expert_score": {"type": "integer", "minimum": 0, "maximum": 10},
            "partnership_count": {"type": "integer"},
            "partnership_detail": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Collab + endorsement + co-brand",
            },
            "partnership_score": {"type": "integer", "minimum": 0, "maximum": 10},
            "overall_trust_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 40,
                "description": "Sum 4 quadrant scores",
            },
            "qoq_delta": {
                "type": "string",
                "description": "Quarter-over-quarter delta vs previous (improved/stable/declined)",
            },
            "weakest_quadrant": {
                "type": "string",
                "description": "authority | social_proof | expert_positioning | partnership",
            },
            "recommendations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3-5 actions next quarter để improve",
            },
            "summary": {"type": "string"},
        },
        "required": [
            "venture",
            "quarter",
            "authority_score",
            "social_proof_score",
            "expert_score",
            "partnership_score",
            "overall_trust_score",
            "weakest_quadrant",
            "summary",
        ],
    },
}


def build_trust_prompt(
    venture: str, quarter: str, current_indicators: dict, previous_quarter: dict
) -> str:
    return f"""Bạn là chuyên gia Trust Capital tracking theo framework Solo Business Growth System v2 Stage 13.

# Venture
{venture}

# Quarter
{quarter}

# Current quarter indicators (from RAG retrieve)
{json.dumps(current_indicators, ensure_ascii=False, indent=2)[:2000]}

# Previous quarter for QoQ comparison
{json.dumps(previous_quarter, ensure_ascii=False, indent=2)[:1500]}

# Task

Audit Trust Capital 4 quadrant cho venture trong quý này:

## 1. Authority signals (0-10)
- Media mention count (PR, press, interview)
- Certification (MARA, official credentials)
- Years experience in domain
- Awards, recognition

## 2. Social proof (0-10)
- Testimonial video count
- Written case study count
- Customer success story (with metrics)
- User-generated content

## 3. Expert positioning (0-10)
- Podcast guest appearance count
- Speaking engagement count
- Book/publication count
- Webinar host count
- Open source contribution

## 4. Partnership/borrowed trust (0-10)
- Strategic partnership count
- Endorsement from authority figure
- Co-brand campaign count
- Mastermind community membership

## Output
- Score 0-10 per quadrant
- Overall trust score (sum 4 = 0-40)
- QoQ delta (improved/stable/declined)
- Weakest quadrant
- 3-5 specific recommendations next quarter

# Quality requirements
- KHÔNG bịa indicator không có evidence
- Reference specific count + name nếu có data
- Recommendations MUST actionable (vd: "Tham gia 2 podcast guest next quarter", not "tăng exposure")
- KHÔNG em-dash, no forbidden term

Output qua tool submit_trust_audit.
"""


class TrustCapitalTracker(BaseBC):
    """BC Trust Capital Tracker, Stage 13."""

    name = "trust_capital_tracker"
    scope = "Quarterly audit Trust Capital 4-quadrant (Stage 13 framework v2)"
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
        venture = ctx.venture_context or "all"
        quarter = payload.get("quarter") or self._current_quarter()

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "ANTHROPIC_API_KEY chưa set"},
            )

        # Retrieve current quarter indicators + previous quarter
        current_indicators = await self._retrieve_indicators(venture, quarter)
        previous_quarter = await self._retrieve_previous_quarter(venture, quarter)

        prompt = build_trust_prompt(venture, quarter, current_indicators, previous_quarter)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_TRUST_AUDIT_TOOL],
                tool_choice={"type": "tool", "name": "submit_trust_audit"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("trust_capital LLM fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        audit = self._parse_response(response)
        if "error" in audit:
            return AgentResult(success=False, output_text=audit["error"], output_payload=audit)

        overall = audit.get("overall_trust_score", 0)
        weakest = audit.get("weakest_quadrant", "?")
        qoq = audit.get("qoq_delta", "?")
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        summary = (
            f"trust audit {quarter} venture={venture} "
            f"overall={overall}/40 weakest={weakest} qoq={qoq}"
        )

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(audit, ensure_ascii=False)[:800],
            "keywords": ["trust_capital", venture, quarter, weakest],
            "tags": ["trust_capital_tracker", "stage_13", "quarterly_audit", venture, quarter],
            "venture": venture,
            "category": "venture_state",
            "context": f"trust.quarterly_audit {quarter} venture={venture} overall={overall}/40",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=audit,
            emitted_memories=[memory_entry],
        )

    async def _retrieve_indicators(self, venture: str, quarter: str) -> dict:
        """Retrieve current quarter trust indicators từ canonical memory."""
        if not self.memory.ready:
            return {}
        try:
            records = await self.memory.retrieve(
                query=f"trust authority testimonial partnership {venture} {quarter}",
                categories=["venture_state", "bio"],
                venture=venture if venture != "all" else None,
                k=20,
            )
            return {
                "retrieved_count": len(records),
                "samples": [
                    {"content": r.content[:200], "tags": r.tags[:5]}
                    for r in records[:10]
                ],
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("retrieve indicators fail: %r", exc)
            return {}

    async def _retrieve_previous_quarter(self, venture: str, quarter: str) -> dict:
        """Retrieve previous quarter trust audit."""
        if not self.memory.ready:
            return {}
        previous_quarter_str = self._previous_quarter(quarter)
        try:
            records = await self.memory.retrieve(
                query=f"trust audit {previous_quarter_str} {venture}",
                categories=["venture_state"],
                venture=venture if venture != "all" else None,
                k=5,
            )
            for r in records:
                if "trust_capital_tracker" in (r.tags or []) and previous_quarter_str in (
                    r.tags or []
                ):
                    return {
                        "previous_quarter": previous_quarter_str,
                        "content": r.content[:500],
                    }
            return {"previous_quarter": previous_quarter_str, "note": "no previous audit found"}
        except Exception as exc:  # noqa: BLE001
            log.warning("retrieve previous quarter fail: %r", exc)
            return {}

    @staticmethod
    def _current_quarter() -> str:
        now = datetime.now(tz=timezone.utc)
        q = (now.month - 1) // 3 + 1
        return f"Q{q}-{now.year}"

    @staticmethod
    def _previous_quarter(current: str) -> str:
        """Q2-2026 → Q1-2026, Q1-2026 → Q4-2025."""
        try:
            q_part, year_part = current.split("-")
            q = int(q_part.replace("Q", ""))
            year = int(year_part)
            if q == 1:
                return f"Q4-{year - 1}"
            return f"Q{q - 1}-{year}"
        except Exception:  # noqa: BLE001
            return "previous_quarter_unknown"

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_trust_audit"
            ):
                return block.input or {}
        return {"error": "No tool_use block"}
