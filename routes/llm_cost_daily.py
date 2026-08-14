"""Bao cao chi phi LLM hang ngay, gui Telegram cho Anna.

Vi sao co file nay (2026-08-13):
    Anna nap $539 credit trong 3 thang ma khong biet tien di dau. Ngay 11/06
    nap 4 lan trong mot ngay, tuc chay het nhanh hon toc do bom vao, va khong
    ai phat hien luc dang xay ra. Bao cao hang ngay de chuyen tu "phat hien khi
    het tien" sang "thay ngay hom sau".

Nguon: breakoutos.llm_usage_log (camas-kernel + breakout-app).

Chay tu dong trong app, khong can cron ngoai. Bat bang LLM_COST_REPORT_AUTO=1.
Goi tay: POST /cron/llm-cost-report (kem header x-camas-cron-secret).
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets as _secrets
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException

from routes.sdl_routes import get_pool
from routes.telegram_alert import send_telegram

log = logging.getLogger("camas.llm_cost_daily")
router = APIRouter(tags=["llm-cost"])

_CRON_SECRET = os.environ.get("CAMAS_CRON_SECRET", "")
# Anna o Perth. Bao cao gui sang som gio Perth chu khong phai gio UTC.
_TZ = ZoneInfo(os.environ.get("REPORT_TZ", "Australia/Perth"))
_REPORT_HOUR = int(os.environ.get("LLM_COST_REPORT_HOUR", "7"))

# Nguong canh bao, USD mot ngay. Vuot thi bao gap.
_NGUONG_CANH_BAO = float(os.environ.get("LLM_COST_ALERT_USD", "20"))

# Ty gia quy ra tien Viet. De thanh bien de chinh duoc khi ty gia doi,
# va IN RO trong bao cao de Anna biet con so dua tren ty gia nao.
_TY_GIA = float(os.environ.get("USD_VND_RATE", "26000"))

_NHAN_NHOM = {
    "hoc_vien_lam_bai": "Học viên làm bài",
    "chat_lop": "Chat lớp",
    "gap_report": "Gap Report",
    "cron": "Cron chạy nền",
    "agent_noi_bo": "Agent nội bộ",
    "fb_autoreply": "Trả lời Facebook",
    "backfill_thu_cong": "Chạy lại thủ công",
    "test_manual": "Test, chạy tay",
    "route_khac": "Route khác",
    "khong_ro": "Không rõ",
}


def _usd(v: Any) -> str:
    """Hien ca do la lan tien Viet. Anna doc tien Viet nhanh hon."""
    if v is None:
        return "n/a"
    u = float(v)
    d = u * _TY_GIA
    if d >= 1_000_000:
        tien_viet = f"{d/1_000_000:.1f} triệu"
    elif d >= 1000:
        tien_viet = f"{d/1000:.0f} nghìn"
    else:
        tien_viet = f"{d:.0f}đ"
    return f"${u:.4f} ({tien_viet})"


async def build_daily_report(pool: asyncpg.Pool, ngay: Optional[str] = None) -> str:
    """Dung noi dung bao cao cho MOT ngay (mac dinh hom qua, gio Perth)."""
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='breakoutos' AND table_name='llm_usage_log'"
        )
        if not exists:
            return "⚠️ Chưa có bảng llm_usage_log. Chạy migration 019 trước."

        # asyncpg doi kieu date that, khong nhan chuoi cho tham so ::date.
        if ngay:
            ngay_obj = date.fromisoformat(ngay)
        else:
            ngay_obj = datetime.now(_TZ).date() - timedelta(days=1)
        hom_qua = ngay_obj.isoformat()

        tong = await conn.fetchrow(
            """
            SELECT count(*) AS so_lan, sum(input_tokens) AS vao, sum(output_tokens) AS ra,
                   sum(estimated_cost_usd) AS tien,
                   count(*) FILTER (WHERE NOT success) AS loi
            FROM breakoutos.llm_usage_log
            WHERE (occurred_at AT TIME ZONE 'UTC' AT TIME ZONE $2)::date = $1::date
            """,
            ngay_obj, str(_TZ),
        )
        if not tong or not tong["so_lan"]:
            return (
                f"📊 <b>Chi phí AI ngày {hom_qua}</b>\n"
                f"Không có lệnh gọi nào. Hệ thống im, không tốn đồng nào."
            )

        truoc = await conn.fetchval(
            """
            SELECT sum(estimated_cost_usd) FROM breakoutos.llm_usage_log
            WHERE (occurred_at AT TIME ZONE 'UTC' AT TIME ZONE $2)::date = ($1::date - 1)
            """,
            ngay_obj, str(_TZ),
        )

        theo_nhom = await conn.fetch(
            """
            SELECT call_group, count(*) AS so_lan, sum(estimated_cost_usd) AS tien
            FROM breakoutos.llm_usage_log
            WHERE (occurred_at AT TIME ZONE 'UTC' AT TIME ZONE $2)::date = $1::date
            GROUP BY 1 ORDER BY tien DESC NULLS LAST LIMIT 6
            """,
            ngay_obj, str(_TZ),
        )
        theo_model = await conn.fetch(
            """
            SELECT model, count(*) AS so_lan, sum(estimated_cost_usd) AS tien
            FROM breakoutos.llm_usage_log
            WHERE (occurred_at AT TIME ZONE 'UTC' AT TIME ZONE $2)::date = $1::date
            GROUP BY 1 ORDER BY tien DESC NULLS LAST LIMIT 5
            """,
            ngay_obj, str(_TZ),
        )
        top = await conn.fetch(
            """
            SELECT source, caller, count(*) AS so_lan, sum(estimated_cost_usd) AS tien
            FROM breakoutos.llm_usage_log
            WHERE (occurred_at AT TIME ZONE 'UTC' AT TIME ZONE $2)::date = $1::date
            GROUP BY 1,2 ORDER BY tien DESC NULLS LAST LIMIT 3
            """,
            ngay_obj, str(_TZ),
        )

    tien = float(tong["tien"] or 0)
    dong = [f"📊 <b>Chi phí AI ngày {hom_qua}</b>", ""]

    if tien >= _NGUONG_CANH_BAO:
        dong.insert(0, f"🚨 <b>VƯỢT NGƯỠNG {_usd(_NGUONG_CANH_BAO)}</b>")

    xu_huong = ""
    if truoc is not None and float(truoc) > 0:
        pct = (tien - float(truoc)) / float(truoc) * 100
        mui = "▲" if pct > 0 else "▼"
        xu_huong = f"  ({mui}{abs(pct):.0f}% so với hôm trước)"
    dong.append(f"<b>Tổng: {_usd(tien)}</b>{xu_huong}")
    dong.append(
        f"{tong['so_lan']} lần gọi · {int(tong['vao'] or 0):,} token vào · "
        f"{int(tong['ra'] or 0):,} token ra"
    )
    if tong["loi"]:
        dong.append(f"⚠️ {tong['loi']} lần thất bại, đã trả tiền token nhưng không ra kết quả")

    dong.append("")
    dong.append("<b>Tiền đi đâu</b>")
    for r in theo_nhom:
        ten = _NHAN_NHOM.get(r["call_group"], r["call_group"] or "?")
        dong.append(f"· {ten}: {_usd(r['tien'])} ({r['so_lan']} lần)")

    dong.append("")
    dong.append("<b>Theo model</b>")
    for r in theo_model:
        dong.append(f"· {r['model']}: {_usd(r['tien'])} ({r['so_lan']} lần)")

    if top:
        dong.append("")
        dong.append("<b>Ba chỗ tốn nhất</b>")
        for r in top:
            dong.append(f"· [{r['source']}] {r['caller']}: {_usd(r['tien'])}")

    dong.append("")
    dong.append(f"<i>Quy đổi theo tỷ giá {_TY_GIA:,.0f}đ/$. Sai thì sửa biến USD_VND_RATE.</i>")
    return "\n".join(dong)


@router.post("/cron/llm-cost-report")
async def cron_llm_cost_report(
    ngay: Optional[str] = None,
    x_camas_cron_secret: Optional[str] = Header(None, alias="x-camas-cron-secret"),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Goi tay hoac tu cron ngoai. Truyen ?ngay=YYYY-MM-DD de chay lai ngay cu."""
    if _CRON_SECRET:
        if not x_camas_cron_secret or not _secrets.compare_digest(
            x_camas_cron_secret, _CRON_SECRET
        ):
            raise HTTPException(status_code=401, detail="cron secret required")
    noi_dung = await build_daily_report(pool, ngay)
    da_gui = await send_telegram(noi_dung)
    return {"da_gui": da_gui, "do_dai": len(noi_dung)}


_da_gui_ngay: Optional[str] = None


async def cost_report_scheduler_loop(stop_event) -> None:
    """Tu chay trong app, khong can cron ngoai.

    Kiem moi gio, gui khi toi gio Perth da hen va hom nay chua gui.
    Bat bang LLM_COST_REPORT_AUTO=1, mac dinh tat cho an toan.
    """
    global _da_gui_ngay
    if os.getenv("LLM_COST_REPORT_AUTO", "0") != "1":
        log.info("bao cao chi phi LLM: tat (LLM_COST_REPORT_AUTO != 1)")
        return
    await asyncio.sleep(45)  # cho app on dinh
    log.info("bao cao chi phi LLM: bat, gui luc %sh gio Perth", _REPORT_HOUR)
    while not stop_event.is_set():
        try:
            gio_perth = datetime.now(_TZ)
            hom_nay = gio_perth.date().isoformat()
            if gio_perth.hour == _REPORT_HOUR and _da_gui_ngay != hom_nay:
                from routes.sdl_routes import get_pool as _gp

                pool = await _gp()
                noi_dung = await build_daily_report(pool)
                if await send_telegram(noi_dung):
                    _da_gui_ngay = hom_nay
                    log.info("da gui bao cao chi phi LLM cho %s", hom_nay)
                else:
                    log.warning("gui bao cao chi phi LLM that bai, se thu lai gio sau")
        except Exception as exc:  # noqa: BLE001 - bao cao hong khong duoc lam gay app
            log.warning("bao cao chi phi LLM loi: %r", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=3600)
        except asyncio.TimeoutError:
            pass
