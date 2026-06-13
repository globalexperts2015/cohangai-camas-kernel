"""6 priorities per Anna 2026-06-12 feature freeze:

1. Demo Mode — pre-filled L1-L3 sample student
2. Event Tracking — POST /sdl/events/track + auto-emit
3. Validation Dashboard — 10-student progress against 5 criteria
4. Feedback Module — POST /sdl/feedback + admin view
5. Founder Dashboard — Anna's overview
6. Error Monitoring — DB log + Telegram alert middleware
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from routes._auth import sign_student
from routes.sdl_routes import get_pool


log = logging.getLogger("camas.validation")
router = APIRouter(tags=["validation"])

ADMIN_KEY = os.environ.get("BREAKOUTOS_ADMIN_KEY", "")


def _check_admin(key: str | None) -> None:
    if not key or not ADMIN_KEY or key != ADMIN_KEY:
        raise HTTPException(401, "Invalid admin key")


# ============================================================
# 1. DEMO MODE
# ============================================================
@router.post("/sdl/admin/demo/seed", status_code=201)
async def seed_demo_student(
    key: str = Query(...),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Create a demo student with full L1-L3 canonical files pre-populated.

    Use for webinar demo + admin testing. Marked metadata.is_demo=true.
    """
    _check_admin(key)
    demo_email = f"demo+{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}@daothihang.com"

    async with pool.acquire() as conn:
        sid = await conn.fetchval(
            """
            INSERT INTO breakoutos.students
              (program_id, cohort_id, email, full_name, status, metadata_json,
               current_level, current_gate)
            VALUES ('foundation', 'demo_cohort', $1, 'Demo Student',
                    'active', $2::jsonb, 3, 'gate_3_value_proposition_pending')
            RETURNING id
            """,
            demo_email,
            json.dumps({"is_demo": True, "seeded_at": datetime.utcnow().isoformat()}),
        )

        # Insert demo founder_profile
        await conn.execute(
            """
            INSERT INTO breakoutos.founder_profiles
              (student_id, mission, vision, why_statement, identity,
               principles_json, anti_vision_json, founder_assets_json, founder_story_json, version)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb, 1)
            """,
            sid,
            "Giúp người Việt học tập, kiếm tiền và tiếp cận cơ hội toàn cầu",
            "5 năm tới vận hành 6 venture với 1 mình + AI, doanh thu 1 triệu USD",
            "Vì tôi tin mỗi người Việt đều có thể độc lập tài chính nếu được trao công cụ đúng",
            "Người sáng lập tập trung vào hệ thống, không phải sáng tạo nội dung",
            json.dumps(["Bán transformation không bán offer", "Solo + AI không scale team",
                        "Hệ thống trước nhân sự", "Founder Identity trước marketing",
                        "Customer Fit > Pain"]),
            json.dumps(["agency 50 nhân sự", "làm việc 12 giờ/ngày",
                        "phụ thuộc quảng cáo", "bán cold call"]),
            json.dumps({"knowledge": ["Master Sustainability Adelaide", "Migration Diploma"],
                        "experience": [{"years": 15, "field": "đào tạo", "role": "founder"}],
                        "certifications": ["MARA track"], "network": {"count": 33000},
                        "skills": ["Shopify", "GHL", "AI"]}),
            json.dumps({"act_1_origin": "Sinh ra ở Quảng Trị làng nhỏ...",
                        "act_2_crisis": "15 năm đào tạo nhưng vẫn bắt đầu lại từ 0 mỗi venture...",
                        "act_3_transformation": "AI xuất hiện, quay lại xây hệ điều hành cho mình..."}),
        )

        # Insert demo customer_profile
        await conn.execute(
            """
            INSERT INTO breakoutos.customer_profiles
              (student_id, target_customer, jobs_json, pains_json, gains_json, fit_score_json, version)
            VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6::jsonb, 1)
            """,
            sid,
            "Phụ nữ văn phòng Việt 30-45 tuổi muốn nguồn thu nhập thứ hai",
            json.dumps({"functional": ["Tìm cách kiếm thêm thu nhập"],
                        "emotional": ["Cảm thấy tự tin"], "social": ["Được con cháu nhìn nhận"]}),
            json.dumps({"obstacles": ["Không biết bắt đầu từ đâu"],
                        "risks": ["Sợ thất bại lần đầu"],
                        "frustrations": ["Thử nhiều cách nhưng quên"]}),
            json.dumps({"required": ["Cách thực tế áp dụng"], "expected": ["AI làm được nhiều việc"],
                        "desired": ["Tự do tài chính"], "unexpected": ["Bộ não thứ hai"]}),
            json.dumps({"components": {"lived_experience": 9, "empathy": 8, "credibility": 9,
                                       "pain": 7, "reach": 8, "wtp": 7},
                        "total": 76, "passes_min_60": True}),
        )

        # Insert demo offer
        await conn.execute(
            """
            INSERT INTO breakoutos.offers
              (student_id, offer_name, target_customer, pain, desired_identity, vehicle,
               transformation, pricing_json, version)
            VALUES ($1, 'BreakoutOS Foundation 7 ngày',
                   'phụ nữ văn phòng muốn nguồn thu nhập thứ hai',
                   'không biết bán gì + không biết phục vụ ai',
                   'người sở hữu doanh nghiệp một người với AI',
                   'BreakoutOS',
                   'Từ rối → có hệ điều hành cá nhân',
                   $2::jsonb, 1)
            """,
            sid, json.dumps({"tier": "Foundation", "price_vnd": 3000000}),
        )

        # Demo canonical_files: 8 L1 + 11 L2 + 8 L3 = 27 files placeholder
        l1_keys = ["life-mission", "vision-statement", "founder-identity",
                   "decision-principles", "anti-vision",
                   "why-statement", "founder-assets", "founder-story"]
        l2_keys = ["who-i-serve", "customer-profile", "statement-mot-dong", "opportunity-map",
                   "why-this-customer", "lived-experience", "customer-empathy-map",
                   "demand-evidence", "conversation-evidence", "buying-journey", "buying-triggers"]
        l3_keys = ["core-offer", "pricing-strategy", "transformation-promise",
                   "positioning-statement", "offer-stack", "offer-financial-model",
                   "value-equation", "guarantee-strategy"]
        for level, keys in [(1, l1_keys), (2, l2_keys), (3, l3_keys)]:
            for fkey in keys:
                tier = "A" if fkey in ("life-mission", "vision-statement", "founder-identity",
                                       "decision-principles", "anti-vision",
                                       "who-i-serve", "customer-profile", "statement-mot-dong",
                                       "opportunity-map",
                                       "core-offer", "pricing-strategy",
                                       "transformation-promise", "positioning-statement") else "B"
                md = (f"---\nfile_key: {fkey}\nstudent_id: {sid}\n"
                      f"tier: {tier}\nlocked: true\nai_generated: {tier=='B'}\nversion: 1\n---\n\n"
                      f"# {fkey.replace('-', ' ').title()} (DEMO)\n\n"
                      f"_This is a demo seed for webinar showcase._\n")
                await conn.execute(
                    """
                    INSERT INTO breakoutos.canonical_files
                      (student_id, level, file_key, file_name, file_type, tier, lock_type,
                       markdown_content, structured_data_json, version, status, generated_by)
                    VALUES ($1, $2, $3, $4, 'canonical', $5, 'core', $6, $7::jsonb, 1, 'locked', 'demo_seed')
                    """,
                    sid, level, fkey, f"{fkey}.md", tier, md,
                    json.dumps({"demo": True}),
                )

        # Demo baseline + current freedom score
        await conn.execute(
            """
            INSERT INTO breakoutos.founder_freedom_score
              (student_id, source, revenue_score, time_score, stress_score, clarity_score,
               automation_score, mission_alignment_score,
               dependency_d3, dependency_d7, dependency_d30, dependency_d90)
            VALUES ($1, 'self_baseline', 6, 5, 4, 5, 3, 8, 1, 1, 0, 0),
                   ($1, 'self_weekly',   12, 14, 8, 11, 7, 16, 1, 3, 3, 0)
            """,
            sid,
        )

    signature = sign_student(str(sid))
    return {
        "demo_student_id": str(sid),
        "demo_email": demo_email,
        "links": {
            "baseline": f"/foundation/baseline?student={sid}&sig={signature}",
            "l1_form": f"/foundation/l1?student={sid}&sig={signature}",
            "l2_form": f"/foundation/l2?student={sid}&sig={signature}",
            "l3_form": f"/foundation/l3?student={sid}&sig={signature}",
            "dashboard": f"/sdl/student/{sid}/dashboard",
            "output_l1": f"/sdl/students/{sid}/output/L1",
            "vault_export": f"/sdl/students/{sid}/vault/export.zip",
        },
    }


@router.delete("/sdl/admin/demo/cleanup")
async def cleanup_demo_students(
    key: str = Query(...), pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Delete all demo students. Run before live launch."""
    _check_admin(key)
    async with pool.acquire() as conn:
        n = await conn.fetchval(
            "DELETE FROM breakoutos.students "
            "WHERE metadata_json->>'is_demo' = 'true' RETURNING (SELECT count(*))",
        )
    return {"deleted": n or 0}


# ============================================================
# 2. EVENT TRACKING
# ============================================================
class EventTrack(BaseModel):
    student_id: UUID | None = None
    event_type: str
    source: str = "frontend"
    level: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/sdl/events/track", status_code=201)
async def track_event(
    body: EventTrack, request: Request,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Generic event tracking from frontend.

    Common event types:
    - page.view
    - form.viewed | form.started | form.abandoned | form.submitted
    - canonical.viewed | canonical.approved
    - gate.requested | gate.passed | gate.failed
    - cta.clicked
    - webinar.joined | webinar.left
    """
    enriched_payload = {
        **body.payload,
        "user_agent": request.headers.get("user-agent", "")[:200],
        "referer": request.headers.get("referer", "")[:200],
    }
    async with pool.acquire() as conn:
        eid = await conn.fetchval(
            """
            INSERT INTO breakoutos.student_events
              (student_id, event_type, source, level, payload_json)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            RETURNING id
            """,
            body.student_id, body.event_type, body.source, body.level,
            json.dumps(enriched_payload, ensure_ascii=False, default=str),
        )
    return {"event_id": eid}


@router.get("/sdl/admin/events")
async def admin_events_timeline(
    key: str = Query(...),
    event_type: str | None = None,
    source: str | None = None,
    student_id: UUID | None = None,
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(200, le=2000),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[dict]:
    _check_admin(key)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, student_id, event_type, source, level, payload_json, created_at
            FROM breakoutos.student_events
            WHERE created_at > now() - ($1 || ' hours')::interval
              AND ($2::text IS NULL OR event_type = $2)
              AND ($3::text IS NULL OR source = $3)
              AND ($4::uuid IS NULL OR student_id = $4)
            ORDER BY created_at DESC LIMIT $5
            """,
            str(hours), event_type, source, student_id, limit,
        )
        return [dict(r) for r in rows]


# ============================================================
# 3. VALIDATION DASHBOARD
# ============================================================
@router.get("/sdl/admin/validation")
async def validation_status(
    key: str = Query(...),
    cohort_id: str = Query("cohort_1"),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """10-student validation criteria status.

    Per Anna 2026-06-12:
    - 10/10 hoàn thành L1-L3 (Gate 1 + Gate 2A + Gate 3 lock)
    - 8/10 có Statement Một Dòng rõ (Tier A approved)
    - 6/10 có Offer validated (Gate 3 passed)
    - 3/10 có First Paid Customer (purchase event ≥1M)
    - 1/10 case study public-ready (custom flag)
    """
    _check_admin(key)
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT count(*) FROM breakoutos.students "
            "WHERE cohort_id=$1 AND (metadata_json->>'is_demo' IS NULL OR metadata_json->>'is_demo' = 'false')",
            cohort_id,
        )
        l1_l3 = await conn.fetchval(
            """
            SELECT count(DISTINCT s.id) FROM breakoutos.students s
            WHERE s.cohort_id=$1 AND s.current_level >= 3
              AND EXISTS (SELECT 1 FROM breakoutos.canonical_locks
                          WHERE student_id=s.id AND gate_key='gate_1_founder' AND unlocked_at IS NULL)
              AND EXISTS (SELECT 1 FROM breakoutos.canonical_locks
                          WHERE student_id=s.id AND gate_key='gate_2_customer_soft' AND unlocked_at IS NULL)
              AND EXISTS (SELECT 1 FROM breakoutos.canonical_locks
                          WHERE student_id=s.id AND gate_key='gate_3_value_proposition' AND unlocked_at IS NULL)
            """,
            cohort_id,
        )
        statement = await conn.fetchval(
            """
            SELECT count(DISTINCT s.id) FROM breakoutos.students s
            WHERE s.cohort_id=$1
              AND EXISTS (SELECT 1 FROM breakoutos.canonical_files
                          WHERE student_id=s.id AND file_key='statement-mot-dong'
                          AND status IN ('reviewed','locked'))
            """,
            cohort_id,
        )
        offer_val = await conn.fetchval(
            """
            SELECT count(DISTINCT s.id) FROM breakoutos.students s
            WHERE s.cohort_id=$1
              AND EXISTS (SELECT 1 FROM breakoutos.canonical_locks
                          WHERE student_id=s.id AND gate_key='gate_3_value_proposition' AND unlocked_at IS NULL)
            """,
            cohort_id,
        )
        first_paid = await conn.fetchval(
            """
            SELECT count(DISTINCT s.id) FROM breakoutos.students s
            JOIN breakoutos.student_events e ON e.student_id=s.id
            WHERE s.cohort_id=$1 AND e.event_type='purchase.completed'
              AND (e.payload_json->>'amount_vnd')::int >= 1000000
            """,
            cohort_id,
        )
        case_studies = await conn.fetchval(
            """
            SELECT count(*) FROM breakoutos.students
            WHERE cohort_id=$1 AND metadata_json->>'case_study_public' = 'true'
            """,
            cohort_id,
        )

    criteria = [
        {"label": "Hoàn thành L1-L3", "target": 10, "actual": l1_l3 or 0},
        {"label": "Statement 1 dòng rõ", "target": 8, "actual": statement or 0},
        {"label": "Offer validated (Gate 3)", "target": 6, "actual": offer_val or 0},
        {"label": "First Paid Customer ≥1M", "target": 3, "actual": first_paid or 0},
        {"label": "Case study public-ready", "target": 1, "actual": case_studies or 0},
    ]
    overall_pass = all(c["actual"] >= c["target"] for c in criteria)

    return {
        "cohort_id": cohort_id,
        "total_students_non_demo": total,
        "criteria": criteria,
        "overall_pass": overall_pass,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/sdl/admin/validation/dashboard", response_class=HTMLResponse)
async def validation_dashboard_html(
    key: str = Query(...),
    cohort_id: str = Query("cohort_1"),
    pool: asyncpg.Pool = Depends(get_pool),
) -> HTMLResponse:
    _check_admin(key)
    data = await validation_status(key=key, cohort_id=cohort_id, pool=pool)
    rows = "".join(
        f'<tr><td>{c["label"]}</td><td>{c["actual"]}</td><td>{c["target"]}</td>'
        f'<td>{"✓" if c["actual"] >= c["target"] else "✗"}</td></tr>'
        for c in data["criteria"]
    )
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><title>Validation · {cohort_id}</title>
<style>body{{font-family:system-ui;padding:30px;background:#fafaf7;color:#0a0a0a}}
h1{{color:#d63031}}table{{border-collapse:collapse;width:100%;background:#fff;font-size:15px;max-width:680px;margin:20px 0}}
th,td{{padding:14px 18px;border-bottom:1px solid #eee;text-align:left}}
th{{background:#0a0a0a;color:#fff;font-size:12px;letter-spacing:1px;text-transform:uppercase}}
.pass{{color:#0a8700;font-weight:800}}.fail{{color:#d63031;font-weight:800}}
.overall{{font-size:24px;margin:20px 0;padding:20px;background:{'#e9f9e9' if data['overall_pass'] else '#fff5f5'};border-left:6px solid {'#0a8700' if data['overall_pass'] else '#d63031'};border-radius:0 12px 12px 0}}</style></head>
<body><h1>Validation Dashboard · {cohort_id}</h1>
<div class="overall">{'✓ All criteria PASS' if data['overall_pass'] else '✗ Chưa đủ criteria'} · Total students {data['total_students_non_demo']}</div>
<table><thead><tr><th>Criteria</th><th>Actual</th><th>Target</th><th>Status</th></tr></thead>
<tbody>{rows}</tbody></table>
<p style="margin-top:30px;color:#666;font-size:13px">Checked at {data['checked_at']}</p>
<p><a href="/sdl/admin/dashboard?key={key}" style="color:#d63031">← Admin home</a> · <a href="/sdl/admin/founder-dashboard?key={key}" style="color:#d63031">Founder Dashboard →</a></p>
</body></html>""")


# ============================================================
# 4. FEEDBACK MODULE
# ============================================================
class FeedbackCreate(BaseModel):
    student_id: UUID
    target_type: str = Field(..., examples=["canonical_file", "gate", "level", "overall_nps", "webinar_session"])
    target_key: str | None = None
    rating: int = Field(..., ge=1, le=10)
    comment: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


@router.post("/sdl/feedback", status_code=201)
async def submit_feedback(body: FeedbackCreate, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    async with pool.acquire() as conn:
        fid = await conn.fetchval(
            """
            INSERT INTO breakoutos.feedback
              (student_id, target_type, target_key, rating, comment, metadata_json)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            RETURNING id
            """,
            body.student_id, body.target_type, body.target_key, body.rating,
            body.comment, json.dumps(body.metadata_json),
        )
        # Telegram alert Anna real-time
        try:
            from routes.telegram_alert import alert_feedback
            meta = await conn.fetchrow(
                "SELECT email, full_name FROM breakoutos.students WHERE id=$1", body.student_id,
            )
            if meta:
                alert_feedback(
                    str(body.student_id), body.target_type, body.rating,
                    body.comment or "", meta["email"] or "", meta["full_name"] or "",
                )
        except Exception:
            pass
    return {"feedback_id": fid}


@router.get("/sdl/admin/feedback")
async def admin_feedback_list(
    key: str = Query(...),
    target_type: str | None = None,
    cohort_id: str | None = None,
    limit: int = Query(100, le=500),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    _check_admin(key)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT f.id, f.student_id, f.target_type, f.target_key, f.rating,
                   f.comment, f.created_at, s.cohort_id, s.email
            FROM breakoutos.feedback f
            JOIN breakoutos.students s ON s.id = f.student_id
            WHERE ($1::text IS NULL OR f.target_type = $1)
              AND ($2::text IS NULL OR s.cohort_id = $2)
            ORDER BY f.created_at DESC LIMIT $3
            """,
            target_type, cohort_id, limit,
        )
        # NPS calculation: rating 9-10 promoter, 7-8 passive, 1-6 detractor
        nps_rows = await conn.fetch(
            """
            SELECT rating, count(*) AS cnt FROM breakoutos.feedback
            WHERE target_type='overall_nps'
              AND ($1::text IS NULL OR student_id IN
                   (SELECT id FROM breakoutos.students WHERE cohort_id=$1))
            GROUP BY rating
            """,
            cohort_id,
        )
        total_nps = sum(r["cnt"] for r in nps_rows)
        promoters = sum(r["cnt"] for r in nps_rows if r["rating"] >= 9)
        detractors = sum(r["cnt"] for r in nps_rows if r["rating"] <= 6)
        nps = round((promoters - detractors) / total_nps * 100) if total_nps else None
    return {
        "feedback_count": len(rows),
        "feedback": [dict(r) for r in rows],
        "nps": {"score": nps, "total_responses": total_nps,
                "promoters": promoters,
                "detractors": detractors} if total_nps else {"score": None, "total_responses": 0},
    }


# ============================================================
# 5. FOUNDER DASHBOARD (Anna's overview)
# ============================================================
@router.get("/sdl/admin/founder-dashboard", response_class=HTMLResponse)
async def founder_dashboard(
    key: str = Query(...),
    cohort_id: str = Query("cohort_1"),
    pool: asyncpg.Pool = Depends(get_pool),
) -> HTMLResponse:
    _check_admin(key)
    async with pool.acquire() as conn:
        # Active students
        total = await conn.fetchval(
            "SELECT count(*) FROM breakoutos.students WHERE cohort_id=$1 "
            "AND (metadata_json->>'is_demo' IS NULL OR metadata_json->>'is_demo' = 'false')",
            cohort_id,
        )
        # Gate completion per gate
        gate_stats = await conn.fetch(
            """
            SELECT gate_key, count(DISTINCT student_id) AS n
            FROM breakoutos.canonical_locks cl
            JOIN breakoutos.students s ON s.id=cl.student_id
            WHERE s.cohort_id=$1 AND cl.unlocked_at IS NULL
              AND (s.metadata_json->>'is_demo' IS NULL OR s.metadata_json->>'is_demo' = 'false')
            GROUP BY gate_key
            ORDER BY gate_key
            """,
            cohort_id,
        )
        # Avg Freedom Score baseline vs latest
        avg_baseline = await conn.fetchval(
            """
            SELECT avg(total_score) FROM breakoutos.founder_freedom_score f
            JOIN breakoutos.students s ON s.id=f.student_id
            WHERE s.cohort_id=$1 AND f.source='self_baseline'
            """,
            cohort_id,
        )
        avg_current = await conn.fetchval(
            """
            SELECT avg(total_score) FROM breakoutos.v_freedom_score_latest v
            JOIN breakoutos.students s ON s.id=v.student_id
            WHERE s.cohort_id=$1
            """,
            cohort_id,
        )
        # Stuck > 48h
        stuck = await conn.fetch(
            """
            SELECT id, email, current_level, current_gate, updated_at
            FROM breakoutos.students
            WHERE cohort_id=$1 AND current_gate LIKE '%pending'
              AND updated_at < now() - INTERVAL '48 hours'
            ORDER BY updated_at ASC LIMIT 10
            """,
            cohort_id,
        )
        # No baseline (block at T0)
        no_baseline = await conn.fetchval(
            """
            SELECT count(*) FROM breakoutos.students s
            WHERE s.cohort_id=$1
              AND NOT EXISTS (SELECT 1 FROM breakoutos.founder_freedom_score f
                              WHERE f.student_id=s.id AND f.source='self_baseline')
            """,
            cohort_id,
        )
        # Recent errors 24h
        recent_errors = await conn.fetchval(
            "SELECT count(*) FROM breakoutos.system_errors "
            "WHERE occurred_at > now() - INTERVAL '24 hours'",
        )
        # NPS rolling
        nps_rows = await conn.fetch(
            """
            SELECT rating, count(*) AS cnt FROM breakoutos.feedback f
            JOIN breakoutos.students s ON s.id=f.student_id
            WHERE f.target_type='overall_nps' AND s.cohort_id=$1
            GROUP BY rating
            """,
            cohort_id,
        )
        total_nps = sum(r["cnt"] for r in nps_rows)
        promoters = sum(r["cnt"] for r in nps_rows if r["rating"] >= 9)
        detractors = sum(r["cnt"] for r in nps_rows if r["rating"] <= 6)
        nps = round((promoters - detractors) / total_nps * 100) if total_nps else None

    gate_html = "".join(
        f'<li>{g["gate_key"]} · <strong>{g["n"]}</strong> students locked</li>'
        for g in gate_stats
    ) or '<li>Chưa có gate nào lock</li>'

    stuck_html = "".join(
        f'<tr><td><code>{str(r["id"])[:8]}…</code></td><td>{r["email"]}</td>'
        f'<td>L{r["current_level"]}</td><td>{r["current_gate"]}</td>'
        f'<td>{(datetime.utcnow() - r["updated_at"].replace(tzinfo=None)).days}d</td></tr>'
        for r in stuck
    ) or '<tr><td colspan="5" style="text-align:center;color:#888">Không có student stuck</td></tr>'

    baseline_str = f"{avg_baseline:.1f}" if avg_baseline else "—"
    current_str = f"{avg_current:.1f}" if avg_current else "—"
    delta = (avg_current - avg_baseline) if (avg_baseline and avg_current) else 0

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><title>Founder Dashboard · Anna</title>
<style>body{{font-family:system-ui;padding:30px 20px;background:#fafaf7;color:#0a0a0a;max-width:1100px;margin:0 auto}}
h1{{color:#d63031;font-size:32px}}h2{{margin-top:32px;font-size:20px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0}}
.kpi{{background:#fff;border:1px solid #e5dfd0;border-radius:14px;padding:22px;text-align:center}}
.kpi-label{{font-size:12px;color:#5a5453;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:8px;font-weight:700}}
.kpi-value{{font-size:38px;font-weight:800;color:#d63031;line-height:1}}
.kpi-meta{{font-size:13px;color:#5a5453;margin-top:6px}}
table{{border-collapse:collapse;width:100%;background:#fff;font-size:14px;border-radius:12px;overflow:hidden}}
th,td{{padding:12px 16px;border-bottom:1px solid #eee;text-align:left}}
th{{background:#0a0a0a;color:#fff;font-size:11px;letter-spacing:1px;text-transform:uppercase}}
ul{{list-style:none;padding:0}}li{{background:#fff;padding:12px 18px;border-radius:8px;margin-bottom:6px;font-family:monospace;font-size:13px}}
.nav{{margin:30px 0;display:flex;gap:14px;flex-wrap:wrap}}
.nav a{{padding:10px 18px;background:#0a0a0a;color:#fff;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600}}
.alert{{background:#fff5f5;border-left:4px solid #d63031;padding:14px 18px;border-radius:0 10px 10px 0;margin:10px 0}}
</style></head><body>
<h1>Founder Dashboard · {cohort_id}</h1>

<div class="kpis">
  <div class="kpi"><div class="kpi-label">Active</div><div class="kpi-value">{total or 0}</div><div class="kpi-meta">students không demo</div></div>
  <div class="kpi"><div class="kpi-label">FS Baseline</div><div class="kpi-value">{baseline_str}</div><div class="kpi-meta">avg /100</div></div>
  <div class="kpi"><div class="kpi-label">FS Current</div><div class="kpi-value">{current_str}</div><div class="kpi-meta">{'+' if delta > 0 else ''}{delta:.1f} Δ</div></div>
  <div class="kpi"><div class="kpi-label">NPS</div><div class="kpi-value">{nps if nps is not None else '—'}</div><div class="kpi-meta">{total_nps} responses</div></div>
</div>

{f'<div class="alert">⚠️ {no_baseline} student chưa fill baseline T0 · {recent_errors} error 24h</div>' if (no_baseline or recent_errors) else ''}

<h2>Gate completion</h2>
<ul>{gate_html}</ul>

<h2>Students stuck >48h</h2>
<table><thead><tr><th>ID</th><th>Email</th><th>Level</th><th>Gate</th><th>Stuck</th></tr></thead>
<tbody>{stuck_html}</tbody></table>

<div class="nav">
  <a href="/sdl/admin/dashboard?key={key}">All students</a>
  <a href="/sdl/admin/validation/dashboard?key={key}">Validation criteria</a>
  <a href="/sdl/admin/blocked?key={key}">Blocked students</a>
  <a href="/sdl/admin/events?key={key}&hours=24">Events 24h</a>
  <a href="/sdl/admin/feedback?key={key}">Feedback + NPS</a>
  <a href="/sdl/admin/errors?key={key}">System errors</a>
</div>
</body></html>""")


# ============================================================
# 6. ERROR MONITORING
# ============================================================
async def log_system_error(
    pool: asyncpg.Pool,
    route: str, method: str, status_code: int,
    error_type: str, error_message: str, traceback_str: str = "",
    request_body: dict | None = None, student_id: UUID | None = None,
    user_agent: str = "", ip_address: str = "",
) -> int | None:
    """Helper to log errors from any route. Called by middleware."""
    try:
        async with pool.acquire() as conn:
            return await conn.fetchval(
                """
                INSERT INTO breakoutos.system_errors
                  (student_id, route, method, status_code, error_type, error_message,
                   traceback, request_body, user_agent, ip_address)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10)
                RETURNING id
                """,
                student_id, route, method, status_code, error_type, error_message,
                traceback_str[:5000],
                json.dumps(request_body, ensure_ascii=False, default=str) if request_body else None,
                user_agent[:300], ip_address[:64],
            )
    except Exception as exc:
        log.exception("log_system_error itself failed: %s", exc)
        return None


@router.get("/sdl/admin/errors")
async def admin_errors_list(
    key: str = Query(...),
    hours: int = Query(24, ge=1, le=720),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    _check_admin(key)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, occurred_at, route, method, status_code, error_type,
                   substring(error_message for 200) AS error_message, notified_telegram
            FROM breakoutos.system_errors
            WHERE occurred_at > now() - ($1 || ' hours')::interval
            ORDER BY occurred_at DESC LIMIT 200
            """,
            str(hours),
        )
        by_route = await conn.fetch(
            """
            SELECT route, count(*) AS n, max(occurred_at) AS last_at
            FROM breakoutos.system_errors
            WHERE occurred_at > now() - ($1 || ' hours')::interval
            GROUP BY route ORDER BY n DESC LIMIT 20
            """,
            str(hours),
        )
    return {
        "errors": [dict(r) for r in rows],
        "errors_by_route": [dict(r) for r in by_route],
        "total": len(rows),
    }
