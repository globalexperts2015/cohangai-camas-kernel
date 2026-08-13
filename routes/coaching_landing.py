"""Coaching Landing Page, Breakout Coaching 52 tuần.

GET /coaching        Landing chính (serve static/coaching-landing.html)
GET /mentoring       Alias lịch sử, cùng nội dung
GET /coaching/apply  Redirect về /coaching (flow apply 12 tuần cũ đã bỏ)
GET /mentoring/apply Redirect về /coaching

Chương trình hiện hành (từ 07/2026): Breakout Coaching 52 tuần, thanh toán
trực tiếp trên trang, không có bước ứng tuyển/xét duyệt. Form application
của bản mentoring 12 tuần cũ (2026-06-13) đã gỡ 2026-08-05 vì sai offer
hiện hành và không còn POST handler.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse


router = APIRouter(tags=["mentoring-landing"])

_LANDING_FILE = Path(__file__).resolve().parent.parent / "static" / "coaching-landing.html"


@router.get("/coaching", response_class=HTMLResponse, include_in_schema=False)
@router.get("/mentoring", response_class=HTMLResponse)
async def coaching_landing() -> HTMLResponse:
    return HTMLResponse(_LANDING_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# CAU TRUC URL CANONICAL, Anna chot 2026-08-12
#
#   Khoa mien phi   https://breakout.live/
#   Foundation      https://os.breakout.live/foundation
#   Customer System https://os.breakout.live/customer-system
#   Growth System   https://os.breakout.live/growth-system
#   Khoa tong 7 tuan https://os.breakout.live/bof
#   Coaching        https://os.breakout.live/coaching
#
# Moi URL cu deu 301 ve URL canonical tuong ung, KHONG xoa, de link da phat ra
# ngoai khong chet va Google chi index MOT URL cho moi khoa.
# ---------------------------------------------------------------------------

_BOF_FILE = Path(__file__).resolve().parent.parent / "static" / "bof-landing.html"


@router.get("/bof", response_class=HTMLResponse, include_in_schema=False)
async def bof_landing() -> HTMLResponse:
    """Khoa tong 7 tuan (Foundation + Customer System + Growth System), 24tr.

    Bac truoc Breakout Coaching 52 tuan: hoc phi 24tr duoc khau tru vao 150tr neu
    hoc vien di tiep trong 3 thang sau khi ket thuc khoa.
    Nguon noi dung: wiki/projects/breakout/landing-nen-tang-van-hanh-7-tuan-2026-08-12.md
    """
    return HTMLResponse(_BOF_FILE.read_text(encoding="utf-8"))


@router.get("/fob", include_in_schema=False)
@router.get("/nen-tang-van-hanh", include_in_schema=False)
async def bof_landing_aliases():
    """URL cu -> /bof canonical."""
    return RedirectResponse(url="/bof", status_code=301)


_CS_FILE = Path(__file__).resolve().parent.parent / "static" / "customer-success-landing.html"


@router.get("/customer-system", response_class=HTMLResponse, include_in_schema=False)
async def customer_system_landing() -> HTMLResponse:
    """Khoa Customer System, tang 2 thang san pham Breakout, 6tr.

    Dinh vi (Anna chot 12/08): khong dung o cham soc khach sau ban, ma la
    hieu khach -> tim van de cot loi -> thiet ke phieu san pham -> roi moi cham soc.
    Giao trinh: 7 module CIS (wiki/projects/breakout/giao-trinh/customer-insight-system-outline.md).
    Thanh toan dung san pham `customer` da chay san (6tr, tag breakout-da-mua-customer-system).
    """
    return HTMLResponse(_CS_FILE.read_text(encoding="utf-8"))


@router.get("/customer-success", include_in_schema=False)
async def customer_system_alias():
    """URL cu -> /customer-system canonical."""
    return RedirectResponse(url="/customer-system", status_code=301)


_GS_FILE = Path(__file__).resolve().parent.parent / "static" / "growth-system-landing.html"


@router.get("/growth-system", response_class=HTMLResponse, include_in_schema=False)
async def growth_system_landing() -> HTMLResponse:
    """Khoa Growth System, tang 3 thang san pham Breakout, 15tr.

    Chuyen ve os.breakout.live 2026-08-12 theo cau truc URL Anna chot. Ban goc
    truoc do o breakout/webapp/frontend/growth-system.html (nay 301 sang day).
    """
    return HTMLResponse(_GS_FILE.read_text(encoding="utf-8"))


@router.get("/thanh-toan-coaching", response_class=HTMLResponse, include_in_schema=False)
async def coaching_payment_private() -> HTMLResponse:
    """Trang thanh toan kin, Anna gui rieng sau khi khach dong y (2026-08-06)."""
    _f = Path(__file__).resolve().parent.parent / "static" / "thanh-toan-coaching.html"
    return HTMLResponse(_f.read_text(encoding="utf-8"))


GSC_VERIFICATION_TOKENS = {"c66fa30bfc653b0e"}  # token file GSC cua Anna


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    """Sitemap os.breakout.live: chi trang marketing public (GSC 2026-08-06)."""
    urls = "".join(f"<url><loc>https://os.breakout.live{p}</loc></url>" for p in ["/coaching", "/foundation", "/customer-system", "/growth-system", "/bof"])
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    from fastapi.responses import Response
    return Response(content=xml, media_type="application/xml")


@router.get("/google{gsc_token}.html", include_in_schema=False)
async def gsc_verification_file(gsc_token: str) -> PlainTextResponse:
    """GSC FILE verification: chi tra token da biet, ten khac 404 (Google probe chong catch-all)."""
    if gsc_token not in GSC_VERIFICATION_TOKENS:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")
    return PlainTextResponse(f"google-site-verification: google{gsc_token}.html")


@router.get("/coaching/apply", include_in_schema=False)
@router.get("/mentoring/apply", include_in_schema=False)
async def coaching_apply_redirect() -> RedirectResponse:
    return RedirectResponse(url="/coaching", status_code=301)
