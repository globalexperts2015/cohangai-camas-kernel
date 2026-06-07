"""Tool registry + native MCP client wrapper.

Two backends:
    1. Local Python function tools (sepay_confirm, zalo_send_zns, ghl_tag_contact...)
    2. MCP servers (Vault MCP, CDP MCP, GHL MCP, Sepay MCP, plus Anna's claude.ai MCP set)

Agent.tools[] = whitelist allowed tool names. Kernel enforces qua ToolLayer.invoke.
"""
from __future__ import annotations

import os
from typing import Any, Awaitable, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class ToolSpec(BaseModel):
    """Mô tả 1 tool, dùng OpenAI function-calling format cho Anthropic compat."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON schema params (OpenAI function-calling format)",
    )
    backend: str = Field(
        default="local",
        description="local | mcp_vault | mcp_cdp | mcp_ghl | mcp_sepay | mcp_claude_ai",
    )
    requires_approval: bool = Field(
        default=False,
        description="True cho tool chạm tiền (Sepay refund) hoặc external broadcast",
    )


class ToolLayer:
    """Registry + dispatcher. Stub returns NotImplementedError trên invoke không wire."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}
        self._mcp_servers: dict[str, str] = {
            "mcp_vault": os.getenv("MCP_VAULT_URL", ""),
            "mcp_cdp": os.getenv("MCP_CDP_URL", ""),
            "mcp_ghl": os.getenv("MCP_GHL_URL", ""),
            "mcp_sepay": os.getenv("MCP_SEPAY_URL", ""),
        }

    def register(self, spec: ToolSpec, handler: Optional[ToolHandler] = None) -> None:
        """Đăng ký tool vào registry. handler có thể None cho MCP-backed tool."""
        self._specs[spec.name] = spec
        if handler is not None:
            self._handlers[spec.name] = handler

    def list(self, allowed: Optional[list[str]] = None) -> list[ToolSpec]:
        if allowed is None:
            return list(self._specs.values())
        return [self._specs[n] for n in allowed if n in self._specs]

    def get_spec(self, name: str) -> Optional[ToolSpec]:
        return self._specs.get(name)

    async def invoke(
        self,
        name: str,
        params: dict[str, Any],
        allowed: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Kernel-mediated tool call. Enforce allowed list.

        Tool requires_approval=True sẽ raise PendingApproval (Q3 add) khi
        agent autonomy < L1. Hiện stub raises NotImplementedError cho MCP backend
        chưa wire.
        """
        if allowed is not None and name not in allowed:
            raise PermissionError(f"Tool {name} không nằm trong allowed list của agent")
        spec = self._specs.get(name)
        if spec is None:
            raise KeyError(f"Tool {name} chưa đăng ký registry")
        if spec.backend == "local":
            handler = self._handlers.get(name)
            if handler is None:
                raise NotImplementedError(f"Local tool {name} chưa wire handler")
            return await handler(params)
        raise NotImplementedError(
            f"MCP backend {spec.backend} chờ wire client (Q3 task)"
        )
