"""External API clients for Market Demand Engine.

Sources:
- DataForSEO: keyword volume + CPC + competition + SERP top 10
- YouTube Data API v3: search result count + top video stats
- Google Trends (pytrends): trend growth 12 months

All clients cache results 7 ngày trong `market_signal_cache` table.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

import asyncpg

log = logging.getLogger("camas.e6_market_demand.external_apis")

DATAFORSEO_LOGIN = os.environ.get("DATAFORSEO_LOGIN", "").strip()
DATAFORSEO_PASSWORD = os.environ.get("DATAFORSEO_PASSWORD", "").strip()
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
LOCATION_CODE_VN = 1028581
LANGUAGE_CODE_VI = "vi"


async def _get_cached(pool: asyncpg.Pool, keyword: str, source: str,
                       location_code: int = LOCATION_CODE_VN,
                       language_code: str = LANGUAGE_CODE_VI) -> Optional[dict]:
    """Check cache 7 ngày."""
    if not pool:
        return None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT signal_json FROM market_signal_cache "
            "WHERE keyword=$1 AND source=$2 AND location_code=$3 AND language_code=$4 "
            "AND expires_at > NOW() ORDER BY fetched_at DESC LIMIT 1",
            keyword, source, location_code, language_code,
        )
        if row:
            return row["signal_json"]
    return None


async def _set_cached(pool: asyncpg.Pool, keyword: str, source: str,
                       signal_json: dict,
                       location_code: int = LOCATION_CODE_VN,
                       language_code: str = LANGUAGE_CODE_VI) -> None:
    """Save cache 7 ngày, upsert key."""
    if not pool:
        return
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO market_signal_cache (keyword, location_code, language_code, source, signal_json) "
            "VALUES ($1, $2, $3, $4, $5::jsonb) "
            "ON CONFLICT (keyword, location_code, language_code, source) DO UPDATE "
            "SET signal_json = $5::jsonb, fetched_at = NOW(), expires_at = NOW() + INTERVAL '7 days'",
            keyword, location_code, language_code, source, json.dumps(signal_json, ensure_ascii=False),
        )


def _sync_post(url: str, body: bytes, headers: dict) -> dict:
    """Blocking POST helper, gọi từ run_in_executor."""
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode(errors="ignore")[:300]}
    except Exception as e:
        return {"_error": "exception", "_body": str(e)[:200]}


def _sync_get(url: str, headers: dict = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode(errors="ignore")[:300]}
    except Exception as e:
        return {"_error": "exception", "_body": str(e)[:200]}


async def dataforseo_search_volume(pool: asyncpg.Pool, keywords: list[str]) -> dict:
    """Pull Search Volume + CPC + Competition cho 1-N keywords (VN, vi).
    Returns dict {keyword: {volume, cpc, competition_index, competition_level}}.
    """
    if not DATAFORSEO_LOGIN or not DATAFORSEO_PASSWORD:
        return {"_error": "DATAFORSEO_LOGIN/PASSWORD missing"}

    # Check cache per keyword
    cached = {}
    fetch_keywords = []
    for kw in keywords:
        c = await _get_cached(pool, kw, "dataforseo_volume")
        if c is not None:
            cached[kw] = c
        else:
            fetch_keywords.append(kw)

    fresh = {}
    if fetch_keywords:
        auth = base64.b64encode(f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()).decode()
        body = json.dumps([{
            "keywords": fetch_keywords,
            "location_code": LOCATION_CODE_VN,
            "language_code": LANGUAGE_CODE_VI,
        }]).encode()
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None,
            _sync_post,
            "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live",
            body,
            {"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        )
        if "_error" not in data:
            tasks = data.get("tasks", [])
            if tasks and tasks[0].get("status_code") == 20000:
                results = tasks[0].get("result", []) or []
                for r in results:
                    kw = r.get("keyword")
                    signal = {
                        "volume": r.get("search_volume", 0),
                        "cpc": r.get("cpc", 0),
                        "competition_index": r.get("competition_index", 0),
                        "competition_level": r.get("competition", "UNKNOWN"),
                    }
                    fresh[kw] = signal
                    await _set_cached(pool, kw, "dataforseo_volume", signal)
        else:
            log.warning("DataForSEO volume fail: %s", data)

    return {**cached, **fresh}


async def youtube_search_count(pool: asyncpg.Pool, keyword: str) -> dict:
    """Pull YouTube search result count + top video stats cho 1 keyword.
    Returns {total_results_estimated, top_3_videos: [{title, channel, view_count}]}.
    """
    if not YOUTUBE_API_KEY:
        return {"_error": "YOUTUBE_API_KEY missing"}

    cached = await _get_cached(pool, keyword, "youtube_search")
    if cached is not None:
        return cached

    encoded = urllib.parse.quote(keyword)
    url = (
        f"https://www.googleapis.com/youtube/v3/search"
        f"?part=snippet&type=video&q={encoded}&maxResults=10"
        f"&regionCode=VN&key={YOUTUBE_API_KEY}"
    )
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _sync_get, url)
    if "_error" in data:
        log.warning("YouTube search fail keyword=%s: %s", keyword, data)
        return {"_error": data["_error"], "_body": data.get("_body", "")}

    items = data.get("items", []) or []
    page_info = data.get("pageInfo", {})
    signal = {
        "total_results_estimated": page_info.get("totalResults", len(items)),
        "result_count": len(items),
        "top_3_videos": [
            {
                "title": (it.get("snippet", {}).get("title") or "")[:120],
                "channel": (it.get("snippet", {}).get("channelTitle") or "")[:80],
                "published_at": it.get("snippet", {}).get("publishedAt", ""),
            }
            for it in items[:3]
        ],
    }
    await _set_cached(pool, keyword, "youtube_search", signal)
    return signal


async def google_trends_growth(pool: asyncpg.Pool, keyword: str) -> dict:
    """Pull Google Trends 12 months growth % cho 1 keyword.
    Returns {trend_data: [...], growth_pct_12m, current_interest, peak_interest}.
    """
    cached = await _get_cached(pool, keyword, "google_trends")
    if cached is not None:
        return cached

    try:
        from pytrends.request import TrendReq
    except ImportError:
        return {"_error": "pytrends not installed"}

    def _fetch_blocking() -> dict:
        try:
            pytrends = TrendReq(hl="vi-VN", tz=420, timeout=(10, 25), retries=2, backoff_factor=1)
            pytrends.build_payload([keyword], cat=0, timeframe="today 12-m", geo="VN")
            df = pytrends.interest_over_time()
            if df.empty:
                return {"trend_data": [], "growth_pct_12m": 0, "current_interest": 0, "peak_interest": 0}
            values = df[keyword].tolist()
            current = values[-1] if values else 0
            peak = max(values) if values else 0
            first_half_avg = sum(values[: len(values) // 2]) / max(len(values) // 2, 1)
            second_half_avg = sum(values[len(values) // 2 :]) / max(len(values) - len(values) // 2, 1)
            growth = ((second_half_avg - first_half_avg) / max(first_half_avg, 1)) * 100
            return {
                "trend_data_points": len(values),
                "growth_pct_12m": round(growth, 1),
                "current_interest": int(current),
                "peak_interest": int(peak),
            }
        except Exception as e:
            return {"_error": str(e)[:200]}

    loop = asyncio.get_event_loop()
    signal = await loop.run_in_executor(None, _fetch_blocking)
    if "_error" not in signal:
        await _set_cached(pool, keyword, "google_trends", signal)
    return signal
