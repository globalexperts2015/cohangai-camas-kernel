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
# Việt hoá 2026-06-08: BreakoutOS branding, hấp dẫn user, không mention Hormozi/Grand Slam
WIZARD_REGISTRY = {
    "vision_clarity": {
        "agent": "l2_vision_clarity",
        "event": "cohort.vision_clarity",
        "week": 1,
        "title": "Tuần 1: Tầm nhìn 5 năm",
        "subtitle": "Vẽ ra cuộc đời bạn muốn TRƯỚC khi chọn nghề. Founder rõ vision = AI execute đúng đích.",
        "input_label": "Kể về bản thân: tuổi, công việc, gia đình, mục tiêu thu nhập, lifestyle bạn muốn",
        "input_placeholder": "Ví dụ: Em 38 tuổi, nhân viên văn phòng lương 18tr, 2 con nhỏ. Muốn build business online thêm 15-20tr/tháng mà vẫn giữ việc chính trong 12 tháng đầu. Gia đình ủng hộ, ưu tiên family time tối 18-21h...",
        "input_field": "student_data",
    },
    "niche_validator": {
        "agent": "l2_niche_validator_student",
        "event": "cohort.niche_validate",
        "week": 2,
        "title": "Tuần 2: Chọn đúng ngách",
        "subtitle": "Soi 3 dấu hiệu sống còn của ngách. Tránh đổ 6 tháng vào ngách chết.",
        "input_label": "Mô tả ngách bạn đang nghĩ tới (sản phẩm gì + bán cho ai + giải vấn đề gì)",
        "input_placeholder": "Ví dụ: Dạy mẹ bỉm 25-40 tuổi cách bán hàng decor handmade online từ nhà, mục tiêu thu thêm 10tr/tháng mà không cần thuê mặt bằng",
        "input_field": "niche_statement",
    },
    "transformation_mapper": {
        "agent": "l2_transformation_mapper_7d",
        "event": "cohort.transformation_map",
        "week": 3,
        "title": "Tuần 3-4: Thấu hiểu khách hàng",
        "subtitle": "Đọc vị 7 mặt cuộc sống khách hàng TRƯỚC và SAU khi mua bạn. Không hiểu khách = bán không ai mua.",
        "input_label": "Mô tả 1 khách hàng cụ thể bạn muốn phục vụ (càng chi tiết càng tốt)",
        "input_placeholder": "Ví dụ: Chị Lan 32 tuổi, kế toán văn phòng, 2 con nhỏ, lương 14tr. Mỗi tháng cuối khó co kéo, lo tương lai con học trường tư. Chồng làm xa, ủng hộ nhưng không phụ được. Muốn kiếm thêm tại nhà nhưng không biết bắt đầu từ đâu, sợ bị lừa khi học các khoá online...",
        "input_field": "customer_persona",
    },
    "vpc_fit_check": {
        "agent": "l2_vpc_fit_checker",
        "event": "cohort.vpc_fit_check",
        "week": 5,
        "title": "Tuần 5: Khớp khách với sản phẩm",
        "subtitle": "Soi xem sản phẩm bạn có THẬT SỰ giải nỗi đau khách không. Tránh build cái không ai cần.",
        "input_label": "Ý tưởng sản phẩm/khoá học của bạn (giá, format, deliverable chính)",
        "input_placeholder": "Ví dụ: Khoá 6 tuần dạy mẹ bỉm bán decor handmade online từ A-Z. Giá 3 triệu, có group hỗ trợ 6 tháng + 1-on-1 audit sản phẩm đầu tiên...",
        "input_field": "product_idea",
    },
    "mvo_cohort": {
        "agent": "l2_mvo_cohort_launcher",
        "event": "cohort.mvo_launch_plan",
        "week": 6,
        "title": "Tuần 6: Khoá đầu tiên",
        "subtitle": "Thiết kế cohort 5-15 khách trả tiền trong 30 ngày. Đi từ 0 ra dòng tiền đầu tiên.",
        "input_label": "Tóm tắt sản phẩm + khách hàng đã chốt từ các tuần trước",
        "input_placeholder": "Tóm tắt: ngách + khách hàng target + sản phẩm + giá dự kiến + thời gian launch...",
        "input_field": "vpc",
    },
    "offer_engineer": {
        "agent": "l2_offer_engineer_student",
        "event": "cohort.offer_engineer",
        "week": 7,
        "title": "Tuần 7: Đóng gói offer không thể từ chối",
        "subtitle": "Stack giá trị + cam kết + giới hạn = khách gật đầu mà không cần chốt nhiều. Bí mật của founder bán đắt.",
        "input_label": "Tóm tắt khoá đầu tiên + persona khách hàng đã design",
        "input_placeholder": "Tóm tắt khoá đầu tiên (tên + giá + format) + nỗi đau lớn nhất khách hàng + transformation bạn cam kết...",
        "input_field": "mvo",
    },
    "referral_engine": {
        "agent": "l2_referral_engine_template",
        "event": "cohort.referral_engine_design",
        "week": 8,
        "title": "Tuần 8: Cỗ máy giới thiệu (Capstone)",
        "subtitle": "Biến khách hiện tại thành đại sứ. Khách mới về tự động, không cần ads thêm.",
        "input_label": "Tóm tắt offer + khách hàng đã design xuyên 7 tuần",
        "input_placeholder": "Tóm tắt offer chính + persona khách hàng + dòng tiền mục tiêu sau referral...",
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
    """BreakoutOS dashboard, 8 tuần xây Solo Empire."""
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
  <title>BreakoutOS, 8 tuần xây Solo Empire cùng Hằng</title>
  <link rel="stylesheet" href="/cohort/static/cohort-widget.css">
</head>
<body>
  <div class="cohort-container">
    <h1>BreakoutOS</h1>
    <p class="cohort-intro">8 tuần xây Solo Empire cùng Hằng. Mỗi tuần 1 trợ lý AI đồng hành với bạn từ vision đến khách trả tiền đầu tiên.</p>
    <div class="cohort-grid">
      {"".join(cards)}
    </div>
    <p style="text-align:center;color:#999;font-size:13px;margin-top:32px">
      Mỗi trợ lý AI là 1 chuyên gia ảo Hằng đã huấn luyện. Bạn cung cấp tư duy + dữ liệu thật, AI execute 10x nhanh hơn tự làm.
    </p>
  </div>
</body>
</html>""")


@router.get("/wizard/{wizard_name}", response_class=HTMLResponse)
async def cohort_wizard_page(wizard_name: str) -> HTMLResponse:
    """Serve HTML page với embedded widget per wizard."""
    if wizard_name not in WIZARD_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Wizard '{wizard_name}' not found")
    w = WIZARD_REGISTRY[wizard_name]
    action_cfg = get_action_for_wizard(wizard_name)
    deploy_data_attr = f'data-deploy-label="{action_cfg["label"]}"' if action_cfg else ""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <title>{w['title']} | Cohangai Cohort 1</title>
  <link rel="stylesheet" href="/cohort/static/cohort-widget.css">
</head>
<body>
  <div class="cohort-container">
    <a class="cohort-back" href="/cohort/">← BreakoutOS Dashboard</a>
    <div class="cohort-week-label">BreakoutOS · Tuần {w['week']}/8</div>
    <h1>{w['title']}</h1>
    <p class="cohort-subtitle">{w['subtitle']}</p>

    <div id="cohort-widget"
         data-wizard="{wizard_name}"
         data-input-field="{w['input_field']}"
         {deploy_data_attr}>
      <label for="cohort-input">{w['input_label']}</label>
      <textarea id="cohort-input"
                placeholder="{w['input_placeholder']}"
                rows="8"></textarea>

      <div class="cohort-auth">
        <label for="cohort-token">Mã truy cập (Hằng cấp khi bạn vào BreakoutOS):</label>
        <input type="text" id="cohort-token" placeholder="cohort1-tenban-mahash">
      </div>

      <button id="cohort-run-btn" class="cohort-btn cohort-btn-primary">
        Nhờ trợ lý AI phân tích
      </button>

      <div id="cohort-loading" class="cohort-loading" style="display:none">
        <p>Trợ lý AI đang phân tích... (30-90 giây)</p>
      </div>

      <div id="cohort-error" class="cohort-error" style="display:none"></div>

      <div id="cohort-output" class="cohort-output" style="display:none">
        <h2>Kết quả phân tích</h2>
        <div id="cohort-output-markdown"></div>
        <div class="cohort-action-row">
          <button id="cohort-save-btn" class="cohort-btn">💾 Lưu progress</button>
          <button id="cohort-deploy-btn" class="cohort-btn cohort-btn-deploy" style="display:none">
            {action_cfg["label"] if action_cfg else ""}
          </button>
        </div>

        <div id="cohort-deploy-result" class="cohort-deploy-result" style="display:none">
          <h3>✨ Deploy thành công</h3>
          <p>Landing page của bạn:</p>
          <div class="cohort-deploy-url-box">
            <input type="text" id="cohort-deploy-url" readonly>
            <button id="cohort-deploy-copy" class="cohort-btn">📋 Copy</button>
          </div>
          <p><a id="cohort-deploy-open" href="#" target="_blank" class="cohort-btn cohort-btn-primary">🌐 Mở landing</a></p>
        </div>

        <div id="cohort-deploy-loading" style="display:none" class="cohort-loading">
          <p>⏳ Đang deploy landing page... (5-10 giây)</p>
        </div>
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


def _humanize_key(k: str) -> str:
    """Convert snake_case key to Title Case Vietnamese-friendly heading."""
    # Special label mapping for common keys
    label_map = {
        "5_year_roadmap": "Roadmap 5 năm",
        "next_3_action_steps": "3 Bước hành động tiếp theo",
        "non_negotiables": "Non-Negotiables",
        "energy_drivers": "Energy Drivers (nạp năng lượng)",
        "energy_drains": "Energy Drains (hút năng lượng)",
        "life_goal_categories": "5 Life Goal Categories",
        "business_motivation": "Business Motivation (true why)",
        "vision_statement": "Vision Statement",
        "anna_persona_match": "Anna persona match",
        "transformation_arc_summary": "Transformation Arc",
        "primary_dream_outcome": "Primary Dream Outcome",
        "value_equation_score": "Value Equation Score",
        "grand_slam_offer": "Grand Slam Offer",
        "bonus_stack": "Bonus Stack",
        "30_day_plan": "Kế hoạch 30 ngày",
        "waitlist_script": "Waitlist Script",
    }
    if k in label_map:
        return label_map[k]
    return k.replace("_", " ").title()


def _render_dict_as_bullets(d: dict, indent: int = 0) -> list[str]:
    """Render dict nested as Markdown bullets (no raw dict str)."""
    lines = []
    prefix = "  " * indent
    for sk, sv in d.items():
        label = _humanize_key(sk)
        if isinstance(sv, (str, int, float)) and str(sv).strip():
            lines.append(f"{prefix}- **{label}**: {sv}")
        elif isinstance(sv, list) and sv:
            lines.append(f"{prefix}- **{label}**:")
            for sub in sv[:8]:
                if isinstance(sub, dict):
                    lines.extend(_render_dict_as_bullets(sub, indent + 1))
                else:
                    lines.append(f"{prefix}  - {sub}")
        elif isinstance(sv, dict) and sv:
            lines.append(f"{prefix}- **{label}**:")
            lines.extend(_render_dict_as_bullets(sv, indent + 1))
    return lines


def _build_default_markdown(payload: dict, wizard: dict) -> str:
    """Fallback markdown nếu agent KHÔNG return markdown field.

    Render dict/list of dicts as nested bullets thay vì str() raw dict
    (Sprint 14 P0.2 fix bug raw dict rendering).
    """
    lines = [f"# {wizard['title']}", "", f"_{wizard['subtitle']}_", "", "---", ""]
    summary = payload.get("summary", "")
    if summary:
        lines.append(f"## Tóm tắt\n\n{summary}\n")

    skip_keys = {"summary", "markdown_report", "markdown_playbook", "markdown_visual_map", "student_id", "venture"}

    # Priority order cho key fields (render first nếu có)
    priority_keys = [
        "vision_statement",
        "primary_dream_outcome",
        "transformation_arc_summary",
        "grand_slam_offer",
    ]
    rendered_keys = set()

    for pk in priority_keys:
        if pk in payload and payload[pk]:
            v = payload[pk]
            if isinstance(v, str) and v.strip():
                lines.append(f"## {_humanize_key(pk)}\n\n{v}\n")
                rendered_keys.add(pk)

    # Render remaining fields
    for k, v in payload.items():
        if k in skip_keys or k in rendered_keys or not v:
            continue
        heading = _humanize_key(k)
        if isinstance(v, list) and v:
            lines.append(f"## {heading}")
            lines.append("")
            for idx, item in enumerate(v[:10], 1):
                if isinstance(item, dict):
                    # Lookup label inside dict (eg category name)
                    title_candidate = item.get("category") or item.get("name") or item.get("title") or f"Item {idx}"
                    lines.append(f"### {idx}. {title_candidate}")
                    lines.append("")
                    bullet_lines = _render_dict_as_bullets(
                        {sk: sv for sk, sv in item.items() if sk not in {"category", "name", "title"}},
                        indent=0,
                    )
                    lines.extend(bullet_lines)
                    lines.append("")
                else:
                    lines.append(f"- {item}")
            lines.append("")
        elif isinstance(v, dict) and v:
            lines.append(f"## {heading}")
            lines.append("")
            lines.extend(_render_dict_as_bullets(v, indent=0))
            lines.append("")
        elif isinstance(v, str) and v.strip():
            lines.append(f"## {heading}\n\n{v}\n")
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


# Sprint 14 P0.6 Admin Dashboard Observability

ADMIN_KEY_ENV = "COHORT_ADMIN_KEY"


def _verify_admin_key(key: Optional[str]) -> None:
    """Bearer-style auth qua query param ?key=XXX."""
    expected = os.getenv(ADMIN_KEY_ENV, "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=f"Admin disabled, set {ADMIN_KEY_ENV} env var",
        )
    if not key or key != expected:
        raise HTTPException(status_code=401, detail="Invalid admin key")


@router.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, key: Optional[str] = None) -> HTMLResponse:
    """Anna admin view: list students + wizard activity + lead score."""
    _verify_admin_key(key)
    sched = _scheduler(request)
    if getattr(sched, "memory", None) is None:
        raise HTTPException(status_code=503, detail="Memory layer not ready")

    # Pull all chain entries last 30 days
    records = await sched.memory.retrieve_by_tags_recent(
        tags_must_contain=[CHAIN_TAG],
        limit=500,
        venture="cohangai",
    )

    students: dict = {}
    for r in records:
        student_id = None
        wizard = None
        for t in (r.tags or []):
            if t in WIZARD_REGISTRY:
                wizard = t
            elif t not in (CHAIN_TAG, "cohort_1") and not student_id:
                student_id = t
        if not student_id or not wizard:
            continue
        if student_id not in students:
            students[student_id] = {"student_id": student_id, "wizards": {}, "last_activity": r.created_at}
        students[student_id]["wizards"][wizard] = {
            "created_at": r.created_at,
            "content_len": len(r.content or ""),
        }
        if r.created_at and (students[student_id]["last_activity"] is None or r.created_at > students[student_id]["last_activity"]):
            students[student_id]["last_activity"] = r.created_at

    # Sort by # wizards desc then last_activity desc
    sorted_students = sorted(
        students.values(),
        key=lambda s: (len(s["wizards"]), s["last_activity"] or 0),
        reverse=True,
    )

    rows_html = []
    for s in sorted_students[:100]:
        wizard_badges = "".join(
            f'<span class="badge badge-{w}" title="{_esc_html(w)}">{w[:3].upper()}</span>'
            for w in s["wizards"].keys()
        )
        last_str = s["last_activity"].strftime("%d/%m %H:%M") if s["last_activity"] else "?"
        score = len(s["wizards"]) * 10 + (50 if len(s["wizards"]) >= 6 else 0)
        hot_class = "hot" if score >= 50 else ("warm" if score >= 30 else "cold")
        rows_html.append(f"""
        <tr class="row-{hot_class}">
          <td><a href="/cohort/admin/student/{_esc_html(s['student_id'])}?key={_esc_html(key)}">{_esc_html(s['student_id'])}</a></td>
          <td>{wizard_badges}</td>
          <td><strong>{len(s['wizards'])}/7</strong></td>
          <td><span class="score score-{hot_class}">{score}</span></td>
          <td>{last_str}</td>
        </tr>""")

    rows_str = "".join(rows_html) or '<tr><td colspan="5" style="text-align:center;padding:40px;color:#999">Chưa có wizard run nào</td></tr>'
    total_students = len(students)
    hot_count = sum(1 for s in students.values() if len(s["wizards"]) >= 5)

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BreakoutOS Admin</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f7fa;color:#222;padding:24px}}
.container{{max-width:1200px;margin:0 auto}}
h1{{font-size:28px;margin-bottom:8px}}
.subtitle{{color:#666;margin-bottom:24px}}
.stats{{display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap}}
.stat{{background:white;border-radius:12px;padding:16px 20px;flex:1;min-width:180px;box-shadow:0 1px 3px rgba(0,0,0,0.05)}}
.stat-num{{font-size:32px;font-weight:700;color:#0066ff}}
.stat-label{{color:#666;font-size:13px;margin-top:4px}}
table{{width:100%;background:white;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.05)}}
th,td{{padding:12px 16px;text-align:left;border-bottom:1px solid #eee}}
th{{background:#f9fafb;font-size:13px;color:#666;text-transform:uppercase;letter-spacing:0.5px}}
tr:hover{{background:#f9fafb}}
.row-hot{{background:linear-gradient(to right,#fff5f5,white)}}
.row-warm{{background:linear-gradient(to right,#fffbf0,white)}}
.badge{{display:inline-block;background:#e0e7ff;color:#3730a3;font-size:10px;font-weight:600;padding:3px 7px;border-radius:6px;margin-right:4px}}
.score{{display:inline-block;font-weight:700;padding:4px 10px;border-radius:12px}}
.score-hot{{background:#fee;color:#c92a2a}}
.score-warm{{background:#fff4e6;color:#d9480f}}
.score-cold{{background:#e7f5ff;color:#1864ab}}
a{{color:#0066ff;text-decoration:none;font-weight:600}}
a:hover{{text-decoration:underline}}
@media(max-width:600px){{body{{padding:12px}}th,td{{padding:8px}}}}
</style></head>
<body>
<div class="container">
  <h1>BreakoutOS Admin</h1>
  <p class="subtitle">Theo dõi học viên hoàn thành 8 tuần. Cập nhật 30 ngày gần nhất.</p>

  <div class="stats">
    <div class="stat"><div class="stat-num">{total_students}</div><div class="stat-label">Total students có activity</div></div>
    <div class="stat"><div class="stat-num">{hot_count}</div><div class="stat-label">Hot leads (≥5 wizards)</div></div>
    <div class="stat"><div class="stat-num">{len(records)}</div><div class="stat-label">Total wizard runs</div></div>
    <div class="stat"><div class="stat-num">{len(WIZARD_REGISTRY)}</div><div class="stat-label">Wizards available</div></div>
  </div>

  <table>
    <thead><tr>
      <th>Student ID</th>
      <th>Wizards completed</th>
      <th>Progress</th>
      <th>Lead score</th>
      <th>Last activity</th>
    </tr></thead>
    <tbody>{rows_str}</tbody>
  </table>

  <p style="margin-top:24px;color:#999;font-size:13px;text-align:center">
    Lead score = wizards × 10 + 50 bonus nếu ≥6/7 wizards.
    Hot ≥50 | Warm 30-49 | Cold &lt;30
  </p>
</div>
</body></html>""")


def _esc_html(s) -> str:
    import html as _html
    return _html.escape(str(s or ""), quote=True)


@router.get("/admin/student/{student_id}", response_class=HTMLResponse)
async def admin_student_detail(
    student_id: str, request: Request, key: Optional[str] = None
) -> HTMLResponse:
    """Per-student detail: list all wizard outputs với preview + link full markdown."""
    _verify_admin_key(key)
    sched = _scheduler(request)
    if getattr(sched, "memory", None) is None:
        raise HTTPException(status_code=503, detail="Memory layer not ready")

    records = await sched.memory.retrieve_by_tags_recent(
        tags_must_contain=[CHAIN_TAG, student_id],
        limit=50,
        venture="cohangai",
    )

    if not records:
        return HTMLResponse(f"""<!DOCTYPE html><html><body style="font-family:sans-serif;padding:40px;text-align:center">
        <h2>Student '{_esc_html(student_id)}' chưa có wizard activity</h2>
        <a href="/cohort/admin/dashboard?key={_esc_html(key)}">← Dashboard</a>
        </body></html>""")

    items_html = []
    for r in records:
        wizard = "?"
        for t in (r.tags or []):
            if t in WIZARD_REGISTRY:
                wizard = t
                break
        wizard_meta = WIZARD_REGISTRY.get(wizard, {})
        title = wizard_meta.get("title", wizard)
        created = r.created_at.strftime("%d/%m %H:%M") if r.created_at else "?"
        try:
            parsed = json.loads(r.content)
            preview_keys = list(parsed.keys())[:8] if isinstance(parsed, dict) else []
            preview = ", ".join(preview_keys)
        except (TypeError, ValueError, json.JSONDecodeError):
            preview = (r.content or "")[:150]

        items_html.append(f"""
        <div class="card">
          <div class="card-header">
            <h3>{_esc_html(title)}</h3>
            <span class="time">{created}</span>
          </div>
          <div class="card-body">
            <div class="meta">Wizard: <code>{_esc_html(wizard)}</code> · Content len: {len(r.content or '')} chars</div>
            <div class="preview">{_esc_html(preview)}</div>
          </div>
        </div>""")

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc_html(student_id)} | Cohort 1 Admin</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f7fa;color:#222;padding:24px}}
.container{{max-width:900px;margin:0 auto}}
.back{{color:#0066ff;text-decoration:none;font-weight:600;margin-bottom:16px;display:inline-block}}
h1{{font-size:28px;margin-bottom:24px}}
.summary{{background:white;border-radius:12px;padding:20px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,0.05)}}
.card{{background:white;border-radius:12px;margin-bottom:16px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.05)}}
.card-header{{background:#f9fafb;padding:16px 20px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;align-items:center}}
.card-header h3{{font-size:18px}}
.time{{color:#999;font-size:13px}}
.card-body{{padding:16px 20px}}
.meta{{font-size:13px;color:#666;margin-bottom:8px}}
.preview{{color:#444;font-size:14px;background:#f9fafb;padding:12px;border-radius:8px;border-left:3px solid #0066ff}}
code{{background:#eef;padding:2px 6px;border-radius:4px;font-size:12px}}
</style></head>
<body>
<div class="container">
  <a class="back" href="/cohort/admin/dashboard?key={_esc_html(key)}">← Dashboard</a>
  <h1>📋 {_esc_html(student_id)}</h1>
  <div class="summary">
    <strong>{len(records)} wizard outputs</strong> · Latest activity:
    {records[0].created_at.strftime("%d/%m/%Y %H:%M") if records[0].created_at else "?"}
  </div>
  {"".join(items_html)}
</div>
</body></html>""")


def mount_static(app):
    """Mount static dir cho widget JS/CSS. Call from main.py."""
    if STATIC_DIR.exists():
        app.mount("/cohort/static", StaticFiles(directory=str(STATIC_DIR)), name="cohort_static")
