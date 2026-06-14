"""L2.1 Vision Clarity Coach (NEW), Cohangai cohort 1 wizard.

Stage 2 framework v2 dual use. Help student clarify vision + life goal +
business motivation BEFORE jump into niche selection.

Trigger event: cohort.vision_clarity
Autonomy L1.
Output: Markdown vision statement + life goal map + 5-year roadmap suggestion.
Emit canonical fact category=profile (student-level vision artifact).
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

log = logging.getLogger("camas.l2_vision_clarity")

EXPECTED_EVENTS = {"cohort.vision_clarity"}

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 4000
DEFAULT_TIMEOUT = 120.0


SUBMIT_VISION_TOOL = {
    "name": "submit_vision_clarity",
    "description": "Submit vision clarity output cho student cohort",
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "string"},
            "venture": {"type": "string"},
            "vision_statement": {
                "type": "string",
                "description": "1-2 câu vision tổng cho 5 năm tới",
            },
            "life_goal_categories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "tài chính | gia đình | sức khoẻ | sự nghiệp | cộng đồng"},
                        "5_year_goal": {"type": "string"},
                        "1_year_goal": {"type": "string"},
                        "3_month_goal": {"type": "string"},
                    },
                },
            },
            "business_motivation": {
                "type": "string",
                "description": "Tại sao build solo business (vs corporate path)",
            },
            "non_negotiables": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Điều không thể compromise (vd: 2h/ngày family, không chuyển nước ngoài)",
            },
            "energy_drivers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Hoạt động cho student năng lượng",
            },
            "energy_drains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Hoạt động hút năng lượng → tránh design business gắn với chúng",
            },
            "5_year_roadmap": {
                "type": "string",
                "description": "Markdown roadmap 5 năm theo Y1/Y2/Y3/Y5 milestones",
            },
            "next_3_action_steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3 actions trong 30 ngày tới",
            },
            "anna_persona_match": {
                "type": "string",
                "description": "nhan_vien_vp | me_bim_sua | chu_shop | custom | none",
            },
            "markdown_report": {
                "type": "string",
                "description": "Full Markdown report cho student dashboard, format đẹp với headings ## + bullets, KHÔNG raw dict",
            },
            "summary": {"type": "string"},
        },
        "required": [
            "student_id",
            "venture",
            "vision_statement",
            "life_goal_categories",
            "business_motivation",
            "next_3_action_steps",
            "markdown_report",
            "summary",
        ],
    },
}


def build_vision_prompt(student_data: dict, venture: str) -> str:
    return f"""Bạn là Vision Clarity Coach cho Cohangai Cohort 1, applying framework Solo Business Growth System v2 Stage 2.

Triết lý: Trước khi pick niche, student phải CLEAR về vision + life goal + non-negotiables.
Many solo founder fail vì pick niche tốt nhưng KHÔNG align với life vision → burnout.

# Student profile
{json.dumps(student_data, ensure_ascii=False, indent=2)[:2500]}

# Venture context
{venture}

# Task

Build comprehensive vision clarity artifact cho student:

## 1. Vision statement (1-2 câu)
Tổng vision 5 năm tới. Concrete + emotional + specific.

## 2. Life goal categories (5 areas)
Mỗi area: 5-year + 1-year + 3-month goal.
- Tài chính (revenue, savings, investment)
- Gia đình (parenting, marriage, support parents)
- Sức khoẻ (physical, mental, sleep)
- Sự nghiệp (skills, identity, recognition)
- Cộng đồng (impact, network, give back)

## 3. Business motivation
Tại sao build solo business (vs corporate / vs no business)?
Identify true "why" (not surface like "kiếm tiền nhiều").

## 4. Non-negotiables
Điều student KHÔNG compromise (ví dụ: family time, location, ethics).
Business model PHẢI respect non-negotiables.

## 5. Energy drivers vs drains
- Drivers: activities cho student năng lượng (vd: dạy 1on1, write content)
- Drains: hút năng lượng (vd: cold calling, networking events)
- Design business gắn với drivers, AVOID drains nếu có thể.

## 6. 5-year roadmap (Markdown)
Format:
```
## Year 1 (2026-2027)
- Milestone 1: ...
- Milestone 2: ...

## Year 2
...

## Year 3
...

## Year 5
...
```

## 7. Next 3 action steps (30 ngày tới)
Concrete, measurable, schedulable.

## 8. Full markdown_report (BẮT BUỘC)

Build COMPLETE Markdown report dashboard-friendly. KHÔNG render raw dict object. Format chuẩn:

```
# Vision Clarity Report

## Vision 5 năm
[Vision statement câu hoàn chỉnh]

## 5 Life Goal Categories

### 1. Tài chính
- 5 năm: [goal]
- 1 năm: [goal]
- 3 tháng: [goal]

### 2. Gia đình
- 5 năm: ...
- 1 năm: ...
- 3 tháng: ...

(... tiếp 3 category còn lại)

## Business Motivation
[True why...]

## Non-Negotiables
- [item 1]
- [item 2]
- ...

## Energy Drivers vs Drains
**Drivers**:
- ...
**Drains**:
- ...

## 5-Year Roadmap
[markdown roadmap đã format]

## 3 Action Steps tuần tới
1. ...
2. ...
3. ...
```

Mỗi life_goal_category render thành sub-heading ### với 3 bullet (5 năm / 1 năm / 3 tháng). KHÔNG dump JSON.

# Quality requirements
- KHÔNG generic ("sống ý nghĩa"), MUST specific với student data
- Reference 3 chân dung Anna (NV VP / Mẹ bỉm / Chủ shop) nếu match
- Empathetic Vietnamese tone (Anna voice DNA: mộc mạc, concrete)
- KHÔNG em-dash, no forbidden term
- Roadmap milestone có timeline + measurable

Output qua tool submit_vision_clarity.
"""


class L2VisionClarity(BaseBC):
    """L2.1 Vision Clarity Coach (NEW) for Cohangai Cohort 1."""

    name = "l2_vision_clarity"
    scope = "Vision clarity coaching Stage 2 cho student Cohangai cohort 1 (NEW wizard)"
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
        student_data = payload.get("student_data", {})
        venture = ctx.venture_context or "cohangai"

        if not student_data:
            return AgentResult(
                success=False,
                output_text="Missing student_data",
                output_payload={"error": "payload.student_data empty"},
            )

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "ANTHROPIC_API_KEY chưa set"},
            )

        prompt = build_vision_prompt(student_data, venture)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_VISION_TOOL],
                tool_choice={"type": "tool", "name": "submit_vision_clarity"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("l2_vision_clarity LLM fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        vision = self._parse_response(response)
        if "error" in vision:
            return AgentResult(success=False, output_text=vision["error"], output_payload=vision)

        student_id = vision.get("student_id", "unknown")
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = f"vision_clarity student={student_id} venture={venture}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(vision, ensure_ascii=False)[:800],
            "keywords": ["vision_clarity", "cohort_1", student_id, venture],
            "tags": ["l2", "vision_clarity", "stage_2", "cohort_1", venture, date_str],
            "venture": venture,
            "category": "profile",
            "context": f"cohort.vision_clarity {date_str} student={student_id}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=vision,
            emitted_memories=[memory_entry],
        )

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_vision_clarity"
            ):
                return block.input or {}
        return {"error": "No tool_use block"}
