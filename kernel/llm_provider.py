"""Cửa duy nhất tạo client LLM cho camas-kernel.

Vì sao có file này (2026-08-13):
    Tài khoản Anthropic hết credit, thẻ của Anna bị từ chối khi nạp dù ngân
    hàng xác nhận thẻ bình thường. Toàn bộ AI của hệ thống chết theo, học viên
    Foundation kẹt ở Gate 1 vì không sinh được file Tier B.

    AWS Bedrock chạy đúng những model Claude đó nhưng TÍNH TIỀN SAU qua hoá đơn
    AWS, không bắt nạp trước. Đó là chỗ gỡ được nút thắt.

Cách dùng:
    from kernel.llm_provider import build_async_client
    client = build_async_client()          # thay cho AsyncAnthropic(api_key=...)

    LLM_PROVIDER=bedrock  -> đi qua AWS, tính vào hoá đơn AWS
    (không đặt)           -> gọi thẳng Anthropic như cũ

Client trả về tự dịch tên model sang mã Bedrock, nên chỗ gọi giữ nguyên
`model="claude-sonnet-4-6"`. Khi credit Anthropic quay lại, gỡ biến
LLM_PROVIDER là xong, không phải sửa code lần nữa.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

log = logging.getLogger("camas.llm_provider")

DEFAULT_BEDROCK_REGION = "ap-southeast-2"

# Mã model trên Bedrock khác mã gọi thẳng Anthropic. Dòng Claude mới bắt buộc
# đi qua "inference profile", tiền tố au. giữ dữ liệu chạy trong nước Úc.
# Bảng này chỉ liệt kê model ĐÃ ĐƯỢC CẤP QUYỀN trên tài khoản AWS 292718260367
# (kiểm chứng bằng lệnh gọi thật ngày 2026-08-13).
_BEDROCK_MODEL_MAP: dict[str, str] = {
    "claude-sonnet-4-6": "au.anthropic.claude-sonnet-4-6",
    "claude-sonnet-4-5": "au.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-haiku-4-5": "au.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-haiku-4-5-20251001": "au.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-opus-4-6": "au.anthropic.claude-opus-4-6-v1",
    # Chưa tick trên Bedrock console, tạm hạ xuống Opus 4.6.
    "claude-opus-4-7": "au.anthropic.claude-opus-4-6-v1",
    "claude-opus-4-8": "au.anthropic.claude-opus-4-6-v1",
    "claude-opus-5": "au.anthropic.claude-opus-4-6-v1",
    "claude-sonnet-5": "au.anthropic.claude-sonnet-4-6",
}

# Model bị hạ cấp so với thứ code xin. Ghi log để không âm thầm đổi chất lượng.
_DOWNGRADED = {"claude-opus-4-7", "claude-opus-4-8", "claude-opus-5", "claude-sonnet-5"}

_MAP_WARNED: set[str] = set()


def provider() -> str:
    """Trả về 'bedrock' hoặc 'anthropic'."""
    return "bedrock" if os.environ.get("LLM_PROVIDER", "").strip().lower() == "bedrock" else "anthropic"


def _model_map() -> dict[str, str]:
    """Bảng dịch model, cho phép đè bằng biến môi trường.

    Khi Anna tick thêm model mới trên Bedrock console, chỉ cần đặt
    BEDROCK_MODEL_MAP dạng JSON trên Railway là nâng cấp được ngay,
    không cần deploy lại code.
    """
    raw = os.environ.get("BEDROCK_MODEL_MAP", "").strip()
    if not raw:
        return _BEDROCK_MODEL_MAP
    try:
        override = json.loads(raw)
        if isinstance(override, dict):
            return {**_BEDROCK_MODEL_MAP, **{str(k): str(v) for k, v in override.items()}}
        log.warning("BEDROCK_MODEL_MAP khong phai object JSON, bo qua")
    except (ValueError, TypeError) as exc:
        log.warning("BEDROCK_MODEL_MAP khong doc duoc (%s), dung bang mac dinh", exc)
    return _BEDROCK_MODEL_MAP


def resolve_model(model: str) -> str:
    """Dịch tên model sang mã của provider đang dùng."""
    if provider() != "bedrock" or not isinstance(model, str):
        return model
    # Đã là mã Bedrock sẵn thì để nguyên.
    if model.startswith(("au.", "apac.", "global.", "us.", "eu.", "anthropic.")):
        return model
    mapped = _model_map().get(model)
    if mapped is None:
        log.error(
            "Model %s chua co trong bang dich Bedrock, gui nguyen ban, nhieu kha nang loi",
            model,
        )
        return model
    if model in _DOWNGRADED and model not in _MAP_WARNED:
        _MAP_WARNED.add(model)
        log.warning(
            "Model %s chua duoc cap quyen tren Bedrock, dang chay tam bang %s",
            model, mapped,
        )
    return mapped


class _MessagesProxy:
    """Bọc client.messages để tự dịch tên model trước khi gửi."""

    def __init__(self, inner: Any, mapper: Callable[[str], str]) -> None:
        self._inner = inner
        self._mapper = mapper

    def _fix(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        if "model" in kwargs:
            kwargs["model"] = self._mapper(kwargs["model"])
        return kwargs

    async def create(self, **kwargs: Any) -> Any:
        return await self._inner.create(**self._fix(kwargs))

    def stream(self, **kwargs: Any) -> Any:
        return self._inner.stream(**self._fix(kwargs))

    async def count_tokens(self, **kwargs: Any) -> Any:
        return await self._inner.count_tokens(**self._fix(kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _ClientProxy:
    """Bọc client Anthropic/Bedrock, chỉ can thiệp đúng phần messages."""

    def __init__(self, inner: Any, mapper: Callable[[str], str]) -> None:
        self._inner = inner
        self._messages = _MessagesProxy(inner.messages, mapper)

    @property
    def messages(self) -> _MessagesProxy:
        return self._messages

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def build_async_client(api_key: str | None = None) -> Any:
    """Tạo async client theo provider đang cấu hình.

    api_key chỉ dùng cho đường gọi thẳng Anthropic. Đường Bedrock lấy thông tin
    đăng nhập từ AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION.
    """
    if provider() == "bedrock":
        from anthropic import AsyncAnthropicBedrock

        region = os.environ.get("AWS_REGION", DEFAULT_BEDROCK_REGION)
        log.info("LLM provider = bedrock, region %s", region)
        return _ClientProxy(AsyncAnthropicBedrock(aws_region=region), resolve_model)

    from anthropic import AsyncAnthropic

    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError(
            "Chua co ANTHROPIC_API_KEY. Neu tai khoan Anthropic het credit, "
            "dat LLM_PROVIDER=bedrock de chay qua AWS."
        )
    return AsyncAnthropic(api_key=key)


def ready() -> bool:
    """Có đủ thông tin đăng nhập để gọi LLM không."""
    if provider() == "bedrock":
        return bool(
            os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY")
        )
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
