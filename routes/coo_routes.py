"""E1 AI COO endpoints (Sprint 16 BreakoutOS v3).

POST /coo/daily/all       Cron 6am Perth, daily report tất cả student enabled
POST /coo/weekly/all      Cron Sunday 8pm Perth, weekly retro
POST /coo/monthly/all     Cron 1st of month 9am Perth, monthly memo
POST /coo/run/{student}   Manual trigger 1 student, period query param
GET  /coo/dashboard/{student}   HTML dashboard report history
GET  /coo/reports/{student}     JSON API report list

Cron-job.org POST kèm header X-CAMAS-Cron-Secret. Auth verify từ env
CAMAS_CRON_SECRET (cùng pattern với /kernel/execute).

Iteration student: SELECT từ public.student_config WHERE coo_enabled = true.
Per student dispatch event coo.daily / coo.weekly / coo.monthly qua
Scheduler.execute() sync. Return summary {processed, errors, results}.

Main.py wire (em sẽ tự làm, FYI):
    from routes.coo_routes import router as coo_router
    app.include_router(coo_router)
"""
from __future__ import annotations

import json
import logging
import os
import secrets as _secrets
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from kernel.base_agent import ExecutionContext
from kernel.scheduler import Scheduler

log = logging.getLogger("camas.routes.coo")

router = APIRouter(prefix="/coo", tags=["coo"])

_CAMAS_CRON_SECRET = os.getenv("CAMAS_CRON_SECRET", "")
DEFAULT_AGENT_NAME = "e1_ai_coo"
DEFAULT_VENTURE = "cohangai"


def _verify_cron_secret(x_camas_cron_secret: Optional[str]) -> None:
    """Verify header CAMAS_CRON_SECRET. Skip if env empty (dev)."""
    if not _CAMAS_CRON_SECRET:
        return
    if not x_camas_cron_secret:
        raise HTTPException(
            status_code=401,
            detail="Missing X-CAMAS-Cron-Secret header",
        )
    if not _secrets.compare_digest(x_camas_cron_secret, _CAMAS_CRON_SECRET):
        raise HTTPException(
            status_code=401,
            detail="Invalid X-CAMAS-Cron-Secret",
        )


def _scheduler(request: Request) -> Scheduler:
    sched = getattr(request.app.state, "scheduler", None)
    if sched is None:
        raise HTTPException(status_code=503, detail="Scheduler chưa boot")
    return sched


def _memory_layer(request: Request) -> Any:
    """Resolve MemoryLayer từ scheduler. Fallback None nếu app.state thiếu."""
    sched = _scheduler(request)
    return getattr(sched, "_memory", None) or getattr(
        request.app.state, "memory", None
    )


async def _list_enabled_students(memory_layer: Any) -> list[dict[str, str]]:
    """Lấy danh sách student có coo_enabled=true từ student_config.

    Fallback nếu table chưa có hoặc DB unreachable: trả 1 student "anna"
    (founder default). Pattern fail-soft.
    """
    fallback = [
        {
            "student_id": "anna",
            "tenant_id": "anna",
            "student_name": "Hằng",
            "telegram_chat_id": "",
        }
    ]
    if memory_layer is None or not getattr(memory_layer, "dsn", None):
        return fallback
    try:
        pool = await memory_layer._get_pool()  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        log.warning("coo_routes pool fail: %r", exc)
        return fallback
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    student_id,
                    COALESCE(tenant_id, student_id) AS tenant_id,
                    COALESCE(student_name, student_id) AS student_name,
                    COALESCE(telegram_chat_id, '') AS telegram_chat_id
                FROM public.student_config
                WHERE COALESCE(coo_enabled, true) = true
                ORDER BY student_id
                """
            )
            if rows:
                return [
                    {
                        "student_id": r["student_id"],
                        "tenant_id": r["tenant_id"],
                        "student_name": r["student_name"],
                        "telegram_chat_id": r["telegram_chat_id"],
                    }
                    for r in rows
                ]
    except Exception as exc:  # noqa: BLE001
        log.warning("coo_routes query student_config fail: %r", exc)
    return fallback


async def _dispatch_period(
    request: Request,
    period: str,
    event_name: str,
) -> dict[str, Any]:
    """Common: iterate enabled student, dispatch agent per student."""
    sched = _scheduler(request)
    memory = _memory_layer(request)
    students = await _list_enabled_students(memory)

    processed = 0
    errors: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for student in students:
        ctx = ExecutionContext(
            run_id=str(uuid.uuid4()),
            user_id=student.get("student_id"),
            venture_context=DEFAULT_VENTURE,
            trigger_event=event_name,
            payload={
                "student_id": student["student_id"],
                "tenant_id": student.get("tenant_id") or student["student_id"],
                "student_name": student.get("student_name")
                or student["student_id"],
                "telegram_chat_id": student.get("telegram_chat_id") or "",
                "period": period,
            },
        )
        try:
            result = await sched.execute(DEFAULT_AGENT_NAME, ctx)
            processed += 1
            results.append(
                {
                    "student_id": student["student_id"],
                    "success": result.success,
                    "escalation_required": result.escalation_required,
                    "stop_reason": result.error,
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "coo dispatch fail student=%s err=%r",
                student.get("student_id"),
                exc,
            )
            errors.append(
                {"student_id": student["student_id"], "error": str(exc)[:200]}
            )

    return {
        "period": period,
        "event": event_name,
        "students_total": len(students),
        "processed": processed,
        "errors": errors,
        "results": results,
    }


# ----------------------------------------------------------------
# Cron endpoints
# ----------------------------------------------------------------
@router.post("/daily/all")
async def trigger_daily_all(
    request: Request,
    x_camas_cron_secret: Optional[str] = Header(None, alias="x-camas-cron-secret"),
) -> dict[str, Any]:
    """Cron 6am Perth daily. Iterate all enabled students, dispatch coo.daily."""
    _verify_cron_secret(x_camas_cron_secret)
    return await _dispatch_period(request, "daily", "coo.daily")


@router.post("/weekly/all")
async def trigger_weekly_all(
    request: Request,
    x_camas_cron_secret: Optional[str] = Header(None, alias="x-camas-cron-secret"),
) -> dict[str, Any]:
    """Cron Sunday 8pm Perth. Weekly retro report."""
    _verify_cron_secret(x_camas_cron_secret)
    return await _dispatch_period(request, "weekly", "coo.weekly")


@router.post("/monthly/all")
async def trigger_monthly_all(
    request: Request,
    x_camas_cron_secret: Optional[str] = Header(None, alias="x-camas-cron-secret"),
) -> dict[str, Any]:
    """Cron 1st of month 9am Perth. Strategic monthly memo."""
    _verify_cron_secret(x_camas_cron_secret)
    return await _dispatch_period(request, "monthly", "coo.monthly")


# ----------------------------------------------------------------
# Manual trigger
# ----------------------------------------------------------------
@router.post("/run/{student_id}")
async def trigger_one_student(
    request: Request,
    student_id: str,
    period: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    x_camas_cron_secret: Optional[str] = Header(None, alias="x-camas-cron-secret"),
) -> dict[str, Any]:
    """Manual trigger COO report cho 1 student, period query param."""
    _verify_cron_secret(x_camas_cron_secret)
    if period not in {"daily", "weekly", "monthly"}:
        raise HTTPException(status_code=400, detail="period invalid")

    sched = _scheduler(request)
    memory = _memory_layer(request)
    students = await _list_enabled_students(memory)
    student = next(
        (s for s in students if s["student_id"] == student_id),
        None,
    )
    if student is None:
        # Allow ad-hoc: fall back tới student_id literal
        student = {
            "student_id": student_id,
            "tenant_id": student_id,
            "student_name": student_id,
            "telegram_chat_id": "",
        }

    event_name = f"coo.{period}"
    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        user_id=student_id,
        venture_context=DEFAULT_VENTURE,
        trigger_event=event_name,
        payload={
            "student_id": student["student_id"],
            "tenant_id": student["tenant_id"],
            "student_name": student["student_name"],
            "telegram_chat_id": student["telegram_chat_id"],
            "period": period,
        },
    )
    result = await sched.execute(DEFAULT_AGENT_NAME, ctx)
    return {
        "student_id": student_id,
        "period": period,
        "success": result.success,
        "escalation_required": result.escalation_required,
        "output_text": result.output_text,
        "output_payload": result.output_payload,
    }


# ----------------------------------------------------------------
# Report history (JSON)
# ----------------------------------------------------------------
@router.get("/reports/{student_id}")
async def list_reports(
    request: Request,
    student_id: str,
    period: Optional[str] = Query(None, pattern="^(daily|weekly|monthly)$"),
    limit: int = Query(20, ge=1, le=200),
    key: str = Query(""),
) -> JSONResponse:
    """JSON API list report history cho student. Auth qua key query (xem dashboard)."""
    _verify_dashboard_key(key)
    memory = _memory_layer(request)
    if memory is None or not getattr(memory, "dsn", None):
        return JSONResponse({"student_id": student_id, "reports": []})
    try:
        pool = await memory._get_pool()  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        log.warning("list_reports pool fail: %r", exc)
        return JSONResponse(
            {"student_id": student_id, "reports": [], "error": str(exc)}
        )

    try:
        async with pool.acquire() as conn:
            if period:
                rows = await conn.fetch(
                    """
                    SELECT id, period, report_date, msg, analysis, narrative,
                           created_at
                    FROM public.coo_report
                    WHERE student_id = $1 AND period = $2
                    ORDER BY created_at DESC
                    LIMIT $3
                    """,
                    student_id,
                    period,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id, period, report_date, msg, analysis, narrative,
                           created_at
                    FROM public.coo_report
                    WHERE student_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    student_id,
                    limit,
                )
            return JSONResponse(
                {
                    "student_id": student_id,
                    "count": len(rows),
                    "reports": [
                        {
                            "id": r["id"],
                            "period": r["period"],
                            "report_date": (
                                r["report_date"].isoformat()
                                if r["report_date"]
                                else None
                            ),
                            "msg": r["msg"],
                            "analysis": _safe_json(r["analysis"]),
                            "narrative": _safe_json(r["narrative"]),
                            "created_at": (
                                r["created_at"].isoformat()
                                if r["created_at"]
                                else None
                            ),
                        }
                        for r in rows
                    ],
                }
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("list_reports query fail: %r", exc)
        return JSONResponse(
            {"student_id": student_id, "reports": [], "error": str(exc)[:200]}
        )


# ----------------------------------------------------------------
# HTML dashboard
# ----------------------------------------------------------------
@router.get("/dashboard/{student_id}", response_class=HTMLResponse)
async def get_dashboard(
    request: Request,
    student_id: str,
    key: str = Query(""),
    period: Optional[str] = Query(None, pattern="^(daily|weekly|monthly)$"),
) -> HTMLResponse:
    """HTML dashboard cho student xem report history.

    Auth qua query `?key=<COO_DASHBOARD_KEY>` để student tự bookmark.
    Render simple HTML, không cần framework.
    """
    _verify_dashboard_key(key)
    memory = _memory_layer(request)
    reports: list[dict[str, Any]] = []

    if memory is not None and getattr(memory, "dsn", None):
        try:
            pool = await memory._get_pool()  # noqa: SLF001
            async with pool.acquire() as conn:
                if period:
                    rows = await conn.fetch(
                        """
                        SELECT id, period, report_date, msg, created_at
                        FROM public.coo_report
                        WHERE student_id = $1 AND period = $2
                        ORDER BY created_at DESC
                        LIMIT 30
                        """,
                        student_id,
                        period,
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT id, period, report_date, msg, created_at
                        FROM public.coo_report
                        WHERE student_id = $1
                        ORDER BY created_at DESC
                        LIMIT 30
                        """,
                        student_id,
                    )
                reports = [dict(r) for r in rows]
        except Exception as exc:  # noqa: BLE001
            log.warning("dashboard query fail: %r", exc)

    html = _render_dashboard_html(student_id, reports, period)
    return HTMLResponse(html)


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------
def _verify_dashboard_key(key: str) -> None:
    """Verify dashboard query key. Skip if COO_DASHBOARD_KEY env empty."""
    expected = os.getenv("COO_DASHBOARD_KEY", "")
    if not expected:
        return
    if not key or not _secrets.compare_digest(key, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _safe_json(value: Any) -> Any:
    """Parse asyncpg JSONB result an toàn (có thể là str hoặc dict)."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:  # noqa: BLE001
            return value
    return value


def _render_dashboard_html(
    student_id: str,
    reports: list[dict[str, Any]],
    period_filter: Optional[str],
) -> str:
    """Render dashboard HTML đơn giản. Tiếng Việt, không framework."""
    filter_label = (
        f"period={period_filter}" if period_filter else "tất cả periods"
    )
    rows_html_parts: list[str] = []
    for r in reports:
        msg = str(r.get("msg") or "")
        msg_html = (
            msg.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        period = r.get("period", "?")
        report_date = r.get("report_date")
        created_at = r.get("created_at")
        date_str = str(report_date or created_at or "?")
        rows_html_parts.append(
            f"""
            <details class="report">
                <summary><strong>{period}</strong> {date_str}</summary>
                <pre>{msg_html}</pre>
            </details>
            """
        )
    rows_html = "\n".join(rows_html_parts) or "<p>Chưa có report.</p>"

    return f"""<!doctype html>
<html lang="vi">
<head>
    <meta charset="utf-8">
    <title>AI COO Dashboard - {student_id}</title>
    <style>
        body {{
            font-family: -apple-system, system-ui, sans-serif;
            max-width: 720px;
            margin: 24px auto;
            padding: 0 16px;
            color: #1a1a1a;
        }}
        h1 {{ font-size: 20px; }}
        .meta {{ color: #666; font-size: 13px; margin-bottom: 16px; }}
        .report {{
            border: 1px solid #ddd;
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 8px;
            background: #fafafa;
        }}
        .report summary {{ cursor: pointer; font-size: 14px; }}
        pre {{
            font-family: ui-monospace, monospace;
            white-space: pre-wrap;
            font-size: 13px;
            background: #fff;
            padding: 12px;
            border-radius: 4px;
            border: 1px solid #eee;
            margin-top: 8px;
        }}
    </style>
</head>
<body>
    <h1>AI COO Dashboard - {student_id}</h1>
    <p class="meta">{filter_label} | {len(reports)} report gần nhất</p>
    {rows_html}
</body>
</html>"""
