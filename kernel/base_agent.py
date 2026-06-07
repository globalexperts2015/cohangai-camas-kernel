"""Base contract for every CAMAS agent (BC + Phong).

Every concrete agent subclasses BaseBC and implements run().
The kernel handles auto inject + auto extract memory around run(),
plus pre publish gate (Voice + Compliance) when the agent emits content.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class AutonomyLevel(str, Enum):
    """Anna chốt 3 mức autonomy trong AIOS spec."""

    L1_AUTO = "L1"
    L2_APPROVE = "L2"
    L3_PROPOSE = "L3"


class EscalationTarget(str, Enum):
    """Kênh leo thang khi agent gặp case L2/L3."""

    TELEGRAM_OPS = "telegram_breakout_ops"
    EMAIL_ANNA = "email_anna"
    NONE = "none"


class ExecutionContext(BaseModel):
    """Mọi input vào BaseBC.run() đi qua context typed này.

    user_id thường là customer_uuid trong CDP (hoặc anna_uuid cho founder action).
    venture_context giúp BC9 áp đúng compliance layer + auto inject filter shared memory.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(description="UUID v4 unique cho mỗi run")
    user_id: Optional[str] = None
    venture_context: str = Field(
        default="all",
        description="speakout | breakout | cohangai | bmcorner | dahafa | migration | dat_gia_nghia | personal | all",
    )
    trigger_event: str = Field(
        description="Tên event kích hoạt, vd sepay.payment.success"
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Dữ liệu thô từ webhook hoặc scheduler",
    )
    injected_memories: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Kernel auto inject memories (đã convert JSON sang NL)",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


class AgentResult(BaseModel):
    """Output chuẩn mọi BaseBC.run() trả về.

    Kernel dùng output_text + emitted_memories để auto extract +
    pre publish gate (Voice + Compliance) nếu publish_target khác None.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    output_text: Optional[str] = None
    output_payload: dict[str, Any] = Field(default_factory=dict)
    emitted_memories: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Memory dict tuân thủ schema CAMASMemoryMetadata",
    )
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    publish_target: Optional[str] = Field(
        default=None,
        description="fb | tiktok | youtube | email | zns | telegram | None",
    )
    escalation_required: bool = False
    escalation_reason: Optional[str] = None
    error: Optional[str] = None

    # Sprint 8 instrumentation: surface ctx.injected_memories qua response
    # Cho phép benchmark + debug verify auto_inject pipeline working
    injected_memories: list[dict[str, Any]] = Field(
        default_factory=list,
        description="4-tier Profile/Task/Conversation/Canonical injected by Scheduler before agent.run()",
    )


class BaseBC(ABC):
    """Abstract base cho mọi BC (7) + Phong ban (10) + cron/routine.

    Concrete agent KHÔNG override execute() trực tiếp.
    Override run() và để execute() handle scaffolding (logging, escalation, gates).
    """

    name: str
    """Tên agent canonical, vd 'bc1_team_leader', 'phong_05_sepay_zns'."""

    scope: str
    """Mô tả ngắn 1 dòng phạm vi quyết định."""

    autonomy_level: AutonomyLevel = AutonomyLevel.L3_PROPOSE
    """Mặc định L3, promote qua threshold trong constitution."""

    escalate_to: EscalationTarget = EscalationTarget.TELEGRAM_OPS

    tools: list[str] = []
    """Danh sách tool name agent được phép gọi, kernel enforce qua ToolLayer."""

    requires_voice_gate: bool = False
    """True cho agent publish content (Phong 02, BC10 share, reel pipeline)."""

    requires_compliance_gate: bool = False
    """True cho mọi agent publish content public hoặc chạm Sepay/Zalo/GHL TOS."""

    def __init__(
        self,
        name: Optional[str] = None,
        scope: Optional[str] = None,
        autonomy_level: Optional[AutonomyLevel] = None,
    ) -> None:
        if name is not None:
            self.name = name
        if scope is not None:
            self.scope = scope
        if autonomy_level is not None:
            self.autonomy_level = autonomy_level
        if not getattr(self, "name", None):
            raise ValueError("BaseBC subclass phải set 'name'")
        if not getattr(self, "scope", None):
            raise ValueError("BaseBC subclass phải set 'scope'")

    @abstractmethod
    async def run(self, ctx: ExecutionContext) -> AgentResult:
        """Logic agent. Concrete subclass phải implement.

        Lưu ý: KHÔNG retrieve memory thủ công, kernel đã auto inject vào
        ctx.injected_memories trước khi gọi run().
        """

    async def execute(self, ctx: ExecutionContext) -> AgentResult:
        """Wrapper kernel gọi. Không override.

        Scaffolding sẽ được kernel scheduler bao quanh:
        - Pre: auto inject memory + voice gate + compliance gate (nếu cần)
        - Call: self.run(ctx)
        - Post: auto extract memory + escalation check
        """
        try:
            result = await self.run(ctx)
        except NotImplementedError as exc:
            return AgentResult(
                success=False,
                error=f"{self.name} chưa wire: {exc}",
                escalation_required=True,
                escalation_reason="NotImplementedError",
            )
        except Exception as exc:  # noqa: BLE001
            return AgentResult(
                success=False,
                error=f"{self.name} crash: {exc!r}",
                escalation_required=True,
                escalation_reason="unhandled_exception",
            )
        return result
