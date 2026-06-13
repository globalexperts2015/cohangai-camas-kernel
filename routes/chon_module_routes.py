"""BreakoutOS CHỌN module orchestrator route.

POST /cohort/run-chon-module: chạy 9 engines tuần tự, store opportunity_run + breakdown.
GET /cohort/chon-module/{run_id}: pull full output 1 run.
GET /cohort/chon-module/student/{student_id}: list latest runs cho compare.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Optional

import asyncpg
import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from kernel.base_agent import ExecutionContext
from routes._auth import sign_student

# Telegram BreakoutOps group ID
TELEGRAM_OPS_GROUP_ID = os.environ.get("TELEGRAM_OPS_GROUP_ID", "-1003813280155")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


async def send_telegram_notification(text: str) -> bool:
    """Gửi notification vào group BreakoutOps."""
    if not TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN missing, skip notification")
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_OPS_GROUP_ID,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
            )
            if resp.status_code != 200:
                log.warning("Telegram non-200: %s %s", resp.status_code, resp.text[:200])
            return resp.status_code == 200
    except Exception as e:
        log.warning("Telegram send fail: %r", e)
        return False


def _classification_emoji(classification: str) -> str:
    """Pick emoji for opportunity classification."""
    mapping = {
        "BUILD_IMMEDIATELY": "🟢",
        "HIGH_PRIORITY": "🟢",
        "TEST_FIRST": "🟡",
        "RESEARCH_MORE": "🟠",
        "REJECT": "🔴",
    }
    return mapping.get(classification, "⚪")

log = logging.getLogger("camas.chon_module")
router = APIRouter(prefix="/cohort/chon-module", tags=["chon-module"])

# Weights from spec chốt 2026-06-11
WEIGHTS = {
    "founder_fit": 0.20,
    "customer_problem": 0.25,
    "market_demand": 0.25,
    "financial": 0.20,
    "lifestyle_fit": 0.10,
}


def _scheduler(request: Request):
    return request.app.state.scheduler


def _verify_token(token: Optional[str]) -> str:
    """Reuse cohort_widget_routes._verify_student_token logic."""
    from .cohort_widget_routes import _verify_student_token
    return _verify_student_token(token)


async def _db_pool() -> Optional[asyncpg.Pool]:
    """Lazy create DB pool."""
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("CDP_DATABASE_URL")
    if not dsn:
        return None
    return await asyncpg.create_pool(dsn, min_size=1, max_size=3, command_timeout=15)


@router.post("/run")
async def run_chon_module(
    request: Request,
    x_cohort_student_token: Optional[str] = Header(None),
) -> JSONResponse:
    """Run full 9-engine pipeline cho 1 opportunity.

    Body JSON:
    {
        "founder_profile": {...},
        "customer_hypothesis": "...",
        "opportunity_hypothesis": "...",
        "financial_target_vnd": 3000000000,
        "lifestyle_choice": "solo_ai" | "lean_team" | "growth_team",
        "label": "Optional label e.g. Dược mỹ phẩm scale Úc",
        "keywords_for_market_demand": ["kw1", "kw2", ...],
        "financial_inputs": {"aov_vnd": 1500000, "margin_pct": 60, ...}
    }
    """
    student_id = _verify_token(x_cohort_student_token)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # P0.2 Anna 2026-06-12: Gate 2A Customer Soft Cert check
    # Require breakoutos_student_id (UUID) + verify gate_2_customer_soft passed
    breakoutos_sid = body.get("breakoutos_student_id") or body.get("sdl_student_id")
    if breakoutos_sid:
        try:
            from routes.sdl_routes import check_gate_passed, get_pool
            from uuid import UUID as _UUID
            sdl_pool = await get_pool()
            passed = await check_gate_passed(sdl_pool, _UUID(str(breakoutos_sid)), "gate_2_customer_soft")
            if not passed:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "Gate 2A Customer Soft Cert chưa pass",
                        "message": "Bạn cần hoàn thành Tầng 2 Customer Intelligence OS trước khi chạy Module CHỌN.",
                        "redirect": (
                            f"/foundation/l2?student={breakoutos_sid}"
                            f"&sig={sign_student(str(breakoutos_sid))}"
                        ),
                    },
                )
        except HTTPException:
            raise
        except Exception as exc:
            log.warning("Gate check error (non-blocking): %r", exc)
    else:
        # No SDL student_id provided — Anna's amendment: enforce, block bypass
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Missing breakoutos_student_id",
                "message": "Module CHỌN yêu cầu student đăng nhập SDL. Liên hệ Hằng Zalo.",
            },
        )

    founder_profile = body.get("founder_profile") or {}
    customer_hypothesis = body.get("customer_hypothesis") or ""
    opportunity_hypothesis = body.get("opportunity_hypothesis") or ""
    financial_target_vnd = int(body.get("financial_target_vnd") or 0)
    lifestyle_choice = body.get("lifestyle_choice") or "solo_ai"
    label = body.get("label") or opportunity_hypothesis[:80]
    keywords = body.get("keywords_for_market_demand") or []
    financial_inputs = body.get("financial_inputs") or {}

    if not founder_profile or not customer_hypothesis or not opportunity_hypothesis:
        raise HTTPException(
            status_code=400,
            detail="Required: founder_profile + customer_hypothesis + opportunity_hypothesis",
        )

    sched = _scheduler(request)
    pool = await _db_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="DATABASE_URL not configured")

    # Create opportunity_run row
    run_id = uuid.uuid4()
    async with pool.acquire() as conn:
        version = await conn.fetchval(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM opportunity_run WHERE student_id=$1",
            student_id,
        )
        await conn.execute(
            "INSERT INTO opportunity_run (run_id, student_id, token, version, label, inputs_json, "
            "founder_profile_json, customer_hypothesis_json, financial_target_vnd, lifestyle_choice, "
            "idea_hypothesis, status, started_at) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9, $10, $11, 'running', NOW())",
            run_id, student_id, x_cohort_student_token, version, label,
            json.dumps(body, ensure_ascii=False),
            json.dumps(founder_profile, ensure_ascii=False),
            json.dumps({"hypothesis": customer_hypothesis}, ensure_ascii=False),
            financial_target_vnd, lifestyle_choice, opportunity_hypothesis,
        )

    log.info("CHỌN module run started: student=%s run=%s version=%s", student_id, run_id, version)

    # Run 5 LLM engines in parallel (independent inputs)
    sub_scores = {}
    engine_outputs = {}

    async def _run_engine(engine_name: str, event: str, payload: dict) -> tuple[str, dict]:
        ctx = ExecutionContext(
            run_id=str(uuid.uuid4()),
            user_id=student_id,
            venture_context="cohangai",
            trigger_event=event,
            payload={**payload, "student_id": student_id},
        )
        try:
            agent_name = {
                "founder_fit": "e3_founder_fit",
                "customer_problem": "e4_customer_problem",
                "desire": "e5_desire",
                "market_demand": "e6_market_demand",
                "solution_design": "e7_solution_design",
                "financial": "e8_financial",
                "lifestyle_fit": "e9_lifestyle_fit",
                "decision": "e10_decision",
                "recommendation": "e11_recommendation",
            }[engine_name]
            t0 = time.time()
            result = await sched.execute(agent_name, ctx)
            duration_ms = int((time.time() - t0) * 1000)
            payload_out = result.output_payload or {}
            score = None
            for key in ("founder_fit_score", "problem_strength_score", "market_demand_score",
                        "financial_viability_score", "lifestyle_fit_score", "desire_strength_score",
                        "solution_design_score", "opportunity_score"):
                if key in payload_out:
                    score = payload_out[key]
                    break
            return engine_name, {
                "success": result.success,
                "score": score,
                "output": payload_out,
                "duration_ms": duration_ms,
                "error": result.output_text if not result.success else None,
            }
        except Exception as e:
            log.exception("Engine %s fail", engine_name)
            return engine_name, {
                "success": False,
                "score": None,
                "output": {"error": str(e)[:200]},
                "duration_ms": 0,
                "error": str(e)[:200],
            }

    # Phase A: parallel independent engines (founder_fit + market_demand + customer_problem)
    phase_a = await asyncio.gather(
        _run_engine("founder_fit", "wizard.founder_fit", {
            "founder_profile": founder_profile,
            "opportunity_hypothesis": opportunity_hypothesis,
            "lifestyle_choice": lifestyle_choice,
        }),
        _run_engine("customer_problem", "wizard.customer_problem", {
            "customer_hypothesis": customer_hypothesis,
            "opportunity_hypothesis": opportunity_hypothesis,
        }),
        _run_engine("market_demand", "wizard.market_demand", {
            "keywords": keywords or [opportunity_hypothesis[:60]],
        }),
    )
    for name, data in phase_a:
        engine_outputs[name] = data
        if data["score"] is not None:
            sub_scores[name] = data["score"]
        await _persist_engine_output(pool, run_id, name, data)

    # Phase B: Desire depends on Customer Problem
    problem_map = engine_outputs.get("customer_problem", {}).get("output", {})
    desire_name, desire_data = await _run_engine("desire", "wizard.desire", {
        "customer_hypothesis": customer_hypothesis,
        "problem_map": problem_map,
    })
    engine_outputs[desire_name] = desire_data
    if desire_data["score"] is not None:
        sub_scores[desire_name] = desire_data["score"]
    await _persist_engine_output(pool, run_id, desire_name, desire_data)

    # Phase C: Solution Design depends on Founder + Customer + Desire
    desire_map = desire_data.get("output", {})
    sol_name, sol_data = await _run_engine("solution_design", "wizard.solution_design", {
        "founder_profile": founder_profile,
        "customer_hypothesis": customer_hypothesis,
        "problem_map": problem_map,
        "desire_map": desire_map,
        "lifestyle_choice": lifestyle_choice,
    })
    engine_outputs[sol_name] = sol_data
    if sol_data["score"] is not None:
        sub_scores[sol_name] = sol_data["score"]
    await _persist_engine_output(pool, run_id, sol_name, sol_data)

    # Phase D: Financial + Lifestyle in parallel (both depend on Solution Design)
    sol_output = sol_data.get("output", {})
    primary_rec = sol_output.get("primary_recommendation") or {}
    price_range = primary_rec.get("estimated_price_range_vnd") or {}
    inferred_aov = financial_inputs.get("aov_vnd") or price_range.get("mid") or 1500000
    inferred_margin = financial_inputs.get("margin_pct") or 60

    phase_d = await asyncio.gather(
        _run_engine("financial", "wizard.financial", {
            "profit_target_vnd": financial_target_vnd or 1000000000,
            "aov_vnd": inferred_aov,
            "margin_pct": inferred_margin,
            "conversion_rate_pct": financial_inputs.get("conversion_rate_pct", 2.5),
            "optin_rate_pct": financial_inputs.get("optin_rate_pct", 18),
            "repeat_purchase_ratio": financial_inputs.get("repeat_purchase_ratio", 1.5),
        }),
        _run_engine("lifestyle_fit", "wizard.lifestyle_fit", {
            "opportunity_hypothesis": opportunity_hypothesis,
            "solution_design": sol_output,
            "lifestyle_choice": lifestyle_choice,
            "founder_profile": founder_profile,
        }),
    )
    for name, data in phase_d:
        engine_outputs[name] = data
        if data["score"] is not None:
            sub_scores[name] = data["score"]
        await _persist_engine_output(pool, run_id, name, data)

    # Phase E: Decision (aggregator)
    decision_name, decision_data = await _run_engine("decision", "wizard.decision", {
        "sub_scores": {
            "founder_fit": sub_scores.get("founder_fit", 0),
            "customer_problem": sub_scores.get("customer_problem", 0),
            "market_demand": sub_scores.get("market_demand", 0),
            "financial": sub_scores.get("financial", 0),
            "lifestyle_fit": sub_scores.get("lifestyle_fit", 0),
        },
    })
    engine_outputs[decision_name] = decision_data
    await _persist_engine_output(pool, run_id, decision_name, decision_data)
    opportunity_score = decision_data.get("output", {}).get("opportunity_score", 0)
    classification = decision_data.get("output", {}).get("classification", "UNKNOWN")

    # Phase F: Recommendation (final)
    rec_name, rec_data = await _run_engine("recommendation", "wizard.recommendation", {
        "founder_fit": engine_outputs.get("founder_fit", {}).get("output", {}),
        "customer_problem": problem_map,
        "desire": desire_map,
        "market_demand": engine_outputs.get("market_demand", {}).get("output", {}),
        "solution_design": sol_output,
        "financial": engine_outputs.get("financial", {}).get("output", {}),
        "lifestyle_fit": engine_outputs.get("lifestyle_fit", {}).get("output", {}),
        "decision": decision_data.get("output", {}),
        "opportunity_hypothesis": opportunity_hypothesis,
        "lifestyle_choice": lifestyle_choice,
    })
    engine_outputs[rec_name] = rec_data
    await _persist_engine_output(pool, run_id, rec_name, rec_data)

    # Update opportunity_run with final score
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE opportunity_run SET opportunity_score=$1, classification=$2, "
            "status='completed', completed_at=NOW() WHERE run_id=$3",
            opportunity_score, classification, run_id,
        )

    log.info(
        "CHỌN module run done: student=%s run=%s score=%s classification=%s",
        student_id, run_id, opportunity_score, classification,
    )

    # Gap 6 DISABLED 2026-06-11: success notification = noise. Anna chốt im lặng.
    # CHỈ alert khi student có vấn đề (REJECT score <40 hoặc API limit).
    if classification == "REJECT":
        # Học viên opportunity REJECTED - Anna có thể cần 1-1 review
        asyncio.create_task(send_telegram_notification(
            f"⚠️ *Học viên cần Anna 1-1 review*\n\n"
            f"Student `{student_id}` chạy CHỌN module → Score {opportunity_score}/100 REJECT.\n"
            f"Label: {label[:60]}\n\n"
            f"Học viên có thể bỏ cuộc nếu không có Anna intervene. "
            f"Xem run: `/cohort/chon-module/runs/{run_id}`"
        ))
    # KHÔNG send notification cho BUILD/HIGH/TEST/RESEARCH (success cases).

    await pool.close()

    return JSONResponse({
        "success": True,
        "run_id": str(run_id),
        "version": version,
        "student_id": student_id,
        "label": label,
        "opportunity_score": opportunity_score,
        "classification": classification,
        "sub_scores": sub_scores,
        "engine_outputs": engine_outputs,
    })


async def _persist_engine_output(pool, run_id, engine_name: str, data: dict):
    """Save 1 engine output row to opportunity_score_breakdown."""
    weight_pct = int(WEIGHTS.get(engine_name, 0) * 100)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO opportunity_score_breakdown "
            "(run_id, engine_name, sub_score, weight_pct, output_json, status, duration_ms, completed_at) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, NOW()) "
            "ON CONFLICT (run_id, engine_name) DO UPDATE "
            "SET sub_score=$3, output_json=$5::jsonb, status=$6, duration_ms=$7, completed_at=NOW()",
            run_id, engine_name, data.get("score"), weight_pct,
            json.dumps(data.get("output", {}), ensure_ascii=False, default=str),
            "completed" if data.get("success") else "failed",
            data.get("duration_ms", 0),
        )


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> JSONResponse:
    """Pull full output 1 run."""
    pool = await _db_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="DATABASE_URL not configured")
    async with pool.acquire() as conn:
        run = await conn.fetchrow(
            "SELECT * FROM opportunity_run WHERE run_id=$1::uuid", run_id,
        )
        if not run:
            await pool.close()
            raise HTTPException(status_code=404, detail="Run not found")
        breakdowns = await conn.fetch(
            "SELECT engine_name, sub_score, weight_pct, output_json, status, duration_ms "
            "FROM opportunity_score_breakdown WHERE run_id=$1::uuid ORDER BY engine_name",
            run_id,
        )
    await pool.close()
    return JSONResponse({
        "run_id": str(run["run_id"]),
        "student_id": run["student_id"],
        "version": run["version"],
        "label": run["label"],
        "opportunity_score": run["opportunity_score"],
        "classification": run["classification"],
        "status": run["status"],
        "started_at": run["started_at"].isoformat() if run["started_at"] else None,
        "completed_at": run["completed_at"].isoformat() if run["completed_at"] else None,
        "breakdowns": [
            {
                "engine": b["engine_name"],
                "sub_score": b["sub_score"],
                "weight_pct": b["weight_pct"],
                "duration_ms": b["duration_ms"],
                "status": b["status"],
                "output": b["output_json"],
            }
            for b in breakdowns
        ],
    })


@router.get("/student/{student_id}/runs")
async def list_student_runs(student_id: str) -> JSONResponse:
    """List opportunity runs for student (compare view)."""
    pool = await _db_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="DATABASE_URL not configured")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT run_id, version, label, opportunity_score, classification, status, "
            "started_at, completed_at FROM opportunity_run "
            "WHERE student_id=$1 ORDER BY version DESC LIMIT 50",
            student_id,
        )
    await pool.close()
    return JSONResponse({
        "student_id": student_id,
        "runs": [
            {
                "run_id": str(r["run_id"]),
                "version": r["version"],
                "label": r["label"],
                "opportunity_score": r["opportunity_score"],
                "classification": r["classification"],
                "status": r["status"],
                "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            }
            for r in rows
        ],
    })


# ============================================================================
# GAP 1: Page chính /cohort/cho-n-cai-de-ban (form 7-step) + result page
# ============================================================================

PAGE_CSS = """
body{margin:0;background:#fafafa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#222;line-height:1.65}
.container{max-width:760px;margin:0 auto;padding:24px 18px 80px}
.banner{background:linear-gradient(135deg,#ff7e5f,#d63031);color:white;padding:24px 22px;border-radius:16px;margin-bottom:22px}
.banner .label{font-size:11px;letter-spacing:1.5px;text-transform:uppercase;opacity:0.9;margin-bottom:8px}
.banner h1{margin:0 0 6px;font-size:25px;font-weight:700}
.banner p{margin:0;font-size:14px;opacity:0.95}
.card{background:white;border-radius:14px;padding:20px 22px;margin-bottom:14px;box-shadow:0 2px 10px rgba(0,0,0,0.04)}
.card h2{font-size:17px;margin:0 0 12px;color:#d63031}
.card h3{font-size:14px;margin:14px 0 6px;color:#444}
.card label{display:block;font-size:13px;font-weight:600;color:#444;margin:14px 0 6px}
.card input[type=text],.card input[type=number],.card textarea,.card select{width:100%;box-sizing:border-box;border:1px solid #e0e0e0;border-radius:10px;padding:11px 13px;font-size:14px;font-family:inherit}
.card textarea{resize:vertical;min-height:80px}
.card input:focus,.card textarea:focus,.card select:focus{outline:none;border-color:#ff7e5f}
.radio-group{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:8px}
.radio-card{border:2px solid #e0e0e0;border-radius:10px;padding:10px 12px;cursor:pointer;font-size:13px;text-align:center}
.radio-card.selected{border-color:#d63031;background:#fff5f5;color:#d63031;font-weight:600}
.btn-primary{display:block;width:100%;box-sizing:border-box;padding:16px;background:linear-gradient(135deg,#ff7e5f,#d63031);color:white;border:none;border-radius:12px;font-size:16px;font-weight:600;cursor:pointer;margin-top:18px}
.btn-primary:disabled{opacity:0.5;cursor:wait}
.note{background:#fff8e1;border-left:4px solid #ffc107;padding:12px 14px;border-radius:0 8px 8px 0;font-size:13px;color:#7a5a00;margin-bottom:16px}
.persona-card{background:#e8f8f5;border-left:4px solid #2a9d8f;padding:14px 18px;border-radius:0 12px 12px 0;margin-bottom:16px}
.persona-card strong{color:#2a9d8f}
.score-big{font-size:64px;font-weight:700;color:#d63031;text-align:center;margin:14px 0 4px}
.classification-badge{display:inline-block;padding:6px 16px;border-radius:20px;font-size:13px;font-weight:600;color:white}
.cls-BUILD_IMMEDIATELY{background:#2a9d8f}
.cls-HIGH_PRIORITY{background:#52b788}
.cls-TEST_FIRST{background:#f4a261}
.cls-RESEARCH_MORE{background:#e76f51}
.cls-REJECT{background:#9d0208}
.sub-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px}
.sub-item{background:#fafafa;border-radius:10px;padding:10px 14px}
.sub-item .sub-name{font-size:12px;color:#666;text-transform:uppercase;letter-spacing:0.5px}
.sub-item .sub-score{font-size:22px;font-weight:700;color:#d63031;margin-top:4px}
.sub-item .sub-weight{font-size:11px;color:#999}
.loading-card{text-align:center;padding:60px 20px;color:#666;font-size:15px}
.loading-card .spinner{width:48px;height:48px;border:4px solid #ffe0d0;border-top-color:#d63031;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 16px}
@keyframes spin{to{transform:rotate(360deg)}}
.cta-block{background:#fff8e1;border:2px solid #ffc107;padding:20px;border-radius:16px;text-align:center;margin:24px 0}
.cta-block h3{color:#c08a00;margin:0 0 8px}
.cta-block a{display:inline-block;background:linear-gradient(135deg,#ff7e5f,#d63031);color:white;padding:14px 28px;border-radius:12px;text-decoration:none;font-weight:600;font-size:15px;margin-top:10px}
.footer{text-align:center;color:#aaa;font-size:12px;padding:18px 0}
.footer a{color:#666;margin:0 6px}
.compare-table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13px}
.compare-table th{background:#d63031;color:white;padding:10px;text-align:left}
.compare-table td{padding:10px;border-bottom:1px solid #eee;vertical-align:top}
.compare-table tr:nth-child(even) td{background:#fafafa}
.report-md h1,.report-md h2,.report-md h3{font-size:15px;margin:12px 0 6px;color:#444}
.report-md p{margin:6px 0;font-size:14px;line-height:1.7}
.report-md ul{padding-left:22px;font-size:14px;line-height:1.7}
/* V3.5 Intro UI */
.intro-hero{background:linear-gradient(135deg,#1a1a1a,#2d2d2d);color:white;padding:32px 24px;border-radius:18px;margin-bottom:18px;text-align:center}
.intro-hero .tag{display:inline-block;background:rgba(255,126,95,0.2);color:#ff9b80;padding:6px 14px;border-radius:20px;font-size:11px;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:14px;font-weight:600}
.intro-hero h1{font-size:32px;margin:0 0 14px;font-weight:800;line-height:1.2}
.intro-hero .sub{font-size:16px;opacity:0.9;margin:0 0 8px;line-height:1.5}
.intro-hero .meta{font-size:13px;opacity:0.7;margin-top:14px}
.outcomes-block{background:white;border-radius:16px;padding:24px 22px;margin-bottom:18px;box-shadow:0 2px 10px rgba(0,0,0,0.04)}
.outcomes-block .title{font-size:13px;color:#999;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:6px;font-weight:600}
.outcomes-block h2{font-size:22px;color:#1a1a1a;margin:0 0 18px;font-weight:700}
.outcomes-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.outcome-item{background:#fff5f3;border-left:4px solid #d63031;border-radius:0 12px 12px 0;padding:14px 16px}
.outcome-item .num{display:inline-block;background:#d63031;color:white;width:24px;height:24px;border-radius:50%;text-align:center;line-height:24px;font-size:12px;font-weight:700;margin-right:8px}
.outcome-item strong{display:block;font-size:14px;color:#1a1a1a;margin-bottom:4px}
.outcome-item p{margin:0;font-size:12px;color:#666;line-height:1.5}
.journey-block{background:white;border-radius:16px;padding:24px 22px;margin-bottom:18px;box-shadow:0 2px 10px rgba(0,0,0,0.04)}
.journey-block .title{font-size:13px;color:#999;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:6px;font-weight:600}
.journey-block h2{font-size:22px;color:#1a1a1a;margin:0 0 6px;font-weight:700}
.journey-block .hint{font-size:13px;color:#666;margin:0 0 18px}
.cluster{margin-bottom:16px;border:1px solid #f0f0f0;border-radius:12px;padding:16px;background:#fafafa}
.cluster-header{display:flex;align-items:center;margin-bottom:12px}
.cluster-badge{font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:4px 10px;border-radius:8px;margin-right:10px;color:white}
.cluster-1 .cluster-badge{background:#2a9d8f}
.cluster-2 .cluster-badge{background:#e76f51}
.cluster-3 .cluster-badge{background:#9d4edd}
.cluster h3{font-size:15px;margin:0;color:#1a1a1a;font-weight:700}
.engines{display:grid;gap:8px}
.engine-item{display:flex;align-items:flex-start;background:white;border-radius:10px;padding:12px 14px;border:1px solid #eee}
.engine-num{font-size:18px;font-weight:800;color:#d63031;min-width:34px}
.engine-body strong{display:block;font-size:14px;color:#1a1a1a;margin-bottom:2px}
.engine-body p{margin:0;font-size:12px;color:#666;line-height:1.5}
.cta-scroll{display:block;width:100%;box-sizing:border-box;padding:18px;background:linear-gradient(135deg,#ff7e5f,#d63031);color:white;border:none;border-radius:14px;font-size:17px;font-weight:700;cursor:pointer;text-decoration:none;text-align:center;margin:24px 0 18px;box-shadow:0 6px 20px rgba(214,48,49,0.25)}
.cta-scroll:hover{transform:translateY(-1px);box-shadow:0 8px 24px rgba(214,48,49,0.35)}
.cta-meta{text-align:center;font-size:12px;color:#999;margin-bottom:24px}
@media(max-width:600px){.outcomes-grid{grid-template-columns:1fr}.intro-hero h1{font-size:24px}}
"""


@router.get("/", response_class=HTMLResponse)
async def chon_module_landing(request: Request) -> HTMLResponse:
    """Landing page /cohort/cho-n-cai-de-ban: form 7 section + submit."""
    token = request.query_params.get("token", "")
    prefill_b64 = request.query_params.get("prefill", "")
    breakoutos_sid = (request.query_params.get("breakoutos_student_id")
                      or request.query_params.get("sdl_student_id") or "")

    # Decode prefill JSON if exists (Gap 5)
    import base64 as _b64
    prefill_data = {}
    if prefill_b64:
        try:
            prefill_data = json.loads(_b64.urlsafe_b64decode(prefill_b64.encode("ascii")).decode("utf-8"))
        except Exception:
            prefill_data = {}

    import html as _html

    def pf(key: str, default: str = "") -> str:
        v = prefill_data.get(key, default)
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False, indent=2)
        return _html.escape(str(v))

    fp = prefill_data.get("founder_profile", {}) or {}
    fp_text = json.dumps(fp, ensure_ascii=False, indent=2) if fp else ""

    has_prefill = bool(prefill_data)
    prefill_banner = (
        '<div class="persona-card"><strong>Trợ lý AI đã pre-fill data buổi 2 bạn nộp.</strong> '
        'Bạn xem lại + chỉnh sửa nếu cần, sau đó click "Chạy 9 Engines" để AI phân tích cơ hội của bạn.</div>'
        if has_prefill else ""
    )

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chọn Đúng Cái Để Bán | BreakoutOS</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="container">

  <div class="intro-hero">
    <div class="tag">BreakoutOS · Tầng Tăng Trưởng (Growth)</div>
    <h1>Chọn Đúng Thứ Để Bán</h1>
    <p class="sub">9 AI Engine phân tích HONEST cơ hội kinh doanh của bạn.</p>
    <p class="sub">Trong 6 phút, bạn biết NÊN bán cái gì, BÁN CHO AI, BÁN BAO NHIÊU, BÁN NHƯ THẾ NÀO.</p>
    <p class="meta">Đây không phải khoá học. Đây là cỗ máy ra quyết định bạn cần khi đứng giữa 3-5 hướng đi mà chưa biết chọn cái nào.</p>
  </div>

  {prefill_banner}

  <div class="outcomes-block">
    <div class="title">Sau 6 phút bạn có</div>
    <h2>4 tài sản quyết định, sẵn sàng hành động</h2>
    <div class="outcomes-grid">
      <div class="outcome-item">
        <strong><span class="num">1</span>Opportunity Score 0-100</strong>
        <p>Điểm số HONEST cơ hội bạn đang cân nhắc. GO / TEST / NO-GO rõ ràng.</p>
      </div>
      <div class="outcome-item">
        <strong><span class="num">2</span>Customer Profile chi tiết</strong>
        <p>Khách hàng nào bạn có quyền phục vụ nhất + pain map + desire map.</p>
      </div>
      <div class="outcome-item">
        <strong><span class="num">3</span>Value Ladder 5 tầng</strong>
        <p>Sản phẩm nào bán trước, sau, đỉnh. Giá đề xuất từng tầng.</p>
      </div>
      <div class="outcome-item">
        <strong><span class="num">4</span>Action Plan 30 ngày</strong>
        <p>3-5 bước cụ thể bạn phải làm tuần tới, có deadline + KPI.</p>
      </div>
    </div>
  </div>

  <div class="journey-block">
    <div class="title">9 Engine bạn sẽ đi qua</div>
    <h2>Hành trình từ "không biết chọn cái nào" → "đây chính là thứ tôi cần bán"</h2>
    <p class="hint">9 Engine chia 3 cụm. Mỗi cụm trả lời 1 câu hỏi cốt lõi. Bạn fill 1 form, AI chạy cả 9 engine tự động.</p>

    <div class="cluster cluster-1">
      <div class="cluster-header">
        <span class="cluster-badge">Cụm 1 · Hiểu Mình</span>
        <h3>Tôi mạnh gì? Tôi có quyền phục vụ ai?</h3>
      </div>
      <div class="engines">
        <div class="engine-item">
          <div class="engine-num">E1</div>
          <div class="engine-body">
            <strong>Founder Fit</strong>
            <p>Đo độ vừa giữa năng lực + động lực + lived experience của bạn với cơ hội. Lived Experience cân 30% (cao nhất).</p>
          </div>
        </div>
      </div>
    </div>

    <div class="cluster cluster-2">
      <div class="cluster-header">
        <span class="cluster-badge">Cụm 2 · Hiểu Khách</span>
        <h3>Khách của tôi là ai? Họ cần gì? Thị trường có cầu không?</h3>
      </div>
      <div class="engines">
        <div class="engine-item">
          <div class="engine-num">E2</div>
          <div class="engine-body">
            <strong>Customer Problem</strong>
            <p>Pain Map 6 trục mất mát. Mỗi pain có Pain Scale 1-10. Khách của bạn đang đau ở đâu nhất.</p>
          </div>
        </div>
        <div class="engine-item">
          <div class="engine-num">E3</div>
          <div class="engine-body">
            <strong>Desire</strong>
            <p>Desire Map 5 chiều + Transformation Map "Từ X → trở thành Y". Khách muốn trở thành ai.</p>
          </div>
        </div>
        <div class="engine-item">
          <div class="engine-num">E4</div>
          <div class="engine-body">
            <strong>Market Demand</strong>
            <p>Pull data LIVE từ DataForSEO + YouTube + Google Trends. Volume tìm kiếm, đối thủ, xu hướng 12 tháng.</p>
          </div>
        </div>
        <div class="engine-item">
          <div class="engine-num">E5</div>
          <div class="engine-body">
            <strong>Decision (Opportunity Score)</strong>
            <p>Tổng hợp E1-E4 thành Score 0-100 + classification BUILD / TEST / RESEARCH / REJECT.</p>
          </div>
        </div>
      </div>
    </div>

    <div class="cluster cluster-3">
      <div class="cluster-header">
        <span class="cluster-badge">Cụm 3 · Thiết Kế Hệ Thống</span>
        <h3>Tôi đóng gói thành sản phẩm gì? Có khả thi tài chính không? Có hợp lifestyle không?</h3>
      </div>
      <div class="engines">
        <div class="engine-item">
          <div class="engine-num">E6</div>
          <div class="engine-body">
            <strong>Solution Design</strong>
            <p>Ma trận 7 loại sản phẩm × pain × khách. Đề xuất Statement Một Dòng + Offer Stack.</p>
          </div>
        </div>
        <div class="engine-item">
          <div class="engine-num">E7</div>
          <div class="engine-body">
            <strong>Financial Feasibility</strong>
            <p>Có đạt mục tiêu lợi nhuận năm không? Cần bao nhiêu khách. AOV bao nhiêu. Margin bao nhiêu.</p>
          </div>
        </div>
        <div class="engine-item">
          <div class="engine-num">E8</div>
          <div class="engine-body">
            <strong>Lifestyle Fit</strong>
            <p>Solo + AI hay Lean Team hay Growth Team. Match với lifestyle bạn muốn 5 năm tới.</p>
          </div>
        </div>
        <div class="engine-item">
          <div class="engine-num">E9</div>
          <div class="engine-body">
            <strong>Recommendation</strong>
            <p>Value Ladder 5 tier + Action Plan 30 ngày + 3 dòng câu chốt cho website / pitch / email.</p>
          </div>
        </div>
      </div>
    </div>
  </div>

  <a href="#form-section" class="cta-scroll">Bắt đầu hành trình 9 Engine →</a>
  <p class="cta-meta">Miễn phí với gói Foundation. ~6 phút. Bạn có thể re-run với cơ hội khác.</p>

  <div id="form-section"></div>

  <div class="note">
    Module chạy ~6 phút. AI sẽ phân tích Founder Fit + Customer Problem + Desire + Market Demand (data live) + Solution Design + Financial Feasibility + Lifestyle Fit, rồi tổng hợp Opportunity Score.
  </div>

  <form id="chon-form">
    <input type="hidden" name="token" value="{_html.escape(token)}">
    <input type="hidden" name="breakoutos_student_id" value="{_html.escape(breakoutos_sid)}">

    <div class="card">
      <h2>1. Founder Profile</h2>
      <p style="font-size:13px;color:#666;margin:0 0 8px">Mô tả kinh nghiệm + kỹ năng + chuyên môn + tài sản hiện có của bạn (JSON hoặc text dài).</p>
      <label>Founder Profile JSON hoặc mô tả</label>
      <textarea name="founder_profile_text" rows="10" placeholder='{{"age":35,"experience":"...","skills":["..."],"network":"...","assets":["..."]}}'>{_html.escape(fp_text)}</textarea>
    </div>

    <div class="card">
      <h2>2. Khách hàng (Customer Hypothesis)</h2>
      <label>Mô tả 1 khách hàng cụ thể bạn muốn phục vụ</label>
      <textarea name="customer_hypothesis" rows="5" placeholder="Mẹ Việt 30-45t định cư Úc 2-5 năm, có con nhỏ, đang dùng skincare phương Tây nhưng nhớ dược mỹ phẩm Việt...">{pf("customer_hypothesis")}</textarea>
    </div>

    <div class="card">
      <h2>3. Cơ hội kinh doanh (Opportunity)</h2>
      <label>Mô tả cơ hội bạn đang cân nhắc</label>
      <textarea name="opportunity_hypothesis" rows="5" placeholder="Scale dược mỹ phẩm Việt sang Úc, launch 1 SKU đầu qua TGA + Amazon AU + community founder Việt Sydney/Melbourne, target 50 khách 12 tháng...">{pf("opportunity_hypothesis")}</textarea>
      <label>Label ngắn (để compare sau)</label>
      <input type="text" name="label" placeholder="Ví dụ: Dược mỹ phẩm scale Úc" value="{pf('label')}">
    </div>

    <div class="card">
      <h2>4. Mục tiêu tài chính</h2>
      <label>Mục tiêu lợi nhuận năm (VND)</label>
      <input type="number" name="financial_target_vnd" placeholder="3000000000" value="{pf('financial_target_vnd', '3000000000')}">
      <h3>Giả định bổ sung (optional, có default)</h3>
      <label>AOV (Average Order Value, VND)</label>
      <input type="number" name="aov_vnd" placeholder="1500000" value="{pf('aov_vnd', '1500000')}">
      <label>Margin % (gross margin)</label>
      <input type="number" name="margin_pct" placeholder="60" step="1" value="{pf('margin_pct', '60')}">
    </div>

    <div class="card">
      <h2>5. Lifestyle Target</h2>
      <p style="font-size:13px;color:#666;margin:0 0 8px">Chọn lifestyle bạn muốn sau khi cơ hội này thành công.</p>
      <div class="radio-group" id="lifestyle-group">
        <div class="radio-card selected" data-value="solo_ai"><strong>Solo + AI</strong><br><small>1 người + AI &lt;30h/tuần</small></div>
        <div class="radio-card" data-value="lean_team"><strong>Lean Team</strong><br><small>3-5 nhân viên &lt;40h/tuần</small></div>
        <div class="radio-card" data-value="growth_team"><strong>Growth Team</strong><br><small>10+ nhân viên 50h+</small></div>
      </div>
      <input type="hidden" name="lifestyle_choice" id="lifestyle_choice" value="solo_ai">
    </div>

    <div class="card">
      <h2>6. Keywords cho Market Demand</h2>
      <label>3-10 keywords (phân tách bằng dấu phẩy)</label>
      <input type="text" name="keywords_for_market_demand" placeholder="dược mỹ phẩm việt, kem dưỡng da sau sinh, skincare thảo dược" value="{pf('keywords_csv')}">
      <p style="font-size:12px;color:#999;margin-top:4px">AI pull live data từ DataForSEO + YouTube + Google Trends cho mỗi keyword.</p>
    </div>

    <button type="submit" class="btn-primary" id="submit-btn">Chạy 9 Engines (~6 phút)</button>
  </form>

  <div id="status" style="display:none"></div>

  <div class="footer">
    BreakoutOS Core Module · Chốt spec 2026-06-11 ·
    <a href="/cohort/">Hub</a> ·
    <a href="/cohort/chon-module/student/runs" id="my-runs-link">Runs của tôi</a>
  </div>
</div>

<script>
  // Lifestyle radio cards
  document.querySelectorAll('#lifestyle-group .radio-card').forEach(card => {{
    card.addEventListener('click', () => {{
      document.querySelectorAll('#lifestyle-group .radio-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      document.getElementById('lifestyle_choice').value = card.dataset.value;
    }});
  }});

  // Form submit → POST /cohort/chon-module/run
  const form = document.getElementById('chon-form');
  const statusDiv = document.getElementById('status');
  const submitBtn = document.getElementById('submit-btn');

  form.addEventListener('submit', async (e) => {{
    e.preventDefault();
    const token = form.querySelector('input[name=token]').value.trim();
    if (!token) {{ alert('Token thiếu. Vào URL có ?token=wk2-b3-...'); return; }}

    // Parse founder profile
    let founderProfile = {{}};
    const fpText = form.querySelector('textarea[name=founder_profile_text]').value.trim();
    if (fpText.startsWith('{{')) {{
      try {{ founderProfile = JSON.parse(fpText); }} catch (err) {{
        founderProfile = {{raw_description: fpText}};
      }}
    }} else {{
      founderProfile = {{raw_description: fpText}};
    }}

    const keywordsCsv = form.querySelector('input[name=keywords_for_market_demand]').value.trim();
    const keywords = keywordsCsv.split(',').map(k => k.trim()).filter(k => k.length > 0);

    const breakoutosSid = (form.querySelector('input[name=breakoutos_student_id]')?.value || '').trim();
    const body = {{
      founder_profile: founderProfile,
      customer_hypothesis: form.querySelector('textarea[name=customer_hypothesis]').value.trim(),
      opportunity_hypothesis: form.querySelector('textarea[name=opportunity_hypothesis]').value.trim(),
      financial_target_vnd: parseInt(form.querySelector('input[name=financial_target_vnd]').value || '3000000000'),
      lifestyle_choice: form.querySelector('input[name=lifestyle_choice]').value,
      label: form.querySelector('input[name=label]').value.trim(),
      keywords_for_market_demand: keywords,
      financial_inputs: {{
        aov_vnd: parseInt(form.querySelector('input[name=aov_vnd]').value || '1500000'),
        margin_pct: parseFloat(form.querySelector('input[name=margin_pct]').value || '60'),
      }},
      breakoutos_student_id: breakoutosSid,
    }};

    submitBtn.disabled = true;
    submitBtn.textContent = 'Đang chạy...';
    statusDiv.style.display = 'block';
    statusDiv.innerHTML = '<div class="loading-card"><div class="spinner"></div>9 engines đang chạy parallel + sequential. Ước tính 5-7 phút.<br><br>Bạn có thể đóng tab + check Telegram BreakoutOps để nhận notification khi xong.</div>';

    try {{
      const resp = await fetch('/cohort/chon-module/run', {{
        method: 'POST',
        headers: {{
          'Content-Type': 'application/json',
          'X-Cohort-Student-Token': token,
        }},
        body: JSON.stringify(body),
      }});
      const data = await resp.json();
      if (!resp.ok || !data.success) {{
        throw new Error(data.detail || data.error || 'Run failed');
      }}
      // Redirect to result page
      window.location.href = `/cohort/chon-module/runs/${{data.run_id}}/page?token=${{encodeURIComponent(token)}}`;
    }} catch (err) {{
      statusDiv.innerHTML = `<div class="card" style="border-left:4px solid #c00"><strong>Lỗi:</strong> ${{err.message}}</div>`;
      submitBtn.disabled = false;
      submitBtn.textContent = 'Chạy lại 9 Engines';
    }}
  }});

  // Update "Runs của tôi" link with token
  const token = document.querySelector('input[name=token]').value.trim();
  if (token) {{
    const sid = token.startsWith('wk2-b') ? `webinar-guest-${{token.split('-')[2]}}` :
                token.startsWith('cohort1-') ? token.split('-')[1] : 'unknown';
    document.getElementById('my-runs-link').href = `/cohort/chon-module/student/${{sid}}/page`;
  }}
</script>
</body>
</html>""")


@router.get("/runs/{run_id}/page", response_class=HTMLResponse)
async def chon_run_result_page(run_id: str, request: Request) -> HTMLResponse:
    """Result page: render full 9-engine output beautifully."""
    pool = await _db_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="DATABASE_URL not configured")
    async with pool.acquire() as conn:
        run = await conn.fetchrow("SELECT * FROM opportunity_run WHERE run_id=$1::uuid", run_id)
        if not run:
            await pool.close()
            raise HTTPException(status_code=404, detail="Run not found")
        breakdowns = await conn.fetch(
            "SELECT engine_name, sub_score, weight_pct, output_json, status "
            "FROM opportunity_score_breakdown WHERE run_id=$1::uuid",
            run_id,
        )
    await pool.close()

    import html as _html
    score = run["opportunity_score"] or 0
    classification = run["classification"] or "UNKNOWN"
    label = run["label"] or "(no label)"
    token = request.query_params.get("token", "")

    # Build sub-scores section
    weight_map = {"founder_fit": 20, "customer_problem": 25, "market_demand": 25,
                  "financial": 20, "lifestyle_fit": 10}
    def _decode(v):
        if isinstance(v, str):
            try: return json.loads(v)
            except Exception: return {}
        return v or {}
    bd_map = {}
    for _b in breakdowns:
        _d = dict(_b)
        _d["output_json"] = _decode(_d.get("output_json"))
        bd_map[_d["engine_name"]] = _d
    sub_html = '<div class="sub-grid">'
    for engine in ["founder_fit", "customer_problem", "market_demand", "financial", "lifestyle_fit"]:
        b = bd_map.get(engine, {})
        sub_score = b.get("sub_score", 0) or 0
        sub_html += f'''<div class="sub-item">
          <div class="sub-name">{engine.replace("_", " ").title()}</div>
          <div class="sub-score">{sub_score}/100</div>
          <div class="sub-weight">Weight {weight_map.get(engine, 0)}%</div>
        </div>'''
    sub_html += '</div>'

    # Engine detail sections (collapsible)
    engine_details = []
    engine_labels = {
        "founder_fit": "1. Founder Fit",
        "customer_problem": "2. Customer Problem",
        "desire": "3. Desire",
        "market_demand": "4. Market Demand",
        "solution_design": "5. Solution Design",
        "financial": "6. Financial Feasibility",
        "lifestyle_fit": "7. Lifestyle Fit",
        "decision": "8. Decision",
        "recommendation": "9. Recommendation",
    }
    report_keys = {
        "founder_fit": "founder_profile_report",
        "customer_problem": "customer_problem_report",
        "desire": "desire_report",
        "market_demand": "market_demand_report",
        "solution_design": "solution_report",
        "financial": "financial_report",
        "lifestyle_fit": "lifestyle_report",
        "recommendation": "recommendation_report",
    }
    for engine in ["founder_fit", "customer_problem", "desire", "market_demand",
                   "solution_design", "financial", "lifestyle_fit", "decision", "recommendation"]:
        b = bd_map.get(engine, {})
        out = b.get("output_json", {}) or {}
        report_key = report_keys.get(engine)
        report_md = out.get(report_key, "") if report_key else ""
        # Simple markdown → HTML
        report_html = _html.escape(report_md or "").replace("\n## ", "</p><h3>").replace("## ", "<h3>").replace("\n", "<br>")
        sub_score = b.get("sub_score")
        score_label = f"<strong>Score: {sub_score}/100</strong><br>" if sub_score is not None else ""
        engine_details.append(f'''<details class="card"><summary style="cursor:pointer;font-weight:600;color:#d63031">{engine_labels.get(engine, engine)}</summary>
          {score_label}
          <div class="report-md" style="margin-top:10px"><p>{report_html}</p></div>
        </details>''')

    pdf_url = f"/cohort/chon-module/runs/{run_id}/pdf"

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kết quả: {_html.escape(label)} | BreakoutOS CHỌN module</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="container">
  <div class="banner">
    <div class="label">BreakoutOS · Opportunity Run #{run["version"]}</div>
    <h1>{_html.escape(label)}</h1>
    <p>9 engines hoàn thành. Đây là Opportunity Score + breakdown chi tiết.</p>
  </div>

  <div class="card">
    <h2 style="text-align:center">Opportunity Score</h2>
    <div class="score-big">{score}/100</div>
    <div style="text-align:center;margin-top:8px"><span class="classification-badge cls-{classification}">{classification.replace("_", " ")}</span></div>
    {sub_html}
  </div>

  <h2 style="font-size:18px;margin:24px 0 12px;color:#444">Báo cáo chi tiết 9 engines</h2>
  {''.join(engine_details)}

  <div class="cta-block">
    <h3>Cần export PDF tất cả 10 reports?</h3>
    <p style="margin:0;font-size:13px;color:#666">Download 1 file PDF tổng hợp đầy đủ Founder Profile + Customer Problem + Desire + Market Demand + Solution + Financial + Lifestyle + Decision + Recommendation + Action Plan 30 ngày.</p>
    <a href="{pdf_url}?token={_html.escape(token)}" target="_blank">Download PDF</a>
  </div>

  <div class="footer">
    <a href="/cohort/chon-module/?token={_html.escape(token)}">Chạy opportunity mới</a> ·
    <a href="/cohort/chon-module/student/runs/page?token={_html.escape(token)}">So sánh runs của tôi</a>
  </div>
</div>
</body>
</html>""")


@router.get("/student/{student_id}/page", response_class=HTMLResponse)
async def chon_compare_page(student_id: str, request: Request) -> HTMLResponse:
    """Gap 2: Multi-opportunity compare view side-by-side."""
    pool = await _db_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="DATABASE_URL not configured")
    async with pool.acquire() as conn:
        runs = await conn.fetch(
            "SELECT run_id, version, label, opportunity_score, classification, status, "
            "completed_at FROM opportunity_run "
            "WHERE student_id=$1 AND status='completed' ORDER BY version DESC LIMIT 10",
            student_id,
        )
        # Pull sub-scores for top 3 to compare
        sub_scores_by_run = {}
        for r in runs[:5]:
            bd = await conn.fetch(
                "SELECT engine_name, sub_score FROM opportunity_score_breakdown "
                "WHERE run_id=$1::uuid",
                r["run_id"],
            )
            sub_scores_by_run[str(r["run_id"])] = {b["engine_name"]: b["sub_score"] for b in bd}
    await pool.close()

    import html as _html
    token = request.query_params.get("token", "")
    if not runs:
        body_html = '<div class="card"><p>Chưa có opportunity run nào. <a href="/cohort/chon-module/?token=' + _html.escape(token) + '">Chạy run đầu tiên</a>.</p></div>'
    else:
        # Build compare table
        compare_runs = list(runs[:5])
        header_cells = "<th>Engine</th>" + "".join(
            f"<th>v{r['version']}<br><small>{_html.escape(r['label'] or '')[:40]}</small></th>"
            for r in compare_runs
        )
        rows_html = []
        # Opportunity Score row
        rows_html.append(
            "<tr><td><strong>Opportunity Score</strong></td>" +
            "".join(
                f"<td><strong>{r['opportunity_score'] or 0}/100</strong><br><span class='classification-badge cls-{r['classification']}'>{(r['classification'] or '').replace('_', ' ')}</span></td>"
                for r in compare_runs
            ) +
            "</tr>"
        )
        # Sub-score rows
        for engine in ["founder_fit", "customer_problem", "desire", "market_demand",
                       "solution_design", "financial", "lifestyle_fit"]:
            cells = "".join(
                f"<td>{sub_scores_by_run.get(str(r['run_id']), {}).get(engine, '-')}/100</td>"
                for r in compare_runs
            )
            rows_html.append(f"<tr><td>{engine.replace('_', ' ').title()}</td>{cells}</tr>")
        # Actions row (link to detail)
        action_cells = "".join(
            f'<td><a href="/cohort/chon-module/runs/{r["run_id"]}/page?token={_html.escape(token)}" style="color:#d63031">Xem chi tiết</a></td>'
            for r in compare_runs
        )
        rows_html.append(f"<tr><td>Action</td>{action_cells}</tr>")

        body_html = f'''
        <div class="card">
          <h2>So sánh {len(compare_runs)} opportunity gần nhất</h2>
          <p style="font-size:13px;color:#666">Side-by-side compare để chọn opportunity tốt nhất đầu tư trước.</p>
          <table class="compare-table">
            <thead><tr>{header_cells}</tr></thead>
            <tbody>{''.join(rows_html)}</tbody>
          </table>
        </div>
        '''

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>So sánh runs | BreakoutOS CHỌN module</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="container">
  <div class="banner">
    <div class="label">BreakoutOS · Compare runs</div>
    <h1>Opportunity Compare</h1>
    <p>Student: {_html.escape(student_id)}</p>
  </div>
  {body_html}
  <div class="footer">
    <a href="/cohort/chon-module/?token={_html.escape(token)}">Chạy opportunity mới</a>
  </div>
</div>
</body>
</html>""")


# ============================================================================
# GAP 3: PDF export 10 reports
# ============================================================================

@router.get("/runs/{run_id}/pdf")
async def chon_run_pdf_export(run_id: str) -> Response:
    """Export 1 run → 1 PDF tổng hợp 10 reports."""
    pool = await _db_pool()
    if not pool:
        raise HTTPException(status_code=500, detail="DATABASE_URL not configured")
    async with pool.acquire() as conn:
        run = await conn.fetchrow("SELECT * FROM opportunity_run WHERE run_id=$1::uuid", run_id)
        if not run:
            await pool.close()
            raise HTTPException(status_code=404, detail="Run not found")
        breakdowns = await conn.fetch(
            "SELECT engine_name, sub_score, output_json FROM opportunity_score_breakdown "
            "WHERE run_id=$1::uuid",
            run_id,
        )
    await pool.close()

    # Try weasyprint first (proper PDF). Fall back to HTML inline if not installed.
    def _decode(v):
        if isinstance(v, str):
            try: return json.loads(v)
            except Exception: return {}
        return v or {}
    bd_map = {}
    for _b in breakdowns:
        _d = dict(_b)
        _d["output_json"] = _decode(_d.get("output_json"))
        bd_map[_d["engine_name"]] = _d
    import html as _html
    label = run["label"] or "(no label)"
    score = run["opportunity_score"] or 0
    classification = run["classification"] or "UNKNOWN"

    # Assemble big HTML
    report_keys = {
        "founder_fit": ("Founder Fit", "founder_profile_report"),
        "customer_problem": ("Customer Problem", "customer_problem_report"),
        "desire": ("Desire", "desire_report"),
        "market_demand": ("Market Demand", "market_demand_report"),
        "solution_design": ("Solution Design", "solution_report"),
        "financial": ("Financial Feasibility", "financial_report"),
        "lifestyle_fit": ("Lifestyle Fit", "lifestyle_report"),
        "recommendation": ("Breakout Recommendation", "recommendation_report"),
    }
    sections = []
    for engine, (title, report_key) in report_keys.items():
        b = bd_map.get(engine, {})
        out = b.get("output_json", {}) or {}
        report_md = out.get(report_key, "") if report_key else ""
        sub_score = b.get("sub_score")
        sub_label = f"<p><strong>Sub-score: {sub_score}/100</strong></p>" if sub_score is not None else ""
        report_html = _html.escape(report_md or "").replace("\n## ", "</p><h3>").replace("## ", "<h3>").replace("\n", "<br>")
        sections.append(f'<section><h2>{title}</h2>{sub_label}<div><p>{report_html}</p></div></section>')

    # Recommendation action plan
    rec_out = bd_map.get("recommendation", {}).get("output_json", {}) or {}
    action_plan = rec_out.get("action_plan_30_days", [])
    ap_html = ""
    if action_plan:
        ap_html = "<section><h2>Action Plan 30 ngày</h2><ol>"
        for wk in action_plan:
            ap_html += f"<li><strong>Tuần {wk.get('week')} — {_html.escape(wk.get('focus', ''))}</strong><br>"
            ap_html += "Actions: <ul>" + "".join(f"<li>{_html.escape(a)}</li>" for a in wk.get("actions", [])) + "</ul>"
            ap_html += f"Deliverable: {_html.escape(wk.get('deliverable', ''))}<br>"
            ap_html += f"Success metric: {_html.escape(wk.get('success_metric', ''))}</li>"
        ap_html += "</ol></section>"

    full_html = f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<title>{_html.escape(label)} | Opportunity Report</title>
<style>
@page {{ size: A4; margin: 2cm; }}
body {{ font-family: -apple-system, sans-serif; line-height: 1.6; color: #222; }}
h1 {{ color: #d63031; font-size: 24px; }}
h2 {{ color: #d63031; font-size: 18px; border-bottom: 2px solid #d63031; padding-bottom: 4px; margin-top: 30px; }}
h3 {{ font-size: 14px; color: #444; margin-top: 14px; }}
.cover {{ text-align: center; margin: 40px 0; }}
.cover .score {{ font-size: 56px; font-weight: 700; color: #d63031; margin: 16px 0; }}
.cover .badge {{ display: inline-block; padding: 6px 16px; background: #d63031; color: white; border-radius: 20px; font-size: 12px; }}
section {{ page-break-inside: avoid; margin-bottom: 30px; }}
ul, ol {{ padding-left: 22px; }}
small {{ color: #999; }}
</style>
</head>
<body>
  <div class="cover">
    <small>BreakoutOS · CHỌN ĐÚNG CÁI ĐỂ BÁN · Opportunity Report</small>
    <h1>{_html.escape(label)}</h1>
    <div class="score">{score}/100</div>
    <div class="badge">{classification.replace('_', ' ')}</div>
    <p><small>Generated: {run['completed_at'].strftime('%Y-%m-%d %H:%M') if run['completed_at'] else 'pending'}</small></p>
  </div>
  {''.join(sections)}
  {ap_html}
  <hr><p><small>BreakoutOS Core Module · Chốt spec 2026-06-11 · Anna Đào Thị Hằng</small></p>
</body></html>"""

    # Try WeasyPrint
    try:
        from weasyprint import HTML as WPHtml
        pdf_bytes = WPHtml(string=full_html).write_pdf()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="opportunity_{run_id[:8]}.pdf"'},
        )
    except ImportError:
        # Fallback: serve as HTML for browser print-to-PDF
        return HTMLResponse(
            content=full_html + '<script>setTimeout(() => window.print(), 800)</script>',
            headers={"Content-Disposition": f'inline; filename="opportunity_{run_id[:8]}.html"'},
        )
    except Exception as e:
        log.warning("PDF render fail: %r", e)
        # Fallback HTML
        return HTMLResponse(content=full_html)
