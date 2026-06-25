"""Brevo transactional email helper cho thông báo student-facing BreakoutOS.

Sender + replyTo theo quy ước Anna: "Đào Thị Hằng" <support@daothihang.com>.
Best-effort: mọi lỗi gửi đều nuốt + log, KHÔNG raise (caller không được fail vì email).
"""
from __future__ import annotations

import logging
import os

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore

log = logging.getLogger("camas.email")

SENDER = {"name": "Đào Thị Hằng", "email": "support@daothihang.com"}
REPLY_TO = {"email": "support@daothihang.com"}
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


async def send_brevo_email(
    to_email: str, to_name: str | None, subject: str, html: str,
) -> bool:
    """Gửi 1 email transactional qua Brevo. Trả True nếu Brevo nhận (2xx)."""
    if httpx is None:
        log.warning("httpx unavailable, skip email to %s", to_email)
        return False
    key = os.environ.get("BREVO_API_KEY", "")
    if not key:
        log.warning("BREVO_API_KEY not set, skip email to %s", to_email)
        return False
    if not to_email or "@" not in to_email:
        log.warning("invalid to_email %r, skip", to_email)
        return False
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                BREVO_URL,
                json={
                    "sender": SENDER,
                    "to": [{"email": to_email, "name": to_name or to_email}],
                    "subject": subject,
                    "htmlContent": html,
                    "replyTo": REPLY_TO,
                },
                headers={"api-key": key, "content-type": "application/json"},
            )
        ok = resp.status_code in (200, 201, 202)
        if not ok:
            log.warning("Brevo send fail %s: %s", resp.status_code, resp.text[:200])
        return ok
    except Exception as exc:  # noqa: BLE001
        log.warning("Brevo send exception to %s: %r", to_email, exc)
        return False
