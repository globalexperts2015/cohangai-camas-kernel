"""Cohort Widget Routes for GHL Membership embed.

Sprint 14 P0.3 Cohort 1 LMS UI integration prototype.

Endpoints:
- GET /cohort/wizard/{wizard_name}: serve HTML page embed widget
- POST /cohort/run-wizard: trigger agent + return Markdown output
- POST /cohort/save-progress: save student progress to memory layer

Auth:
- Student auth qua header `X-Cohort-Student-Token`
- Token validate against GHL contact_id (placeholder stub, real: query GHL)
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from kernel.base_agent import ExecutionContext

log = logging.getLogger("camas.cohort_widget")

router = APIRouter(prefix="/cohort", tags=["cohort"])

STATIC_DIR = Path(__file__).parent.parent / "static"

# Wizard registry: student-facing name → agent_name + trigger_event + week
WIZARD_REGISTRY = {
    "vision_clarity": {
        "agent": "l2_vision_clarity",
        "event": "cohort.vision_clarity",
        "week": 1,
        "title": "Bước 1: Vision Clarity",
        "subtitle": "Làm rõ vision + life goal trước khi pick niche",
        "input_label": "Mô tả bản thân, mục tiêu, gia đình, lifestyle bạn muốn",
        "input_placeholder": "Ví dụ: Em là NV ngân hàng 38 tuổi, lương 18tr, 2 con. Muốn build AI Solo Empire để có thêm 15-20tr/tháng, gia đình ủng hộ, không bỏ việc ngay...",
        "input_field": "student_data",
    },
    "niche_validator": {
        "agent": "l2_niche_validator_student",
        "event": "cohort.niche_validate",
        "week": 2,
        "title": "Bước 2: Niche Validation",
        "subtitle": "Validate niche 3-indicator test",
        "input_label": "Niche statement bạn muốn validate",
        "input_placeholder": "Ví dụ: Dạy Shopify dropshipping cho mẹ bỉm 25-40 muốn kiếm 10tr/tháng tại nhà",
        "input_field": "niche_statement",
    },
    "transformation_mapper": {
        "agent": "l2_transformation_mapper_7d",
        "event": "cohort.transformation_map",
        "week": 3,
        "title": "Bước 3-4: Transformation 7D",
        "subtitle": "Map customer transformation across 7 dimensions",
        "input_label": "Persona target của bạn",
        "input_placeholder": "Ví dụ: Mẹ bỉm 25-40 muốn kiếm 10tr/tháng tại nhà từ Shopify dropshipping, lo lắng tương lai tài chính, gia đình chưa ủng hộ...",
        "input_field": "customer_persona",
    },
    "vpc_fit_check": {
        "agent": "l2_vpc_fit_checker",
        "event": "cohort.vpc_fit_check",
        "week": 5,
        "title": "Bước 5: VPC Fit Check",
        "subtitle": "Check fit Tròn Vuông persona ↔ product",
        "input_label": "Ý tưởng product/service của bạn",
        "input_placeholder": "Ví dụ: Course 6 tuần dạy Shopify dropshipping cho mẹ bỉm, giá 3M VND, group + 1on1 audit",
        "input_field": "product_idea",
    },
    "mvo_cohort": {
        "agent": "l2_mvo_cohort_launcher",
        "event": "cohort.mvo_launch_plan",
        "week": 6,
        "title": "Bước 5-6: MVO Cohort Launcher",
        "subtitle": "Design + launch first paid cohort 5-15 customer",
        "input_label": "VPC fit + ý tưởng MVO của bạn",
        "input_placeholder": "Tóm tắt output các bước trước...",
        "input_field": "vpc",
    },
    "offer_engineer": {
        "agent": "l2_offer_engineer_student",
        "event": "cohort.offer_engineer",
        "week": 7,
        "title": "Bước 7: Grand Slam Offer",
        "subtitle": "Build Hormozi $100M Offer cho first cohort",
        "input_label": "MVO + transformation context",
        "input_placeholder": "Tóm tắt MVO + transformation đã design...",
        "input_field": "mvo",
    },
    "referral_engine": {
        "agent": "l2_referral_engine_template",
        "event": "cohort.referral_engine_design",
        "week": 8,
        "title": "Bước 8: Referral Engine (Capstone)",
        "subtitle": "5th scale lever cho venture của bạn",
        "input_label": "Offer + persona đã design",
        "input_placeholder": "Tóm tắt offer + persona từ các bước trước...",
        "input_field": "offer",
    },
}


def _verify_student_token(token: Optional[str]) -> str:
    """Validate student token + return student_id.

    Placeholder stub: token format `cohort1-{student_id}-{hash}`.
    Real: query GHL contact + verify membership active.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing X-Cohort-Student-Token")
    if not token.startswith("cohort1-"):
        raise HTTPException(status_code=401, detail="Invalid token format")
    parts = token.split("-", 2)
    if len(parts) < 3:
        raise HTTPException(status_code=401, detail="Malformed token")
    return parts[1]


def _scheduler(request: Request):
    sched = getattr(request.app.state, "scheduler", None)
    if sched is None:
        raise HTTPException(status_code=503, detail="Scheduler chưa boot")
    return sched


@router.get("/", response_class=HTMLResponse)
async def cohort_index() -> HTMLResponse:
    """Cohort 1 dashboard index, list 7 wizards."""
    cards = []
    for slug, w in sorted(WIZARD_REGISTRY.items(), key=lambda x: x[1]["week"]):
        cards.append(f"""
        <div class="cohort-card">
          <div class="cohort-week">Tuần {w['week']}</div>
          <h3>{w['title']}</h3>
          <p>{w['subtitle']}</p>
          <a class="cohort-btn" href="/cohort/wizard/{slug}">Bắt đầu →</a>
        </div>
        """)
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <title>Cohangai Cohort 1 Dashboard</title>
  <link rel="stylesheet" href="/cohort/static/cohort-widget.css">
</head>
<body>
  <div class="cohort-container">
    <h1>🚀 Cohangai Cohort 1 Dashboard</h1>
    <p class="cohort-intro">8 tuần build AI Solo Empire cùng Hằng. Mỗi tuần 1 wizard AI hỗ trợ bạn.</p>
    <div class="cohort-grid">
      {"".join(cards)}
    </div>
  </div>
</body>
</html>""")


@router.get("/wizard/{wizard_name}", response_class=HTMLResponse)
async def cohort_wizard_page(wizard_name: str) -> HTMLResponse:
    """Serve HTML page với embedded widget per wizard."""
    if wizard_name not in WIZARD_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Wizard '{wizard_name}' not found")
    w = WIZARD_REGISTRY[wizard_name]
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <title>{w['title']} | Cohangai Cohort 1</title>
  <link rel="stylesheet" href="/cohort/static/cohort-widget.css">
</head>
<body>
  <div class="cohort-container">
    <a class="cohort-back" href="/cohort/">← Dashboard</a>
    <div class="cohort-week-label">Tuần {w['week']}</div>
    <h1>{w['title']}</h1>
    <p class="cohort-subtitle">{w['subtitle']}</p>

    <div id="cohort-widget"
         data-wizard="{wizard_name}"
         data-input-field="{w['input_field']}">
      <label for="cohort-input">{w['input_label']}</label>
      <textarea id="cohort-input"
                placeholder="{w['input_placeholder']}"
                rows="8"></textarea>

      <div class="cohort-auth">
        <label for="cohort-token">Student token (do Anna cấp):</label>
        <input type="text" id="cohort-token" placeholder="cohort1-yourstudentid-yourhash">
      </div>

      <button id="cohort-run-btn" class="cohort-btn cohort-btn-primary">
        🤖 Chạy AI Wizard
      </button>

      <div id="cohort-loading" class="cohort-loading" style="display:none">
        <p>⏳ AI đang phân tích... (30-90 giây)</p>
      </div>

      <div id="cohort-error" class="cohort-error" style="display:none"></div>

      <div id="cohort-output" class="cohort-output" style="display:none">
        <h2>📋 Kết quả</h2>
        <div id="cohort-output-markdown"></div>
        <button id="cohort-save-btn" class="cohort-btn">💾 Lưu progress</button>
      </div>
    </div>
  </div>

  <script src="/cohort/static/cohort-widget.js"></script>
</body>
</html>""")


@router.post("/run-wizard")
async def run_wizard(
    request: Request,
    x_cohort_student_token: Optional[str] = Header(None),
) -> JSONResponse:
    """Trigger wizard agent + return Markdown output."""
    student_id = _verify_student_token(x_cohort_student_token)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    wizard_name = body.get("wizard")
    if not wizard_name or wizard_name not in WIZARD_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Invalid wizard. Available: {list(WIZARD_REGISTRY.keys())}")

    w = WIZARD_REGISTRY[wizard_name]
    input_value = body.get("input", "").strip()
    if not input_value or len(input_value) < 10:
        raise HTTPException(status_code=400, detail="Input quá ngắn, cần ≥ 10 chars")

    # Build agent payload với student_id + input field
    payload = {
        "student_id": student_id,
        w["input_field"]: input_value if w["input_field"] != "student_data" else {"description": input_value},
    }

    sched = _scheduler(request)
    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        user_id=student_id,
        venture_context="cohangai",
        trigger_event=w["event"],
        payload=payload,
    )
    log.info("Cohort wizard run: student=%s wizard=%s", student_id, wizard_name)
    result = await sched.execute(w["agent"], ctx)

    if not result.success:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": result.error or result.output_text,
                "wizard": wizard_name,
            },
        )

    # Extract Markdown từ agent output_payload
    op = result.output_payload or {}
    markdown = op.get("markdown_report") or op.get("markdown_playbook") or op.get("markdown_visual_map") or _build_default_markdown(op, w)

    return JSONResponse({
        "success": True,
        "wizard": wizard_name,
        "student_id": student_id,
        "summary": result.output_text,
        "markdown": markdown,
        "payload": op,  # full JSON for debug/dev
    })


def _build_default_markdown(payload: dict, wizard: dict) -> str:
    """Fallback markdown nếu agent KHÔNG return markdown field."""
    lines = [f"# {wizard['title']}\n", f"_{wizard['subtitle']}_\n", "---\n"]
    summary = payload.get("summary", "")
    if summary:
        lines.append(f"## Tóm tắt\n\n{summary}\n")

    # Render top-level fields
    skip_keys = {"summary", "markdown_report", "markdown_playbook", "markdown_visual_map", "student_id"}
    for k, v in payload.items():
        if k in skip_keys or not v:
            continue
        if isinstance(v, list) and v:
            lines.append(f"## {k.replace('_', ' ').title()}\n")
            for item in v[:10]:
                if isinstance(item, dict):
                    lines.append(f"- {item}")
                else:
                    lines.append(f"- {item}")
            lines.append("")
        elif isinstance(v, str) and len(v) > 20:
            lines.append(f"## {k.replace('_', ' ').title()}\n\n{v}\n")
    return "\n".join(lines)


@router.post("/save-progress")
async def save_progress(
    request: Request,
    x_cohort_student_token: Optional[str] = Header(None),
) -> JSONResponse:
    """Save student progress to memory layer (per wizard completion)."""
    student_id = _verify_student_token(x_cohort_student_token)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    wizard_name = body.get("wizard")
    if not wizard_name or wizard_name not in WIZARD_REGISTRY:
        raise HTTPException(status_code=400, detail="Invalid wizard")

    sched = _scheduler(request)
    if not sched.memory or not sched.memory.ready:
        return JSONResponse({"success": False, "error": "Memory layer not ready"})

    w = WIZARD_REGISTRY[wizard_name]
    summary = body.get("summary", "")[:500]

    try:
        await sched.memory.emit(
            agent_name="cohort_widget",
            content_summary=f"Student {student_id} completed wizard {wizard_name} (week {w['week']})",
            keywords=["cohort_progress", student_id, wizard_name, f"week-{w['week']}"],
            tags=["cohort_progress", "cohort_1", student_id, wizard_name, f"week-{w['week']}"],
            venture="cohangai",
            category="task",
            context=f"Cohort wizard completion student={student_id} wizard={wizard_name}",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Save progress fail: %r", exc)
        return JSONResponse({"success": False, "error": str(exc)})

    return JSONResponse({
        "success": True,
        "student_id": student_id,
        "wizard": wizard_name,
        "week": w["week"],
        "saved_at": "now",
    })


def mount_static(app):
    """Mount static dir cho widget JS/CSS. Call from main.py."""
    if STATIC_DIR.exists():
        app.mount("/cohort/static", StaticFiles(directory=str(STATIC_DIR)), name="cohort_static")
