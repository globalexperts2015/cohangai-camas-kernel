"""Perfect Webinar Designer agent (flat schema fix per Sprint 14 anti-pattern 11).

Stage 9 enhance per framework v2. Apply Brunson Expert Secrets Perfect Webinar
90min framework: Why → What → How → Case Study → Stack → Close.

Trigger event: webinar.design_perfect_90min
Autonomy L2.
Output: 90min webinar structure flat schema + Markdown script.
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

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 7000
DEFAULT_TIMEOUT = 240.0


SUBMIT_WEBINAR_TOOL = {
    "name": "submit_perfect_webinar",
    "description": "Submit 90min webinar design (flat schema)",
    "input_schema": {
        "type": "object",
        "properties": {
            "venture": {"type": "string"},
            "webinar_title": {"type": "string"},
            "target_offer": {"type": "string"},
            "target_offer_price_vnd": {"type": "integer"},
            "total_duration_minutes": {"type": "integer"},
            "expected_conversion_rate_pct": {"type": "number"},
            "s1_intro_minutes": {"type": "integer"},
            "s1_intro_key_message": {"type": "string"},
            "s1_intro_slides": {"type": "array", "items": {"type": "string"}},
            "s2_hook_minutes": {"type": "integer"},
            "s2_big_promise": {"type": "string"},
            "s2_epiphany_bridge_story": {"type": "string"},
            "s2_slides": {"type": "array", "items": {"type": "string"}},
            "s3_big_domino_minutes": {"type": "integer"},
            "s3_big_domino_belief": {
                "type": "string",
                "description": "1 niềm tin lớn nếu đổ thì mọi objection đổ theo",
            },
            "s3_secret_1": {"type": "string"},
            "s3_secret_1_story": {"type": "string"},
            "s3_secret_1_false_belief": {"type": "string"},
            "s3_secret_1_new_belief": {"type": "string"},
            "s3_secret_2": {"type": "string"},
            "s3_secret_2_story": {"type": "string"},
            "s3_secret_2_false_belief": {"type": "string"},
            "s3_secret_2_new_belief": {"type": "string"},
            "s3_secret_3": {"type": "string"},
            "s3_secret_3_story": {"type": "string"},
            "s3_secret_3_false_belief": {"type": "string"},
            "s3_secret_3_new_belief": {"type": "string"},
            "s4_what_how_minutes": {"type": "integer"},
            "s4_framework_taught": {"type": "string"},
            "s4_key_steps": {"type": "array", "items": {"type": "string"}},
            "s5_case_study_minutes": {"type": "integer"},
            "s5_case_study_name": {"type": "string"},
            "s5_before_state": {"type": "string"},
            "s5_after_state": {"type": "string"},
            "s5_metric_outcome": {"type": "string"},
            "s6_stack_minutes": {"type": "integer"},
            "s6_core_offer": {"type": "string"},
            "s6_stack_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item": {"type": "string"},
                        "value_vnd": {"type": "integer"},
                    },
                },
                "description": "Stack 6-10 items",
            },
            "s6_total_stack_value_vnd": {"type": "integer"},
            "s6_today_price_vnd": {"type": "integer"},
            "s6_guarantee": {"type": "string"},
            "s7_qa_minutes": {"type": "integer"},
            "s7_common_objections": {"type": "array", "items": {"type": "string"}},
            "s7_trial_closes": {"type": "array", "items": {"type": "string"}},
            "s7_scarcity_urgency": {"type": "string"},
            "markdown_full_script": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": [
            "venture",
            "webinar_title",
            "target_offer",
            "target_offer_price_vnd",
            "total_duration_minutes",
            "s3_big_domino_belief",
            "s3_secret_1",
            "s3_secret_2",
            "s3_secret_3",
            "s6_core_offer",
            "s6_stack_items",
            "s6_total_stack_value_vnd",
            "s6_today_price_vnd",
            "markdown_full_script",
            "summary",
        ],
    },
}


def build_webinar_prompt(venture: str, target_offer: dict, persona: dict, key_secrets: list) -> str:
    return f"""Bạn là Webinar Designer theo Brunson Expert Secrets Perfect Webinar 90min framework.

Cấu trúc 90 min:
- 5 min intro (who + what)
- 10 min hook + big promise
- 25 min Big Domino + 3 secrets
- 20 min What + How
- 10 min case study
- 15 min stack offer
- 5 min Q&A close

# Venture
{venture}

# Target offer
{json.dumps(target_offer, ensure_ascii=False, indent=2)[:1500]}

# Persona
{json.dumps(persona, ensure_ascii=False, indent=2)[:1500]}

# Key secrets hints
{json.dumps(key_secrets, ensure_ascii=False)[:800]}

# Task

Output ALL fields (flat schema):

## Section 1 (5 min): Intro
- s1_intro_minutes (5)
- s1_intro_key_message
- s1_intro_slides (3-5 slides)

## Section 2 (10 min): Hook + Big Promise
- s2_hook_minutes (10)
- s2_big_promise (specific)
- s2_epiphany_bridge_story (vulnerability moment + turning point)
- s2_slides

## Section 3 (25 min): Big Domino + 3 secrets
- s3_big_domino_minutes (25)
- s3_big_domino_belief (1 belief nếu đổ → mọi objection đổ)
- s3_secret_1 + story + false_belief + new_belief
- s3_secret_2 + story + false_belief + new_belief
- s3_secret_3 + story + false_belief + new_belief

## Section 4 (20 min): What + How
- s4_what_how_minutes (20)
- s4_framework_taught
- s4_key_steps (5-7)

## Section 5 (10 min): Case Study
- s5_case_study_minutes (10)
- s5_case_study_name
- s5_before_state + s5_after_state + s5_metric_outcome

## Section 6 (15 min): Stack Offer
- s6_stack_minutes (15)
- s6_core_offer
- s6_stack_items (6-10 items với value_vnd)
- s6_total_stack_value_vnd (5-10x today price)
- s6_today_price_vnd
- s6_guarantee

## Section 7 (5 min): Q&A Close
- s7_qa_minutes (5)
- s7_common_objections + trial_closes
- s7_scarcity_urgency

## Total + conversion + markdown_full_script

# Quality
- Big Domino SPECIFIC + EMOTIONAL
- 3 secrets có Anna's real story
- Stack value 5-10x today price
- Anna voice (Hằng/bạn)
- KHÔNG em-dash

Output qua tool submit_perfect_webinar.
"""


class PerfectWebinarDesigner(BaseBC):
    """Perfect Webinar Designer 90min flat schema."""

    name = "perfect_webinar_designer"
    scope = "Design 90min Brunson Perfect Webinar (Stage 9 enhance, flat schema)"
    autonomy_level = AutonomyLevel.L2_APPROVE
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = True
    requires_compliance_gate = True

    def __init__(self, llm: LLMLayer, memory: MemoryLayer, model: str = DEFAULT_MODEL) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(success=False, output_text=f"unsupported {event}", output_payload={"supported": list(EXPECTED_EVENTS)})

        payload = ctx.payload or {}
        venture = ctx.venture_context or "breakout"
        target_offer = payload.get("target_offer", {})
        persona = payload.get("persona", {})
        key_secrets = payload.get("key_secrets", [])

        if not target_offer:
            return AgentResult(success=False, output_text="Missing target_offer", output_payload={"error": "target_offer empty"})

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_webinar_prompt(venture, target_offer, persona, key_secrets)

        try:
            response = await self.llm.client.messages.create(
                model=self.model, max_tokens=DEFAULT_MAX_TOKENS,
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
        domino = bool(result.get("s3_big_domino_belief"))
        stack = len(result.get("s6_stack_items", []))
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = f"webinar venture={venture} '{title}' duration={duration}min conv={conv}% domino={domino} stack={stack}"

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
