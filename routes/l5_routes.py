"""L5 Revenue Growth OS routes.

5 canonical: traffic-engine, lead-engine, sales-process, retention-engine, ascension-engine.
Gate 5: First Paid Customer ≥1M + 1 repeat/referral + 4 engine evidence.
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


log = logging.getLogger("camas.l5")
router = APIRouter(prefix="/sdl/l5", tags=["sdl-l5"], dependencies=[Depends(require_service_key)])


class L5IntakePayload(BaseModel):
    student_id: UUID
    traffic_channels: list[dict[str, Any]] = Field(default_factory=list)
    lead_capture: dict[str, Any] = Field(default_factory=dict)
    sales_stages: list[dict[str, Any]] = Field(default_factory=list)
    retention_plays: list[dict[str, Any]] = Field(default_factory=list)
    ascension_ladder: list[dict[str, Any]] = Field(default_factory=list)


L5_FILES = [
    ("traffic-engine", "Traffic Engine: Content + Ads + SEO + Referral"),
    ("lead-engine", "Lead Engine: Capture + Score + Segmentation"),
    ("sales-process", "Sales Process: Discovery + Follow-up + Proposal + Close"),
    ("retention-engine", "Retention Engine: Upsell + Cross-sell + Community + Referral"),
    ("ascension-engine", "Ascension Engine: Value Ladder LTV expansion"),
]


@router.post("/intake", status_code=201)
async def l5_intake(payload: L5IntakePayload, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    await require_level_access(pool, payload.student_id, 5, "L5 Revenue Growth OS")
    if not await check_gate_passed(pool, payload.student_id, "gate_4_business_operating"):
        raise HTTPException(403, "Gate 4 Business Operating chưa pass.")
    default_ascension = [
        {"tier": "Foundation", "price_vnd": 3_000_000},
        {"tier": "Customer System", "price_vnd": 6_000_000},
        {"tier": "Growth System", "price_vnd": 15_000_000},
        {"tier": "Breakout Founder", "price_vnd": 50_000_000},
    ]
    data_map = {
        "traffic-engine": {"channels": payload.traffic_channels or
                           [{"name": "Content"}, {"name": "Ads"}, {"name": "SEO"}, {"name": "Referral"}]},
        "lead-engine": payload.lead_capture or
                       {"capture": "Tally form", "score_formula": "lead-scoring 5am cron",
                        "segments": ["Hot ≥50", "Warm 30-49", "Cold <30"]},
        "sales-process": {"stages": payload.sales_stages or
                          [{"name": "Discovery", "duration": "30m call"},
                           {"name": "Follow-up", "rule": "no-response 24h/3d/7d"},
                           {"name": "Proposal", "trigger": "hot lead ≥5M"},
                           {"name": "Close", "channels": ["Sepay ≥500k", "Anna 1-1 ≥5M"]}]},
        "retention-engine": {"plays": payload.retention_plays or
                             [{"name": "Upsell", "trigger": "Tier complete"},
                              {"name": "Cross-sell"}, {"name": "Community"}, {"name": "Referral 10-20%"}]},
        "ascension-engine": {"ladder": payload.ascension_ladder or default_ascension,
                             "ltv_target_vnd": 74_000_000},
    }
    results = {}
    async with pool.acquire() as conn:
        for file_key, desc in L5_FILES:
            structured = data_map[file_key]
            md = (
                f"---\nfile_key: {file_key}\nstudent_id: {payload.student_id}\n"
                f"tier: C\nlock_type: strategic\nlocked: false\nai_generated: false\nversion: 1\n---\n\n"
                f"# {file_key.replace('-', ' ').title()}\n\n{desc}\n\n"
                f"```json\n{json.dumps(structured, ensure_ascii=False, indent=2)}\n```\n"
            )
            prev_v = await conn.fetchval(
                "SELECT max(version) FROM breakoutos.canonical_files "
                "WHERE student_id=$1 AND file_key=$2", payload.student_id, file_key,
            )
            next_v = (prev_v or 0) + 1
            row = await conn.fetchrow(
                """
                INSERT INTO breakoutos.canonical_files
                  (student_id, level, file_key, file_name, file_type, tier, lock_type,
                   markdown_content, structured_data_json, version, status, generated_by)
                VALUES ($1, 5, $2, $3, 'canonical', 'C', 'strategic',
                        $4, $5::jsonb, $6, 'reviewed', 'student')
                RETURNING id
                """,
                payload.student_id, file_key, f"{file_key}.md", md,
                json.dumps(structured, ensure_ascii=False), next_v,
            )
            results[file_key] = {"id": str(row["id"]), "version": next_v}
        await conn.execute(
            "UPDATE breakoutos.students SET current_level=5, current_gate='gate_5_revenue_growth_pending' "
            "WHERE id=$1", payload.student_id,
        )
    return {"status": "l5_canonical_saved", "files": results}


@router.get("/evidence")
async def l5_evidence(student_id: UUID, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    """Check L5 evidence: first paid customer ≥1M + 1 repeat/referral."""
    async with pool.acquire() as conn:
        revenue = await conn.fetchval(
            """
            SELECT count(*) FROM breakoutos.student_events
            WHERE student_id=$1 AND event_type='purchase.completed'
              AND (payload_json->>'amount_vnd')::int >= 1000000
            """,
            student_id,
        )
        repeat = await conn.fetchval(
            "SELECT count(*) FROM breakoutos.student_events "
            "WHERE student_id=$1 AND event_type IN ('purchase.repeat', 'referral.converted')",
            student_id,
        )
        traffic = await conn.fetchval(
            "SELECT count(*) FROM breakoutos.student_events "
            "WHERE student_id=$1 AND event_type LIKE 'traffic.%'", student_id,
        )
        leads = await conn.fetchval(
            "SELECT count(*) FROM breakoutos.student_events "
            "WHERE student_id=$1 AND event_type LIKE 'lead.%'", student_id,
        )
        sales = await conn.fetchval(
            "SELECT count(*) FROM breakoutos.student_events "
            "WHERE student_id=$1 AND event_type LIKE 'sales.%'", student_id,
        )
        retention = await conn.fetchval(
            "SELECT count(*) FROM breakoutos.student_events "
            "WHERE student_id=$1 AND event_type LIKE 'retention.%'", student_id,
        )
    engines_active = sum([traffic > 0, leads > 0, sales > 0, retention > 0])
    return {
        "student_id": str(student_id),
        "first_paid_customer_count": revenue,
        "repeat_or_referral_count": repeat,
        "engines_with_evidence": engines_active,
        "passes_gate_5": revenue >= 1 and repeat >= 1 and engines_active >= 4,
    }


@router.post("/gate-5/lock")
async def lock_gate_5(student_id: UUID, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    evidence = await l5_evidence(student_id, pool)
    if not evidence["passes_gate_5"]:
        raise HTTPException(412, {"error": "Evidence chưa đủ", "evidence": evidence})
    from routes.sdl_routes import lock_gate as sdl_lock_gate
    return await sdl_lock_gate(student_id, "gate_5_revenue_growth", pool)
