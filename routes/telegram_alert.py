"""Telegram alert helper for SDL key events.

Per Anna 2026-06-12: "Khi có ai test, cần báo Anna kiểm tra kết quả ngay."

Critical events to alert:
- payment.completed (Sepay)
- baseline.filled (T0 freedom score)
- l1.intake.submitted
- gate_1_founder.locked
- l2.intake.submitted
- gate_2_customer_soft.locked
- l3.intake.submitted
- gate_3_value_proposition.locked
- module_chon.run.completed
- feedback.submitted
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request

from routes._auth import sign_student


log = logging.getLogger("camas.tg_alert")

TG_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_OPS_GROUP = os.environ.get("TELEGRAM_OPS_GROUP_ID", "-1003813280155")
BREAKOUTOS_ADMIN_KEY = os.environ.get("BREAKOUTOS_ADMIN_KEY", "")


def send_telegram_sync(message: str, chat_id: str | None = None, parse_mode: str = "HTML") -> bool:
    """Synchronous Telegram send. Returns True if 200 OK."""
    if not TG_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set, skip alert")
        return False
    target = chat_id or TG_OPS_GROUP
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": target,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status == 200
    except Exception as exc:
        log.warning("Telegram alert fail: %r", exc)
        return False


async def send_telegram(message: str, chat_id: str | None = None) -> bool:
    """Async wrapper. Runs sync call in executor."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, send_telegram_sync, message, chat_id)


def _student_meta_block(student_id: str, email: str = "", name: str = "") -> str:
    return (
        f"<b>Student:</b> {name or '(no name)'}\n"
        f"<b>Email:</b> {email or '(no email)'}\n"
        f"<b>ID:</b> <code>{student_id[:8]}…</code>\n"
        f"<b>Dashboard:</b> https://os.breakout.live/sdl/student/{student_id}/dashboard\n"
        f"<b>Admin:</b> https://os.breakout.live/sdl/admin/founder-dashboard?key={BREAKOUTOS_ADMIN_KEY}"
    )


# ============================================================
# Event-specific alert builders
# ============================================================
def alert_baseline_filled(student_id: str, email: str = "", name: str = "",
                          total_score: int = 0) -> None:
    signature = sign_student(student_id)
    msg = (
        f"🎯 <b>BASELINE T0 đo xong</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_student_meta_block(student_id, email, name)}\n"
        f"<b>Điểm khởi đầu:</b> {total_score}/100\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Action Anna:</b> Gửi link L1 form qua Zalo:\n"
        f"https://os.breakout.live/foundation/l1?student={student_id}&sig={signature}"
    )
    send_telegram_sync(msg)


def alert_l1_intake_submitted(student_id: str, email: str = "", name: str = "") -> None:
    signature = sign_student(student_id)
    msg = (
        f"📝 <b>L1 INTAKE SUBMITTED</b> (Founder OS)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_student_meta_block(student_id, email, name)}\n"
        f"<b>Trạng thái:</b> 5 Tier A đã lưu, AI đang sinh 3 Tier B (~1-2 phút)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Action Anna:</b> Đợi AI extract xong, review canonical files với student qua Zalo:\n"
        f"https://os.breakout.live/sdl/students/{student_id}/output/L1?sig={signature}"
    )
    send_telegram_sync(msg)


def alert_gate_locked(student_id: str, gate_key: str, email: str = "", name: str = "") -> None:
    gate_human = {
        "gate_1_founder": "🔒 Gate 1 · Founder Cert (HARD LOCK)",
        "gate_2_customer_soft": "🔓 Gate 2A · Customer Soft Cert",
        "gate_2_customer_hard": "🔒 Gate 2B · Customer Hard Cert (escalated)",
        "gate_3_value_proposition": "🔒 Gate 3 · Value Proposition Cert (HARD LOCK)",
        "gate_4_business_operating": "🔒 Gate 4 · Business Operating Cert",
        "gate_5_revenue_growth": "🔒 Gate 5 · Revenue Growth Cert",
        "gate_6a_founder_freedom": "🎓 Gate 6a · Founder Freedom GRADUATED",
    }.get(gate_key, gate_key)
    msg = (
        f"{gate_human}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_student_meta_block(student_id, email, name)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Action Anna:</b> Chúc mừng student qua Zalo, mở tầng tiếp theo."
    )
    send_telegram_sync(msg)


def alert_l2_intake_submitted(student_id: str, fit_score: int, email: str = "", name: str = "") -> None:
    signature = sign_student(student_id)
    msg = (
        f"📝 <b>L2 INTAKE SUBMITTED</b> (Customer Intelligence OS)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_student_meta_block(student_id, email, name)}\n"
        f"<b>Customer Fit Score:</b> {fit_score}/100 {'✓' if fit_score >= 60 else '⚠ thấp'}\n"
        f"<b>AI đang sinh:</b> 7 Tier B (~3-5 phút)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Action:</b>\n"
        f"https://os.breakout.live/sdl/students/{student_id}/output/L2?sig={signature}"
    )
    send_telegram_sync(msg)


def alert_l3_intake_submitted(student_id: str, offer_name: str = "", email: str = "", name: str = "") -> None:
    signature = sign_student(student_id)
    msg = (
        f"📝 <b>L3 INTAKE SUBMITTED</b> (Value Proposition OS)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_student_meta_block(student_id, email, name)}\n"
        f"<b>Offer:</b> {offer_name}\n"
        f"<b>AI Opus đang sinh:</b> Value Equation + Guarantee + Offer Stack + Financial Model\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Action:</b>\n"
        f"https://os.breakout.live/sdl/students/{student_id}/output/L3?sig={signature}"
    )
    send_telegram_sync(msg)


def alert_module_chon_run(student_id: str, total_score: int = 0,
                         classification: str = "", email: str = "", name: str = "") -> None:
    msg = (
        f"⚙️ <b>MODULE CHỌN ĐÃ CHẠY</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_student_meta_block(student_id, email, name)}\n"
        f"<b>Opportunity Score:</b> {total_score}/100 · {classification}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    send_telegram_sync(msg)


def alert_feedback(student_id: str, target_type: str, rating: int,
                  comment: str = "", email: str = "", name: str = "") -> None:
    emoji = "🟢" if rating >= 8 else ("🟡" if rating >= 6 else "🔴")
    msg = (
        f"{emoji} <b>FEEDBACK</b> · {target_type} · {rating}/10\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_student_meta_block(student_id, email, name)}\n"
        f"<b>Comment:</b> {comment[:300] if comment else '(no comment)'}\n"
    )
    send_telegram_sync(msg)


def alert_test_action(action: str, student_id: str, email: str = "", name: str = "",
                     extra: dict | None = None) -> None:
    """Generic alert for any test/student action."""
    extra_str = ""
    if extra:
        extra_str = "\n".join(f"<b>{k}:</b> {v}" for k, v in extra.items())
    msg = (
        f"⚡ <b>STUDENT ACTION</b> · {action}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_student_meta_block(student_id, email, name)}\n"
        + (f"{extra_str}\n" if extra_str else "")
    )
    send_telegram_sync(msg)
