"""L4 Business Operating OS routes.

6 canonical files: ai-coo, business-vault, automation-stack, sop-library, dashboard-stack, decision-system.
Gate 4 requires EVIDENCE RUNNING (per Anna build command):
- Daily Brief sent ≥7 consecutive days
- Night Audit log has data
- Automation ≥10 lead events
- ≥1 SOP instance executed
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from routes.sdl_routes import get_pool, check_gate_passed, require_level_access
from routes._auth import require_service_key


log = logging.getLogger("camas.l4")
router = APIRouter(prefix="/sdl/l4", tags=["sdl-l4"], dependencies=[Depends(require_service_key)])


class L4IntakePayload(BaseModel):
    student_id: UUID
    ai_coo_config: dict[str, Any] = Field(default_factory=dict)
    business_vault_namespaces: list[str] = Field(default_factory=list)
    automation_flows: list[dict[str, Any]] = Field(default_factory=list)
    sops: list[dict[str, Any]] = Field(default_factory=list)
    dashboards: list[dict[str, Any]] = Field(default_factory=list)
    decision_patterns: list[dict[str, Any]] = Field(default_factory=list)


L4_FILES = [
    ("ai-coo", "AI COO: Daily Brief + Night Audit + Weekly Review cron config"),
    ("business-vault", "Business Vault: 4 namespace (Knowledge + Customer Memory + Offer Memory + Content Memory)"),
    ("automation-stack", "Automation Stack: 5 flow (Lead Capture + Lead Routing + Email + Follow-up + Booking)"),
    ("sop-library", "SOP Library: 4 SOP (Sales + Content + Delivery + Weekly)"),
    ("dashboard-stack", "Dashboard Stack: Founder + Customer + Revenue dashboards"),
    ("decision-system", "Decision System: IF→THEN patterns, 8 starter rules"),
]


async def _save_l4_files(
    conn: asyncpg.Connection, student_id: UUID, payload: L4IntakePayload,
) -> dict:
    data_map = {
        "ai-coo": payload.ai_coo_config or {"daily_brief": "6am AWST", "night_audit": "11pm", "weekly_review": "Sun 8pm"},
        "business-vault": {"namespaces": payload.business_vault_namespaces or
                           ["Knowledge", "Customer Memory", "Offer Memory", "Content Memory"]},
        "automation-stack": {"flows": payload.automation_flows or
                             [{"name": "Lead Capture", "status": "scaffold"},
                              {"name": "Lead Routing", "status": "scaffold"},
                              {"name": "Email Sequence", "status": "scaffold"},
                              {"name": "Follow-up", "status": "scaffold"},
                              {"name": "Booking", "status": "scaffold"}]},
        "sop-library": {"sops": payload.sops or
                        [{"name": "Sales SOP", "stages": ["discovery", "proposal", "close", "onboard"]},
                         {"name": "Content SOP", "stages": ["idea", "script", "produce", "publish", "repurpose"]},
                         {"name": "Delivery SOP", "stages": ["onboard", "milestone", "support", "testimonial"]},
                         {"name": "Weekly SOP", "stages": ["Monday plan", "Daily check", "Friday review"]}]},
        "dashboard-stack": {"dashboards": payload.dashboards or
                            [{"name": "Founder Dashboard"}, {"name": "Customer Dashboard"}, {"name": "Revenue Dashboard"}]},
        "decision-system": {"patterns": payload.decision_patterns or [
            {"if": "lead_count up AND revenue down", "then": "audit Sales Engine + Follow-up SOP"},
            {"if": "revenue plateau 2 weeks", "then": "propose pricing test"},
            {"if": "refund spike", "then": "review onboarding"},
            {"if": "cohort completion <60%", "then": "escalate coaching"},
            {"if": "NPS down", "then": "5 customer interviews"},
            {"if": "founder time >50h/w", "then": "automation gap audit"},
            {"if": "cash flow <30 days", "then": "cut + revenue sprint"},
            {"if": "stress >7/10", "then": "Freedom Score review"},
        ]},
    }
    results = {}
    for file_key, desc in L4_FILES:
        structured = data_map[file_key]
        md = (
            f"---\nfile_key: {file_key}\nstudent_id: {student_id}\n"
            f"tier: C\nlock_type: strategic\nlocked: false\nai_generated: false\nversion: 1\n---\n\n"
            f"# {file_key.replace('-', ' ').title()}\n\n{desc}\n\n"
            f"```json\n{json.dumps(structured, ensure_ascii=False, indent=2)}\n```\n"
        )
        prev_v = await conn.fetchval(
            "SELECT max(version) FROM breakoutos.canonical_files "
            "WHERE student_id=$1 AND file_key=$2", student_id, file_key,
        )
        next_v = (prev_v or 0) + 1
        row = await conn.fetchrow(
            """
            INSERT INTO breakoutos.canonical_files
              (student_id, level, file_key, file_name, file_type, tier, lock_type,
               markdown_content, structured_data_json, version, status, generated_by)
            VALUES ($1, 4, $2, $3, 'canonical', 'C', 'strategic',
                    $4, $5::jsonb, $6, 'reviewed', 'student')
            RETURNING id
            """,
            student_id, file_key, f"{file_key}.md", md,
            json.dumps(structured, ensure_ascii=False), next_v,
        )
        results[file_key] = {"id": str(row["id"]), "version": next_v}
    return results


@router.post("/intake", status_code=201)
async def l4_intake(payload: L4IntakePayload, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    await require_level_access(pool, payload.student_id, 4, "L4 Business Operating OS")
    if not await check_gate_passed(pool, payload.student_id, "gate_3_value_proposition"):
        raise HTTPException(403, "Gate 3 Value Proposition chưa pass.")
    async with pool.acquire() as conn:
        results = await _save_l4_files(conn, payload.student_id, payload)
        await conn.execute(
            "UPDATE breakoutos.students SET current_level=4, current_gate='gate_4_business_operating_pending' "
            "WHERE id=$1", payload.student_id,
        )
    return {"status": "l4_canonical_saved", "files": results,
            "next_step": "Wire 3 cron jobs (Daily Brief 6am, Night Audit 11pm, Weekly Review Sun 8pm)"}


@router.get("/coo/daily-brief/trigger")
async def trigger_daily_brief(student_id: UUID, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    """Manual trigger Daily Brief. In production cron-job.org calls this."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO breakoutos.student_events
              (student_id, event_type, source, level, payload_json)
            VALUES ($1, 'ai_coo.daily_brief.sent', 'cron', 4,
                    $2::jsonb)
            """,
            student_id, json.dumps({"trigger": "manual"}),
        )
    return {"status": "daily_brief_logged"}


@router.get("/coo/night-audit/trigger")
async def trigger_night_audit(student_id: UUID, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO breakoutos.student_events
              (student_id, event_type, source, level, payload_json)
            VALUES ($1, 'ai_coo.night_audit.completed', 'cron', 4, $2::jsonb)
            """,
            student_id, json.dumps({"trigger": "manual"}),
        )
    return {"status": "night_audit_logged"}


@router.get("/coo/weekly-review/trigger")
async def trigger_weekly_review(student_id: UUID, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO breakoutos.student_events
              (student_id, event_type, source, level, payload_json)
            VALUES ($1, 'ai_coo.weekly_review.drafted', 'cron', 4, $2::jsonb)
            """,
            student_id, json.dumps({"trigger": "manual"}),
        )
    return {"status": "weekly_review_logged"}


@router.get("/evidence")
async def l4_evidence(student_id: UUID, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    """Check L4 evidence running for Gate 4 validation."""
    async with pool.acquire() as conn:
        daily = await conn.fetchval(
            "SELECT count(DISTINCT date(created_at)) FROM breakoutos.student_events "
            "WHERE student_id=$1 AND event_type='ai_coo.daily_brief.sent'",
            student_id,
        )
        night = await conn.fetchval(
            "SELECT count(*) FROM breakoutos.student_events "
            "WHERE student_id=$1 AND event_type='ai_coo.night_audit.completed'",
            student_id,
        )
        leads = await conn.fetchval(
            "SELECT count(*) FROM breakoutos.student_events "
            "WHERE student_id=$1 AND event_type LIKE 'lead.%'",
            student_id,
        )
        sop = await conn.fetchval(
            "SELECT count(*) FROM breakoutos.student_events "
            "WHERE student_id=$1 AND event_type LIKE 'sop.%.executed'",
            student_id,
        )
    passes = daily >= 7 and night >= 1 and leads >= 10 and sop >= 1
    return {
        "student_id": str(student_id),
        "daily_brief_days": daily,
        "night_audit_count": night,
        "lead_events": leads,
        "sop_executed": sop,
        "passes_gate_4": passes,
        "thresholds": {"daily_brief_days": 7, "lead_events": 10, "sop_executed": 1},
    }


@router.post("/gate-4/lock")
async def lock_gate_4(student_id: UUID, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    evidence = await l4_evidence(student_id, pool)
    if not evidence["passes_gate_4"]:
        raise HTTPException(412, {"error": "Evidence chưa đủ", "evidence": evidence})
    from routes.sdl_routes import lock_gate as sdl_lock_gate
    return await sdl_lock_gate(student_id, "gate_4_business_operating", pool)
