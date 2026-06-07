"""Creatomate render API client cho Pban02.

API contract:
- POST /v1/renders body `{template_id, modifications, output_format}`,
  Authorization Bearer. Response = ARRAY `[{id, status, url, ...}]` vì
  Creatomate có thể trả nhiều render khi template multi-output.
- GET /v1/renders/{id} → `{status, url, snapshot_url, ...}`,
  status enum: queued | planned | transcribing | rendering | succeeded | failed.
- GET /v1/templates/{id} → schema modifications (list element + property keys).

Template `c64d72d8-f05d-4d77-a5fb-1c600686672c` HighlightedSubtitles:
- Standard keys giả định: `Audio.source`, `Subtitle.text`, `Title.text`.
- Verify một lần bằng get_template() rồi cache.

Style: tiếng Việt docstring, ZERO em-dash, async/await, graceful errors.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

log = logging.getLogger("camas.pban_02_noi_dung.creatomate_client")

DEFAULT_BASE_URL = "https://api.creatomate.com"
DEFAULT_TIMEOUT = 60.0

STATUS_QUEUED = "queued"
STATUS_PLANNED = "planned"
STATUS_RENDERING = "rendering"
STATUS_TRANSCRIBING = "transcribing"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
TERMINAL_STATUSES = {STATUS_SUCCEEDED, STATUS_FAILED}


class CreatomateAPIError(Exception):
    """Lỗi từ Creatomate API."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        body: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class CreatomateClient:
    """Async wrapper Creatomate render API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key:
            raise ValueError("CreatomateClient cần api_key")
        self.token = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ============================================================
    # Low-level HTTP
    # ============================================================
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        json_body: Optional[dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.request(
                    method,
                    url,
                    headers=self._headers(),
                    json=json_body,
                )
            except httpx.HTTPError as exc:
                raise CreatomateAPIError(
                    f"Creatomate {method} {path} network fail: {exc!r}"
                ) from exc
        if resp.status_code >= 400:
            raise CreatomateAPIError(
                f"Creatomate {method} {path} status={resp.status_code}",
                status_code=resp.status_code,
                body=resp.text[:500],
            )
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise CreatomateAPIError(
                f"Creatomate {method} {path} không parse JSON: {exc!r}",
                status_code=resp.status_code,
                body=resp.text[:500],
            ) from exc

    # ============================================================
    # Templates (read-only, free)
    # ============================================================
    async def get_template(self, template_id: str) -> dict[str, Any]:
        """Inspect template. Trả về schema raw từ Creatomate.

        Dùng để verify modification keys một lần (Audio.source, Subtitle.text,
        Title.text...) trước khi submit render production.
        """
        if not template_id:
            raise ValueError("get_template cần template_id")
        log.info("Creatomate get_template id=%s", template_id)
        data = await self._request("GET", f"/v1/templates/{template_id}")
        return data if isinstance(data, dict) else {"raw": data}

    def extract_modification_keys(self, template: dict[str, Any]) -> list[str]:
        """Best-effort extract danh sách modification key từ template schema.

        Creatomate trả `elements: [{name, type, ...}]`. Subtitle/text element
        thường có key `<Name>.text`, Audio element `<Name>.source`. Logic
        approximation, agent có thể fallback list cố định nếu trống.
        """
        keys: list[str] = []
        elements = template.get("elements") or template.get("source", {}).get(
            "elements", []
        )
        if not isinstance(elements, list):
            return keys
        for el in elements:
            if not isinstance(el, dict):
                continue
            name = el.get("name")
            el_type = el.get("type")
            if not name:
                continue
            if el_type in ("text", "subtitle"):
                keys.append(f"{name}.text")
            elif el_type == "audio":
                keys.append(f"{name}.source")
            elif el_type in ("image", "video"):
                keys.append(f"{name}.source")
        return keys

    # ============================================================
    # Renders
    # ============================================================
    async def submit_render(
        self,
        template_id: str,
        modifications: dict[str, Any],
        output_format: str = "mp4",
    ) -> dict[str, Any]:
        """POST /v1/renders. Creatomate trả ARRAY render, trả phần tử đầu.

        Args:
            template_id: UUID template Creatomate.
            modifications: dict `{"Subtitle.text": "...", "Audio.source": URL}`.
            output_format: `mp4` default, có thể `gif` hoặc `jpg` cho snapshot.

        Returns:
            dict `{id, status, url, snapshot_url, ...}` của render đầu trong array.
        """
        if not template_id:
            raise ValueError("submit_render cần template_id")
        body: dict[str, Any] = {
            "template_id": template_id,
            "output_format": output_format,
            "modifications": modifications or {},
        }
        log.info(
            "Creatomate submit_render template=%s mods=%d format=%s",
            template_id,
            len(modifications or {}),
            output_format,
        )
        data = await self._request("POST", "/v1/renders", json_body=body)
        # Creatomate trả LIST. Lấy phần tử đầu.
        if isinstance(data, list):
            if not data:
                raise CreatomateAPIError(
                    "Creatomate submit_render trả empty array"
                )
            first = data[0]
        elif isinstance(data, dict):
            first = data
        else:
            raise CreatomateAPIError(
                f"Creatomate submit_render shape lạ: {type(data).__name__}"
            )

        if not isinstance(first, dict) or not first.get("id"):
            raise CreatomateAPIError(
                f"Creatomate submit_render thiếu id: {first}"
            )

        log.info(
            "Creatomate submit_render ok id=%s status=%s",
            first.get("id"),
            first.get("status"),
        )
        return first

    async def get_status(self, render_id: str) -> dict[str, Any]:
        """Poll status 1 lần. Return `{status, url, snapshot_url, ...}`."""
        if not render_id:
            raise ValueError("get_status cần render_id")
        data = await self._request("GET", f"/v1/renders/{render_id}")
        if not isinstance(data, dict):
            raise CreatomateAPIError(
                f"Creatomate get_status shape lạ: {type(data).__name__}"
            )
        return data

    async def wait_for_completion(
        self,
        render_id: str,
        max_wait_seconds: int = 300,
        poll_interval: float = 5.0,
    ) -> dict[str, Any]:
        """Poll get_status() đến khi succeeded/failed hoặc timeout.

        Returns dict tương tự get_status() + key `timed_out: bool`.
        """
        if max_wait_seconds <= 0:
            raise ValueError("max_wait_seconds phải dương")
        if poll_interval <= 0:
            raise ValueError("poll_interval phải dương")

        elapsed = 0.0
        last: dict[str, Any] = {"status": None}
        while elapsed < max_wait_seconds:
            try:
                last = await self.get_status(render_id)
            except CreatomateAPIError as exc:
                log.warning(
                    "Creatomate poll error render_id=%s: %r", render_id, exc
                )
            status = (last.get("status") or "").lower()
            if status in TERMINAL_STATUSES:
                last["timed_out"] = False
                log.info(
                    "Creatomate wait done render_id=%s status=%s after %.1fs",
                    render_id,
                    status,
                    elapsed,
                )
                return last
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        last["timed_out"] = True
        log.warning(
            "Creatomate wait timeout render_id=%s last_status=%s after %ds",
            render_id,
            last.get("status"),
            max_wait_seconds,
        )
        return last
