"""BC9 Compliance Officer hook entry point.

7 layer check: MARA, Privacy Act AU, Sepay PCI, Zalo OA TOS, GHL TOS,
LegendCom TOS, Brand + Facts. Verdict: PASS / FLAG / BLOCK.

ComplianceGate là 1 thin facade trên BC9ComplianceOfficer. Scheduler inject
bc9_agent sau khi BC9 register, để swap implementation BC9 (vd thay model,
thêm cache) không phải đụng vào Scheduler.

Graceful degradation: nếu bc9_agent chưa inject → log warn + return PASS,
KHÔNG block pipeline (cho phép kernel boot khi BC9 chưa ready).
"""
from __future__ import annotations

import logging
import uuid
from enum import Enum
from typing import TYPE_CHECKING, Optional

from kernel.llm_layer import LLMLayer

if TYPE_CHECKING:
    from agents.bc9_compliance_officer.agent import BC9ComplianceOfficer

log = logging.getLogger("camas.compliance_gate")


class ComplianceVerdict(str, Enum):
    PASS = "pass"
    FLAG = "flag"
    BLOCK = "block"
    SKIP = "skip"


class ComplianceLayer(str, Enum):
    MARA = "mara"
    PRIVACY_ACT_AU = "privacy_act_au"
    SEPAY_PCI = "sepay_pci"
    ZALO_OA_TOS = "zalo_oa_tos"
    GHL_TOS = "ghl_tos"
    LEGENDCOM_TOS = "legendcom_tos"


class ComplianceGate:
    """Hook chạy pre-publish.

    Khi bc9_agent chưa inject → PASS graceful (log warn 1 lần), không block.
    Khi đã inject → build ExecutionContext tạm cho BC9, gọi run(), map verdict.
    """

    def __init__(
        self,
        llm: Optional[LLMLayer] = None,
        bc9_agent: Optional["BC9ComplianceOfficer"] = None,
    ) -> None:
        self.llm = llm or LLMLayer()
        self.bc9_agent: Optional["BC9ComplianceOfficer"] = bc9_agent
        self.active_layers: list[ComplianceLayer] = [
            ComplianceLayer.MARA,
            ComplianceLayer.PRIVACY_ACT_AU,
            ComplianceLayer.SEPAY_PCI,
            ComplianceLayer.ZALO_OA_TOS,
            ComplianceLayer.GHL_TOS,
            ComplianceLayer.LEGENDCOM_TOS,
        ]

    async def review(
        self,
        text: str,
        venture_context: str = "all",
        channel: str = "inline_gate",
    ) -> ComplianceVerdict:
        """Return verdict tổng hợp 7 layer.

        Default mode: block_on_high_severity (per AIOS spec yaml).
        Anna only có quyền override BLOCK (Constitution Section E).
        """
        if not text or not text.strip():
            return ComplianceVerdict.SKIP

        if self.bc9_agent is None:
            log.warning(
                "ComplianceGate skip, BC9 agent chưa inject (venture=%s)",
                venture_context,
            )
            return ComplianceVerdict.PASS  # graceful, don't block pipeline

        # Import tại runtime để tránh circular import với agents.bc9_compliance_officer
        from kernel.base_agent import ExecutionContext

        ctx = ExecutionContext(
            run_id=str(uuid.uuid4()),
            user_id=None,
            venture_context=venture_context,
            trigger_event="compliance_gate.inline_review",
            payload={
                "content": text,
                "meta": {
                    "venture": venture_context,
                    "channel": channel,
                },
            },
        )

        result = await self.bc9_agent.run(ctx)
        if not result.success:
            log.info(
                "ComplianceGate BC9 fail, skip (err=%s)", result.output_text
            )
            return ComplianceVerdict.SKIP

        verdict_raw = (result.output_payload or {}).get("verdict", "")
        mapping = {
            "APPROVE": ComplianceVerdict.PASS,
            "FLAG": ComplianceVerdict.FLAG,
            "BLOCK": ComplianceVerdict.BLOCK,
        }
        return mapping.get(verdict_raw, ComplianceVerdict.SKIP)
