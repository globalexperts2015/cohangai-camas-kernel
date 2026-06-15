"""K3 bridge: poll WebinarKit registrants -> CAMAS register (luồng "WK trước -> CAMAS").

Chạy TRONG CAMAS (canonical backend). Poll registrant của webinar Breakout Challenge
dùng chung, lọc theo session date K3, rồi tạo session CAMAS in-process (idempotent).
Tránh hẳn duplication ở breakout/webapp. Cron-job.org gọi /cron/k3-bridge mỗi 5-15 phút.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets as _secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Header, HTTPException
from typing import Optional

log = logging.getLogger("camas.k3_bridge")
router = APIRouter(tags=["k3-bridge"])

WK_BASE = "https://webinarkit.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/537.36"
WK_WEBINAR_ID = os.getenv("WEBINARKIT_WEBINAR_ID", "6a1da3ca0137ce8107b43d76")
WK_WHITELABEL = os.getenv("WEBINARKIT_WHITELABEL", "webinar.breakout.live")
K3_DATES = {
    d.strip()
    for d in os.getenv(
        "K3_SESSION_DATES", "2026-06-18,2026-06-19,2026-06-20"
    ).split(",")
    if d.strip()
}
K3_COHORT = os.getenv("K3_COHORT_ID", "k3-2026-06")
_CRON_SECRET = os.getenv("CAMAS_CRON_SECRET", "")

_cookie_cache: dict[str, object] = {"cookie": None, "exp": 0.0}


def _wk_login() -> str:
    email = os.environ.get("WEBINARKIT_EMAIL", "").strip()
    pw = os.environ.get("WEBINARKIT_PASSWORD", "").strip()
    if not email or not pw:
        raise RuntimeError("WEBINARKIT_EMAIL/PASSWORD chưa set")
    req = urllib.request.Request(f"{WK_BASE}/signin", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        html = r.read().decode("utf-8", "ignore")
        set_cookies = r.headers.get_all("Set-Cookie") or []
    m = re.search(r'name="_csrf"\s+value="([^"]+)"', html)
    if not m:
        raise RuntimeError("Không tìm thấy _csrf trong WK signin")
    pre = "; ".join(c.split(";", 1)[0] for c in set_cookies)
    body = urllib.parse.urlencode(
        {"_csrf": m.group(1), "email": email, "password": pw}
    ).encode()
    req = urllib.request.Request(
        f"{WK_BASE}/signin", data=body, method="POST",
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": pre,
            "Referer": f"{WK_BASE}/signin",
        },
    )

    class _NoRedir(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(_NoRedir)
    try:
        opener.open(req, timeout=20)
        raise RuntimeError("WK login không redirect (credentials sai?)")
    except urllib.error.HTTPError as e:
        if e.code not in (302, 303):
            raise RuntimeError(f"WK login status {e.code}")
        post = e.headers.get_all("Set-Cookie") or []
    if not post:
        raise RuntimeError("WK login không có Set-Cookie")
    cookie = "; ".join(c.split(";", 1)[0] for c in post)
    _cookie_cache["cookie"] = cookie
    _cookie_cache["exp"] = time.time() + 6 * 3600
    return cookie


def _cookie() -> str:
    c = _cookie_cache.get("cookie")
    if c and float(_cookie_cache.get("exp", 0)) > time.time() + 60:
        return str(c)
    return _wk_login()


def _fetch_registrants() -> list[dict]:
    cookie = _cookie()
    rows: list[dict] = []
    base = f"https://{WK_WHITELABEL}/webinar/analytics/registrants/{WK_WEBINAR_ID}"
    for page in range(0, 200):
        url = f"{base}?page={page}"
        hdr = {"User-Agent": UA, "Cookie": cookie, "Accept": "application/json"}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=20) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 401 and page == 0:
                cookie = _wk_login()
                hdr["Cookie"] = cookie
                with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=20) as r:
                    body = r.read()
            else:
                raise
        chunk = (json.loads(body) or {}).get("registrants") or []
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < 25:
            break
    return rows


@router.post("/cron/k3-bridge")
async def cron_k3_bridge(
    x_camas_cron_secret: Optional[str] = Header(None, alias="x-camas-cron-secret"),
) -> dict:
    """Poll WK registrants K3 -> tạo session CAMAS in-process (idempotent)."""
    if _CRON_SECRET:
        if not x_camas_cron_secret or not _secrets.compare_digest(
            x_camas_cron_secret, _CRON_SECRET
        ):
            raise HTTPException(status_code=401, detail="cron secret required")
    # Lazy import tránh circular.
    from routes.challenge_k3 import register, RegisterRequest
    from routes.sdl_routes import get_pool

    regs = await asyncio.to_thread(_fetch_registrants)
    seen: set[str] = set()
    matched: list[tuple[str, str]] = []
    for r in regs:
        email = (r.get("email") or "").strip().lower()
        if not email or "@" not in email or email in seen:
            continue
        if (r.get("presentationDate") or "")[:10] in K3_DATES:
            seen.add(email)
            matched.append((email, (r.get("name") or r.get("firstName") or "")))

    pool = await get_pool()
    registered = 0
    errors: list[str] = []
    for email, name in matched:
        try:
            await register(
                RegisterRequest(
                    email=email,
                    full_name=name or None,
                    cohort_id=K3_COHORT,
                    access_tier="free",
                ),
                pool=pool,
                idempotency_key=f"wk-bridge:{email}",
            )
            registered += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{email}: {type(exc).__name__}")
    log.info("k3-bridge: fetched=%d matched=%d registered=%d", len(regs), len(matched), registered)
    return {
        "fetched": len(regs),
        "matched": len(matched),
        "registered": registered,
        "errors": errors[:10],
    }
