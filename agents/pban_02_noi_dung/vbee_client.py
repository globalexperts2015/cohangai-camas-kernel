"""Vbee Special plan TTS API client cho Pban02.

Async submit + status polling pattern. Vbee Special plan:
- POST /tts trả `{request_id, status}` immediate (no audio inline)
- GET  /tts/{request_id} → `{status, audio_link}` (PENDING|SUCCESS|FAILED)
- audio_link là S3-like URL, 24h expiry

Voice canonical (memory `reference-vbee-voice` + `feedback-voice-vbee-clone-only`):
- Anna personal brand reels: VBEE_VOICE_ID_ANNA_CLONE (quangtri_female clone)
- Về Úc / Migration channel: VBEE_VOICE_ID_NGOCHUYEN (news anchor HN)

Style: tiếng Việt docstring, ZERO em-dash, type hints, async/await,
graceful errors (raise VbeeAPIError, NOT crash kernel).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

log = logging.getLogger("camas.pban_02_noi_dung.vbee_client")

DEFAULT_TIMEOUT = 60.0
DEFAULT_BASE_URL = "https://vbee.vn/api/v1"
MAX_RETRIES = 3

# Status enum theo Vbee
STATUS_PENDING = "PENDING"
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
TERMINAL_STATUSES = {STATUS_SUCCESS, STATUS_FAILED}


class VbeeAPIError(Exception):
    """Lỗi từ Vbee API (auth, rate, bad request, timeout)."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        body: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class VbeeClient:
    """Async wrapper Vbee Special plan TTS.

    Features:
    - submit_tts() POST /tts, return ngay request_id
    - get_status() GET /tts/{id}
    - wait_for_completion() poll loop với cap timeout + interval

    Token KHÔNG log full. Errors bọc thành VbeeAPIError.
    """

    BASE_URL = DEFAULT_BASE_URL

    def __init__(
        self,
        api_key: str,
        app_id: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key:
            raise ValueError("VbeeClient cần api_key")
        if not app_id:
            raise ValueError("VbeeClient cần app_id")
        self.token = api_key
        self.app_id = app_id
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

    async def _post(self, path: str, json_body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(url, headers=self._headers(), json=json_body)
            except httpx.HTTPError as exc:
                raise VbeeAPIError(f"Vbee POST {path} network fail: {exc!r}") from exc
        if resp.status_code >= 400:
            raise VbeeAPIError(
                f"Vbee POST {path} status={resp.status_code}",
                status_code=resp.status_code,
                body=resp.text[:500],
            )
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise VbeeAPIError(
                f"Vbee POST {path} không parse JSON: {exc!r}",
                status_code=resp.status_code,
                body=resp.text[:500],
            ) from exc
        return data

    async def _get(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(url, headers=self._headers())
            except httpx.HTTPError as exc:
                raise VbeeAPIError(f"Vbee GET {path} network fail: {exc!r}") from exc
        if resp.status_code >= 400:
            raise VbeeAPIError(
                f"Vbee GET {path} status={resp.status_code}",
                status_code=resp.status_code,
                body=resp.text[:500],
            )
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise VbeeAPIError(
                f"Vbee GET {path} không parse JSON: {exc!r}",
                status_code=resp.status_code,
                body=resp.text[:500],
            ) from exc

    # ============================================================
    # Public API
    # ============================================================
    async def submit_tts(
        self,
        text: str,
        voice_code: str,
        audio_type: str = "mp3",
        callback_url: Optional[str] = None,
    ) -> dict[str, Any]:
        """Submit TTS request bất đồng bộ.

        Args:
            text: Nội dung tiếng Việt (đã transliterate EN abbreviation theo
                memory `feedback-vbee-phonetic-en-abbrev`).
            voice_code: Mã voice Vbee, vd `hn_female_ngochuyen_full_48k-fhg`.
            audio_type: `mp3` hoặc `wav`.
            callback_url: Tùy chọn, Vbee POST callback khi job done.

        Returns:
            dict `{request_id, status, ...}` từ Vbee. Status thường là `PENDING`.
        """
        if not text or not text.strip():
            raise ValueError("VbeeClient.submit_tts cần text không rỗng")
        if not voice_code:
            raise ValueError("VbeeClient.submit_tts cần voice_code")

        body: dict[str, Any] = {
            "app_id": self.app_id,
            "voice_code": voice_code,
            "input_text": text,
            "audio_type": audio_type,
        }
        if callback_url:
            body["callback_url"] = callback_url

        log.info(
            "Vbee submit_tts voice=%s len=%d audio_type=%s callback=%s",
            voice_code,
            len(text),
            audio_type,
            bool(callback_url),
        )
        data = await self._post("/tts", body)
        # Vbee thường wrap trong {result: {...}} hoặc trả flat
        result = data.get("result") if isinstance(data.get("result"), dict) else data
        # Normalize field
        out = {
            "request_id": result.get("request_id") or result.get("id") or data.get("request_id"),
            "status": result.get("status") or data.get("status") or STATUS_PENDING,
            "raw": data,
        }
        if not out["request_id"]:
            raise VbeeAPIError(
                f"Vbee submit_tts không có request_id trong response: {data}"
            )
        log.info(
            "Vbee submit_tts request_id=%s status=%s",
            out["request_id"],
            out["status"],
        )
        return out

    async def get_status(self, request_id: str) -> dict[str, Any]:
        """Poll status 1 lần. Return `{status, audio_link, ...}`."""
        if not request_id:
            raise ValueError("VbeeClient.get_status cần request_id")
        data = await self._get(f"/tts/{request_id}")
        result = data.get("result") if isinstance(data.get("result"), dict) else data
        return {
            "request_id": request_id,
            "status": result.get("status") or data.get("status"),
            "audio_link": result.get("audio_link") or data.get("audio_link"),
            "raw": data,
        }

    async def wait_for_completion(
        self,
        request_id: str,
        max_wait_seconds: int = 120,
        poll_interval: float = 3.0,
    ) -> dict[str, Any]:
        """Poll get_status() đến khi terminal hoặc hết timeout.

        Returns dict tương tự get_status() + key `timed_out: bool`.
        """
        if max_wait_seconds <= 0:
            raise ValueError("max_wait_seconds phải dương")
        if poll_interval <= 0:
            raise ValueError("poll_interval phải dương")

        elapsed = 0.0
        last_status: dict[str, Any] = {"status": None}
        while elapsed < max_wait_seconds:
            try:
                last_status = await self.get_status(request_id)
            except VbeeAPIError as exc:
                log.warning("Vbee poll error request_id=%s: %r", request_id, exc)
                # Tiếp tục poll, có thể Vbee tạm fail
            status = (last_status.get("status") or "").upper()
            if status in TERMINAL_STATUSES:
                last_status["timed_out"] = False
                log.info(
                    "Vbee wait done request_id=%s status=%s after %.1fs",
                    request_id,
                    status,
                    elapsed,
                )
                return last_status
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        last_status["timed_out"] = True
        log.warning(
            "Vbee wait timeout request_id=%s last_status=%s after %ds",
            request_id,
            last_status.get("status"),
            max_wait_seconds,
        )
        return last_status
