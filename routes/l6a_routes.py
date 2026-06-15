"""L6a Founder Freedom OS routes.

4 canonical: freedom-score, weekly-review, ai-twin, ceo-dashboard.
Gate 6a: Freedom Score ≥70 + 8 weekly reviews approved.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from routes.sdl_routes import get_pool, check_gate_passed
from routes._auth import require_service_key


log = logging.getLogger("camas.l6a")
router = APIRouter(prefix="/sdl/l6a", tags=["sdl-l6a"], dependencies=[Depends(require_service_key)])


L6A_FILES = [
    ("freedom-score", "Founder Freedom Score: 7 components, North Star Metric"),
    ("weekly-review", "Weekly Review: Auto-draft Sun 8pm, founder approve Mon 8am"),
    ("ai-twin", "AI Twin: /sdl/students/{id}/memory/query API"),
    ("ceo-dashboard", "CEO Dashboard: revenue + funnel + customer health + 1 decision pending"),
]


@router.post("/intake", status_code=201)
async def l6a_intake(student_id: UUID, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    if not await check_gate_passed(pool, student_id, "gate_5_revenue_growth"):
        raise HTTPException(403, "Gate 5 Revenue Growth chưa pass.")
    data_map = {
        "freedom-score": {
            "components": ["Revenue 18", "Time 18", "Stress 13", "Clarity 13",
                          "Automation 10", "Mission 18", "Dependency 10"],
            "target": 70, "max": 100,
            "dependency_levels": ["D3", "D7", "D30", "D90"],
        },
        "weekly-review": {
            "auto_draft_cron": "Sun 8pm AWST",
            "founder_approve_by": "Mon 8am",
            "review_period": "8 weeks consecutive for graduation",
        },
        "ai-twin": {
            "endpoint": f"/sdl/students/{student_id}/memory/query",
            "data_sources": ["agent_memory pgvector", "canonical_files vault"],
        },
        "ceo-dashboard": {
            "widgets": ["revenue_ytd", "funnel_rate", "customer_health", "decision_pending"],
        },
    }
    results = {}
    async with pool.acquire() as conn:
        for file_key, desc in L6A_FILES:
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
                VALUES ($1, 6, $2, $3, 'canonical', 'C', 'strategic',
                        $4, $5::jsonb, $6, 'reviewed', 'student')
                RETURNING id
                """,
                student_id, file_key, f"{file_key}.md", md,
                json.dumps(structured, ensure_ascii=False), next_v,
            )
            results[file_key] = {"id": str(row["id"]), "version": next_v}
        await conn.execute(
            "UPDATE breakoutos.students SET current_level=6, current_gate='gate_6a_founder_freedom_pending' "
            "WHERE id=$1", student_id,
        )
    return {"status": "l6a_canonical_saved", "files": results}


@router.get("/eligibility")
async def l6a_eligibility(student_id: UUID, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    """Gate 6a: Freedom Score ≥70 + 8 weekly reviews approved."""
    async with pool.acquire() as conn:
        latest_score = await conn.fetchval(
            "SELECT total_score FROM breakoutos.v_freedom_score_latest WHERE student_id=$1",
            student_id,
        )
        weekly_count = await conn.fetchval(
            "SELECT count(*) FROM breakoutos.student_events "
            "WHERE student_id=$1 AND event_type='ai_coo.weekly_review.approved'",
            student_id,
        )
    passes = (latest_score or 0) >= 70 and (weekly_count or 0) >= 8
    return {
        "student_id": str(student_id),
        "latest_freedom_score": latest_score,
        "weekly_reviews_approved": weekly_count,
        "thresholds": {"freedom_score": 70, "weekly_reviews": 8},
        "passes_gate_6a": passes,
    }


@router.post("/gate-6a/lock")
async def lock_gate_6a(student_id: UUID, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    elig = await l6a_eligibility(student_id, pool)
    if not elig["passes_gate_6a"]:
        raise HTTPException(412, {"error": "Chưa đủ điều kiện graduate", "eligibility": elig})
    from routes.sdl_routes import lock_gate as sdl_lock_gate
    result = await sdl_lock_gate(student_id, "gate_6a_founder_freedom", pool)
    result["graduated"] = True
    result["founder_freedom_status"] = "ACHIEVED"
    return result
