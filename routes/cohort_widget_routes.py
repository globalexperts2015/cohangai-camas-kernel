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

import json

from kernel.base_agent import ExecutionContext
from kernel.memory_layer import MemoryRecord
from kernel.output_actions import (
    generate_landing_id,
    generate_offer_landing_html,
    get_action_for_wizard,
)
from kernel.voice_gate import apply_voice_rewrite, voice_rewrite_enabled

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


# Sprint 14 P0.4 Memory Chain
# Mapping current wizard → which payload keys to inject từ previous wizards
# Format: {wizard_friendly_name: {payload_key_in_current: source_wizard_friendly_name}}
WIZARD_CHAIN_DEPS = {
    "vision_clarity": {},  # First wizard, no chain
    "niche_validator": {
        "vision_context": "vision_clarity",
    },
    "transformation_mapper": {
        "vision_context": "vision_clarity",
        "niche_context": "niche_validator",
    },
    "vpc_fit_check": {
        "transformation_context": "transformation_mapper",
        "persona": "transformation_mapper",
    },
    "mvo_cohort": {
        "vision": "vision_clarity",
        "niche": "niche_validator",
        "transformation": "transformation_mapper",
        "vpc": "vpc_fit_check",
    },
    "offer_engineer": {
        "transformation": "transformation_mapper",
        "mvo": "mvo_cohort",
        "persona": "vpc_fit_check",
    },
    "referral_engine": {
        "offer": "offer_engineer",
        "persona": "vpc_fit_check",
    },
}

CHAIN_TAG = "cohort_chain"


def _chain_enabled() -> bool:
    """Env flag MEMORY_CHAIN_ENABLED, default true."""
    return os.getenv("MEMORY_CHAIN_ENABLED", "true").lower() in ("1", "true", "yes")


async def _retrieve_chain_context(memory, student_id: str, wizard_name: str) -> dict:
    """Retrieve previous wizard outputs cho chain context injection.

    Lookup recent memory entries tagged [CHAIN_TAG, student_id, prev_wizard_name].
    Returns dict mapping payload_key → parsed_output_dict.
    """
    if not memory or not getattr(memory, "ready", False):
        return {}

    deps = WIZARD_CHAIN_DEPS.get(wizard_name, {})
    if not deps:
        return {}

    chain_ctx: dict = {}
    for payload_key, source_wizard in deps.items():
        if payload_key in chain_ctx:
            continue  # Already populated by another dep (eg persona)
        try:
            records = await memory.retrieve_by_tags_recent(
                tags_must_contain=[CHAIN_TAG, student_id, source_wizard],
                limit=1,
                venture="cohangai",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Chain retrieve fail student=%s source=%s: %r",
                student_id,
                source_wizard,
                exc,
            )
            continue
        if not records:
            log.info(
                "Chain dep missing: student=%s wizard=%s needs %s output (skip)",
                student_id,
                wizard_name,
                source_wizard,
            )
            continue
        try:
            parsed = json.loads(records[0].content)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = {"raw": records[0].content}
        chain_ctx[payload_key] = parsed

    return chain_ctx


async def _store_chain_output(
    memory,
    student_id: str,
    wizard_name: str,
    agent_name: str,
    full_output: dict,
) -> None:
    """Store full wizard output cho chain retrieval downstream wizards.

    Tagged [CHAIN_TAG, student_id, wizard_name]. Content = full JSON dict.
    """
    if not memory or not getattr(memory, "ready", False):
        return

    try:
        content = json.dumps(full_output, ensure_ascii=False)
    except (TypeError, ValueError):
        content = str(full_output)

    summary = full_output.get("summary") or full_output.get("verdict") or ""
    keywords = ["cohort_chain", student_id, wizard_name]
    tags = [CHAIN_TAG, student_id, wizard_name, "cohort_1"]

    record = MemoryRecord(
        agent_name=f"cohort_chain_{wizard_name}",
        content=content,
        keywords=keywords,
        tags=tags,
        category="task",
        context=f"Cohort chain output student={student_id} wizard={wizard_name}",
        venture="cohangai",
        evolution_history=[],
    )

    try:
        await memory.store(record)
    except Exception as exc:  # noqa: BLE001
        log.warning("Chain store fail student=%s wizard=%s: %r", student_id, wizard_name, exc)


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

    # Sprint 14 P0.4 Memory Chain, inject previous wizard outputs
    chain_loaded: list[str] = []
    if _chain_enabled() and getattr(sched, "memory", None) is not None:
        chain_ctx = await _retrieve_chain_context(sched.memory, student_id, wizard_name)
        for key, value in chain_ctx.items():
            payload[key] = value
            chain_loaded.append(key)

    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        user_id=student_id,
        venture_context="cohangai",
        trigger_event=w["event"],
        payload=payload,
    )
    log.info(
        "Cohort wizard run: student=%s wizard=%s chain_loaded=%s",
        student_id,
        wizard_name,
        chain_loaded,
    )
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

    # Sprint 14 P0.3 voice gate, rewrite Markdown sang Anna voice qua Haiku 4.5
    voice_rewritten = False
    if voice_rewrite_enabled() and getattr(sched, "llm", None) is not None:
        try:
            rewritten = await apply_voice_rewrite(sched.llm, markdown, venture_context="cohangai")
            if rewritten != markdown:
                markdown = rewritten
                voice_rewritten = True
        except Exception as exc:  # noqa: BLE001
            log.warning("Voice rewrite fail in run_wizard: %r, fall back original", exc)

    # Sprint 14 P0.4 Memory Chain, persist full output for downstream wizards
    chain_stored = False
    if _chain_enabled() and getattr(sched, "memory", None) is not None:
        try:
            await _store_chain_output(sched.memory, student_id, wizard_name, agent_name=w["agent"], full_output=op)
            chain_stored = True
        except Exception as exc:  # noqa: BLE001
            log.warning("Chain store fail in run_wizard: %r", exc)

    return JSONResponse({
        "success": True,
        "wizard": wizard_name,
        "student_id": student_id,
        "summary": result.output_text,
        "markdown": markdown,
        "voice_rewritten": voice_rewritten,
        "chain_loaded": chain_loaded,
        "chain_stored": chain_stored,
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


# Sprint 15-16 P0.5 PILOT Output → Action endpoints

LANDING_TAG = "cohort_landing"


@router.post("/wizard/{wizard_name}/deploy-action")
async def deploy_action(
    wizard_name: str,
    request: Request,
    x_cohort_student_token: Optional[str] = Header(None),
) -> JSONResponse:
    """Deploy wizard output sang artifact thật (PILOT: offer_engineer → HTML landing).

    Body: {"wizard_output": {...full wizard output_payload}}
    Returns: {"success": true, "url": "...", "landing_id": "...", "action_type": "..."}
    """
    student_id = _verify_student_token(x_cohort_student_token)

    action_cfg = get_action_for_wizard(wizard_name)
    if action_cfg is None:
        raise HTTPException(
            status_code=400,
            detail=f"Wizard '{wizard_name}' chưa support deploy-action. Pilot scope: offer_engineer.",
        )

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    wizard_output = body.get("wizard_output") or {}
    if not wizard_output:
        # Fallback: retrieve latest wizard output từ memory chain
        sched = _scheduler(request)
        if getattr(sched, "memory", None) is not None:
            records = await sched.memory.retrieve_by_tags_recent(
                tags_must_contain=[CHAIN_TAG, student_id, wizard_name],
                limit=1,
                venture="cohangai",
            )
            if records:
                try:
                    wizard_output = json.loads(records[0].content)
                except (TypeError, ValueError):
                    pass

    if not wizard_output:
        raise HTTPException(
            status_code=400,
            detail=f"Cần wizard_output trong body HOẶC chạy {wizard_name} trước để memory chain có data.",
        )

    landing_id = generate_landing_id(student_id, wizard_name)

    if action_cfg["action_type"] == "html_landing":
        html_content = generate_offer_landing_html(
            offer_payload=wizard_output,
            student_id=student_id,
            landing_id=landing_id,
        )

        sched = _scheduler(request)
        if getattr(sched, "memory", None) is not None:
            try:
                record = MemoryRecord(
                    agent_name=f"cohort_landing_{wizard_name}",
                    content=html_content,
                    keywords=[LANDING_TAG, landing_id, student_id, wizard_name],
                    tags=[LANDING_TAG, landing_id, student_id, wizard_name, "cohort_1"],
                    category="task",
                    context=f"Landing page deployed student={student_id} wizard={wizard_name} id={landing_id}",
                    venture="cohangai",
                    evolution_history=[],
                )
                await sched.memory.store(record)
            except Exception as exc:  # noqa: BLE001
                log.warning("Landing store fail: %r", exc)
                raise HTTPException(status_code=500, detail=f"Storage fail: {exc}")
        else:
            raise HTTPException(status_code=503, detail="Memory layer not ready, không persist được")

        base_url = os.getenv("CAMAS_PUBLIC_URL", "https://camas-kernel-production.up.railway.app")
        landing_url = f"{base_url}/cohort/landing/{landing_id}"

        log.info("Landing deployed student=%s wizard=%s id=%s", student_id, wizard_name, landing_id)

        return JSONResponse({
            "success": True,
            "action_type": "html_landing",
            "landing_id": landing_id,
            "url": landing_url,
            "wizard": wizard_name,
        })

    raise HTTPException(status_code=500, detail=f"Action type '{action_cfg['action_type']}' not implemented")


@router.get("/landing/{landing_id}", response_class=HTMLResponse)
async def serve_landing(landing_id: str, request: Request) -> HTMLResponse:
    """Serve generated HTML landing page by ID."""
    sched = _scheduler(request)
    if getattr(sched, "memory", None) is None:
        raise HTTPException(status_code=503, detail="Memory layer not ready")

    records = await sched.memory.retrieve_by_tags_recent(
        tags_must_contain=[LANDING_TAG, landing_id],
        limit=1,
        venture="cohangai",
    )

    if not records:
        raise HTTPException(status_code=404, detail=f"Landing '{landing_id}' not found")

    return HTMLResponse(records[0].content)


def mount_static(app):
    """Mount static dir cho widget JS/CSS. Call from main.py."""
    if STATIC_DIR.exists():
        app.mount("/cohort/static", StaticFiles(directory=str(STATIC_DIR)), name="cohort_static")
