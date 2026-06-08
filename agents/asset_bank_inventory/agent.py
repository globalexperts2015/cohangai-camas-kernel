"""Asset Bank Inventory agent.

Stage 1.1 framework v2 Solo Business Growth System. Enumerate tài sản cá nhân
trước khi tìm sản phẩm. Triết lý: "Nhiều người đi tìm sản phẩm. Thực tế phải
đi tìm tài sản trước."

10 asset categories:
1. Kiến thức (Knowledge)
2. Kinh nghiệm (Experience)
3. Trải nghiệm (Life experience)
4. Học vấn (Education)
5. Chứng chỉ (Certification)
6. Network
7. Quy trình đã xây (Built process)
8. Case study
9. Thành công (Success)
10. Thất bại (Failure as asset)

Trigger event: asset.inventory_build
Autonomy L1.
Output: Asset Bank JSON categorized + monetization potential per asset.
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

log = logging.getLogger("camas.asset_bank_inventory")

EXPECTED_EVENTS = {"asset.inventory_build"}

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 5000
DEFAULT_TIMEOUT = 150.0


SUBMIT_ASSET_BANK_TOOL = {
    "name": "submit_asset_bank",
    "description": "Submit Asset Bank Inventory 10 categories",
    "input_schema": {
        "type": "object",
        "properties": {
            "founder_id": {"type": "string"},
            "venture": {"type": "string"},
            "assets_knowledge": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "asset": {"type": "string"},
                        "years_depth": {"type": "string"},
                        "monetization_potential": {"type": "string", "description": "high | medium | low"},
                        "evidence": {"type": "string"},
                    },
                },
            },
            "assets_experience": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "asset": {"type": "string"},
                        "scope": {"type": "string", "description": "vd: scale 25 tỷ Speakout, quản 70 NS"},
                        "monetization_potential": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                },
            },
            "assets_life_experience": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "asset": {"type": "string"},
                        "context": {"type": "string", "description": "vd: du học, định cư, solo business"},
                        "monetization_potential": {"type": "string"},
                    },
                },
            },
            "assets_education": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "degree": {"type": "string"},
                        "institution": {"type": "string"},
                        "year": {"type": "string"},
                    },
                },
            },
            "assets_certification": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "cert": {"type": "string"},
                        "year": {"type": "string"},
                        "expires": {"type": "string"},
                    },
                },
            },
            "assets_network": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "network": {"type": "string"},
                        "size": {"type": "string"},
                        "monetization_potential": {"type": "string"},
                    },
                },
            },
            "assets_built_process": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "process": {"type": "string"},
                        "documentation_state": {"type": "string"},
                        "monetization_potential": {"type": "string"},
                    },
                },
            },
            "assets_case_study": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "case": {"type": "string"},
                        "result": {"type": "string"},
                        "story_arc": {"type": "string"},
                    },
                },
            },
            "assets_success": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "win": {"type": "string"},
                        "metric": {"type": "string"},
                        "year": {"type": "string"},
                    },
                },
            },
            "assets_failure": {
                "type": "array",
                "description": "Failures = asset cho storytelling + lesson",
                "items": {
                    "type": "object",
                    "properties": {
                        "failure": {"type": "string"},
                        "lesson": {"type": "string"},
                        "year": {"type": "string"},
                    },
                },
            },
            "top_5_monetizable_assets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "asset": {"type": "string"},
                        "category": {"type": "string"},
                        "product_idea": {"type": "string", "description": "Sản phẩm/service xây từ asset này"},
                        "estimated_market_size_vnd": {"type": "integer"},
                    },
                },
            },
            "asset_count_total": {"type": "integer"},
            "high_potential_count": {"type": "integer"},
            "markdown_report": {"type": "string", "description": "Full Markdown Asset Bank cho dashboard"},
            "summary": {"type": "string"},
        },
        "required": [
            "founder_id",
            "venture",
            "assets_knowledge",
            "assets_experience",
            "top_5_monetizable_assets",
            "asset_count_total",
            "markdown_report",
            "summary",
        ],
    },
}


def build_asset_prompt(founder_id: str, founder_data: dict, venture: str) -> str:
    return f"""Bạn là Asset Bank Coach theo framework Solo Business Growth System v2 Stage 1.1.

Triết lý: "Nhiều người đi tìm sản phẩm. Thực tế phải đi tìm tài sản trước."

# Founder
ID: {founder_id}
Venture: {venture}

# Founder data input
{json.dumps(founder_data, ensure_ascii=False, indent=2)[:3500]}

# Task

Enumerate Asset Bank 10 categories cho founder:

## 1. Kiến thức (Knowledge)
Skills cụ thể (vd: Shopify, GHL, AI, Tiếng Anh, Di trú). Mỗi cái: years_depth + monetization_potential (high/medium/low) + evidence.

## 2. Kinh nghiệm (Experience)
Business/career milestones cụ thể (vd: Build Speakout 25 tỷ, quản 70 NS). scope + evidence.

## 3. Trải nghiệm (Life experience)
Hành trình cá nhân (vd: du học, định cư, solo business). context + monetization_potential.

## 4. Học vấn (Education)
Degrees + institutions + year.

## 5. Chứng chỉ (Certification)
Cert name + year + expires.

## 6. Network
Communities + numbers + monetization_potential.

## 7. Quy trình đã xây (Built process)
SOP/workflow/system đã document. documentation_state + monetization_potential.

## 8. Case study
Real customer success từ work cũ. case + result + story_arc.

## 9. Thành công (Success)
Wins specific với metric + year.

## 10. Thất bại (Failure as asset)
Failures = asset cho storytelling. failure + lesson + year. KHÔNG public-shaming, dùng để empathy + authenticity.

## Top 5 Monetizable Assets
Pick 5 assets cross-category với highest monetization potential:
- asset + category
- product_idea (sản phẩm/service build từ asset)
- estimated_market_size_vnd (Vietnamese market)

## Markdown report
Full dashboard-friendly cho founder review.

# Quality requirements
- Specific với founder data, KHÔNG generic
- Numbers + years + metrics rõ
- Failures = asset, KHÔNG là weakness
- KHÔNG em-dash, no "mẹ đơn thân", no Perth/Adelaide
- Pronoun "bạn"

Output qua tool submit_asset_bank.
"""


class AssetBankInventory(BaseBC):
    """Asset Bank Inventory, Stage 1.1 framework v2."""

    name = "asset_bank_inventory"
    scope = "Enumerate founder asset bank 10 categories trước khi tìm sản phẩm (Stage 1.1)"
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
                output_payload={"trigger_event": event, "supported": list(EXPECTED_EVENTS)},
            )

        payload = ctx.payload or {}
        founder_id = payload.get("founder_id", "unknown")
        founder_data = payload.get("founder_data", {})
        venture = ctx.venture_context or "breakout"

        if not founder_data:
            return AgentResult(
                success=False,
                output_text="Missing founder_data",
                output_payload={"error": "payload.founder_data empty"},
            )

        if not self.llm.ready:
            return AgentResult(success=False, output_text="LLM not ready", output_payload={"error": "LLM not ready"})

        prompt = build_asset_prompt(founder_id, founder_data, venture)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_ASSET_BANK_TOOL],
                tool_choice={"type": "tool", "name": "submit_asset_bank"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("asset_bank LLM fail: %r", exc)
            return AgentResult(success=False, output_text=f"LLM fail: {exc}", output_payload={"error": str(exc)})

        bank = self._parse_response(response)
        if "error" in bank:
            return AgentResult(success=False, output_text=bank["error"], output_payload=bank)

        total = bank.get("asset_count_total", 0)
        high = bank.get("high_potential_count", 0)
        top5 = len(bank.get("top_5_monetizable_assets", []))
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = f"asset bank founder={founder_id} total={total} high_potential={high} top5_count={top5}"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(bank, ensure_ascii=False)[:800],
            "keywords": ["asset_bank", "stage_1_1", founder_id, venture],
            "tags": ["asset_bank_inventory", "stage_1_1", venture, date_str],
            "venture": venture,
            "category": "profile",
            "context": f"asset.inventory_build {date_str} founder={founder_id} total={total}",
        }

        return AgentResult(success=True, output_text=summary, output_payload=bank, emitted_memories=[memory_entry])

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "submit_asset_bank":
                return block.input or {}
        return {"error": "No tool_use block"}
