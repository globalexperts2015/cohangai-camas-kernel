"""L2 Customer Intelligence OS routes.

Tier A 4 file: who-i-serve, customer-profile, statement-mot-dong, opportunity-map
Tier B 7 file: why-this-customer, lived-experience, customer-empathy-map,
               demand-evidence, conversation-evidence, buying-journey, buying-triggers

Customer Fit Score 6 components (Anna V3.5): Lived 30/Empathy 20/Cred 15/Pain 15/Reach 10/WTP 10
Full VPC 10 dimensions (3 Jobs + 3 Pains + 4 Gains)
Statement Một Dòng 4 ý: WHO + CURRENT PAIN + DESIRED IDENTITY + VEHICLE

Gates:
- Gate 2A Customer SOFT lock @ T4
- Gate 2B Customer HARD lock @ T5+ (after L3 Offer Validation)
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from agents.l2_extraction import L2_EXTRACTION_REGISTRY, extract_l2_canonical, render_l2_markdown
from routes._auth import request_signature, require_student_signature
from routes.sdl_routes import get_pool, check_gate_passed


log = logging.getLogger("camas.l2")
router = APIRouter(prefix="/sdl/l2", tags=["sdl-l2"])


# ============================================================
# Schemas
# ============================================================
class CustomerJobs(BaseModel):
    functional: list[str] = []
    emotional: list[str] = []
    social: list[str] = []


class CustomerPains(BaseModel):
    obstacles: list[str] = []
    risks: list[str] = []
    frustrations: list[str] = []


class CustomerGains(BaseModel):
    required: list[str] = []
    expected: list[str] = []
    desired: list[str] = []
    unexpected: list[str] = []


class CustomerFitInput(BaseModel):
    lived_experience: int = Field(..., ge=0, le=10)
    empathy: int = Field(..., ge=0, le=10)
    credibility: int = Field(..., ge=0, le=10)
    pain: int = Field(..., ge=0, le=10)
    reach: int = Field(..., ge=0, le=10)
    wtp: int = Field(..., ge=0, le=10)


class StatementMotDong(BaseModel):
    who: str
    current_pain: str
    desired_identity: str
    vehicle: str
    full_statement: str = ""  # auto-composed if empty


class OpportunityScoredInput(BaseModel):
    name: str
    founder_fit_score: int = Field(..., ge=0, le=10)
    market_demand_score: int = Field(..., ge=0, le=10)
    monetization_score: int = Field(..., ge=0, le=10)
    ai_leverage_score: int = Field(..., ge=0, le=10)
    confidence_score: int = Field(..., ge=0, le=10)


class L2IntakePayload(BaseModel):
    student_id: UUID
    who_i_serve: str = Field(..., min_length=20)
    customer_profile_text: str = Field(..., min_length=30)
    customer_jobs: CustomerJobs
    customer_pains: CustomerPains
    customer_gains: CustomerGains
    customer_fit: CustomerFitInput
    statement_mot_dong: StatementMotDong
    opportunities: list[OpportunityScoredInput] = Field(..., min_length=1)
    selected_opportunity: str


def _compute_fit_score(fi: CustomerFitInput) -> dict:
    """Anna V3.5 weights: Lived 30/Empathy 20/Cred 15/Pain 15/Reach 10/WTP 10"""
    weighted = {
        "lived_experience": fi.lived_experience * 3.0,  # × 30/10
        "empathy": fi.empathy * 2.0,                    # × 20/10
        "credibility": fi.credibility * 1.5,            # × 15/10
        "pain": fi.pain * 1.5,                          # × 15/10
        "reach": fi.reach,                              # × 10/10
        "wtp": fi.wtp,                                  # × 10/10
    }
    total = sum(weighted.values())
    return {
        "components": fi.dict(),
        "weighted": weighted,
        "total": int(total),
        "passes_min_60": total >= 60,
    }


def _compose_statement(sm: StatementMotDong) -> str:
    if sm.full_statement.strip():
        return sm.full_statement
    return (
        f"Tôi giúp {sm.who} muốn {sm.current_pain} "
        f"trở thành {sm.desired_identity} "
        f"thông qua {sm.vehicle}."
    )


async def _save_l2_tier_a(
    conn: asyncpg.Connection, student_id: UUID, payload: L2IntakePayload,
) -> dict:
    """Save 4 Tier A files + customer_profile + opportunity_map typed rows."""
    fit_score = _compute_fit_score(payload.customer_fit)
    full_statement = _compose_statement(payload.statement_mot_dong)

    files_to_create = [
        ("who-i-serve", payload.who_i_serve, {"text": payload.who_i_serve}),
        ("customer-profile",
         payload.customer_profile_text,
         {
             "text": payload.customer_profile_text,
             "jobs": payload.customer_jobs.dict(),
             "pains": payload.customer_pains.dict(),
             "gains": payload.customer_gains.dict(),
             "fit_score": fit_score,
         }),
        ("statement-mot-dong",
         full_statement,
         payload.statement_mot_dong.dict() | {"full_statement": full_statement}),
        ("opportunity-map",
         json.dumps([o.dict() for o in payload.opportunities], ensure_ascii=False, indent=2),
         {
             "opportunities": [o.dict() for o in payload.opportunities],
             "selected": payload.selected_opportunity,
         }),
    ]

    results = {}
    for file_key, raw_text, structured in files_to_create:
        md = (
            f"---\nfile_key: {file_key}\nstudent_id: {student_id}\n"
            f"tier: A\nlock_type: strategic\nlocked: false\nai_generated: false\nversion: 1\n---\n\n"
            f"# {file_key.replace('-', ' ').title()}\n\n{raw_text}\n"
        )
        prev_v = await conn.fetchval(
            "SELECT max(version) FROM breakoutos.canonical_files "
            "WHERE student_id=$1 AND file_key=$2",
            student_id, file_key,
        )
        next_v = (prev_v or 0) + 1
        row = await conn.fetchrow(
            """
            INSERT INTO breakoutos.canonical_files
              (student_id, level, file_key, file_name, file_type, tier, lock_type,
               markdown_content, structured_data_json, version, status, generated_by)
            VALUES ($1, 2, $2, $3, 'canonical', 'A', 'strategic',
                    $4, $5::jsonb, $6, 'draft', 'student')
            RETURNING id
            """,
            student_id, file_key, f"{file_key}.md", md,
            json.dumps(structured, ensure_ascii=False), next_v,
        )
        results[file_key] = {"id": str(row["id"]), "version": next_v}

    # Upsert customer_profiles typed row
    await conn.execute(
        """
        INSERT INTO breakoutos.customer_profiles
          (student_id, target_customer, jobs_json, pains_json, gains_json,
           fit_score_json, status, version)
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6::jsonb, 'draft', 1)
        ON CONFLICT (student_id, version) DO UPDATE
        SET target_customer = EXCLUDED.target_customer,
            jobs_json = EXCLUDED.jobs_json,
            pains_json = EXCLUDED.pains_json,
            gains_json = EXCLUDED.gains_json,
            fit_score_json = EXCLUDED.fit_score_json,
            updated_at = now()
        """,
        student_id, payload.customer_profile_text,
        json.dumps(payload.customer_jobs.dict()),
        json.dumps(payload.customer_pains.dict()),
        json.dumps(payload.customer_gains.dict()),
        json.dumps(fit_score),
    )

    # Insert opportunity_map row
    sel = next((o for o in payload.opportunities if o.name == payload.selected_opportunity),
               payload.opportunities[0])
    await conn.execute(
        """
        INSERT INTO breakoutos.opportunity_maps
          (student_id, opportunities_json, selected_opportunity,
           founder_fit_score, market_demand_score, monetization_score,
           ai_leverage_score, confidence_score, status, version)
        VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7, $8, 'draft', 1)
        """,
        student_id,
        json.dumps([o.dict() for o in payload.opportunities]),
        payload.selected_opportunity,
        sel.founder_fit_score, sel.market_demand_score, sel.monetization_score,
        sel.ai_leverage_score, sel.confidence_score,
    )

    return {"files": results, "fit_score": fit_score, "statement_full": full_statement}


async def _trigger_l2_ai_extraction(
    pool: asyncpg.Pool, student_id: UUID, payload: L2IntakePayload,
) -> None:
    """Background: run 7 L2 Tier B extractions sequentially."""
    # Pull L1 context for richer extraction
    async with pool.acquire() as conn:
        fp = await conn.fetchrow(
            "SELECT identity, founder_assets_json, founder_story_json FROM breakoutos.founder_profiles "
            "WHERE student_id=$1 ORDER BY version DESC LIMIT 1",
            student_id,
        )

    inputs = {
        "who_i_serve": payload.who_i_serve,
        "customer_profile": payload.customer_profile_text,
        "statement_mot_dong": _compose_statement(payload.statement_mot_dong),
        "identity": fp["identity"] if fp else "(L1 chưa có)",
        "founder_assets": fp["founder_assets_json"] if fp else {},
        "founder_story": fp["founder_story_json"] if fp else {},
    }

    for file_key in L2_EXTRACTION_REGISTRY.keys():
        try:
            structured = await extract_l2_canonical(file_key, inputs)
            md = render_l2_markdown(file_key, structured, student_id)
            sig = hashlib.sha256(md.encode()).hexdigest()
            async with pool.acquire() as conn:
                prev_v = await conn.fetchval(
                    "SELECT max(version) FROM breakoutos.canonical_files "
                    "WHERE student_id=$1 AND file_key=$2",
                    student_id, file_key,
                )
                next_v = (prev_v or 0) + 1
                await conn.execute(
                    """
                    INSERT INTO breakoutos.canonical_files
                      (student_id, level, file_key, file_name, file_type, tier, lock_type,
                       markdown_content, structured_data_json, version, status, generated_by, ai_signature)
                    VALUES ($1, 2, $2, $3, 'canonical', 'B', 'strategic',
                            $4, $5::jsonb, $6, 'ai_generated', 'ai_haiku', $7)
                    """,
                    student_id, file_key, f"{file_key}.md", md,
                    json.dumps(structured, ensure_ascii=False), next_v, sig,
                )
                # Update typed customer_profiles columns
                col_map = {
                    "buying-journey": "buying_journey_json",
                    "buying-triggers": "buying_triggers_json",
                    "demand-evidence": "demand_evidence_json",
                    "conversation-evidence": "conversation_evidence_json",
                }
                if col_map.get(file_key):
                    await conn.execute(
                        f"UPDATE breakoutos.customer_profiles SET {col_map[file_key]}=$1::jsonb "
                        "WHERE student_id=$2 AND version=1",
                        json.dumps(structured, ensure_ascii=False), student_id,
                    )
        except Exception as exc:
            log.exception("L2 extract %s failed: %s", file_key, exc)


# ============================================================
# Endpoints
# ============================================================
@router.post("/intake", status_code=202)
async def l2_intake(
    payload: L2IntakePayload,
    background: BackgroundTasks,
    request: Request,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Submit L2 Tier A 4 file. Triggers 7 Tier B AI extract async."""
    sig = request_signature(request)
    require_student_signature(str(payload.student_id), sig)

    # Check Gate 1 passed (L1 done)
    if not await check_gate_passed(pool, payload.student_id, "gate_1_founder"):
        raise HTTPException(403, {
            "error": "Gate 1 Founder Cert chưa pass",
            "action": "complete_l1",
            "redirect": f"/foundation/l1?student={payload.student_id}&sig={sig}",
        })

    async with pool.acquire() as conn:
        result = await _save_l2_tier_a(conn, payload.student_id, payload)
        await conn.execute(
            "UPDATE breakoutos.students SET current_level=2, current_gate='gate_2_customer_pending', "
            "updated_at=now() WHERE id=$1",
            payload.student_id,
        )
        await conn.execute(
            """
            INSERT INTO breakoutos.student_events
              (student_id, event_type, source, level, payload_json)
            VALUES ($1, 'l2.intake.submitted', 'form', 2, $2::jsonb)
            """,
            payload.student_id,
            json.dumps({"fit_score": result["fit_score"]["total"]}),
        )

    # Telegram alert Anna real-time
    try:
        from routes.telegram_alert import alert_l2_intake_submitted
        async with pool.acquire() as conn:
            meta = await conn.fetchrow(
                "SELECT email, full_name FROM breakoutos.students WHERE id=$1",
                payload.student_id,
            )
        if meta:
            alert_l2_intake_submitted(
                str(payload.student_id), result["fit_score"]["total"],
                meta["email"] or "", meta["full_name"] or "",
            )
    except Exception:
        pass

    background.add_task(_trigger_l2_ai_extraction, pool, payload.student_id, payload)

    return {
        "status": "tier_a_saved_ai_extracting",
        "tier_a_files": result["files"],
        "fit_score_total": result["fit_score"]["total"],
        "fit_score_passes_60": result["fit_score"]["passes_min_60"],
        "statement_mot_dong": result["statement_full"],
        "tier_b_pending": list(L2_EXTRACTION_REGISTRY.keys()),
        "next_step": (
            f"/sdl/l2/canonical?student_id={payload.student_id}&sig={sig}"
        ),
    }


@router.get("/canonical")
async def list_l2_canonical(
    student_id: UUID,
    request: Request,
    sig: str = "",
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """List all L2 canonical file states."""
    require_student_signature(str(student_id), request_signature(request, sig))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (file_key) id, file_key, file_name, tier,
              status, version, generated_by, updated_at
            FROM breakoutos.canonical_files
            WHERE student_id=$1 AND level=2
            ORDER BY file_key, version DESC
            """,
            student_id,
        )
        expected = [
            ("who-i-serve", "A"), ("customer-profile", "A"),
            ("statement-mot-dong", "A"), ("opportunity-map", "A"),
            ("why-this-customer", "B"), ("lived-experience", "B"),
            ("customer-empathy-map", "B"), ("demand-evidence", "B"),
            ("conversation-evidence", "B"), ("buying-journey", "B"),
            ("buying-triggers", "B"),
        ]
        existing = {r["file_key"]: dict(r) for r in rows}
        state = []
        for key, tier in expected:
            if key in existing:
                state.append({"file_key": key, "tier": tier, **existing[key]})
            else:
                state.append({"file_key": key, "tier": tier, "status": "missing", "version": 0})
        return {
            "student_id": str(student_id),
            "level": 2,
            "canonical_files": state,
            "tier_a_count": sum(1 for f in state if f["tier"] == "A" and f["status"] != "missing"),
            "tier_b_count": sum(1 for f in state if f["tier"] == "B" and f["status"] != "missing"),
        }


@router.post("/gate-2a/lock")
async def lock_gate_2a(
    student_id: UUID,
    request: Request,
    sig: str = "",
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Gate 2A Customer SOFT Cert.

    Admin-only (Anna 2026-06-25): học viên không tự khóa Gate 2 / tự lên Level 3.
    """
    from routes.sdl_routes import require_admin_key
    require_admin_key(request)
    from routes.sdl_routes import lock_gate as sdl_lock_gate
    return await sdl_lock_gate(student_id, "gate_2_customer_soft", pool)


@router.post("/gate-2b/escalate")
async def escalate_gate_2b(
    student_id: UUID,
    request: Request,
    sig: str = "",
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Gate 2B HARD escalate (only after L3 Gate 3 passes)."""
    require_student_signature(str(student_id), request_signature(request, sig))
    if not await check_gate_passed(pool, student_id, "gate_3_value_proposition"):
        raise HTTPException(412, "Gate 3 Value Proposition chưa pass. Customer Hard chỉ escalate sau L3.")
    from routes.sdl_routes import lock_gate as sdl_lock_gate
    return await sdl_lock_gate(student_id, "gate_2_customer_hard", pool)
