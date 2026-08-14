"""Gửi email cho học viên BreakoutOS. Đường chính GHL, đường lùi Brevo.

Vì sao đổi (2026-08-13): Brevo hết credit từ 19/07 (kiểm tra API thấy
sendLimit còn 0). Mọi email cho học viên đang thất bại trong im lặng. Anna đã
chuyển Về Úc sang GHL hồi tháng 7, camas-kernel là chỗ còn sót lại.

Vì sao chưa dùng AWS SES: SES còn ở sandbox (ProductionAccessEnabled=False),
chỉ gửi được tới địa chỉ đã xác minh. Gmail của học viên chưa xác minh nên
SES sẽ từ chối. Khi nào xin được production access thì chuyển sang SES vì
rẻ và ổn định hơn.

Đổi đường bằng biến EMAIL_PROVIDER: ghl (mặc định) | brevo.


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


async def _send_brevo_raw(
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


GHL_SEARCH_URL = "https://services.leadconnectorhq.com/contacts/search"
GHL_MESSAGE_URL = "https://services.leadconnectorhq.com/conversations/messages"


async def send_ghl_email(
    to_email: str, to_name: str | None, subject: str, html: str,
) -> bool:
    """Gửi email qua GHL Conversations API.

    GHL gửi theo contact chứ không theo địa chỉ, nên phải tìm contact trước.
    Không tìm thấy thì trả False, KHÔNG tự tạo contact mới: tạo contact là
    đụng vào dữ liệu CRM của Anna, không phải việc của lớp gửi email.
    """
    if httpx is None:
        log.warning("httpx unavailable, skip email to %s", to_email)
        return False
    tok = os.environ.get("GHL_API_KEY", "").strip()
    loc = os.environ.get("GHL_LOCATION_ID", "").strip()
    if not tok or not loc:
        log.warning("GHL_API_KEY/GHL_LOCATION_ID chua set, skip email")
        return False
    if not to_email or "@" not in to_email:
        log.warning("invalid to_email %r, skip", to_email)
        return False
    headers = {
        "Authorization": f"Bearer {tok}",
        "Version": "2021-07-28",
        "Content-Type": "application/json",
        # GHL chan request thieu User-Agent (loi 403 "1010").
        "User-Agent": "camas-kernel/1.0",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(GHL_SEARCH_URL, headers=headers, json={
                "locationId": loc, "pageLimit": 1,
                "filters": [{"field": "email", "operator": "eq", "value": to_email}],
            })
            if r.status_code >= 300:
                log.warning("GHL tim contact loi %s: %s", r.status_code, r.text[:160])
                return False
            contacts = (r.json() or {}).get("contacts", [])
            if not contacts:
                log.warning("GHL khong co contact cho %s, khong gui duoc", to_email)
                return False
            r2 = await client.post(GHL_MESSAGE_URL, headers=headers, json={
                "type": "Email", "contactId": contacts[0]["id"], "locationId": loc,
                "subject": subject, "html": html,
                "emailFrom": SENDER["email"],
            })
            if r2.status_code >= 300:
                log.warning("GHL gui email loi %s: %s", r2.status_code, r2.text[:160])
                return False
            log.info("da gui email qua GHL toi %s", to_email)
            return True
    except Exception as exc:  # noqa: BLE001 - email hong khong duoc lam gay caller
        log.warning("GHL gui email that bai: %r", exc)
        return False


async def send_email(
    to_email: str, to_name: str | None, subject: str, html: str,
) -> bool:
    """Cua duy nhat de gui email cho hoc vien. Tu chon duong theo EMAIL_PROVIDER."""
    provider = os.environ.get("EMAIL_PROVIDER", "ghl").strip().lower()
    if provider == "brevo":
        return await _send_brevo_raw(to_email, to_name, subject, html)
    if await send_ghl_email(to_email, to_name, subject, html):
        return True
    log.warning("GHL that bai, thu lui ve Brevo cho %s", to_email)
    return await _send_brevo_raw(to_email, to_name, subject, html)


async def send_brevo_email(
    to_email: str, to_name: str | None, subject: str, html: str,
) -> bool:
    """Ten cu, giu de cho goi khong phai sua. Thuc te di qua send_email()."""
    return await send_email(to_email, to_name, subject, html)
