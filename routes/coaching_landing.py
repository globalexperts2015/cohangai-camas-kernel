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
from fastapi.responses import HTMLResponse, RedirectResponse


router = APIRouter(tags=["mentoring-landing"])

_LANDING_FILE = Path(__file__).resolve().parent.parent / "static" / "coaching-landing.html"


@router.get("/coaching", response_class=HTMLResponse, include_in_schema=False)
@router.get("/mentoring", response_class=HTMLResponse)
async def coaching_landing() -> HTMLResponse:
    return HTMLResponse(_LANDING_FILE.read_text(encoding="utf-8"))


@router.get("/coaching/apply", include_in_schema=False)
@router.get("/mentoring/apply", include_in_schema=False)
async def coaching_apply_redirect() -> RedirectResponse:
    return RedirectResponse(url="/coaching", status_code=301)
