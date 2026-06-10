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
import re
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import json

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]

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
        "title": "Trợ Lý AI Tầm Nhìn",
        "subtitle": "Trước khi bắt đầu kinh doanh, hiểu chính mình để kinh doanh trở thành phong cách sống, không phải gánh nặng.",
        "input_label": "Kể về bản thân: tuổi, công việc, gia đình, mục tiêu thu nhập, lifestyle bạn muốn",
        "input_placeholder": "Ví dụ: Em 38 tuổi, nhân viên văn phòng lương 18tr, 2 con nhỏ. Muốn build business online thêm 15-20tr/tháng mà vẫn giữ việc chính trong 12 tháng đầu. Gia đình ủng hộ, ưu tiên family time tối 18-21h...",
        "input_field": "student_data",
    },
    "niche_validator": {
        "agent": "l2_niche_validator_student",
        "event": "cohort.niche_validate",
        "week": 2,
        "title": "Trợ Lý AI Ngách",
        "subtitle": "Chọn thị trường bạn yêu thương đủ sâu để không bao giờ bỏ cuộc khi gặp khó.",
        "input_label": "Mô tả thị trường/ngách bạn đang nghĩ tới (bạn muốn phục vụ AI, giải vấn đề gì)",
        "input_placeholder": "Ví dụ: Dạy mẹ bỉm 25-40 tuổi cách bán hàng decor handmade online từ nhà, mục tiêu thu thêm 10tr/tháng mà không cần thuê mặt bằng",
        "input_field": "niche_statement",
    },
    "transformation_mapper": {
        "agent": "l2_transformation_mapper_7d",
        "event": "cohort.transformation_map",
        "week": 3,
        "title": "Trợ Lý AI Thấu Khách",
        "subtitle": "Hiểu khách sâu để bán đúng cái khách cần. Phân tích 3 việc khách mua sản phẩm để đạt, Top 3 nỗi đau với Pain Scale 1-10, phiên bản mới của khách, và 3 sản phẩm bạn nên bán.",
        "input_label": "Mô tả 1 khách hàng cụ thể bạn muốn phục vụ (càng chi tiết càng tốt)",
        "input_placeholder": "Ví dụ: Chị Lan 32 tuổi, kế toán văn phòng, 2 con nhỏ, lương 14tr. Mỗi tháng cuối khó co kéo, lo tương lai con học trường tư. Chồng làm xa, ủng hộ nhưng không phụ được. Muốn kiếm thêm tại nhà nhưng không biết bắt đầu từ đâu, sợ bị lừa khi học các khoá online...",
        "input_field": "customer_persona",
    },
    "vpc_fit_check": {
        "agent": "l2_vpc_fit_checker",
        "event": "cohort.vpc_fit_check",
        "week": 5,
        "title": "Trợ Lý AI Giá Trị",
        "subtitle": "Khớp giải pháp với nỗi đau thật của khách. Tránh build cái không ai cần.",
        "input_label": "Ý tưởng sản phẩm/khoá học của bạn (giá, format, deliverable chính)",
        "input_placeholder": "Ví dụ: Khoá 6 tuần dạy mẹ bỉm bán decor handmade online từ A-Z. Giá 3 triệu, có group hỗ trợ 6 tháng + 1-on-1 audit sản phẩm đầu tiên...",
        "input_field": "product_idea",
    },
    "offer_engineer": {
        "agent": "l2_offer_engineer_student",
        "event": "cohort.offer_engineer",
        "week": 6,
        "title": "Trợ Lý AI Đóng Gói",
        "subtitle": "Stack giá trị, cam kết, giới hạn để khách gật đầu. AI tự tạo trang bán hàng đẹp sau khi bạn design xong.",
        "input_label": "Tóm tắt giải pháp + persona khách hàng đã design",
        "input_placeholder": "Tóm tắt khoá/sản phẩm (tên + giá + format) + nỗi đau lớn nhất khách + transformation bạn cam kết...",
        "input_field": "mvo",
    },
    "mvo_cohort": {
        "agent": "l2_mvo_cohort_launcher",
        "event": "cohort.mvo_launch_plan",
        "week": 7,
        "title": "Trợ Lý AI Ra Mắt",
        "subtitle": "Kế hoạch 30 ngày ra mắt 5-15 khách trả tiền. Clone chuỗi email nuôi khách + automation Hằng đã build, customize cho bạn.",
        "input_label": "Tóm tắt offer + giải pháp đã thiết kế",
        "input_placeholder": "Tóm tắt: offer chính + giải pháp + persona khách + thời gian launch dự kiến...",
        "input_field": "vpc",
    },
    "referral_engine": {
        "agent": "l2_referral_engine_template",
        "event": "cohort.referral_engine_design",
        "week": 8,
        "title": "Trợ Lý AI Giới Thiệu (Capstone)",
        "subtitle": "Biến khách thành đại sứ. Clone full hệ thống: CRM nuôi khách + thông báo + thanh toán + đánh giá khách tự động.",
        "input_label": "Tóm tắt offer + khách hàng đã design xuyên 7 tuần",
        "input_placeholder": "Tóm tắt offer chính + persona khách hàng + dòng tiền mục tiêu sau referral...",
        "input_field": "offer",
    },
    # ───── BreakoutOS v3 (added 2026-06-09) ─────
    # GrowthOS layer (Week 5-7)
    "content_engine": {
        "agent": "c1_content_engine",
        "event": "cohort.content_engine",
        "week": 5,
        "title": "Trợ Lý AI Content Engine",
        "subtitle": "Sinh 100 Reel + 30 FB + 30 email + 30 blog + 12 webinar + 4 lead magnet + 30-day calendar. Pull TỪ hồ sơ khách + offer + voice. KHÔNG generic.",
        "input_label": "Voice register (hang_webinar / custom) + ≥5 story THẬT của bạn",
        "input_placeholder": "Voice: custom. Story pool: 1) Tôi mất 6 tháng học cách bán... 2) Bài học đầu tiên là... 3) Khách đầu tiên gọi điện 2 tuần sau... 4)... 5)...",
        "input_field": "content_input",
    },
    "lead_gen_engine": {
        "agent": "c2_lead_gen_engine",
        "event": "cohort.lead_gen",
        "week": 6,
        "title": "Trợ Lý AI Lead Gen Engine",
        "subtitle": "Kế hoạch kéo lead 30 ngày + 5 chiến lược kênh + 4 lead magnet adapt từ Content Engine + tagging logic + funnel map.",
        "input_label": "Lợi thế bạn đã có (audience nào, budget tháng VND)",
        "input_placeholder": "Ví dụ: FB cá nhân 5K friend, có YouTube chưa active, chưa có TikTok, budget 2tr/tháng cho ads...",
        "input_field": "lead_gen_input",
    },
    # FanOS layer (Week 9)
    "fan_hub_setup": {
        "agent": "tool:fan_hub_spawn",
        "event": "cohort.fan_hub_setup",
        "week": 9,
        "title": "Fan Hub Setup",
        "subtitle": "Spawn Fan Hub instance riêng với CRM + tier system + Reputation Ledger + Trust Score. Tài sản dài hạn dùng được cho mọi venture sau.",
        "input_label": "Email primary + display name + custom domain (optional)",
        "input_placeholder": "Email: ban@example.com, Display: Lê Thị Lan, Custom domain: fan.cohanglan.com (hoặc bỏ trống để dùng {slug}.fan.breakout.live)",
        "input_field": "fan_hub_input",
    },
    # ScaleOS layer (Week 10)
    "ai_coo": {
        "agent": "e1_ai_coo",
        "event": "coo.daily",
        "week": 10,
        "title": "AI COO Dashboard",
        "subtitle": "Báo cáo 6am Telegram mỗi sáng + tuần (Sunday 8pm) + tháng. 3 việc cần làm hôm nay + cảnh báo red flag. KHÔNG chỉ báo cáo, ĐỀ XUẤT hành động.",
        "input_label": "Telegram chat_id để nhận daily report",
        "input_placeholder": "Telegram chat_id: -100... (group) hoặc 123... (private chat). Hằng dùng group Breakout Ops -1003813280155.",
        "input_field": "telegram_chat_id",
    },
    "scale_coach": {
        "agent": "e2_scale_coach",
        "event": "cohort.scale_coach",
        "week": 10,
        "title": "Trợ Lý AI Scale Coach",
        "subtitle": "Kế hoạch scale 90 ngày từ 5-15 lên 50-100 khách. Webinar + Membership + Referral + Affiliate + Upsell. AI team + hire decision tree.",
        "input_label": "State hiện tại: số khách trả tiền + doanh thu tháng VND + list size",
        "input_placeholder": "Số khách: 12. Doanh thu tháng: 18tr. List size: 850. Available hours/week: 25. Capital runway: 6 tháng...",
        "input_field": "scale_input",
    },
    "capstone_clone": {
        "agent": "tool:capstone_spawn",
        "event": "cohort.capstone_clone",
        "week": 10,
        "title": "Capstone, AIOS instance riêng",
        "subtitle": "1-click spawn 1 BreakoutOS instance độc lập cho doanh nghiệp của bạn. 7 trợ lý AI + Fan Hub + AI COO + lifetime kernel update.",
        "input_label": "Confirm spawn (yêu cầu đã hoàn thành 10 tuần + có ≥3 khách trả tiền)",
        "input_placeholder": "Confirm: Tôi đã có {N} khách trả tiền và sẵn sàng vận hành BreakoutOS instance riêng.",
        "input_field": "capstone_confirm",
        "requires": ["scale_coach_completed", "min_customers_3"],
    },
}

# Tuần 4 = build customer profile, link transformation_mapper for refined persona
WEEK_4_PLACEHOLDER = {
    "week": 4,
    "title": "Xây dựng hồ sơ khách hàng",
    "subtitle": "Tổng hợp dữ liệu 3 tuần đầu thành hồ sơ khách hàng đầy đủ: persona + nỗi đau + niềm vui + ngôn ngữ + kênh tiếp cận. Đây là nền cho mọi quyết định kinh doanh sau.",
    "wizard_slug": "transformation_mapper",
}


# Sprint 14 P0.4 Memory Chain
# Mapping current wizard → which payload keys to inject từ previous wizards
# Format: {wizard_friendly_name: {payload_key_in_current: source_wizard_friendly_name}}
WIZARD_CHAIN_DEPS = {
    "vision_clarity": {},  # Tuần 1, first wizard, no chain
    "niche_validator": {  # Tuần 2
        "vision_context": "vision_clarity",
    },
    "transformation_mapper": {  # Tuần 3-4
        "vision_context": "vision_clarity",
        "niche_context": "niche_validator",
    },
    "vpc_fit_check": {  # Tuần 5
        "transformation_context": "transformation_mapper",
        "persona": "transformation_mapper",
    },
    "offer_engineer": {  # Tuần 6 (was 7, swapped)
        "transformation": "transformation_mapper",
        "vpc": "vpc_fit_check",
        "persona": "vpc_fit_check",
    },
    "mvo_cohort": {  # Tuần 7 (was 6, swapped) - launch AFTER offer designed
        "vision": "vision_clarity",
        "niche": "niche_validator",
        "transformation": "transformation_mapper",
        "vpc": "vpc_fit_check",
        "offer": "offer_engineer",
    },
    "referral_engine": {  # Tuần 8
        "offer": "offer_engineer",
        "mvo": "mvo_cohort",
        "persona": "vpc_fit_check",
    },
    # ───── BreakoutOS v3 chain deps (added 2026-06-09) ─────
    "content_engine": {  # Tuần 5 (parallel với vpc_fit_check)
        "customer_profile": "transformation_mapper",
        "offer": "offer_engineer",  # nếu chưa có, agent tự handle
    },
    "lead_gen_engine": {  # Tuần 6
        "customer_profile": "transformation_mapper",
        "content_engine_output": "content_engine",
    },
    "fan_hub_setup": {  # Tuần 9
        "customer_profile": "transformation_mapper",
        "offer": "offer_engineer",
    },
    "ai_coo": {  # Tuần 10 (background daily, nhưng setup once)
        "lead_gen": "lead_gen_engine",
        "fan_hub": "fan_hub_setup",
    },
    "scale_coach": {  # Tuần 10
        "offer": "offer_engineer",
        "mvo": "mvo_cohort",
        "referral": "referral_engine",
        "content_engine_output": "content_engine",
        "lead_gen_plan": "lead_gen_engine",
    },
    "capstone_clone": {  # Tuần 10 finale
        "vision": "vision_clarity",
        "niche": "niche_validator",
        "transformation": "transformation_mapper",
        "vpc": "vpc_fit_check",
        "offer": "offer_engineer",
        "mvo": "mvo_cohort",
        "referral": "referral_engine",
        "content_engine_output": "content_engine",
        "lead_gen_plan": "lead_gen_engine",
        "scale_plan": "scale_coach",
        "fan_hub": "fan_hub_setup",
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


# Webinar K2 9-11/6/2026 guest token config
WEBINAR_TOKEN_PATTERN = re.compile(r"^wk2-b([1-3])-([a-f0-9]{8})$")
WEBINAR_GUEST_QUOTA_PER_WIZARD = 5
WEBINAR_GUEST_EXPIRES_AT = "2026-06-18T23:59:59+07:00"

WEBINAR_WIZARDS_PER_BUOI = {
    1: ["vision_clarity", "niche_validator"],
    2: ["transformation_mapper", "vpc_fit_check"],
    3: ["mvo_cohort", "offer_engineer"],
}


def _wizards_for_buoi(buoi: int) -> list[str]:
    """Return allowed wizards for K2 webinar guest token of given buổi."""
    return WEBINAR_WIZARDS_PER_BUOI.get(buoi, [])


def _parse_webinar_token(token: str) -> Optional[dict]:
    """Parse webinar K2 guest token, return tier info or None if not webinar format."""
    m = WEBINAR_TOKEN_PATTERN.match(token)
    if not m:
        return None
    buoi = int(m.group(1))
    return {
        "tier": "webinar_guest",
        "buoi": buoi,
        "phone_hash": m.group(2),
        "quota_per_wizard": WEBINAR_GUEST_QUOTA_PER_WIZARD,
        "expires_at": WEBINAR_GUEST_EXPIRES_AT,
        "allowed_wizards": _wizards_for_buoi(buoi),
    }


def _verify_student_token(token: Optional[str]) -> str:
    """Validate student/webinar token + return student_id.

    Supports 2 formats:
    - Cohort 1 student: `cohort1-{student_id}-{hash}` → return `{student_id}`
    - Webinar K2 guest: `wk2-b{N}-{hash}` → return `webinar-guest-{hash}`
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing X-Cohort-Student-Token")

    # Webinar K2 guest token (9-11/6/2026)
    webinar_info = _parse_webinar_token(token)
    if webinar_info:
        return f"webinar-guest-{webinar_info['phone_hash']}"

    # Cohort 1 student token
    if token.startswith("cohort1-"):
        parts = token.split("-", 2)
        if len(parts) < 3:
            raise HTTPException(status_code=401, detail="Malformed token")
        return parts[1]

    raise HTTPException(status_code=401, detail="Invalid token format")


async def _check_webinar_quota(token: str, wizard_name: str) -> int:
    """Return successful run count for webinar guest token + wizard combo.

    Caller compares against WEBINAR_GUEST_QUOTA_PER_WIZARD. Returns 0 on error,
    allowing run (graceful degradation, don't block webinar audience on infra glitch).
    """
    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
    if not dsn or asyncpg is None:
        log.warning("No DATABASE_URL or asyncpg missing, skip quota check")
        return 0

    conn = None
    try:
        conn = await asyncpg.connect(dsn)
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM wizard_usage_log WHERE token = $1 AND wizard_name = $2 AND success = TRUE",
            token,
            wizard_name,
        )
        return int(count or 0)
    except Exception as exc:  # noqa: BLE001
        log.warning("Quota check fail token=%s wizard=%s: %r", token, wizard_name, exc)
        return 0
    finally:
        if conn:
            await conn.close()


async def _log_wizard_usage(
    token: str,
    student_id: str,
    wizard_name: str,
    buoi: Optional[int],
    success: bool,
    utm: Optional[dict] = None,
) -> None:
    """Persist wizard usage event to wizard_usage_log table.

    Fail silently on infra error to avoid blocking user-facing wizard runs.
    """
    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
    if not dsn or asyncpg is None:
        return

    utm = utm or {}
    conn = None
    try:
        conn = await asyncpg.connect(dsn)
        await conn.execute(
            """
            INSERT INTO wizard_usage_log
            (token, student_id, wizard_name, buoi, utm_source, utm_medium, utm_campaign, utm_content, success)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            token,
            student_id,
            wizard_name,
            buoi,
            utm.get("source"),
            utm.get("medium"),
            utm.get("campaign"),
            utm.get("content"),
            success,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Usage log fail token=%s wizard=%s: %r", token, wizard_name, exc)
    finally:
        if conn:
            await conn.close()


def _scheduler(request: Request):
    sched = getattr(request.app.state, "scheduler", None)
    if sched is None:
        raise HTTPException(status_code=503, detail="Scheduler chưa boot")
    return sched


@router.get("/", response_class=HTMLResponse)
async def cohort_index() -> HTMLResponse:
    """BreakoutOS v3 dashboard, premium hub center + 10 tuần orbit (5 OS layer)."""
    sorted_wizards = sorted(WIZARD_REGISTRY.items(), key=lambda x: x[1]["week"])
    # Build 8 cards: 7 wizards + 1 Tuần 4 placeholder
    cards_by_week: dict = {}
    for slug, w in sorted_wizards:
        cards_by_week[w["week"]] = (slug, w)

    # Build week cards (7 wizards + 1 Tuần 4 practice placeholder)
    cards_html = []
    for week in range(1, 9):
        if week == 4:
            p = WEEK_4_PLACEHOLDER
            cards_html.append(f"""
        <a class="orbit-card orbit-card-{week} orbit-card-practice" href="/cohort/wizard/{p['wizard_slug']}">
          <div class="orbit-card-glow"></div>
          <div class="orbit-card-num">04</div>
          <div class="orbit-card-tag">Thực hành</div>
          <h3>{p['title']}</h3>
          <p>{p['subtitle']}</p>
          <span class="orbit-card-cta">Đào sâu lại <svg viewBox="0 0 16 16" width="14" height="14"><path d="M1 8h12m-4-4l4 4-4 4" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
        </a>""")
        elif week in cards_by_week:
            slug, w = cards_by_week[week]
            cards_html.append(f"""
        <a class="orbit-card orbit-card-{week}" href="/cohort/wizard/{slug}">
          <div class="orbit-card-glow"></div>
          <div class="orbit-card-num">{week:02d}</div>
          <div class="orbit-card-tag">Tuần {week}</div>
          <h3>{w['title']}</h3>
          <p>{w['subtitle']}</p>
          <span class="orbit-card-cta">Bắt đầu <svg viewBox="0 0 16 16" width="14" height="14"><path d="M1 8h12m-4-4l4 4-4 4" stroke="currentColor" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
        </a>""")

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BreakoutOS, hệ điều hành xây Solo Empire</title>
  <meta name="description" content="Hệ điều hành xây doanh nghiệp một người với AI. 10 tuần, 10 trợ lý AI Đào Thị Hằng huấn luyện. 1 instance riêng. Lifetime kernel update.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800;900&family=Playfair+Display:ital,wght@0,400;0,500;1,400&display=swap">
  <link rel="stylesheet" href="/cohort/static/cohort-widget.css">
</head>
<body class="os-home">
  <div class="os-bg-grid"></div>
  <div class="os-bg-glow os-bg-glow-1"></div>
  <div class="os-bg-glow os-bg-glow-2"></div>

  <nav class="os-nav">
    <div class="os-nav-inner">
      <div class="os-logo">
        <span class="os-logo-word">BREAKOUT</span><span class="os-logo-os">OS</span>
      </div>
      <div class="os-nav-meta">
        <span class="os-nav-pill"><span class="os-nav-dot"></span> Cohort 1 · Đang vận hành</span>
      </div>
    </div>
  </nav>

  <main class="os-main">

    <section class="os-system">
      <div class="os-system-head">
        <div class="os-hero-eyebrow">
          <span class="os-eyebrow-dot"></span>
          Hệ điều hành xây doanh nghiệp một người
        </div>
        <p class="os-system-slogan-top">Một người. Một AI. Một doanh nghiệp.</p>
      </div>

      <div class="orbit-mega">
        <div class="orbit-ring orbit-ring-mid-deco"></div>
        <div class="orbit-ring orbit-ring-inner-deco"></div>
        <div class="orbit-glow"></div>

        <div class="orbit-hub">
          <div class="hub-inner">
            <div class="hub-shimmer"></div>
            <div class="hub-frame"></div>
            <div class="hub-badge">SYSTEM CORE</div>
            <div class="hub-wordmark">
              <span class="hub-word-breakout">BREAKOUT</span><span class="hub-word-os">OS</span>
            </div>
            <div class="hub-divider"></div>
            <p class="hub-tagline">Hệ điều hành<br>Solo Empire</p>
            <p class="hub-meta">10 tuần · 10 trợ lý · 5 OS layer</p>
          </div>
        </div>

        <div class="orbit-inner-group">{"".join(cards_html)}</div>
      </div>

      <div class="os-system-foot">
        <div class="os-system-stats">
          <div class="os-stat"><b>10</b><span>tuần lộ trình</span></div>
          <div class="os-stat-rule"></div>
          <div class="os-stat"><b>10</b><span>trợ lý AI</span></div>
          <div class="os-stat-rule"></div>
          <div class="os-stat"><b>6</b><span>sản phẩm tự động</span></div>
          <div class="os-stat-rule"></div>
          <div class="os-stat"><b>1</b><span>founder vận hành</span></div>
        </div>
        <p class="os-system-caption">
          <em>BreakoutOS</em> ở trung tâm, 10 trợ lý AI vận hành xung quanh,<br>5 OS layer xếp chồng từ tầm nhìn đến scale 90 ngày sau cohort.
        </p>
      </div>
    </section>

    <section class="os-products">
      <div class="os-products-head">
        <div class="os-hero-eyebrow">
          <span></span>
          Sản phẩm tự động vận hành
          <span></span>
        </div>
        <h2 class="os-products-title">6 sản phẩm AI sinh ra,<br><em>bạn chỉ cần share.</em></h2>
        <p class="os-products-sub">
          Sau 10 tuần, BreakoutOS đã sản xuất sẵn cho bạn 6 sản phẩm tự động + 1 Fan Hub riêng + 1 AI COO Dashboard + 1 Capstone AIOS instance. Tất cả chạy 24/7. Lifetime kernel update.
        </p>
      </div>

      <div class="os-products-grid">
        <a class="os-product-card" href="/cohort/wizard/offer_engineer">
          <div class="os-product-num">01</div>
          <div class="os-product-icon">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 16.5L3 22l5.5-1.5L20 9 15 4z"/><path d="M14 5l5 5"/></svg>
          </div>
          <h4>Trang bán hàng</h4>
          <p>HTML landing từ offer bạn design. CTA Zalo deeplink, mobile responsive, ready share.</p>
          <span class="os-product-source">TUẦN 6</span>
        </a>

        <a class="os-product-card" href="/cohort/wizard/offer_engineer">
          <div class="os-product-num">02</div>
          <div class="os-product-icon">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
          </div>
          <h4>Kho ads + content</h4>
          <p>5 headlines, 3 Reel hooks, 3 FB ad copy, 7 email subject. Ready paste FB Ads + TikTok.</p>
          <span class="os-product-source">TUẦN 6</span>
        </a>

        <a class="os-product-card" href="/cohort/wizard/mvo_cohort">
          <div class="os-product-num">03</div>
          <div class="os-product-icon">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>
          </div>
          <h4>Chuỗi email nuôi khách</h4>
          <p>5 email tự động chào, giỏ hàng, sau mua, win-back. Brevo / MailerLite ready.</p>
          <span class="os-product-source">TUẦN 7</span>
        </a>

        <a class="os-product-card" href="/cohort/wizard/mvo_cohort">
          <div class="os-product-num">04</div>
          <div class="os-product-icon">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20M6 15h4"/></svg>
          </div>
          <h4>Hệ thống thu tiền</h4>
          <p>Trang thanh toán, hướng dẫn QR, bank info form. Share link ngay cho khách.</p>
          <span class="os-product-source">TUẦN 7</span>
        </a>

        <a class="os-product-card" href="/cohort/wizard/referral_engine">
          <div class="os-product-num">05</div>
          <div class="os-product-icon">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>
          </div>
          <h4>Chăm sóc khách hàng</h4>
          <p>6 workflow tự động: Welcome, Onboarding, Cart Abandon, Post-purchase, Refund, Win-back.</p>
          <span class="os-product-source">TUẦN 8</span>
        </a>

        <a class="os-product-card" href="/cohort/wizard/referral_engine">
          <div class="os-product-num">06</div>
          <div class="os-product-icon">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 20V10m6 10V4m6 16v-8m6 8V8"/></svg>
          </div>
          <h4>Chấm điểm khách hàng</h4>
          <p>Lead score 3 tier Nóng / Ấm / Lạnh tự động. Tập trung khách đáng giá nhất.</p>
          <span class="os-product-source">TUẦN 8</span>
        </a>
      </div>
    </section>

    <footer class="os-footer">
      <div class="os-footer-inner">
        <div class="os-footer-brand">
          <div class="os-logo">
            <span class="os-logo-word">BREAKOUT</span><span class="os-logo-os">OS</span>
          </div>
          <div class="os-footer-rule"></div>
          <p class="os-footer-slogan">Một người. Một AI. Một doanh nghiệp.</p>
          <p class="os-footer-tagline">Đào Thị Hằng huấn luyện, vận hành thật trên 6 ventures.</p>
        </div>
        <div class="os-footer-meta">
          <span>© 2026 Đào Thị Hằng</span>
          <span class="os-footer-sep">·</span>
          <a href="https://breakout.live">breakout.live</a>
        </div>
      </div>
    </footer>
  </main>
</body>
</html>""")


@router.get("/wizard/{wizard_name}", response_class=HTMLResponse)
async def cohort_wizard_page(wizard_name: str) -> HTMLResponse:
    """Serve HTML page với embedded widget per wizard."""
    if wizard_name not in WIZARD_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Wizard '{wizard_name}' not found")
    w = WIZARD_REGISTRY[wizard_name]
    from kernel.output_actions import get_actions_for_wizard
    actions_list = get_actions_for_wizard(wizard_name)
    # Render multiple deploy buttons (1 per action_type)
    deploy_buttons_html = "".join(
        f'<button class="cohort-btn cohort-btn-deploy cohort-deploy-action-btn" '
        f'data-action-type="{a["action_type"]}" data-label="{_esc_html(a["label"])}" '
        f'style="display:none">{_esc_html(a["label"])}</button>'
        for a in actions_list
    )
    # Backward compat: data-deploy-label kept for single-action (offer_engineer existing)
    action_cfg = actions_list[0] if actions_list else None
    deploy_data_attr = f'data-deploy-label="{_esc_html(action_cfg["label"])}"' if action_cfg else ""
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

      <div class="cohort-auth" style="display:none">
        <input type="hidden" id="cohort-token">
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
          {deploy_buttons_html}
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


# Webinar K2 9-11/6/2026 Tally form URLs (created 2026-06-08 via API, 21 blocks each)
WEBINAR_K2_TALLY_URLS = {
    1: "https://tally.so/r/aQzkNE",  # K2 Buổi 1 · Vision Submission
    2: "https://tally.so/r/68P4JO",  # K2 Buổi 2 · Customer Submission
    3: "https://tally.so/r/7REjl9",  # K2 Buổi 3 · Offer Capstone Submission
}


@router.get("/webinar-demo/{wizard_name}", response_class=HTMLResponse)
async def webinar_demo_page(wizard_name: str, request: Request) -> HTMLResponse:
    """Simplified mobile-responsive landing for K2 9-11/6/2026 webinar audience.

    Token auto-extracted from URL ?token=wk2-b{N}-{hash}. No manual token entry.
    Embed Tally form button at end for submission + review live next buổi.
    """
    if wizard_name not in WIZARD_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Wizard '{wizard_name}' not found")

    w = WIZARD_REGISTRY[wizard_name]
    token = request.query_params.get("token", "")
    webinar_info = _parse_webinar_token(token) if token else None
    buoi = webinar_info["buoi"] if webinar_info else 0
    tally_url = WEBINAR_K2_TALLY_URLS.get(buoi, "")

    # UTM tracking (auto-attach for analytics)
    utm_source = request.query_params.get("utm_source", "webinar_k2")
    utm_medium = request.query_params.get("utm_medium", "wizard_demo")
    utm_campaign = request.query_params.get("utm_campaign", f"b{buoi}" if buoi else "")
    utm_content = request.query_params.get("utm_content", token)

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
  <title>{w['title']} | Webinar K2 Buổi {buoi or '?'}</title>
  <link rel="stylesheet" href="/cohort/static/cohort-widget.css">
  <style>
    body {{ background: #fafafa; margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
    .wd-container {{ max-width: 640px; margin: 0 auto; padding: 16px; }}
    .wd-badge {{ display: inline-block; background: linear-gradient(135deg, #ff7e5f, #d63031); color: white; padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 12px; }}
    .wd-title {{ font-size: 24px; font-weight: 700; margin: 0 0 8px; color: #222; line-height: 1.3; }}
    .wd-subtitle {{ font-size: 15px; color: #666; margin: 0 0 24px; line-height: 1.5; }}
    .wd-form {{ background: white; border-radius: 16px; padding: 20px; box-shadow: 0 2px 12px rgba(0,0,0,0.04); margin-bottom: 16px; }}
    .wd-form label {{ display: block; font-size: 13px; font-weight: 600; color: #444; margin-bottom: 8px; }}
    .wd-form textarea {{ width: 100%; box-sizing: border-box; border: 1px solid #e0e0e0; border-radius: 10px; padding: 12px; font-size: 15px; font-family: inherit; resize: vertical; min-height: 140px; }}
    .wd-form textarea:focus {{ outline: none; border-color: #ff7e5f; }}
    .wd-btn {{ display: block; width: 100%; box-sizing: border-box; padding: 14px; background: linear-gradient(135deg, #ff7e5f, #d63031); color: white; border: none; border-radius: 12px; font-size: 16px; font-weight: 600; cursor: pointer; margin-top: 12px; }}
    .wd-btn:disabled {{ opacity: 0.5; cursor: wait; }}
    .wd-loading {{ text-align: center; color: #999; font-size: 13px; padding: 16px; }}
    .wd-error {{ background: #fff0f0; color: #c00; border-radius: 10px; padding: 12px 16px; font-size: 14px; margin-top: 12px; }}
    .wd-output {{ background: white; border-radius: 16px; padding: 20px; box-shadow: 0 2px 12px rgba(0,0,0,0.04); margin-bottom: 16px; }}
    .wd-output h2 {{ font-size: 18px; margin: 0 0 12px; color: #222; }}
    .wd-output-md {{ font-size: 14px; line-height: 1.7; color: #333; }}
    .wd-output-md h1, .wd-output-md h2, .wd-output-md h3 {{ font-size: 16px; font-weight: 600; margin-top: 16px; margin-bottom: 8px; }}
    .wd-output-md ul, .wd-output-md ol {{ padding-left: 20px; }}
    .wd-cta {{ background: #fff8e1; border: 2px solid #ffc107; border-radius: 16px; padding: 20px; text-align: center; margin: 24px 0; }}
    .wd-cta h3 {{ font-size: 17px; margin: 0 0 8px; color: #c08a00; }}
    .wd-cta p {{ font-size: 14px; color: #666; margin: 0 0 16px; }}
    .wd-tally-btn {{ display: inline-block; background: linear-gradient(135deg, #ff7e5f, #d63031); color: white; padding: 14px 28px; border-radius: 12px; font-weight: 600; text-decoration: none; font-size: 15px; }}
    .wd-footer {{ text-align: center; color: #aaa; font-size: 12px; padding: 20px 0; }}
    .wd-token-warn {{ background: #fff0f0; color: #c00; padding: 12px; border-radius: 10px; margin-bottom: 16px; font-size: 13px; }}
  </style>
</head>
<body>
  <div class="wd-container">
    <div class="wd-badge">Team Cô Hằng AI · Buổi {buoi or '?'}</div>
    <h1 class="wd-title">{w['title']}</h1>
    <p class="wd-subtitle">{w['subtitle']}</p>

    {"<div class='wd-token-warn'>⚠️ Token không hợp lệ. Bạn cần nhắn <strong>K2BUOI" + str(buoi or 1) + "</strong> đến Zalo 0932093593 để nhận token truy cập.</div>" if not webinar_info else ""}

    <div class="wd-form" id="wd-form">
      <label for="wd-input">{w['input_label']}</label>
      <textarea id="wd-input"
                placeholder="{w['input_placeholder']}"
                rows="8"></textarea>
      <button class="wd-btn" id="wd-run-btn" {"disabled" if not webinar_info else ""}>
        Nhờ trợ lý AI phân tích
      </button>
      <div class="wd-loading" id="wd-loading" style="display:none">
        Trợ lý AI đang phân tích, 30-90 giây...
      </div>
      <div class="wd-error" id="wd-error" style="display:none"></div>
    </div>

    <div class="wd-output" id="wd-output" style="display:none">
      <h2>Kết quả phân tích</h2>
      <div class="wd-output-md" id="wd-output-md"></div>
    </div>

    <div class="wd-cta" id="wd-cta" style="display:none">
      <h3>Submit để được Hằng review LIVE buổi mai</h3>
      <p>Top 3 outputs xuất sắc nhất sẽ được đọc tên + output LIVE đầu buổi tiếp theo + nhận <strong>1 vé Foundation 1 triệu</strong>.</p>
      <a class="wd-tally-btn" id="wd-tally-btn" target="_blank" rel="noopener">
        Submit output Team Cô Hằng AI
      </a>
    </div>

    <div class="wd-footer">
      Cohangai · BreakoutOS K2 9-11/6/2026 · 7 wizard CAMAS Kernel
    </div>
  </div>

  <script>
    (function() {{
      const TOKEN = {json.dumps(token)};
      const WIZARD_NAME = {json.dumps(wizard_name)};
      const TALLY_URL = {json.dumps(tally_url)};
      const UTM = {{
        source: {json.dumps(utm_source)},
        medium: {json.dumps(utm_medium)},
        campaign: {json.dumps(utm_campaign)},
        content: {json.dumps(utm_content)},
      }};

      const $input = document.getElementById('wd-input');
      const $runBtn = document.getElementById('wd-run-btn');
      const $loading = document.getElementById('wd-loading');
      const $error = document.getElementById('wd-error');
      const $output = document.getElementById('wd-output');
      const $outputMd = document.getElementById('wd-output-md');
      const $cta = document.getElementById('wd-cta');
      const $tallyBtn = document.getElementById('wd-tally-btn');

      function mdToHtml(md) {{
        // Minimal Markdown → HTML (headers, bold, lists). For full render use marked.js if needed.
        return md
          .replace(/^### (.+)$/gm, '<h3>$1</h3>')
          .replace(/^## (.+)$/gm, '<h2>$1</h2>')
          .replace(/^# (.+)$/gm, '<h1>$1</h1>')
          .replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')
          .replace(/^- (.+)$/gm, '<li>$1</li>')
          .replace(/(<li>.+<\\/li>(\\n|$))+/g, '<ul>$&</ul>')
          .replace(/\\n\\n/g, '</p><p>')
          .replace(/^([^<].*)/gm, '<p>$1</p>')
          .replace(/<p><\\/p>/g, '');
      }}

      $runBtn.addEventListener('click', async () => {{
        const input = $input.value.trim();
        if (input.length < 10) {{
          $error.textContent = 'Input quá ngắn, cần ít nhất 10 ký tự';
          $error.style.display = 'block';
          return;
        }}
        $error.style.display = 'none';
        $runBtn.disabled = true;
        $loading.style.display = 'block';
        try {{
          const resp = await fetch('/cohort/run-wizard', {{
            method: 'POST',
            headers: {{
              'Content-Type': 'application/json',
              'X-Cohort-Student-Token': TOKEN,
            }},
            body: JSON.stringify({{
              wizard: WIZARD_NAME,
              input: input,
              utm: UTM,
            }}),
          }});
          const data = await resp.json();
          if (!resp.ok || !data.success) {{
            throw new Error(data.detail || data.error || 'Lỗi không xác định');
          }}
          $outputMd.innerHTML = mdToHtml(data.markdown || data.summary || '');
          $output.style.display = 'block';
          if (TALLY_URL) {{
            const tallyWithOutput = TALLY_URL + '?token=' + encodeURIComponent(TOKEN)
              + '&output=' + encodeURIComponent((data.markdown || '').slice(0, 4000))
              + '&wizard=' + encodeURIComponent(WIZARD_NAME);
            $tallyBtn.href = tallyWithOutput;
            $cta.style.display = 'block';
          }}
          window.scrollTo({{ top: $output.offsetTop - 20, behavior: 'smooth' }});
        }} catch (err) {{
          $error.textContent = err.message;
          $error.style.display = 'block';
        }} finally {{
          $loading.style.display = 'none';
          $runBtn.disabled = false;
        }}
      }});
    }})();
  </script>
</body>
</html>""")


@router.post("/run-wizard")
async def run_wizard(
    request: Request,
    x_cohort_student_token: Optional[str] = Header(None),
) -> JSONResponse:
    """Trigger wizard agent + return Markdown output."""
    student_id = _verify_student_token(x_cohort_student_token)

    # Parse webinar K2 guest tier info (None if Cohort 1 student)
    webinar_info = _parse_webinar_token(x_cohort_student_token or "")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    wizard_name = body.get("wizard")
    if not wizard_name or wizard_name not in WIZARD_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Invalid wizard. Available: {list(WIZARD_REGISTRY.keys())}")

    # Webinar K2 guest gate: allowed_wizards per buổi + quota 5 runs/wizard
    if webinar_info:
        if wizard_name not in webinar_info["allowed_wizards"]:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Wizard '{wizard_name}' chưa unlock cho buổi {webinar_info['buoi']}. "
                    "Bạn cần Cohort 1 K2 (Foundation/Customer/Growth/Breakout Founder) để dùng đủ 7 wizard."
                ),
            )
        used_count = await _check_webinar_quota(x_cohort_student_token or "", wizard_name)
        if used_count >= WEBINAR_GUEST_QUOTA_PER_WIZARD:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Hết lượt thử miễn phí ({WEBINAR_GUEST_QUOTA_PER_WIZARD}/wizard). "
                    "Bạn cần Foundation 3M để dùng unlimited 12 tuần Breakout Founder."
                ),
            )

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
        # Webinar K2 failure log (don't count failed runs toward quota, but track for debug)
        if webinar_info:
            await _log_wizard_usage(
                token=x_cohort_student_token or "",
                student_id=student_id,
                wizard_name=wizard_name,
                buoi=webinar_info["buoi"],
                success=False,
                utm=body.get("utm") or {},
            )
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

    # Webinar K2 usage log + UTM tracking
    if webinar_info:
        await _log_wizard_usage(
            token=x_cohort_student_token or "",
            student_id=student_id,
            wizard_name=wizard_name,
            buoi=webinar_info["buoi"],
            success=True,
            utm=body.get("utm") or {},
        )

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
    """Deploy wizard output sang artifact thật.

    Body:
      - wizard_output: full output payload (optional, fallback memory chain)
      - action_type: which action to deploy (e.g. 'html_landing', 'email_sequence',
        'payment_landing', 'crm_workflow', 'lead_scoring'). Default = wizard's first action.

    Returns: {"success": true, "url": "...", "landing_id": "...", "action_type": "..."}
    """
    from kernel.output_actions import get_actions_for_wizard, get_action_by_type

    student_id = _verify_student_token(x_cohort_student_token)

    actions_list = get_actions_for_wizard(wizard_name)
    if not actions_list:
        raise HTTPException(
            status_code=400,
            detail=f"Wizard '{wizard_name}' chưa support deploy-action.",
        )

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Pick action_type: body override, else first action default
    requested_action = body.get("action_type")
    if requested_action:
        action_cfg = get_action_by_type(wizard_name, requested_action)
        if action_cfg is None:
            raise HTTPException(
                status_code=400,
                detail=f"Action type '{requested_action}' không support cho wizard {wizard_name}. Available: {[a['action_type'] for a in actions_list]}",
            )
    else:
        action_cfg = actions_list[0]

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

    action_type = action_cfg["action_type"]
    handler = action_cfg["handler"]
    landing_id = generate_landing_id(student_id, f"{wizard_name}-{action_type[:6]}")

    # Dispatch to handler (offer payload key naming varies, handler accepts payload dict)
    try:
        html_content = handler(
            wizard_output,
            student_id,
            landing_id,
        )
    except TypeError:
        # Legacy handler signature (offer_engineer): offer_payload= kwarg
        html_content = handler(
            offer_payload=wizard_output,
            student_id=student_id,
            landing_id=landing_id,
        )

    sched = _scheduler(request)
    if getattr(sched, "memory", None) is None:
        raise HTTPException(status_code=503, detail="Memory layer not ready, không persist được")

    try:
        record = MemoryRecord(
            agent_name=f"cohort_artifact_{wizard_name}_{action_type}",
            content=html_content,
            keywords=[LANDING_TAG, landing_id, student_id, wizard_name, action_type],
            tags=[LANDING_TAG, landing_id, student_id, wizard_name, action_type, "cohort_1"],
            category="task",
            context=f"Artifact deployed student={student_id} wizard={wizard_name} action={action_type} id={landing_id}",
            venture="cohangai",
            evolution_history=[],
        )
        await sched.memory.store(record)
    except Exception as exc:  # noqa: BLE001
        log.warning("Artifact store fail: %r", exc)
        raise HTTPException(status_code=500, detail=f"Storage fail: {exc}")

    base_url = os.getenv("CAMAS_PUBLIC_URL", "https://camas-kernel-production.up.railway.app")
    landing_url = f"{base_url}/cohort/landing/{landing_id}"

    log.info(
        "Artifact deployed student=%s wizard=%s action=%s id=%s",
        student_id, wizard_name, action_type, landing_id,
    )

    return JSONResponse({
        "success": True,
        "action_type": action_type,
        "landing_id": landing_id,
        "url": landing_url,
        "wizard": wizard_name,
    })


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


@router.get("/admin/webinar-submissions", response_class=HTMLResponse)
async def admin_webinar_submissions(
    request: Request,
    buoi: int = 1,
    key: Optional[str] = None,
) -> HTMLResponse:
    """Webinar K2 admin view: list wizard runs per buổi sorted by activity desc.

    Hằng uses this 6-7am sáng hôm sau buổi để pick top 3 winners.
    Query wizard_usage_log table (migration 004).
    """
    _verify_admin_key(key)
    if buoi not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="buoi phải là 1, 2, hoặc 3")

    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
    if not dsn or asyncpg is None:
        raise HTTPException(status_code=503, detail="Database not configured")

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT
                token,
                student_id,
                COUNT(*) FILTER (WHERE success = TRUE) AS runs_success,
                COUNT(*) FILTER (WHERE success = FALSE) AS runs_failed,
                array_agg(DISTINCT wizard_name) AS wizards_used,
                MAX(run_at) AS last_run,
                MIN(run_at) AS first_run,
                MAX(utm_source) AS utm_source,
                MAX(utm_campaign) AS utm_campaign
            FROM wizard_usage_log
            WHERE buoi = $1
            GROUP BY token, student_id
            ORDER BY runs_success DESC, last_run DESC
            LIMIT 100
            """,
            buoi,
        )
    finally:
        await conn.close()

    # Render simple table
    table_rows = []
    for i, r in enumerate(rows, start=1):
        wizards = ", ".join(sorted(r["wizards_used"] or []))
        last_run = r["last_run"].strftime("%H:%M %d/%m") if r["last_run"] else "—"
        score = int(r["runs_success"] or 0) * 5  # +5/wizard run
        token_short = (r["token"] or "")[:18] + "..." if len(r["token"] or "") > 18 else r["token"]
        table_rows.append(f"""
        <tr>
          <td class="rank">#{i}</td>
          <td class="token" title="{r['token']}">{token_short}</td>
          <td>{r['student_id']}</td>
          <td class="num">{r['runs_success']}</td>
          <td class="num fail">{r['runs_failed']}</td>
          <td class="wizards">{wizards}</td>
          <td>{score}</td>
          <td>{last_run}</td>
          <td><input type="checkbox" class="winner-pick" data-token="{r['token']}" data-buoi="{buoi}"></td>
          <td><textarea class="why-pick" data-token="{r['token']}" rows="2" placeholder="Why pick..."></textarea></td>
        </tr>
        """)

    table_html = "".join(table_rows) if table_rows else "<tr><td colspan='10' style='text-align:center;padding:40px;color:#999'>Chưa có submission cho Buổi {}</td></tr>".format(buoi)

    buoi_meta = {
        1: ("BÁN CÁI GÌ", "vision_clarity + niche_validator"),
        2: ("BÁN CHO AI", "transformation_mapper + vpc_fit_check"),
        3: ("BÁN NHƯ THẾ NÀO", "mvo_cohort + offer_engineer"),
    }
    title, wizards_buoi = buoi_meta[buoi]

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <title>K2 B{buoi} Submissions Review | Hằng Admin</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #fafafa; margin: 0; padding: 24px; color: #222; }}
    .container {{ max-width: 1400px; margin: 0 auto; }}
    h1 {{ font-size: 22px; margin: 0 0 4px; }}
    .meta {{ color: #666; font-size: 13px; margin-bottom: 20px; }}
    .nav {{ margin-bottom: 16px; }}
    .nav a {{ display: inline-block; padding: 8px 16px; background: white; border-radius: 8px; text-decoration: none; color: #444; margin-right: 8px; font-size: 13px; font-weight: 600; }}
    .nav a.active {{ background: linear-gradient(135deg, #ff7e5f, #d63031); color: white; }}
    table {{ width: 100%; background: white; border-collapse: collapse; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.04); }}
    thead {{ background: #f5f5f5; }}
    th {{ text-align: left; padding: 12px 10px; font-size: 12px; font-weight: 600; color: #666; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #e5e5e5; }}
    td {{ padding: 10px; font-size: 13px; border-bottom: 1px solid #f5f5f5; vertical-align: middle; }}
    .rank {{ font-weight: 700; color: #888; }}
    .token {{ font-family: monospace; font-size: 11px; color: #555; }}
    .num {{ text-align: center; font-weight: 600; }}
    .num.fail {{ color: #c00; }}
    .wizards {{ font-size: 12px; color: #666; }}
    .winner-pick {{ width: 20px; height: 20px; cursor: pointer; }}
    .why-pick {{ width: 100%; border: 1px solid #e5e5e5; border-radius: 6px; padding: 6px; font-family: inherit; font-size: 12px; resize: vertical; }}
    .summary {{ background: #fff8e1; border: 2px solid #ffc107; border-radius: 12px; padding: 16px; margin-bottom: 16px; }}
    .summary strong {{ color: #c08a00; }}
    .actions {{ position: fixed; bottom: 20px; right: 20px; background: white; padding: 12px 20px; border-radius: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.1); }}
    .actions button {{ background: linear-gradient(135deg, #ff7e5f, #d63031); color: white; border: none; padding: 10px 20px; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; }}
    .actions span {{ margin-right: 12px; color: #666; font-size: 13px; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>K2 Webinar Buổi {buoi}, {title}</h1>
    <p class="meta">Wizards demo: {wizards_buoi} · Voucher reward: 1 vé Foundation 1M cho 3 winners</p>

    <div class="nav">
      <a href="?key={key}&buoi=1" class="{'active' if buoi == 1 else ''}">Buổi 1</a>
      <a href="?key={key}&buoi=2" class="{'active' if buoi == 2 else ''}">Buổi 2</a>
      <a href="?key={key}&buoi=3" class="{'active' if buoi == 3 else ''}">Buổi 3</a>
      <a href="/cohort/admin/webinar-submissions/export?key={key}&buoi={buoi}" target="_blank">📥 Export CSV</a>
    </div>

    <div class="summary">
      <strong>Workflow chấm winner</strong>: tick 3 row tốt nhất + viết note Why pick. Click "Lock winners" để generate voucher code + send ZNS + email. Criteria: Specific + Actionable + Heartfelt + Format đủ.
    </div>

    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Token</th>
          <th>Student</th>
          <th>OK</th>
          <th>Fail</th>
          <th>Wizards used</th>
          <th>Score</th>
          <th>Last run</th>
          <th>Pick</th>
          <th>Why pick</th>
        </tr>
      </thead>
      <tbody>
        {table_html}
      </tbody>
    </table>

    <div class="actions">
      <span id="pick-count">0/3 picked</span>
      <button id="lock-btn" disabled>🔒 Lock winners</button>
    </div>
  </div>

  <script>
    const KEY = {json.dumps(key or "")};
    const BUOI = {buoi};

    document.querySelectorAll('.winner-pick').forEach(cb => {{
      cb.addEventListener('change', () => {{
        const picked = document.querySelectorAll('.winner-pick:checked');
        document.getElementById('pick-count').textContent = picked.length + '/3 picked';
        document.getElementById('lock-btn').disabled = picked.length !== 3;
        if (picked.length > 3) {{
          cb.checked = false;
          alert('Chỉ pick được 3 winners');
        }}
      }});
    }});

    document.getElementById('lock-btn').addEventListener('click', async () => {{
      const winners = Array.from(document.querySelectorAll('.winner-pick:checked')).map(cb => {{
        const token = cb.dataset.token;
        const noteEl = document.querySelector(`.why-pick[data-token="${{token}}"]`);
        return {{ token, why: noteEl.value.trim() }};
      }});
      if (winners.length !== 3) {{ alert('Cần pick đúng 3 winners'); return; }}
      if (winners.some(w => !w.why)) {{ alert('Mọi winner cần có note "Why pick"'); return; }}
      if (!confirm('Lock 3 winners + generate voucher Foundation 1M? Sẽ trigger ZNS + email tới winners.')) return;
      const btn = document.getElementById('lock-btn');
      btn.disabled = true;
      btn.textContent = '⏳ Locking...';
      try {{
        const resp = await fetch('/cohort/admin/webinar-submissions/lock-winners?key=' + encodeURIComponent(KEY), {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ buoi: BUOI, winners }}),
        }});
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Lock fail');
        alert('Locked. Voucher codes: ' + data.voucher_codes.join(', '));
        window.location.reload();
      }} catch (err) {{
        alert('Error: ' + err.message);
        btn.disabled = false;
        btn.textContent = '🔒 Lock winners';
      }}
    }});
  </script>
</body>
</html>""")


@router.post("/admin/webinar-submissions/lock-winners")
async def admin_lock_winners(request: Request, key: Optional[str] = None) -> JSONResponse:
    """Lock 3 winners per buổi, generate voucher codes, persist for downstream ZNS+email.

    Persist to `wizard_winner_pick` table (auto-create on first call).
    """
    _verify_admin_key(key)
    body = await request.json()
    buoi = body.get("buoi")
    winners = body.get("winners", [])
    if buoi not in (1, 2, 3) or len(winners) != 3:
        raise HTTPException(status_code=400, detail="buoi + 3 winners required")

    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
    if not dsn or asyncpg is None:
        raise HTTPException(status_code=503, detail="Database not configured")

    voucher_codes = []
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS wizard_winner_pick (
                id SERIAL PRIMARY KEY,
                buoi SMALLINT NOT NULL,
                rank SMALLINT NOT NULL,
                token TEXT NOT NULL,
                why_pick TEXT,
                voucher_code TEXT NOT NULL UNIQUE,
                voucher_value_vnd INT NOT NULL DEFAULT 1000000,
                expires_at TIMESTAMPTZ NOT NULL,
                picked_at TIMESTAMPTZ DEFAULT NOW(),
                notified_at TIMESTAMPTZ,
                redeemed_at TIMESTAMPTZ,
                UNIQUE(buoi, rank)
            );
            """,
        )
        for rank, w in enumerate(winners, start=1):
            code = f"K2-FND-B{buoi}-{rank}"
            voucher_codes.append(code)
            await conn.execute(
                """
                INSERT INTO wizard_winner_pick (buoi, rank, token, why_pick, voucher_code, expires_at)
                VALUES ($1, $2, $3, $4, $5, '2026-06-18T23:59:59+07:00'::timestamptz)
                ON CONFLICT (buoi, rank) DO UPDATE SET
                    token = EXCLUDED.token,
                    why_pick = EXCLUDED.why_pick,
                    voucher_code = EXCLUDED.voucher_code,
                    picked_at = NOW()
                """,
                buoi,
                rank,
                w["token"],
                w["why"],
                code,
            )
    finally:
        await conn.close()

    # Notify Telegram Breakout Ops (best effort)
    try:
        import json as _json
        import urllib.request as _ureq
        tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
        tg_chat = os.getenv("TELEGRAM_BREAKOUT_OPS_CHAT_ID") or "-1003813280155"
        if tg_token:
            msg = f"🏆 K2 B{buoi} winners locked:\n" + "\n".join(
                f"#{i+1} {w['token']} → {voucher_codes[i]}" for i, w in enumerate(winners)
            )
            url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            data = _json.dumps({"chat_id": tg_chat, "text": msg}).encode()
            req = _ureq.Request(url, data=data, headers={"Content-Type": "application/json"})
            _ureq.urlopen(req, timeout=5)
    except Exception as exc:  # noqa: BLE001
        log.warning("Telegram notify fail: %r", exc)

    return JSONResponse({
        "success": True,
        "buoi": buoi,
        "voucher_codes": voucher_codes,
        "count": len(winners),
    })


@router.get("/admin/webinar-submissions/export")
async def admin_webinar_export(
    request: Request,
    buoi: int = 1,
    key: Optional[str] = None,
) -> JSONResponse:
    """Export submissions CSV-ready (JSON list for client to convert)."""
    _verify_admin_key(key)
    if buoi not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="buoi phải là 1, 2, hoặc 3")
    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
    if not dsn or asyncpg is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT token, student_id, wizard_name, success, utm_source, utm_campaign, run_at
            FROM wizard_usage_log
            WHERE buoi = $1
            ORDER BY run_at DESC
            """,
            buoi,
        )
    finally:
        await conn.close()
    return JSONResponse({
        "buoi": buoi,
        "count": len(rows),
        "rows": [
            {
                "token": r["token"],
                "student_id": r["student_id"],
                "wizard_name": r["wizard_name"],
                "success": r["success"],
                "utm_source": r["utm_source"],
                "utm_campaign": r["utm_campaign"],
                "run_at": r["run_at"].isoformat() if r["run_at"] else None,
            }
            for r in rows
        ],
    })


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
