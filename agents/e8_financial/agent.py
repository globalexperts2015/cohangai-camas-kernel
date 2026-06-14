"""E8 Financial Feasibility Engine. BreakoutOS CHỌN module Engine 6/9.

Hybrid: deterministic calculator (Python) + Haiku LLM narrative + GO/NO-GO verdict.
Weight 20% trong tổng Opportunity Score.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from kernel.base_agent import (
    AgentResult, AutonomyLevel, BaseBC, EscalationTarget, ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

from .calculator import calculate_financial_feasibility

log = logging.getLogger("camas.e8_financial")
DEFAULT_MODEL = "claude-haiku-4-5"  # Haiku đủ cho narrative, deterministic calc đã có
DEFAULT_MAX_TOKENS = 2500
DEFAULT_TIMEOUT = 60.0
EXPECTED_EVENTS = {"cohort.financial", "wizard.financial"}


def build_narrative_prompt(calc_result: dict[str, Any], context: dict[str, Any]) -> str:
    chain = calc_result.get("chain", {})
    flags = calc_result.get("flags", [])
    verdict = calc_result.get("verdict", "?")
    score = calc_result.get("financial_viability_score", 0)
    ctx_json = json.dumps(context or {}, ensure_ascii=False, indent=2)[:1200]

    return f"""Bạn là E8 Financial Feasibility Engine narrative writer (BreakoutOS CHỌN module).

Calculator đã tính xong. Nhiệm vụ của bạn: viết báo cáo markdown 350-550 từ tiếng Việt giải thích cho founder.

# Tính toán chi tiết (deterministic)
```json
{json.dumps(calc_result, ensure_ascii=False, indent=2)[:2500]}
```

# Context opportunity
```json
{ctx_json}
```

# Cấu trúc báo cáo

## Tóm tắt
1-2 câu: target {chain.get('revenue_year_vnd', 0):,}đ doanh thu năm cần {chain.get('customers_needed_year', 0)} khách → verdict {verdict}.

## Chain calculation (giải thích)
- Margin/order
- Số đơn cần bán/năm
- Số khách hàng/năm
- Số lead/năm
- Traffic/năm
- Ngân sách quảng cáo/tháng

## Cảnh báo (nếu có flags)
Mỗi flag 1 câu giải thích cho founder hiểu rủi ro cụ thể.

## Verdict
{verdict} score {score}/100. Giải thích lý do.

# Rules

1. KHÔNG bịa số liệu. CHỈ dùng numbers từ chain object.
2. Diễn giải numbers thành ngôn ngữ founder Việt hiểu được.
3. Format VND có dấu phẩy ngàn (vd: 3,000,000đ).
4. Tiếng Việt thuần, câu ngắn 5-15 từ, KHÔNG em-dash.
5. Trả về CHỈ markdown report, không kèm code block fence.
"""


class E8Financial(BaseBC):
    name = "e8_financial"
    scope = (
        "Financial Feasibility Engine. Deterministic chain (profit → AOV → orders → customers → "
        "leads → traffic → ad budget) + Haiku narrative + GO/NO-GO verdict. Weight 20%."
    )
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(self, llm: LLMLayer, memory: Optional[MemoryLayer] = None, model: str = DEFAULT_MODEL):
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model
        log.info("E8 init model=%s", model)

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(success=False, output_text=f"unsupported event {event}",
                               output_payload={"supported": sorted(EXPECTED_EVENTS)})
        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")
        venture = ctx.venture_context or "cohangai"

        raw = payload.get("financial_input")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return AgentResult(success=False, output_text="financial_input must be valid JSON",
                                   output_payload={"error": "invalid_json"})
        else:
            parsed = payload

        profit_target_vnd = int(parsed.get("profit_target_vnd", 0) or 0)
        aov_vnd = int(parsed.get("aov_vnd", 0) or 0)
        margin_pct = float(parsed.get("margin_pct", 0) or 0)
        conversion_rate_pct = float(parsed.get("conversion_rate_pct", 2.0) or 2.0)
        optin_rate_pct = float(parsed.get("optin_rate_pct", 20.0) or 20.0)
        repeat_purchase_ratio = float(parsed.get("repeat_purchase_ratio", 1.0) or 1.0)
        cac_target_vnd = int(parsed.get("cac_target_vnd", 0) or 0)
        months = int(parsed.get("months", 12) or 12)

        if profit_target_vnd <= 0 or aov_vnd <= 0 or margin_pct <= 0:
            return AgentResult(
                success=False,
                output_text="missing profit_target_vnd / aov_vnd / margin_pct",
                output_payload={"error": "missing_required_inputs"},
            )

        # Deterministic calculation
        calc_result = calculate_financial_feasibility(
            profit_target_vnd=profit_target_vnd,
            aov_vnd=aov_vnd,
            margin_pct=margin_pct,
            conversion_rate_pct=conversion_rate_pct,
            optin_rate_pct=optin_rate_pct,
            repeat_purchase_ratio=repeat_purchase_ratio,
            cac_target_vnd=cac_target_vnd,
            months=months,
        )
        if "error" in calc_result:
            return AgentResult(success=False, output_text=calc_result["error"],
                               output_payload={"error": calc_result["error"]})

        # LLM narrative
        narrative = ""
        if self.llm.ready:
            try:
                response = await self.llm.client.messages.create(
                    model=self.model,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    messages=[{"role": "user", "content": build_narrative_prompt(calc_result, parsed)}],
                    timeout=DEFAULT_TIMEOUT,
                )
                # Extract text
                for block in response.content or []:
                    if getattr(block, "type", None) == "text":
                        narrative += getattr(block, "text", "")
            except Exception as exc:
                log.warning("E8 narrative LLM fail: %r", exc)
                narrative = f"## Tóm tắt\n{calc_result.get('verdict', '?')} score {calc_result.get('financial_viability_score', 0)}/100. Narrative LLM failed."

        output = {
            **calc_result,
            "financial_report": narrative,
        }

        score = calc_result.get("financial_viability_score", 0)
        verdict = calc_result.get("verdict", "?")
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        mem = {
            "agent_name": self.name,
            "content_summary": f"financial student={student_id} profit_target={profit_target_vnd:,} verdict={verdict} score={score}",
            "keywords": ["financial", "chon_module", student_id, f"score-{score}"],
            "tags": ["e8", "financial", "chon_module", "engine_6_of_9", verdict.lower(), date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"chon.financial {date_str} student={student_id} score={score} verdict={verdict}",
        }
        return AgentResult(
            success=True,
            output_text=f"e8_financial student={student_id} verdict={verdict} score={score}/100",
            output_payload=output,
            emitted_memories=[mem],
        )
