"""Perfect Webinar Designer agent.

Stage 9 enhance per framework v2. Apply Russell Brunson Expert Secrets Perfect
Webinar 90min framework: Why → What → How → Case Study → Stack → Close.

Triết lý: 90min webinar bán high ticket KHÔNG phải free knowledge dump. Cấu
trúc cụ thể: 5 min intro + 10 min hook + 25 min big domino + 25 min stack +
15 min CTA + 10 min Q&A.

Trigger event: webinar.design_perfect_90min
Autonomy L2 (Anna review trước run live).
Output: slide-by-slide 90min webinar structure + script per section.
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

log = logging.getLogger("camas.perfect_webinar_designer")

EXPECTED_EVENTS = {"webinar.design_perfect_90min"}

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 7000
DEFAULT_TIMEOUT = 240.0


SUBMIT_WEBINAR_TOOL = {
    "name": "submit_perfect_webinar",
    "description": "Submit 90min webinar design Brunson Perfect Webinar framework",
    "input_schema": {
        "type": "object",
        "properties": {
            "venture": {"type": "string"},
            "webinar_title": {"type": "string", "description": "Magnetic title"},
            "target_offer": {"type": "string"},
            "target_offer_price_vnd": {"type": "integer"},
            "section_1_intro": {
                "type": "object",
                "description": "5 min intro: who am I + what learn today",
                "properties": {
                    "duration_minutes": {"type": "integer"},
                    "key_message": {"type": "string"},
                    "slides_outline": {"type": "array", "items": {"type": "string"}},
                },
            },
            "section_2_hook_big_promise": {
                "type": "object",
                "description": "10 min hook + big promise",
                "properties": {
                    "duration_minutes": {"type": "integer"},
                    "big_promise": {"type": "string"},
                    "epiphany_bridge_story": {"type": "string"},
                    "slides_outline": {"type": "array", "items": {"type": "string"}},
                },
            },
            "section_3_big_domino_why": {
                "type": "object",
                "description": "25 min Why (Big Domino, identity shift)",
                "properties": {
                    "duration_minutes": {"type": "integer"},
                    "big_domino_belief": {
                        "type": "string",
                        "description": "1 niềm tin lớn nếu đổ thì mọi objection đổ theo",
                    },
                    "3_secrets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "secret": {"type": "string"},
                                "story": {"type": "string"},
                                "false_belief_destroyed": {"type": "string"},
                                "new_belief_planted": {"type": "string"},
                            },
                        },
                    },
                    "slides_outline": {"type": "array", "items": {"type": "string"}},
                },
            },
            "section_4_what_how": {
                "type": "object",
                "description": "20 min What + How (high-level method)",
                "properties": {
                    "duration_minutes": {"type": "integer"},
                    "framework_taught": {"type": "string"},
                    "key_steps": {"type": "array", "items": {"type": "string"}},
                    "slides_outline": {"type": "array", "items": {"type": "string"}},
                },
            },
            "section_5_case_study": {
                "type": "object",
                "description": "10 min case study (proof)",
                "properties": {
                    "duration_minutes": {"type": "integer"},
                    "case_study_name": {"type": "string"},
                    "before_state": {"type": "string"},
                    "after_state": {"type": "string"},
                    "metric_outcome": {"type": "string"},
                    "slides_outline": {"type": "array", "items": {"type": "string"}},
                },
            },
            "section_6_stack_offer": {
                "type": "object",
                "description": "15 min stack offer (Brunson Stack Method)",
                "properties": {
                    "duration_minutes": {"type": "integer"},
                    "core_offer": {"type": "string"},
                    "stack_items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item": {"type": "string"},
                                "value_vnd": {"type": "integer"},
                            },
                        },
                    },
                    "total_stack_value_vnd": {"type": "integer"},
                    "today_price_vnd": {"type": "integer"},
                    "guarantee": {"type": "string"},
                    "slides_outline": {"type": "array", "items": {"type": "string"}},
                },
            },
            "section_7_qa_close": {
                "type": "object",
                "description": "5 min Q&A + close",
                "properties": {
                    "duration_minutes": {"type": "integer"},
                    "common_objections": {"type": "array", "items": {"type": "string"}},
                    "trial_closes": {"type": "array", "items": {"type": "string"}},
                    "scarcity_urgency": {"type": "string"},
                },
            },
            "total_duration_minutes": {"type": "integer"},
            "expected_conversion_rate_pct": {"type": "number"},
            "markdown_full_script": {
                "type": "string",
                "description": "Full Markdown 90min script slide-by-slide",
            },
            "summary": {"type": "string"},
        },
        "required": [
            "venture",
            "webinar_title",
            "target_offer",
            "target_offer_price_vnd",
            "section_3_big_domino_why",
            "section_6_stack_offer",
            "total_duration_minutes",
            "markdown_full_script",
            "summary",
        ],
    },
}


def build_webinar_prompt(venture: str, target_offer: dict, persona: dict, key_secrets: list) -> str:
    return f"""Bạn là Webinar Designer theo Russell Brunson Expert Secrets Perfect Webinar 90min framework.

Triết lý 90min webinar: KHÔNG free knowledge dump. Cấu trúc:
- 5 min intro (who + what learn)
- 10 min hook + big promise
- 25 min Big Domino + 3 secrets (identity shift)
- 20 min What + How (high-level method only, NOT step-by-step)
- 10 min case study (proof)
- 15 min stack offer
- 5 min Q&A + close

Total = 90 min.

# Venture
{venture}

# Target offer
{json.dumps(target_offer, ensure_ascii=False, indent=2)[:1500]}

# Persona
{json.dumps(persona, ensure_ascii=False, indent=2)[:1500]}

# Key secrets to teach (Anna's framework)
{json.dumps(key_secrets, ensure_ascii=False)[:1000]}

# Task

Design 90min webinar slide-by-slide:

## Section 1 (5 min): Intro
- Who am I + credibility
- What you'll learn today

## Section 2 (10 min): Hook + Big Promise
- Magnetic hook
- Big promise specific
- Epiphany Bridge story (vulnerability moment + turning point)

## Section 3 (25 min): Big Domino Why
- **Big Domino belief**: 1 niềm tin lớn của customer, nếu đổ → mọi objection đổ theo
- 3 secrets, mỗi secret:
  - secret statement
  - story (Anna's real story or case study)
  - false belief destroyed
  - new belief planted
- Identity shift (customer trở thành "someone who...")

## Section 4 (20 min): What + How
- Framework taught (high-level, KHÔNG step-by-step chi tiết)
- Key steps (5-7 bullets)
- Why this works (logic)

## Section 5 (10 min): Case Study
- Real customer success
- Before / After / Metric outcome

## Section 6 (15 min): Stack Offer
- Core offer
- Stack 6-10 items, mỗi cái value_vnd
- Total stack value (anchor 5-10x today price)
- Today price (drop dramatic)
- Guarantee

## Section 7 (5 min): Q&A + Close
- Common objections + trial closes
- Scarcity + urgency

## Expected conversion rate
Realistic Vietnamese market (5-15% typical for warm audience).

## Full Markdown script
Slide-by-slide for Anna read/practice.

# Quality requirements
- Tổng duration = 90 min ±5
- Big Domino must be SPECIFIC + EMOTIONAL
- 3 secrets each có Anna's real story
- Stack value 5-10x today price
- Vietnamese tone Anna voice (Hằng/bạn)
- KHÔNG em-dash

Output qua tool submit_perfect_webinar.
"""


class PerfectWebinarDesigner(BaseBC):
    """Perfect Webinar Designer 90min Brunson framework (Stage 9 enhance)."""

    name = "perfect_webinar_designer"
    scope = "Design 90min Brunson Perfect Webinar slide-by-slide (Stage 9 enhance)"
    autonomy_level = AutonomyLevel.L2_APPROVE  # Anna review trước run live
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
        if event not in EXPECTED_EVENTS:
            return AgentResult(
                success=False,
                output_text=f"{self.name} không xử lý event này",
                output_payload={"trigger_event": event, "supported": list(EXPECTED_EVENTS)},
            )

        payload = ctx.payload or {}
        venture = ctx.venture_context or "breakout"
        target_offer = payload.get("target_offer", {})
        persona = payload.get("persona", {})
        key_secrets = payload.get("key_secrets", [])

        if not target_offer:
            return AgentResult(
                success=False,
                output_text="Missing target_offer",
                output_payload={"error": "target_offer empty"},
            )

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_webinar_prompt(venture, target_offer, persona, key_secrets)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_WEBINAR_TOOL],
                tool_choice={"type": "tool", "name": "submit_perfect_webinar"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("perfect_webinar LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        title = result.get("webinar_title", "")[:60]
        duration = result.get("total_duration_minutes", 0)
        conv = result.get("expected_conversion_rate_pct", 0)
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = f"webinar design venture={venture} '{title}' duration={duration}min conv={conv}%"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:800],
            "keywords": ["webinar_perfect_90min", venture, title],
            "tags": ["perfect_webinar_designer", "stage_9", "brunson", venture, date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"webinar.design_perfect_90min {date_str} venture={venture}",
        }

        return AgentResult(success=True, output_text=summary, output_payload=result, emitted_memories=[memory_entry])

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_perfect_webinar":
                return block.input or {}
        return {"error": "No tool_use block"}
