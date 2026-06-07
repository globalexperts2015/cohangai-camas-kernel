"""Google Ads API client wrapper for Pban01.

Production wrapper với OAuth refresh + retry + structured logging. Dùng raw
httpx thay vì google-ads SDK để tránh thêm grpc + protobuf dep nặng vào
Railway image (chỉ cần REST API cho insights pull).

Stack:
- OAuth2 refresh_token → access_token at https://oauth2.googleapis.com/token
- Google Ads API v18 REST endpoint searchStream với GAQL query
- developer_token + login-customer-id header bắt buộc (login customer = MCC nếu có)

Graceful degradation:
- Thiếu any credential → ready=False, fetch trả [] không raise
- Lý do: Pban01 phải work khi chỉ FB Ads wired, Google Ads chờ Anna apply token

Style: tiếng Việt docstring, ZERO em-dash, type hints, async/await.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

import httpx

log = logging.getLogger("camas.pban_01_quang_cao.gads_client")

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_API_VERSION = "v20"
DEFAULT_TIMEOUT = 60.0
MAX_RETRIES = 3
ACCESS_TOKEN_TTL = 3300  # 55 phút, refresh trước 5 phút safety margin (Google grant 60min)

DEFAULT_INSIGHT_QUERY = """
SELECT
  campaign.id,
  campaign.name,
  campaign.status,
  metrics.cost_micros,
  metrics.impressions,
  metrics.clicks,
  metrics.ctr,
  metrics.average_cpc,
  metrics.average_cpm,
  metrics.conversions,
  metrics.cost_per_conversion
FROM campaign
WHERE segments.date DURING LAST_7_DAYS
""".strip()


class GoogleAdsAPIError(Exception):
    """Lỗi từ Google Ads API (auth, quota, bad query)."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class GoogleAdsClient:
    """Async wrapper Google Ads REST API v18.

    Features:
    - OAuth2 refresh tự động cache access_token TTL 55 phút
    - GAQL query (Google Ads Query Language) cho campaign insights
    - Graceful return [] khi credential missing thay vì raise
    - Structured logging KHÔNG log developer_token hoặc access_token
    """

    def __init__(
        self,
        developer_token: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        customer_id: str,
        login_customer_id: Optional[str] = None,
        api_version: str = DEFAULT_API_VERSION,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.developer_token = developer_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        # Customer ID không dấu (e.g. "4404706501" not "440-470-6501")
        self.customer_id = customer_id.replace("-", "")
        self.login_customer_id = (
            login_customer_id.replace("-", "") if login_customer_id else None
        )
        self.api_version = api_version
        self.base_url = f"https://googleads.googleapis.com/{api_version}"
        self.timeout = timeout

        # OAuth access token cache (in-memory, process lifetime)
        self._access_token: Optional[str] = None
        self._access_token_expires_at: float = 0.0

    @property
    def ready(self) -> bool:
        """True nếu đủ credential. Pban01 dùng để skip call khi chưa wire."""
        return all(
            [
                self.developer_token,
                self.client_id,
                self.client_secret,
                self.refresh_token,
                self.customer_id,
            ]
        )

    # ============================================================
    # OAuth refresh
    # ============================================================
    async def _get_access_token(self) -> str:
        """Lấy access_token từ refresh_token, cache 55 phút.

        Raise GoogleAdsAPIError nếu OAuth fail.
        """
        now = time.time()
        if self._access_token and now < self._access_token_expires_at:
            return self._access_token

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                OAUTH_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        if resp.status_code != 200:
            log.warning(
                "Google Ads OAuth refresh fail status=%s body=%s",
                resp.status_code,
                resp.text[:200],
            )
            raise GoogleAdsAPIError(
                f"OAuth refresh fail: {resp.status_code}", status=resp.status_code
            )

        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise GoogleAdsAPIError("OAuth response thiếu access_token")
        self._access_token = token
        self._access_token_expires_at = now + ACCESS_TOKEN_TTL
        return token

    # ============================================================
    # Search insights (GAQL)
    # ============================================================
    async def fetch_campaign_insights(
        self, query: str = DEFAULT_INSIGHT_QUERY
    ) -> list[dict[str, Any]]:
        """Run GAQL query trên customer, trả list row dict.

        Default query pull campaign-level insights last 7 days. Pass custom GAQL
        nếu cần date range hoặc field khác.

        Return:
        - list[dict] với key: campaign_id, campaign_name, spend, impressions,
          clicks, ctr, cpc, cpm, conversions, cost_per_conversion. Normalize
          micros → currency unit, ctr stay percent (0-100 scale từ Google).
        - [] nếu credential thiếu hoặc account chưa có campaign
        """
        if not self.ready:
            log.info("Google Ads client chưa ready (missing credential), skip fetch")
            return []

        try:
            access_token = await self._get_access_token()
        except GoogleAdsAPIError as exc:
            log.warning("Skip Google Ads fetch vì OAuth fail: %r", exc)
            return []

        url = f"{self.base_url}/customers/{self.customer_id}/googleAds:searchStream"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "developer-token": self.developer_token,
            "Content-Type": "application/json",
        }
        if self.login_customer_id:
            headers["login-customer-id"] = self.login_customer_id

        payload = {"query": query}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("Google Ads HTTP error: %r", exc)
            return []

        if resp.status_code != 200:
            log.warning(
                "Google Ads searchStream fail status=%s body=%s",
                resp.status_code,
                resp.text[:300],
            )
            return []

        # searchStream returns array of GoogleAdsResponse chunks
        try:
            chunks = resp.json()
        except json.JSONDecodeError:
            log.warning("Google Ads response không phải JSON: %s", resp.text[:200])
            return []

        if not isinstance(chunks, list):
            chunks = [chunks]

        rows: list[dict[str, Any]] = []
        for chunk in chunks:
            for result in chunk.get("results", []) or []:
                rows.append(self._normalize_row(result))
        return rows

    @staticmethod
    def _normalize_row(result: dict[str, Any]) -> dict[str, Any]:
        """Convert Google Ads response row → flat dict matching FB insights shape."""
        campaign = result.get("campaign", {}) or {}
        metrics = result.get("metrics", {}) or {}

        cost_micros = int(metrics.get("costMicros") or 0)
        spend = cost_micros / 1_000_000  # micros → currency

        impressions = int(metrics.get("impressions") or 0)
        clicks = int(metrics.get("clicks") or 0)
        ctr = float(metrics.get("ctr") or 0) * 100  # Google returns 0-1, convert percent
        cpc_micros = int(metrics.get("averageCpc") or 0)
        cpc = cpc_micros / 1_000_000
        cpm_micros = int(metrics.get("averageCpm") or 0)
        cpm = cpm_micros / 1_000_000
        conversions = float(metrics.get("conversions") or 0)
        cpa_micros = int(metrics.get("costPerConversion") or 0)
        cost_per_conversion = cpa_micros / 1_000_000

        return {
            "campaign_id": str(campaign.get("id") or ""),
            "campaign_name": campaign.get("name") or "",
            "campaign_status": campaign.get("status") or "",
            "spend": spend,
            "impressions": impressions,
            "clicks": clicks,
            "ctr": ctr,
            "cpc": cpc,
            "cpm": cpm,
            "conversions": conversions,
            "cost_per_conversion": cost_per_conversion,
        }
