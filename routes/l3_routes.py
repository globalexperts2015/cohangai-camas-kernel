"""L3 Value Proposition OS routes.

Module CHỌN E6-E9 home (đã có tại /cohort/chon-module/).
L3 wraps with gate check + canonical save.

Tier A 4 file: core-offer, pricing-strategy, transformation-promise, positioning-statement
Tier B 4 file: offer-stack, financial-model, value-equation, guarantee-strategy
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

from routes._auth import request_signature, require_student_signature
from routes.sdl_routes import get_pool, check_gate_passed, require_level_access


log = logging.getLogger("camas.l3")
router = APIRouter(prefix="/sdl/l3", tags=["sdl-l3"])


# ============================================================
# Schemas
# ============================================================
class L3IntakePayload(BaseModel):
    student_id: UUID
    core_offer_name: str = Field(..., min_length=5)
    core_offer_description: str = Field(..., min_length=30)
    target_customer: str
    pain: str
    desired_identity: str
    vehicle: str
    transformation: str
    pricing_tier: str = "Foundation"
    price_vnd: int = Field(..., ge=100000)
    pricing_rationale: str
    # Positioning
    positioning_category: str
    positioning_frame: str
    positioning_pod: str   # Point of difference
    positioning_rtb: str   # Reason to believe
    positioning_attitude: str = ""


# ============================================================
# Helpers
# ============================================================
async def _save_l3_tier_a(
    conn: asyncpg.Connection, student_id: UUID, payload: L3IntakePayload,
) -> dict:
    """Save 4 Tier A canonical files."""
    transformation_md = f"X → Y · {payload.transformation}"
    positioning_full = (
        f"We are {payload.positioning_category}. "
        f"Unlike {payload.positioning_frame}, we {payload.positioning_pod}. "
        f"Reason to believe: {payload.positioning_rtb}."
    )

    files = [
        ("core-offer",
         f"## {payload.core_offer_name}\n\n{payload.core_offer_description}\n\n"
         f"**Target:** {payload.target_customer}\n**Pain:** {payload.pain}\n"
         f"**Desired Identity:** {payload.desired_identity}\n**Vehicle:** {payload.vehicle}\n"
         f"**Price:** {payload.price_vnd:,} VND",
         {
             "name": payload.core_offer_name,
             "description": payload.core_offer_description,
             "target_customer": payload.target_customer,
             "pain": payload.pain,
             "desired_identity": payload.desired_identity,
             "vehicle": payload.vehicle,
             "transformation": payload.transformation,
             "price_vnd": payload.price_vnd,
         }),
        ("pricing-strategy",
         f"## Pricing Strategy\n\n**Tier:** {payload.pricing_tier}\n"
         f"**Price:** {payload.price_vnd:,} VND\n\n**Rationale:** {payload.pricing_rationale}",
         {"tier": payload.pricing_tier, "price_vnd": payload.price_vnd,
          "rationale": payload.pricing_rationale}),
        ("transformation-promise", transformation_md,
         {"x_to_y": payload.transformation,
          "desired_identity": payload.desired_identity, "vehicle": payload.vehicle}),
        ("positioning-statement", positioning_full,
         {
             "category": payload.positioning_category,
             "frame_of_reference": payload.positioning_frame,
             "point_of_difference": payload.positioning_pod,
             "reason_to_believe": payload.positioning_rtb,
             "target_attitude": payload.positioning_attitude,
             "full_statement": positioning_full,
         }),
    ]

    results = {}
    for file_key, raw_text, structured in files:
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
            VALUES ($1, 3, $2, $3, 'canonical', 'A', 'strategic',
                    $4, $5::jsonb, $6, 'draft', 'student')
            RETURNING id
            """,
            student_id, file_key, f"{file_key}.md", md,
            json.dumps(structured, ensure_ascii=False), next_v,
        )
        results[file_key] = {"id": str(row["id"]), "version": next_v}

    # Upsert offers + positioning typed
    await conn.execute(
        """
        INSERT INTO breakoutos.offers
          (student_id, offer_name, target_customer, pain, desired_identity, vehicle,
           transformation, pricing_json, status, version)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, 'draft', 1)
        ON CONFLICT DO NOTHING
        """,
        student_id, payload.core_offer_name, payload.target_customer,
        payload.pain, payload.desired_identity, payload.vehicle, payload.transformation,
        json.dumps({"tier": payload.pricing_tier, "price_vnd": payload.price_vnd}),
    )
    await conn.execute(
        """
        INSERT INTO breakoutos.positioning_profiles
          (student_id, category, unique_angle, positioning_statement, status, version)
        VALUES ($1, $2, $3, $4, 'draft', 1)
        ON CONFLICT DO NOTHING
        """,
        student_id, payload.positioning_category,
        payload.positioning_pod, positioning_full,
    )

    return {"files": results, "positioning_statement": positioning_full}


async def _generate_l3_tier_b(
    pool: asyncpg.Pool, student_id: UUID, payload: L3IntakePayload,
) -> None:
    """Tier B Hormozi Value Equation + Guarantee + Offer Stack + Financial Model.
    Uses Anthropic Opus for offer reasoning quality."""
    import os
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    prompt = f"""Bạn là Hormozi Offer Architect. Sinh 4 file JSON cho offer của founder.

INPUT:
Core Offer: {payload.core_offer_name} - {payload.core_offer_description}
Target: {payload.target_customer}
Pain: {payload.pain}
Desired Identity: {payload.desired_identity}
Vehicle: {payload.vehicle}
Transformation: {payload.transformation}
Price: {payload.price_vnd:,} VND
Pricing Tier: {payload.pricing_tier}

OUTPUT JSON (strict, 4 keys):
{{
  "offer_stack": {{
    "free_tier": "...", "entry_tier": "...", "core_tier": "...",
    "premium_tier": "...", "ascension_tier": "...",
    "ladder_logic": "1 đoạn giải thích flow nâng cấp"
  }},
  "financial_model": {{
    "margin_pct": <int>, "aov_vnd": <int>, "break_even_customers": <int>,
    "12_month_revenue_forecast_vnd": <int>,
    "scenario_pessimistic": <int>, "scenario_realistic": <int>, "scenario_optimistic": <int>
  }},
  "value_equation": {{
    "dream_outcome": <int 1-10>, "perceived_likelihood": <int 1-10>,
    "time_delay": <int 1-10>, "effort_sacrifice": <int 1-10>,
    "value_score": <float>,
    "improvement_recommendations": [<list 3-5>]
  }},
  "guarantee_strategy": {{
    "recommended_tier": "conditional|unconditional|performance|service|lifetime",
    "description": "...",
    "cost_to_deliver": "...",
    "wtp_impact_pct": <int>,
    "five_tier_options": [
      {{"tier": "conditional", "desc": "..."}},
      {{"tier": "unconditional", "desc": "..."}},
      {{"tier": "performance", "desc": "..."}},
      {{"tier": "service", "desc": "..."}},
      {{"tier": "lifetime", "desc": "..."}}
    ]
  }}
}}

Chỉ trả JSON. Tiếng Việt thuần. Không "—"."""

    try:
        resp = await client.messages.create(
            model="claude-opus-4-7", max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            if raw.endswith("```"): raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()
        if raw.startswith("json"): raw = raw[4:].strip()
        data = json.loads(raw)
    except Exception as exc:
        log.exception("L3 Tier B Opus failed: %s", exc)
        return

    file_map = {
        "offer-stack": data.get("offer_stack", {}),
        "offer-financial-model": data.get("financial_model", {}),
        "value-equation": data.get("value_equation", {}),
        "guarantee-strategy": data.get("guarantee_strategy", {}),
    }
    async with pool.acquire() as conn:
        for file_key, structured in file_map.items():
            md = (
                f"---\nfile_key: {file_key}\nstudent_id: {student_id}\n"
                f"tier: B\nlock_type: strategic\nlocked: false\nai_generated: true\nversion: 1\n---\n\n"
                f"# {file_key.replace('-', ' ').title()}\n\n"
                f"```json\n{json.dumps(structured, ensure_ascii=False, indent=2)}\n```\n"
            )
            sig = hashlib.sha256(md.encode()).hexdigest()
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
                VALUES ($1, 3, $2, $3, 'canonical', 'B', 'strategic',
                        $4, $5::jsonb, $6, 'ai_generated', 'ai_opus', $7)
                """,
                student_id, file_key, f"{file_key}.md", md,
                json.dumps(structured, ensure_ascii=False), next_v, sig,
            )


# ============================================================
# Endpoints
# ============================================================
@router.post("/intake", status_code=202)
async def l3_intake(
    payload: L3IntakePayload,
    background: BackgroundTasks,
    request: Request,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    sig = request_signature(request)
    require_student_signature(str(payload.student_id), sig)
    await require_level_access(pool, payload.student_id, 3, "L3 Value Proposition OS")
    if not await check_gate_passed(pool, payload.student_id, "gate_2_customer_soft"):
        raise HTTPException(403, "Gate 2A Customer Soft chưa pass. Hoàn thành L2 trước.")

    async with pool.acquire() as conn:
        result = await _save_l3_tier_a(conn, payload.student_id, payload)
        await conn.execute(
            "UPDATE breakoutos.students SET current_level=3, current_gate='gate_3_value_proposition_pending' "
            "WHERE id=$1", payload.student_id,
        )
        await conn.execute(
            """
            INSERT INTO breakoutos.student_events
              (student_id, event_type, source, level, payload_json)
            VALUES ($1, 'l3.intake.submitted', 'form', 3, $2::jsonb)
            """,
            payload.student_id, json.dumps({"offer": payload.core_offer_name}),
        )

    # Telegram alert Anna real-time
    try:
        from routes.telegram_alert import alert_l3_intake_submitted
        async with pool.acquire() as conn:
            meta = await conn.fetchrow(
                "SELECT email, full_name FROM breakoutos.students WHERE id=$1",
                payload.student_id,
            )
        if meta:
            alert_l3_intake_submitted(
                str(payload.student_id), payload.core_offer_name,
                meta["email"] or "", meta["full_name"] or "",
            )
    except Exception:
        pass

    background.add_task(_generate_l3_tier_b, pool, payload.student_id, payload)
    return {
        "status": "tier_a_saved_ai_extracting",
        "tier_a_files": result["files"],
        "positioning_statement": result["positioning_statement"],
        "tier_b_pending": ["offer-stack", "offer-financial-model", "value-equation", "guarantee-strategy"],
        "next_step": (
            "Run Module CHỌN E6-E9 at /cohort/chon-module/"
            f"?student={payload.student_id}&sig={sig}"
        ),
    }


@router.get("/canonical")
async def list_l3_canonical(
    student_id: UUID,
    request: Request,
    sig: str = "",
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    require_student_signature(str(student_id), request_signature(request, sig))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (file_key) id, file_key, tier, status, version,
              generated_by, updated_at
            FROM breakoutos.canonical_files WHERE student_id=$1 AND level=3
            ORDER BY file_key, version DESC
            """,
            student_id,
        )
        expected = [
            ("core-offer", "A"), ("pricing-strategy", "A"),
            ("transformation-promise", "A"), ("positioning-statement", "A"),
            ("offer-stack", "B"), ("offer-financial-model", "B"),
            ("value-equation", "B"), ("guarantee-strategy", "B"),
        ]
        existing = {r["file_key"]: dict(r) for r in rows}
        state = [
            ({"file_key": k, "tier": t, **existing[k]} if k in existing
             else {"file_key": k, "tier": t, "status": "missing", "version": 0})
            for k, t in expected
        ]
        return {"student_id": str(student_id), "level": 3, "canonical_files": state}


@router.post("/gate-3/lock")
async def lock_gate_3(
    student_id: UUID,
    request: Request,
    sig: str = "",
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Gate 3 Hard Lock + auto escalate Gate 2B Customer Hard."""
    require_student_signature(str(student_id), request_signature(request, sig))
    from routes.sdl_routes import lock_gate as sdl_lock_gate
    g3 = await sdl_lock_gate(student_id, "gate_3_value_proposition", pool)
    # Auto escalate Gate 2B Customer Hard
    try:
        g2b = await sdl_lock_gate(student_id, "gate_2_customer_hard", pool)
        g3["gate_2b_escalated"] = g2b
    except Exception as exc:
        g3["gate_2b_escalate_warning"] = str(exc)
    return g3
