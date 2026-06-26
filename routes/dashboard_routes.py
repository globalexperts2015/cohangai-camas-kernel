"""Admin + Student dashboard + Markdown vault export."""
from __future__ import annotations

import io
import json
import logging
import os
import zipfile
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from routes._auth import request_signature, require_student_signature, sign_student
from routes.sdl_routes import get_pool


log = logging.getLogger("camas.dashboard")
router = APIRouter(tags=["dashboard"])

ADMIN_KEY = os.environ.get("BREAKOUTOS_ADMIN_KEY", "")
if not ADMIN_KEY:
    log.warning("BREAKOUTOS_ADMIN_KEY not set! Admin routes will reject all.")


def _check_admin(key: str | None) -> None:
    if not key or key != ADMIN_KEY:
        raise HTTPException(401, "Invalid admin key")


# ============================================================
# Admin: list students + cohort filter + gate status
# ============================================================
@router.get("/sdl/admin/students")
async def admin_list_students(
    key: str = Query(...),
    cohort_id: str | None = None,
    status: str | None = None,
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[dict]:
    _check_admin(key)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.person_id, s.program_id, s.cohort_id, s.status,
                   s.current_level, s.current_gate, s.archetype, s.created_at,
                   (SELECT count(*) FROM breakoutos.canonical_files cf
                      WHERE cf.student_id=s.id AND cf.status IN ('reviewed','locked')) AS canonical_done,
                   (SELECT total_score FROM breakoutos.v_freedom_score_latest fs
                      WHERE fs.student_id=s.id) AS freedom_score,
                   (SELECT count(*) FROM breakoutos.canonical_locks cl
                      WHERE cl.student_id=s.id AND cl.unlocked_at IS NULL) AS gates_locked
            FROM breakoutos.students s
            WHERE ($1::text IS NULL OR s.cohort_id=$1)
              AND ($2::text IS NULL OR s.status=$2)
            ORDER BY s.created_at DESC
            """,
            cohort_id, status,
        )
        return [dict(r) for r in rows]


@router.get("/sdl/admin/blocked")
async def admin_blocked_students(
    key: str = Query(...),
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Find students blocked by missing baseline OR failed gates."""
    _check_admin(key)
    async with pool.acquire() as conn:
        no_baseline = await conn.fetch(
            """
            SELECT s.id, s.cohort_id, s.created_at FROM breakoutos.students s
            WHERE NOT EXISTS (
                SELECT 1 FROM breakoutos.founder_freedom_score f
                WHERE f.student_id=s.id AND f.source='self_baseline'
            )
            """,
        )
        stuck = await conn.fetch(
            """
            SELECT s.id, s.cohort_id, s.current_level, s.current_gate, s.updated_at
            FROM breakoutos.students s
            WHERE s.current_gate LIKE '%pending'
              AND s.updated_at < now() - INTERVAL '24 hours'
            """,
        )
    return {
        "no_baseline_count": len(no_baseline),
        "no_baseline": [dict(r) for r in no_baseline],
        "stuck_pending_24h_count": len(stuck),
        "stuck_pending_24h": [dict(r) for r in stuck],
    }


@router.get("/sdl/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard_html(
    key: str = Query(...),
    pool: asyncpg.Pool = Depends(get_pool),
) -> HTMLResponse:
    _check_admin(key)
    async with pool.acquire() as conn:
        students = await conn.fetch(
            """
            SELECT s.id, s.cohort_id, s.current_level, s.current_gate, s.status,
                   (SELECT total_score FROM breakoutos.v_freedom_score_latest fs
                      WHERE fs.student_id=s.id) AS freedom_score
            FROM breakoutos.students s
            ORDER BY s.created_at DESC LIMIT 100
            """,
        )
    rows_html = "".join(
        f'<tr><td><a href="/sdl/student/{r["id"]}/dashboard?key={key}">{str(r["id"])[:8]}…</a></td>'
        f'<td>{r["cohort_id"]}</td>'
        f'<td>L{r["current_level"]}</td>'
        f'<td>{r["current_gate"] or "-"}</td>'
        f'<td>{r["freedom_score"] or "-"}</td>'
        f'<td>{r["status"]}</td></tr>'
        for r in students
    )
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><title>BreakoutOS Admin</title>
<style>body{{font-family:system-ui;padding:30px;background:#fafaf7}}
h1{{color:#d63031}}table{{border-collapse:collapse;width:100%;background:#fff;font-size:14px}}
th,td{{padding:10px 14px;border-bottom:1px solid #eee;text-align:left}}
th{{background:#0a0a0a;color:#fff;font-size:12px;letter-spacing:1px;text-transform:uppercase}}
a{{color:#d63031}}.tag{{padding:2px 8px;border-radius:6px;background:#fff5f5;color:#d63031;font-size:11px}}</style></head>
<body><h1>BreakoutOS Admin · {len(students)} student</h1>
<table><thead><tr><th>ID</th><th>Cohort</th><th>Level</th><th>Gate</th><th>Freedom</th><th>Status</th></tr></thead>
<tbody>{rows_html}</tbody></table></body></html>""")


# ============================================================
# Student dashboard
# ============================================================
@router.get("/sdl/student/{student_id}/dashboard", response_class=HTMLResponse)
async def student_dashboard(
    student_id: UUID, request: Request, key: str | None = None, sig: str = "",
    pool: asyncpg.Pool = Depends(get_pool),
) -> HTMLResponse:
    """Student personal dashboard. Signed student link, optional admin key bypass."""
    if key:
        _check_admin(key)
    else:
        require_student_signature(str(student_id), request_signature(request, sig))

    async with pool.acquire() as conn:
        student = await conn.fetchrow(
            "SELECT * FROM breakoutos.students WHERE id=$1", student_id,
        )
        if not student:
            raise HTTPException(404, "Student not found")
        baseline = await conn.fetchrow(
            "SELECT baseline_at, baseline_score FROM breakoutos.v_freedom_score_baseline "
            "WHERE student_id=$1", student_id,
        )
        latest_fs = await conn.fetchrow(
            "SELECT total_score, measured_at FROM breakoutos.v_freedom_score_latest "
            "WHERE student_id=$1", student_id,
        )
        canonical_count = await conn.fetchval(
            "SELECT count(DISTINCT file_key) FROM breakoutos.canonical_files "
            "WHERE student_id=$1 AND status IN ('reviewed','locked')",
            student_id,
        )
        gates = await conn.fetch(
            """
            SELECT gate_key, lock_status, locked_at
            FROM breakoutos.canonical_locks
            WHERE student_id=$1 AND unlocked_at IS NULL
            ORDER BY locked_at ASC
            """,
            student_id,
        )

    signature = sign_student(str(student_id))
    baseline_html = ""
    if baseline:
        baseline_html = (
            f'<div class="kpi"><div class="kpi-label">Điểm T0 ban đầu</div>'
            f'<div class="kpi-value">{baseline["baseline_score"]}</div>'
            f'<div class="kpi-meta">/ 100</div></div>'
        )
    else:
        baseline_html = (
            f'<div class="kpi alert"><div class="kpi-label">⚠️ Chưa đo T0</div>'
            f'<a href="/foundation/baseline?student={student_id}&sig={signature}" '
            f'class="btn">Đo ngay</a></div>'
        )

    latest_html = ""
    if latest_fs:
        latest_html = (
            f'<div class="kpi"><div class="kpi-label">Điểm hiện tại</div>'
            f'<div class="kpi-value">{latest_fs["total_score"]}</div>'
            f'<div class="kpi-meta">/ 100</div></div>'
        )

    gates_html = "".join(
        f'<li class="{g["lock_status"]}">{g["gate_key"]} · '
        f'{g["lock_status"].upper()} · {g["locked_at"].strftime("%Y-%m-%d")}</li>'
        for g in gates
    ) or '<li class="empty">Chưa có gate nào lock</li>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<title>Bảng điều khiển · BreakoutOS</title>
<style>
body{{font-family:'Be Vietnam Pro',system-ui;background:#fafaf7;padding:30px 20px;color:#0a0a0a}}
.container{{max-width:760px;margin:0 auto}}
h1{{font-size:32px;color:#d63031;margin-bottom:6px}}
h2{{font-size:22px;margin-top:30px;margin-bottom:14px}}
.meta{{color:#5a5453;font-size:14px;margin-bottom:24px}}
.kpis{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:24px}}
.kpi{{background:#fff;border:1px solid #e5dfd0;border-radius:14px;padding:20px}}
.kpi.alert{{border-color:#d63031;background:#fff5f5}}
.kpi-label{{font-size:13px;color:#5a5453;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px}}
.kpi-value{{font-size:36px;font-weight:800;color:#d63031;line-height:1}}
.kpi-meta{{font-size:13px;color:#5a5453;margin-top:4px}}
.btn{{display:inline-block;background:#d63031;color:#fff;padding:8px 16px;border-radius:8px;
  text-decoration:none;font-weight:700;font-size:14px;margin-top:8px}}
ul{{list-style:none;padding:0}}
li{{background:#fff;padding:14px 18px;border-radius:10px;margin-bottom:8px;font-family:monospace;font-size:13px}}
li.hard{{border-left:4px solid #d63031}}
li.soft{{border-left:4px solid #f4a261}}
li.empty{{color:#888;font-style:italic}}
.actions{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:20px}}
.action-link{{background:#0a0a0a;color:#fff;padding:14px;border-radius:10px;text-align:center;text-decoration:none;font-size:14px}}
</style></head><body>
<div class="container">
<h1>Bảng điều khiển</h1>
<p class="meta">Cohort {student["cohort_id"]} · Tầng {student["current_level"]} · {student["current_gate"] or "Chưa bắt đầu"}</p>

<div class="kpis">
  {baseline_html}
  {latest_html or '<div class="kpi"><div class="kpi-label">Điểm hiện tại</div><div class="kpi-value">-</div></div>'}
  <div class="kpi"><div class="kpi-label">Canonical hoàn thành</div><div class="kpi-value">{canonical_count or 0}</div><div class="kpi-meta">/ 47 file</div></div>
</div>

<h2>Gate đã pass</h2>
<ul>{gates_html}</ul>

<h2>Hành động nhanh</h2>
<div class="actions">
  <a href="/foundation/l1?student={student_id}&sig={signature}" class="action-link">L1 Founder OS</a>
  <a href="/foundation/l2?student={student_id}&sig={signature}" class="action-link">L2 Customer Intel</a>
  <a href="/cohort/chon-module/?student_id={student_id}&sig={signature}" class="action-link">Module CHỌN</a>
  <a href="/sdl/students/{student_id}/vault/export.zip?sig={signature}" class="action-link">Tải vault .zip</a>
  <a href="/sdl/students/{student_id}/output/L1?sig={signature}" class="action-link">Output L1 Day 1</a>
  <a href="/sdl/students/{student_id}/output/L2?sig={signature}" class="action-link">Output L2 Day 2</a>
</div>
</div>
</body></html>""")


# ============================================================
# Markdown vault export
# ============================================================
@router.get("/sdl/students/{student_id}/vault/export.zip")
async def export_vault_zip(
    student_id: UUID, pool: asyncpg.Pool = Depends(get_pool),
):
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (file_key) level, file_key, file_name, markdown_content, tier
            FROM breakoutos.canonical_files
            WHERE student_id=$1
            ORDER BY file_key, version DESC
            """,
            student_id,
        )

    AI_CONTEXT_KEYS = {"founder-dna", "brand-voice", "ai-instructions"}
    CANONICAL_OUTPUTS_KEYS = {
        "final-vision", "final-founder-identity", "final-customer-direction",
        "final-statement-mot-dong", "final-offer",
    }
    folder_map = {
        1: "01 Founder OS",
        2: "02 Customer Origin",
        3: "03 Value Proposition OS",
        4: "04 Business Operating OS",
        5: "05 Revenue Growth OS",
        6: "06a Founder Freedom OS",
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # README
        zf.writestr(
            "README.md",
            f"# Bộ Não Số · Student {student_id}\n\n"
            f"Exported from BreakoutOS at {__import__('datetime').datetime.utcnow().isoformat()}Z\n\n"
            f"Total files: {len(rows)}\n\n"
            f"## Folder structure\n"
            f"- 01 Founder OS\n- 02 Customer Origin\n- 03 Value Proposition OS\n"
            f"- 04 Business Operating OS\n- 05 Revenue Growth OS\n"
            f"- 06a Founder Freedom OS\n- 04 AI Context\n- 05 Canonical Outputs\n"
        )
        for r in rows:
            fkey = r["file_key"]
            if fkey in AI_CONTEXT_KEYS:
                folder = "04 AI Context"
            elif fkey in CANONICAL_OUTPUTS_KEYS:
                folder = "05 Canonical Outputs"
            else:
                folder = folder_map.get(r["level"], "00 Other")
            path = f"{folder}/{r['file_name']}"
            zf.writestr(path, r["markdown_content"] or "")

    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="vault-{student_id}.zip"'},
    )


# ============================================================
# Output pages for Day 1 + Day 2 webinar
# ============================================================
@router.get("/sdl/students/{student_id}/output/{level}", response_class=HTMLResponse)
async def output_page(
    student_id: UUID, level: str, request: Request,
    sig: str = "",
    pool: asyncpg.Pool = Depends(get_pool),
) -> HTMLResponse:
    """Output page với review UI: duyệt từng file + duyệt tất cả + khóa Gate."""
    require_student_signature(str(student_id), request_signature(request, sig))
    level_num = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5, "L6a": 6}.get(level)
    if not level_num:
        raise HTTPException(404, "Unknown level")

    # Gate config per level
    gate_config = {
        "L1": {"gate_key": "gate_1_founder", "next_level": "L2", "next_path": "/foundation/l2",
               "expected_count": 8, "title": "Founder OS"},
        "L2": {"gate_key": "gate_2_customer_soft", "next_level": "L3", "next_path": "/foundation/l3",
               "expected_count": 11, "title": "Customer Intelligence"},
    }
    cfg = gate_config.get(level, {})

    async with pool.acquire() as conn:
        files = await conn.fetch(
            """
            SELECT DISTINCT ON (file_key) file_key, markdown_content, tier, status, version
            FROM breakoutos.canonical_files
            WHERE student_id=$1 AND level=$2
            ORDER BY file_key, version DESC
            """,
            student_id, level_num,
        )

    if not files:
        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><title>{level} chưa có output</title>
<style>body{{font-family:'Be Vietnam Pro',system-ui;background:#fafaf7;padding:60px 20px;text-align:center;color:#0a0a0a}}
h1{{color:#d63031}}p{{color:#5a5453}}</style></head>
<body><h1>{level} chưa có output</h1>
<p>Bạn cần hoàn thành intake form trước.</p>
<p><a href="/foundation/{level.lower()}?student={student_id}&sig={sig}" style="background:#d63031;color:#fff;padding:14px 22px;border-radius:10px;text-decoration:none;font-weight:700">Mở {level} intake form</a></p>
</body></html>""", status_code=404)

    if level == "L1":
        expected_files = [
            ("life-mission", "A"), ("vision-statement", "A"),
            ("founder-identity", "A"), ("decision-principles", "A"),
            ("anti-vision", "A"), ("why-statement", "B"),
            ("founder-assets", "B"), ("founder-story", "B"),
        ]
        existing = {f["file_key"]: dict(f) for f in files}
        files = [
            existing.get(key, {
                "file_key": key,
                "markdown_content": (
                    "File này chưa được tạo thành công. "
                    "Bấm “Tạo lại file” để hệ thống xử lý."
                ),
                "tier": tier,
                "status": "missing",
                "version": 0,
            })
            for key, tier in expected_files
        ]

    # Build file cards với review controls
    reviewed_count = sum(1 for f in files if f["status"] in ("reviewed", "locked"))
    total_count = len(files)
    all_reviewed = reviewed_count == total_count and total_count == cfg.get("expected_count", total_count)
    any_locked = any(f["status"] == "locked" for f in files)

    files_html = ""
    for f in files:
        is_done = f["status"] in ("reviewed", "locked")
        is_locked = f["status"] == "locked"
        is_error = f["status"] in ("generation_failed", "missing")
        if is_error and level == "L1" and f["tier"] == "B":
            btn = (
                f'<button class="retry-btn" data-file-key="{f["file_key"]}">'
                f'Tạo lại file</button>'
            )
        elif is_locked:
            btn = ""
        else:
            btn = (
                f'<button class="approve-btn" data-file-key="{f["file_key"]}" '
                f'{("disabled" if is_done else "")}>'
                f'{"✓ Đã duyệt" if is_done else "Duyệt file này"}</button>'
            )
        status_color = "ok" if is_done else ("err" if is_error else "pending")
        content = (f["markdown_content"] or "(file rỗng, AI chưa sinh xong)")[:8000]
        files_html += (
            f'<details class="file-card tier-{f["tier"]} status-{status_color}"><summary>'
            f'<span class="tier-badge">{f["tier"]}</span> '
            f'<strong>{f["file_key"]}</strong> '
            f'<span class="status status-{status_color}">{f["status"]}</span></summary>'
            f'<pre>{content}</pre>'
            f'<div class="file-actions">{btn}</div>'
            f'</details>'
        )

    gate_btn_state = ""
    if any_locked:
        gate_btn_state = '<div class="gate-locked">🔒 Gate đã khóa. Bạn có thể tiếp tục bước sau.</div>'
        if level == "L2":
            gate_btn_state += (
                f'<a class="discovery-btn" href="/sdl/students/{student_id}/discovery/report?sig={sig}">'
                f'🚀 Khám phá cơ hội kinh doanh (Day 3 Discovery Engine)</a>'
                f'<form method="post" action="/sdl/discovery/run?student_id={student_id}" '
                f'style="margin-top:10px"><button type="submit" class="trigger-btn">'
                f'Tạo Discovery Report mới (đợi 30-45s)</button></form>'
            )
        if cfg.get("next_path"):
            gate_btn_state += f'<a class="next-btn" href="{cfg["next_path"]}?student={student_id}&sig={sig}">Mở {cfg["next_level"]} →</a>'
    elif cfg.get("gate_key"):
        expected = cfg.get("expected_count", total_count)
        # Học viên KHÔNG tự khóa gate / tự lên cấp. Anna duyệt qua link admin
        # trong alert Telegram. (Anna 2026-06-25)
        wait_css = ("background:#eef7f0;border:1px solid #cde8d4;color:#1e6b3a;"
                    "padding:14px 18px;border-radius:10px;font-weight:600;text-align:center")
        if all_reviewed:
            gate_btn_state = (f'<div style="{wait_css}">✅ Hồ sơ của bạn đã đủ. '
                              f'Hằng sẽ xem lại và mở tầng tiếp theo cho bạn.</div>')
        else:
            gate_btn_state = (f'<div style="{wait_css}">Đang hoàn thiện hồ sơ '
                              f'({reviewed_count}/{expected} file). Khi đủ, Hằng sẽ duyệt '
                              f'và mở tầng tiếp theo.</div>')

    bulk_btn = (
        '<button id="approve-all-btn">Duyệt tất cả file còn lại</button>'
        if reviewed_count < total_count and not any_locked else ""
    )

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>{level} · {cfg.get("title", "Output")} · BreakoutOS</title>
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{{--red:#d63031;--ok:#27ae60;--warn:#f4a261;--err:#c0392b}}
*{{box-sizing:border-box;margin:0;padding:0;font-family:'Be Vietnam Pro',system-ui}}
body{{background:#fafaf7;padding:30px 20px;color:#0a0a0a;line-height:1.65}}
.container{{max-width:880px;margin:0 auto}}
.header{{margin-bottom:24px}}
h1{{color:var(--red);font-size:30px;font-weight:800;margin-bottom:8px}}
.progress{{background:#fff;border:1px solid #e5dfd0;border-radius:12px;padding:14px 20px;margin-bottom:20px;display:flex;align-items:center;gap:14px}}
.progress-bar{{flex:1;height:10px;background:#e5dfd0;border-radius:999px;overflow:hidden}}
.progress-fill{{height:100%;background:var(--ok);transition:width 0.3s}}
.progress-text{{font-weight:700;font-size:14px}}
.file-card{{background:#fff;border:1.5px solid #e5dfd0;border-radius:12px;padding:18px 22px;margin-bottom:12px}}
.file-card[open]{{border-color:var(--red)}}
.file-card.status-ok{{border-left:4px solid var(--ok)}}
.file-card.status-pending{{border-left:4px solid var(--warn)}}
.file-card.status-err{{border-left:4px solid var(--err)}}
summary{{cursor:pointer;font-size:16px;list-style:none;display:flex;align-items:center;gap:10px}}
summary::-webkit-details-marker{{display:none}}
.tier-badge{{display:inline-block;background:var(--red);color:#fff;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:800}}
.tier-B .tier-badge{{background:var(--warn)}}.tier-C .tier-badge{{background:#999}}
.status{{margin-left:auto;font-size:12px;font-weight:700;padding:4px 10px;border-radius:6px;background:#f0f0f0;color:#666}}
.status-ok{{background:#d4f1de;color:#1e7e34}}
.status-err{{background:#f8d7da;color:#721c24}}
.status-pending{{background:#fff3cd;color:#856404}}
pre{{margin-top:14px;background:#0a0a0a;color:#fff;padding:16px;border-radius:8px;overflow-x:auto;font-size:13px;white-space:pre-wrap;line-height:1.55}}
.file-actions{{margin-top:14px}}
.approve-btn{{background:var(--ok);color:#fff;border:none;padding:10px 22px;border-radius:8px;font-weight:700;cursor:pointer;font-size:14px}}
.approve-btn:disabled{{background:#bbb;cursor:not-allowed}}
.approve-btn:hover:not(:disabled){{background:#218838}}
.retry-btn{{background:var(--red);color:#fff;border:none;padding:10px 22px;border-radius:8px;font-weight:700;cursor:pointer;font-size:14px}}
.retry-btn:disabled{{background:#bbb;cursor:not-allowed}}
#approve-all-btn{{background:var(--warn);color:#fff;border:none;padding:14px 28px;border-radius:10px;font-weight:700;cursor:pointer;font-size:15px;width:100%;margin-bottom:14px}}
#approve-all-btn:hover{{background:#e8941c}}
#lock-gate-btn{{background:var(--red);color:#fff;border:none;padding:18px 28px;border-radius:12px;font-weight:800;cursor:pointer;font-size:17px;width:100%;box-shadow:0 6px 20px rgba(214,48,49,0.3)}}
#lock-gate-btn:disabled{{background:#ccc;box-shadow:none;cursor:not-allowed}}
#lock-gate-btn:hover:not(:disabled){{background:#b71c1c}}
.gate-locked{{background:#d4f1de;border:2px solid var(--ok);border-radius:12px;padding:18px 22px;text-align:center;font-weight:700;color:#1e7e34;margin-bottom:14px}}
.next-btn{{display:block;text-align:center;background:var(--red);color:#fff;padding:18px;border-radius:12px;text-decoration:none;font-weight:800;font-size:16px;margin-bottom:14px}}
.discovery-btn{{display:block;text-align:center;background:linear-gradient(135deg,#0a0a0a,#2d2d2d);color:#fff;padding:22px;border-radius:14px;text-decoration:none;font-weight:800;font-size:18px;margin-bottom:10px;box-shadow:0 6px 20px rgba(0,0,0,0.25)}}
.discovery-btn:hover{{background:linear-gradient(135deg,#1a1a1a,#3d3d3d)}}
.trigger-btn{{display:block;width:100%;background:transparent;color:var(--red);border:2px solid var(--red);padding:14px;border-radius:10px;font-weight:700;font-size:14px;cursor:pointer;font-family:inherit}}
.trigger-btn:hover{{background:var(--red);color:#fff}}
.zip-link{{display:inline-block;background:#0a0a0a;color:#fff;padding:12px 22px;border-radius:10px;text-decoration:none;font-weight:700;font-size:14px;margin-top:20px}}
.toast{{position:fixed;bottom:20px;right:20px;background:#0a0a0a;color:#fff;padding:14px 22px;border-radius:10px;font-weight:700;opacity:0;transition:opacity 0.3s;z-index:1000}}
.toast.show{{opacity:1}}
</style></head>
<body><div class="container">

<div class="header">
  <h1>{level} · {cfg.get("title", "Output")}</h1>
  <p style="color:#5a5453">Xem lại {total_count} canonical file. File thiếu phải được tạo lại, sau đó duyệt đủ để mở Gate.</p>
</div>

<div class="progress">
  <span class="progress-text" id="progress-text">{reviewed_count}/{total_count} đã duyệt</span>
  <div class="progress-bar"><div class="progress-fill" id="progress-fill" style="width:{int(reviewed_count*100/total_count) if total_count else 0}%"></div></div>
</div>

{bulk_btn}

{files_html}

<div style="margin-top:24px">{gate_btn_state}</div>

<p><a href="/sdl/students/{student_id}/vault/export.zip" class="zip-link">⬇ Tải vault .zip</a></p>

</div>

<div class="toast" id="toast"></div>

<script>
const STUDENT_ID = "{student_id}";
const SIG = "{sig}";
const LEVEL = "{level}";
const GATE_KEY = "{cfg.get("gate_key", "")}";
const NEXT_PATH = "{cfg.get("next_path", "")}";
const NEXT_LEVEL = "{cfg.get("next_level", "")}";
const EXPECTED_COUNT = {cfg.get("expected_count", 0)};

function toast(msg, ms=2500) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), ms);
}}

async function approveFile(fileKey) {{
  const r = await fetch(`/sdl/students/${{STUDENT_ID}}/canonical-files/${{fileKey}}/approve?sig=${{encodeURIComponent(SIG)}}`, {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json', 'X-Student-Signature': SIG}}
  }});
  if (!r.ok) {{
    throw new Error(`Approve ${{fileKey}} fail: ${{r.status}}`);
  }}
  return r.json();
}}

document.querySelectorAll('.approve-btn').forEach(btn => {{
  btn.addEventListener('click', async (e) => {{
    e.preventDefault();
    const fk = btn.dataset.fileKey;
    btn.disabled = true; btn.textContent = 'Đang duyệt...';
    try {{
      await approveFile(fk);
      toast(`✓ Đã duyệt ${{fk}}`);
      setTimeout(() => location.reload(), 600);
    }} catch(err) {{
      toast(`Lỗi: ${{err.message}}`, 4000);
      btn.disabled = false; btn.textContent = 'Duyệt file này';
    }}
  }});
}});

document.querySelectorAll('.retry-btn').forEach(btn => {{
  btn.addEventListener('click', async (e) => {{
    e.preventDefault();
    const fk = btn.dataset.fileKey;
    btn.disabled = true;
    btn.textContent = 'Đang tạo lại...';
    try {{
      const r = await fetch(
        `/sdl/l1/extract/${{fk}}?student_id=${{STUDENT_ID}}&sig=${{encodeURIComponent(SIG)}}`,
        {{method: 'POST', headers: {{'X-Student-Signature': SIG}}}}
      );
      if (!r.ok) {{
        const d = await r.json().catch(() => ({{}}));
        throw new Error(d.detail?.message || d.detail?.error || `HTTP ${{r.status}}`);
      }}
      toast(`✓ Đã tạo lại ${{fk}}`);
      setTimeout(() => location.reload(), 700);
    }} catch(err) {{
      toast(`Lỗi tạo file: ${{err.message}}`, 5000);
      btn.disabled = false;
      btn.textContent = 'Tạo lại file';
    }}
  }});
}});

const approveAllBtn = document.getElementById('approve-all-btn');
if (approveAllBtn) {{
  approveAllBtn.addEventListener('click', async () => {{
    if (!confirm('Duyệt tất cả file còn lại?')) return;
    approveAllBtn.disabled = true; approveAllBtn.textContent = 'Đang duyệt tất cả...';
    const pending = Array.from(document.querySelectorAll('.approve-btn:not(:disabled)')).map(b => b.dataset.fileKey);
    let ok = 0, fail = 0;
    for (const fk of pending) {{
      try {{ await approveFile(fk); ok++; }} catch(e) {{ fail++; }}
    }}
    toast(`✓ ${{ok}} duyệt, ${{fail}} lỗi`, 3500);
    setTimeout(() => location.reload(), 700);
  }});
}}

const lockBtn = document.getElementById('lock-gate-btn');
if (lockBtn) {{
  lockBtn.addEventListener('click', async () => {{
    if (!confirm(`Khóa ${{GATE_KEY}}? Hành động không reset được.`)) return;
    lockBtn.disabled = true; lockBtn.textContent = 'Đang khóa Gate...';
    try {{
      const r = await fetch(`/sdl/students/${{STUDENT_ID}}/gates/${{GATE_KEY}}/lock?sig=${{encodeURIComponent(SIG)}}`, {{method: 'POST', headers: {{'X-Student-Signature': SIG}}}});
      if (!r.ok) {{
        const d = await r.json().catch(() => ({{}}));
        throw new Error(d.detail?.error || d.detail || r.statusText);
      }}
      toast(`🔒 Gate đã khóa. Mở ${{NEXT_LEVEL}}...`);
      setTimeout(() => {{
        if (NEXT_PATH) location.href = `${{NEXT_PATH}}?student=${{STUDENT_ID}}&sig=${{encodeURIComponent(SIG)}}`;
        else location.reload();
      }}, 1200);
    }} catch(err) {{
      toast(`Lỗi khóa Gate: ${{err.message}}`, 5000);
      lockBtn.disabled = false; lockBtn.textContent = `🔒 Khóa Gate`;
    }}
  }});
}}
</script>

</body></html>""")
