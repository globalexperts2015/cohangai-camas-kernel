"""Facebook Marketing API client wrapper for Pban01.

Production wrapper với retry, rate limit handling, auto pagination, structured
logging. Dùng bởi Phòng 01 Quảng cáo agent để pull insights, list ad sets, pause
ad set, lấy lookalike audience.

Style: tiếng Việt docstring, ZERO em-dash, type hints, async/await.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import httpx

log = logging.getLogger("camas.pban_01_quang_cao.fb_client")

DEFAULT_API_VERSION = "v21.0"
DEFAULT_TIMEOUT = 60.0
MAX_RETRIES = 3
MAX_PAGES = 5  # blast radius limit cho pagination

# FB Marketing API error codes
FB_ERROR_RATE_LIMIT_CODES = {17, 80004, 4, 32, 613}
FB_ERROR_AUTH_CODES = {190, 102, 104, 200}

DEFAULT_INSIGHT_FIELDS = [
    "impressions",
    "cpm",
    "ctr",
    "cpc",
    "cpp",
    "spend",
    "actions",
    "action_values",
    "cost_per_action_type",
    "reach",
    "frequency",
]


class FBMarketingAPIError(Exception):
    """Lỗi từ FB Marketing API (auth, rate, bad request)."""

    def __init__(self, message: str, code: Optional[int] = None, subcode: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.subcode = subcode


class FBMarketingClient:
    """Async wrapper FB Marketing API v21.0.

    Features:
    - Retry với exponential backoff khi rate limit (3 lần, 2^n giây)
    - Auto pagination tối đa 5 trang (limit blast radius)
    - Graceful 401/190 → raise FBMarketingAPIError không retry
    - Structured logging KHÔNG log token
    """

    def __init__(
        self,
        access_token: str,
        ad_account_id: str,
        api_version: str = DEFAULT_API_VERSION,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.token = access_token
        self.ad_account_id = ad_account_id  # format "act_..."
        self.api_version = api_version
        self.base_url = f"https://graph.facebook.com/{api_version}"
        self.timeout = timeout

    # ============================================================
    # Low-level HTTP
    # ============================================================
    async def _get(
        self, path: str, params: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """GET với retry on rate limit. Auto inject access_token."""
        return await self._request("GET", path, params=params)

    async def _post(
        self, path: str, data: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """POST với retry on rate limit. Auto inject access_token."""
        return await self._request("POST", path, data=data)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        all_params = dict(params or {})
        all_params["access_token"] = self.token
        all_data = dict(data or {})
        if method == "POST":
            all_data["access_token"] = self.token

        last_exc: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    if method == "GET":
                        resp = await client.get(url, params=all_params)
                    else:
                        resp = await client.post(url, params={"access_token": self.token}, data=all_data)

                if resp.status_code == 200:
                    return resp.json()

                # Parse error body
                try:
                    err_body = resp.json()
                except Exception:
                    err_body = {"raw": resp.text[:300]}

                err = err_body.get("error", {}) if isinstance(err_body, dict) else {}
                code = err.get("code")
                subcode = err.get("error_subcode")
                msg = err.get("message", f"HTTP {resp.status_code}")

                # Don't log token in error path
                log.warning(
                    "FB API non-200 method=%s path=%s status=%d code=%s subcode=%s msg=%s",
                    method,
                    path,
                    resp.status_code,
                    code,
                    subcode,
                    msg[:200],
                )

                # Auth errors: don't retry
                if resp.status_code == 401 or (code in FB_ERROR_AUTH_CODES):
                    raise FBMarketingAPIError(
                        f"FB auth error: {msg}", code=code, subcode=subcode
                    )

                # Rate limit: retry với exponential backoff
                if code in FB_ERROR_RATE_LIMIT_CODES or resp.status_code == 429:
                    if attempt < MAX_RETRIES - 1:
                        sleep_s = 2 ** (attempt + 1)
                        log.info(
                            "FB rate limit hit, sleep %ds (attempt %d/%d)",
                            sleep_s,
                            attempt + 1,
                            MAX_RETRIES,
                        )
                        await asyncio.sleep(sleep_s)
                        continue
                    raise FBMarketingAPIError(
                        f"FB rate limit exceeded: {msg}",
                        code=code,
                        subcode=subcode,
                    )

                # Other 4xx/5xx: fail
                raise FBMarketingAPIError(
                    f"FB API error {resp.status_code}: {msg}",
                    code=code,
                    subcode=subcode,
                )
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < MAX_RETRIES - 1:
                    sleep_s = 2 ** (attempt + 1)
                    log.info(
                        "FB network error %r, sleep %ds (attempt %d/%d)",
                        exc,
                        sleep_s,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    await asyncio.sleep(sleep_s)
                    continue
                raise FBMarketingAPIError(f"FB network error: {exc!r}") from exc

        # Defensive: out of loop without return
        if last_exc:
            raise FBMarketingAPIError(f"FB request fail: {last_exc!r}")
        raise FBMarketingAPIError("FB request fail unknown")

    async def _paginate(
        self, path: str, params: Optional[dict[str, Any]] = None
    ) -> list[dict[str, Any]]:
        """Auto-paginate cursor-based, max 5 trang."""
        all_items: list[dict[str, Any]] = []
        current_params = dict(params or {})
        for page in range(MAX_PAGES):
            data = await self._get(path, params=current_params)
            items = data.get("data") or []
            all_items.extend(items)
            paging = data.get("paging") or {}
            cursors = paging.get("cursors") or {}
            after = cursors.get("after")
            next_url = paging.get("next")
            if not after or not next_url:
                break
            current_params = dict(params or {})
            current_params["after"] = after
        return all_items

    # ============================================================
    # High-level FB calls
    # ============================================================
    async def list_active_ad_sets(self) -> list[dict[str, Any]]:
        """List ad set status ACTIVE trong account."""
        params = {
            "fields": "id,name,status,effective_status,daily_budget,lifetime_budget,campaign_id",
            "effective_status": json.dumps(["ACTIVE"]),
            "limit": 100,
        }
        return await self._paginate(f"{self.ad_account_id}/adsets", params=params)

    async def fetch_insights(
        self,
        level: str = "adset",
        date_preset: str = "today",
        fields: Optional[list[str]] = None,
        extra_breakdown_fields: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Pull insights ở level adset/campaign/ad cho date_preset."""
        use_fields = list(fields or DEFAULT_INSIGHT_FIELDS)
        if level == "adset":
            for f in ("adset_id", "adset_name"):
                if f not in use_fields:
                    use_fields.append(f)
        elif level == "campaign":
            for f in ("campaign_id", "campaign_name"):
                if f not in use_fields:
                    use_fields.append(f)
        elif level == "ad":
            for f in ("ad_id", "ad_name"):
                if f not in use_fields:
                    use_fields.append(f)
        if extra_breakdown_fields:
            use_fields.extend(extra_breakdown_fields)

        params = {
            "level": level,
            "date_preset": date_preset,
            "fields": ",".join(use_fields),
            "limit": 100,
        }
        return await self._paginate(
            f"{self.ad_account_id}/insights", params=params
        )

    async def pause_ad_set(self, ad_set_id: str) -> dict[str, Any]:
        """Pause ad set (status=PAUSED).

        CẢNH BÁO: action thật trên account Anna, KHÔNG test smoke.
        """
        return await self._post(ad_set_id, data={"status": "PAUSED"})

    async def get_lookalike_audiences(self) -> list[dict[str, Any]]:
        """List custom audience, filter subtype=LOOKALIKE.

        Note: API v21 thay `approximate_count` bằng
        `approximate_count_lower_bound` + `approximate_count_upper_bound`.
        Trả về `approximate_count` = average lower+upper cho backward compat.
        """
        params = {
            "fields": "id,name,subtype,approximate_count_lower_bound,approximate_count_upper_bound,delivery_status,operation_status",
            "limit": 100,
        }
        all_audiences = await self._paginate(
            f"{self.ad_account_id}/customaudiences", params=params
        )
        # Normalize approximate_count cho downstream
        for a in all_audiences:
            lower = a.get("approximate_count_lower_bound")
            upper = a.get("approximate_count_upper_bound")
            try:
                if lower is not None and upper is not None:
                    a["approximate_count"] = (int(lower) + int(upper)) // 2
                elif upper is not None:
                    a["approximate_count"] = int(upper)
                elif lower is not None:
                    a["approximate_count"] = int(lower)
            except (TypeError, ValueError):
                pass
        # Filter lookalike-like
        lookalikes = [
            a
            for a in all_audiences
            if (a.get("subtype") or "").upper() in {"LOOKALIKE", "LOOKALIKE_AUDIENCE"}
        ]
        return lookalikes if lookalikes else all_audiences

    async def get_campaign_performance_summary(
        self, days: int = 7
    ) -> dict[str, Any]:
        """Aggregate insights N ngày gần, compute avg CPM/CTR/CPC/CPL/ROAS."""
        if days <= 1:
            date_preset = "today"
        elif days <= 7:
            date_preset = "last_7d"
        elif days <= 14:
            date_preset = "last_14d"
        else:
            date_preset = "last_30d"

        rows = await self.fetch_insights(
            level="campaign", date_preset=date_preset
        )

        total_spend = 0.0
        total_impressions = 0
        total_clicks = 0
        total_reach = 0
        total_purchase_value = 0.0
        purchases_count = 0
        leads_count = 0
        cpm_weighted = 0.0
        ctr_weighted = 0.0
        cpc_weighted = 0.0

        for row in rows:
            spend = float(row.get("spend") or 0)
            impressions = int(float(row.get("impressions") or 0))
            cpm = float(row.get("cpm") or 0)
            ctr = float(row.get("ctr") or 0)
            cpc = float(row.get("cpc") or 0)
            reach = int(float(row.get("reach") or 0))

            total_spend += spend
            total_impressions += impressions
            total_reach += reach

            if impressions > 0:
                cpm_weighted += cpm * impressions
                ctr_weighted += ctr * impressions
            if spend > 0 and cpc > 0:
                clicks_for_row = spend / cpc if cpc else 0
                total_clicks += int(clicks_for_row)
                cpc_weighted += cpc * spend

            for action in row.get("actions") or []:
                a_type = action.get("action_type", "")
                a_val = int(float(action.get("value") or 0))
                if a_type in {"purchase", "offsite_conversion.fb_pixel_purchase"}:
                    purchases_count += a_val
                if a_type in {"lead", "offsite_conversion.fb_pixel_lead", "onsite_conversion.lead_grouped"}:
                    leads_count += a_val

            for av in row.get("action_values") or []:
                if av.get("action_type") in {
                    "purchase",
                    "offsite_conversion.fb_pixel_purchase",
                }:
                    total_purchase_value += float(av.get("value") or 0)

        avg_cpm = (
            cpm_weighted / total_impressions if total_impressions else 0
        )
        avg_ctr = (
            ctr_weighted / total_impressions if total_impressions else 0
        )
        avg_cpc = (
            cpc_weighted / total_spend if total_spend else 0
        )
        cost_per_lead = total_spend / leads_count if leads_count else 0
        cost_per_purchase = (
            total_spend / purchases_count if purchases_count else 0
        )
        roas = (
            total_purchase_value / total_spend if total_spend else 0
        )

        return {
            "date_preset": date_preset,
            "days": days,
            "campaigns_count": len(rows),
            "spend_total": total_spend,
            "impressions_total": total_impressions,
            "reach_total": total_reach,
            "cpm": round(avg_cpm, 2),
            "ctr": round(avg_ctr, 4),
            "cpc": round(avg_cpc, 2),
            "cpa": round(cost_per_purchase, 2),
            "cost_per_lead": round(cost_per_lead, 2),
            "purchases_count": purchases_count,
            "leads_count": leads_count,
            "purchase_value_total": round(total_purchase_value, 2),
            "roas": round(roas, 2),
        }
