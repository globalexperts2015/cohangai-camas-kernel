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
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from routes._auth import sign_student
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
    student_id: UUID, key: str | None = None,
    pool: asyncpg.Pool = Depends(get_pool),
) -> HTMLResponse:
    """Student personal dashboard. Optional admin key bypasses ownership."""
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
  <a href="/cohort/chon-module/?student_id={student_id}" class="action-link">Module CHỌN</a>
  <a href="/sdl/students/{student_id}/vault/export.zip" class="action-link">Tải vault .zip</a>
  <a href="/sdl/students/{student_id}/output/L1" class="action-link">Output L1 Day 1</a>
  <a href="/sdl/students/{student_id}/output/L2" class="action-link">Output L2 Day 2</a>
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
    student_id: UUID, level: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> HTMLResponse:
    """Day 1 = L1, Day 2 = L2 output webinar pages."""
    level_num = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5, "L6a": 6}.get(level)
    if not level_num:
        raise HTTPException(404, "Unknown level")

    async with pool.acquire() as conn:
        files = await conn.fetch(
            """
            SELECT DISTINCT ON (file_key) file_key, markdown_content, tier, status
            FROM breakoutos.canonical_files
            WHERE student_id=$1 AND level=$2
            ORDER BY file_key, version DESC
            """,
            student_id, level_num,
        )

    if not files:
        return HTMLResponse(f"<h1>{level} chưa có output</h1>", status_code=404)

    files_html = ""
    for f in files:
        files_html += (
            f'<details class="file-card tier-{f["tier"]}"><summary>'
            f'<span class="tier-badge">{f["tier"]}</span> '
            f'<strong>{f["file_key"]}</strong> '
            f'<span class="status">{f["status"]}</span></summary>'
            f'<pre>{(f["markdown_content"] or "")[:5000]}</pre></details>'
        )

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><title>Output {level} · BreakoutOS</title>
<style>body{{font-family:'Be Vietnam Pro',system-ui;background:#fafaf7;padding:30px 20px;color:#0a0a0a;max-width:880px;margin:0 auto}}
h1{{color:#d63031}}.file-card{{background:#fff;border:1px solid #e5dfd0;border-radius:12px;padding:18px 22px;margin-bottom:12px}}
.file-card[open]{{border-color:#d63031}}.tier-badge{{display:inline-block;background:#d63031;color:#fff;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:800;margin-right:8px}}
.tier-B .tier-badge{{background:#f4a261}}.tier-C .tier-badge{{background:#999}}
summary{{cursor:pointer;font-size:16px}}.status{{font-size:12px;color:#888;margin-left:8px}}
pre{{margin-top:14px;background:#0a0a0a;color:#fff;padding:16px;border-radius:8px;overflow-x:auto;font-size:13px;white-space:pre-wrap}}</style></head>
<body><h1>Output {level} · {len(files)} canonical file</h1>{files_html}
<p style="margin-top:30px"><a href="/sdl/students/{student_id}/vault/export.zip" style="background:#d63031;color:#fff;padding:14px 22px;border-radius:10px;text-decoration:none;font-weight:700">Tải xuống vault .zip</a></p>
</body></html>""")
