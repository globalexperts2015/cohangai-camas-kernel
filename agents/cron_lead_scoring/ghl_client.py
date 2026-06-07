"""GHL (GoHighLevel) Marketing API client wrapper for lead scoring.

Production wrapper với retry on 429 + exponential backoff + paginated fetch +
concurrent batch update với semaphore.

Pattern:
- Personal Integration Token (pit-*) qua header Authorization: Bearer <token>
- Version header `2021-07-28` (per leadconnectorhq.com docs)
- BASE_URL services.leadconnectorhq.com
- Custom field `breakout_lead_score` NUMERICAL, auto-create idempotent
- list_contacts paginated bằng startAfterId cursor (max 2000 contacts)
- update_contact_custom_field PUT /contacts/{id} payload customFields[]
- batch_update_scores concurrency-limited bằng asyncio.Semaphore

Lý do tách thành module riêng (không inline trong agent.py):
- Reusable cho cron_dedupe_contact + cron_stale_alert tương lai
- Test riêng được, không phụ thuộc LLMLayer/MemoryLayer
- Logic retry + pagination phức tạp, agent.py giữ business logic gọn
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

log = logging.getLogger("camas.ghl_client")


GHL_API_BASE = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2021-07-28"
LEAD_SCORE_FIELD_NAME = "Breakout Lead Score"
LEAD_SCORE_FIELD_KEY_CANDIDATES = (
    "breakout_lead_score",
    "contact.breakout_lead_score",
)


class GHLClient:
    """Async GHL Marketing API client cho lead scoring.

    Khởi tạo:
        client = GHLClient(api_token=..., location_id=...)

    Sử dụng cùng async context để reuse httpx connection pool:
        async with httpx.AsyncClient() as http:
            ...

    Note: client tự tạo httpx.AsyncClient mỗi _request để fail-soft, cron 5am
    không cần connection pool tối ưu (chạy 1 lần/ngày).
    """

    BASE_URL = GHL_API_BASE
    VERSION = GHL_API_VERSION

    def __init__(
        self,
        api_token: str,
        location_id: str,
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        self.token = api_token
        self.location_id = location_id
        self.timeout = timeout
        self.max_retries = max_retries

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Version": self.VERSION,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """HTTP request với retry on 429 + exponential backoff.

        Raise httpx.HTTPStatusError on non-retriable 4xx (caller catch).
        Return parsed JSON dict (empty dict nếu 204 No Content).
        """
        url = f"{self.BASE_URL}{path}"
        backoff = 1.0
        last_exc: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.request(
                        method,
                        url,
                        headers=self._headers(),
                        params=params,
                        json=json_body,
                    )
            except httpx.HTTPError as exc:
                last_exc = exc
                log.warning(
                    "GHL %s %s transport fail attempt=%d: %r",
                    method, path, attempt + 1, exc,
                )
                await asyncio.sleep(backoff)
                backoff *= 2
                continue

            # Retry on 429 (rate limit) + 5xx
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                retry_after = float(resp.headers.get("Retry-After", "0") or 0)
                wait_s = retry_after if retry_after > 0 else backoff
                log.warning(
                    "GHL %s %s status=%d attempt=%d wait=%.1fs",
                    method, path, resp.status_code, attempt + 1, wait_s,
                )
                await asyncio.sleep(wait_s)
                backoff *= 2
                continue

            # Non-retriable: 2xx or 4xx (other than 429)
            if 200 <= resp.status_code < 300:
                if resp.status_code == 204 or not resp.content:
                    return {}
                try:
                    return resp.json()
                except Exception:  # noqa: BLE001
                    return {"raw": resp.text[:500]}

            # 4xx non-429: raise to caller
            log.warning(
                "GHL %s %s non-retry status=%d body=%s",
                method, path, resp.status_code, resp.text[:300],
            )
            resp.raise_for_status()

        # Exhausted retries
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(
            f"GHL {method} {path} exhausted {self.max_retries} retries"
        )

    # ------------------------------------------------------------------
    # Custom fields
    # ------------------------------------------------------------------

    async def list_custom_fields(self) -> list[dict[str, Any]]:
        """GET /locations/{locationId}/customFields, return list."""
        path = f"/locations/{self.location_id}/customFields"
        data = await self._request("GET", path)
        # GHL response shape: {"customFields": [...]}
        return data.get("customFields", []) or []

    async def get_or_create_lead_score_field(self) -> str:
        """Return custom field id cho breakout_lead_score. Create nếu chưa có.

        Idempotent: lần 2 chạy tìm field bằng name/fieldKey, không tạo trùng.
        """
        fields = await self.list_custom_fields()
        for f in fields:
            field_key = (f.get("fieldKey") or "").lower()
            name = (f.get("name") or "").lower()
            if (
                field_key in LEAD_SCORE_FIELD_KEY_CANDIDATES
                or name == LEAD_SCORE_FIELD_NAME.lower()
                or "breakout_lead_score" in field_key
                or "breakout lead score" in name
            ):
                fid = f.get("id")
                if fid:
                    log.info(
                        "GHL lead score field found id=%s key=%s",
                        fid, field_key,
                    )
                    return fid

        # Create
        log.info("GHL lead score field chưa có, tạo mới")
        path = f"/locations/{self.location_id}/customFields"
        payload = {
            "name": LEAD_SCORE_FIELD_NAME,
            "dataType": "NUMERICAL",
            "placeholder": "0-100",
            "position": 0,
            "model": "contact",
        }
        data = await self._request("POST", path, json_body=payload)
        # Response shape: {"customField": {...}} hoặc dict trực tiếp
        cf = data.get("customField") or data
        fid = cf.get("id")
        if not fid:
            raise RuntimeError(
                f"GHL create custom field thiếu id, response={data}"
            )
        log.info("GHL lead score field created id=%s", fid)
        return fid

    # ------------------------------------------------------------------
    # Contacts list
    # ------------------------------------------------------------------

    async def list_contacts(
        self,
        max_contacts: int = 2000,
        page_limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Paginated fetch contacts qua /contacts/ endpoint.

        Loop max_pages = max_contacts // page_limit (cap 20 pages = 2000).
        Mỗi page dùng startAfterId cursor từ contact cuối page trước.

        GHL contact shape:
            {"id", "firstName", "lastName", "email", "phone",
             "tags": [...], "customFields": [...], "dateAdded"}
        """
        contacts: list[dict[str, Any]] = []
        max_pages = min(20, (max_contacts // page_limit) + 1)
        start_after_id: Optional[str] = None

        for page_idx in range(max_pages):
            if len(contacts) >= max_contacts:
                break

            params: dict[str, Any] = {
                "locationId": self.location_id,
                "limit": page_limit,
            }
            if start_after_id:
                params["startAfterId"] = start_after_id

            try:
                data = await self._request("GET", "/contacts/", params=params)
            except httpx.HTTPStatusError as exc:
                log.warning(
                    "GHL list_contacts page=%d HTTP fail: %s",
                    page_idx, exc,
                )
                break
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "GHL list_contacts page=%d fail: %r",
                    page_idx, exc,
                )
                break

            page = data.get("contacts", []) or []
            if not page:
                break

            for c in page:
                contacts.append(c)
                if len(contacts) >= max_contacts:
                    break

            # Next cursor = id của contact cuối page
            last = page[-1]
            new_cursor = last.get("id")
            if not new_cursor or new_cursor == start_after_id:
                # Không thay đổi cursor => hết
                break
            start_after_id = new_cursor

        log.info(
            "GHL list_contacts fetched=%d pages=%d max=%d",
            len(contacts), page_idx + 1, max_contacts,
        )
        return contacts

    # ------------------------------------------------------------------
    # Contact update
    # ------------------------------------------------------------------

    async def update_contact_custom_field(
        self,
        contact_id: str,
        custom_field_id: str,
        value: int,
    ) -> bool:
        """PUT /contacts/{id} với customFields[] payload.

        Return True on 2xx, False on fail.
        """
        path = f"/contacts/{contact_id}"
        payload = {
            "customFields": [
                {"id": custom_field_id, "field_value": value},
            ],
        }
        try:
            await self._request("PUT", path, json_body=payload)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "GHL update_contact_custom_field id=%s fail: %r",
                contact_id, exc,
            )
            return False

    async def batch_update_scores(
        self,
        scores: dict[str, int],
        custom_field_id: str,
        max_concurrent: int = 5,
    ) -> dict[str, Any]:
        """Batch update với asyncio.Semaphore limit concurrency.

        Args:
            scores: {contact_id: score_int}
            custom_field_id: GHL custom field id từ get_or_create_lead_score_field
            max_concurrent: parallel API calls cap (default 5, tránh rate limit)

        Return:
            {"success": int, "failed": int, "errors": [(contact_id, repr)]}
        """
        sem = asyncio.Semaphore(max_concurrent)
        results = {"success": 0, "failed": 0, "errors": []}

        async def _one(contact_id: str, value: int) -> None:
            async with sem:
                ok = await self.update_contact_custom_field(
                    contact_id, custom_field_id, value,
                )
                if ok:
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    if len(results["errors"]) < 20:
                        results["errors"].append(contact_id)

        tasks = [_one(cid, val) for cid, val in scores.items()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=False)

        log.info(
            "GHL batch_update_scores total=%d success=%d failed=%d",
            len(scores), results["success"], results["failed"],
        )
        return results
