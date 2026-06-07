"""LLM layer wrapping Anthropic SDK.

Anna's preference (memory feedback-claude-not-openrouter-automation):
    - Sonnet 4.6 default
    - Haiku 4.5 cho FAQ + lightweight extract
    - Opus 4.7 cho weekly strategic agent (Phong 10)
"""
from __future__ import annotations

import os
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

try:
    from anthropic import AsyncAnthropic
except ImportError:  # SDK chưa cài lúc scaffold
    AsyncAnthropic = None  # type: ignore[assignment]


class LLMModel(str, Enum):
    SONNET = "claude-sonnet-4-6"
    HAIKU = "claude-haiku-4-5-20251001"
    OPUS = "claude-opus-4-7"


class LLMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: LLMModel = LLMModel.SONNET
    system: Optional[str] = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tools: Optional[list[dict[str, Any]]] = None
    max_tokens: int = 4096
    temperature: float = 0.7


class LLMResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    stop_reason: Optional[str] = None
    usage: dict[str, int] = Field(default_factory=dict)


class LLMLayer:
    """Thin async wrapper over Anthropic Messages API."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client: Optional[Any] = None
        if AsyncAnthropic is not None and self.api_key:
            self._client = AsyncAnthropic(api_key=self.api_key)

    @property
    def ready(self) -> bool:
        return self._client is not None

    @property
    def client(self) -> Any:
        """Expose underlying AsyncAnthropic client.

        Dùng cho agent (vd BC2) cần gọi messages.create với tool_use cấu hình
        riêng (tool_choice, timeout, custom tools schema) mà LLMRequest typed
        không cover hết.
        """
        if self._client is None:
            raise NotImplementedError(
                "Anthropic client chưa init, set ANTHROPIC_API_KEY trong env"
            )
        return self._client

    async def chat(self, req: LLMRequest) -> LLMResponse:
        if self._client is None:
            raise NotImplementedError(
                "Anthropic client chưa init, set ANTHROPIC_API_KEY trong env"
            )
        resp = await self._client.messages.create(
            model=req.model.value,
            system=req.system or "",
            messages=req.messages,
            tools=req.tools or [],
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in resp.content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_parts.append(getattr(block, "text", ""))
            elif block_type == "tool_use":
                tool_calls.append(
                    {
                        "id": getattr(block, "id", ""),
                        "name": getattr(block, "name", ""),
                        "input": getattr(block, "input", {}),
                    }
                )
        usage = getattr(resp, "usage", None)
        usage_dict: dict[str, int] = {}
        if usage is not None:
            usage_dict = {
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
            }
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=getattr(resp, "stop_reason", None),
            usage=usage_dict,
        )
