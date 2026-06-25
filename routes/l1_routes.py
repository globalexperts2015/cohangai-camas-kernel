"""L1 Founder OS routes.

Per Anna's build command + V3.5.7:
- POST /sdl/l1/intake          Student submits Tier A (5 file content) + trigger AI extract Tier B
- GET  /sdl/l1/canonical       List all L1 canonical files current state
- POST /sdl/l1/extract/{key}   Re-run AI extraction for one Tier B file
- POST /sdl/l1/gate-1/validate Check 8 files ready for lock
- POST /sdl/l1/gate-1/lock     Hard lock Gate 1, snapshot final-vision + final-founder-identity
- GET  /foundation/l1          HTML intake form student-facing
- GET  /sdl/l1/output/{id}     Day 1 webinar output page (signed token)

Blocks L1 access HTTP 412 if no baseline (Freedom Score T0 mandatory).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agents.l1_extraction import EXTRACTION_REGISTRY, extract_canonical, render_markdown
from routes._auth import request_signature, require_student_signature
from routes.freedom_score_routes import has_baseline
from routes.sdl_routes import get_pool


log = logging.getLogger("camas.l1")
router = APIRouter(prefix="/sdl/l1", tags=["sdl-l1"])


# ============================================================
# Tier A intake payload
# ============================================================
class L1IntakePayload(BaseModel):
    student_id: UUID
    life_mission: str = Field(..., min_length=20)
    vision_statement: str = Field(..., min_length=20)
    founder_identity: str = Field(..., min_length=20)
    decision_principles: list[str] = Field(..., min_length=3)
    anti_vision: list[str] = Field(..., min_length=3)
    # Optional context for Tier B extraction
    lived_experience: str = ""
    customer_direction: str = ""


# ============================================================
# Helpers
# ============================================================
async def _ensure_baseline_or_412(
    pool: asyncpg.Pool, student_id: UUID, sig: str = "",
) -> None:
    if not await has_baseline(pool, student_id):
        suffix = f"&sig={sig}" if sig else ""
        raise HTTPException(412, {
            "error": "T0 baseline missing",
            "action": "fill_baseline",
            "redirect": f"/foundation/baseline?student={student_id}{suffix}",
        })


def _ready_for_gate_1(canonical_state: list[dict[str, Any]]) -> bool:
    return len(canonical_state) == 8 and all(
        file_state["status"] in ("reviewed", "locked")
        for file_state in canonical_state
    )


async def _save_tier_a_files(
    conn: asyncpg.Connection, student_id: UUID, payload: L1IntakePayload,
) -> dict[str, dict[str, Any]]:
    """Save 5 Tier A files to canonical_files + founder_profiles."""
    files_to_create = [
        ("life-mission", payload.life_mission, {"text": payload.life_mission}),
        ("vision-statement", payload.vision_statement, {"text": payload.vision_statement}),
        ("founder-identity", payload.founder_identity, {"text": payload.founder_identity}),
        ("decision-principles", "\n".join(f"- {p}" for p in payload.decision_principles),
         {"principles": payload.decision_principles}),
        ("anti-vision", "\n".join(f"- KHÔNG {a}" for a in payload.anti_vision),
         {"items": payload.anti_vision}),
    ]

    results = {}
    for file_key, raw_text, structured in files_to_create:
        md = (
            f"---\nfile_key: {file_key}\nstudent_id: {student_id}\n"
            f"tier: A\nlock_type: core\nlocked: false\nai_generated: false\nversion: 1\n---\n\n"
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
            VALUES ($1, 1, $2, $3, 'canonical', 'A', 'core',
                    $4, $5::jsonb, $6, 'draft', 'student')
            RETURNING id
            """,
            student_id, file_key, f"{file_key}.md", md,
            json.dumps(structured), next_v,
        )
        results[file_key] = {"id": str(row["id"]), "version": next_v}

    # Upsert founder_profiles row
    await conn.execute(
        """
        INSERT INTO breakoutos.founder_profiles
          (student_id, mission, vision, identity, principles_json, anti_vision_json, status, version)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, 'draft', 1)
        ON CONFLICT (student_id, version) DO UPDATE
        SET mission = EXCLUDED.mission,
            vision = EXCLUDED.vision,
            identity = EXCLUDED.identity,
            principles_json = EXCLUDED.principles_json,
            anti_vision_json = EXCLUDED.anti_vision_json,
            updated_at = now()
        """,
        student_id, payload.life_mission, payload.vision_statement,
        payload.founder_identity,
        json.dumps(payload.decision_principles),
        json.dumps(payload.anti_vision),
    )
    return results


async def _trigger_ai_extraction(
    pool: asyncpg.Pool, student_id: UUID, payload: L1IntakePayload,
) -> None:
    """Background task: run 3 Tier B extractions sequentially."""
    inputs = {
        "identity": payload.founder_identity,
        "decision_principles": "\n".join(payload.decision_principles),
        "anti_vision": "\n".join(payload.anti_vision),
        "customer_direction": payload.customer_direction or "(chưa fill)",
        "lived_experience": payload.lived_experience or "(chưa fill)",
        "mission": payload.life_mission,
    }

    # Step 1: why-statement (depends on identity + principles + anti_vision + customer)
    try:
        why_struct = await extract_canonical("why-statement", inputs)
        await _persist_tier_b(pool, student_id, "why-statement", why_struct)
        inputs["why_statement"] = why_struct.get("why_core", "")
    except Exception as exc:
        log.exception("why-statement extract failed: %s", exc)

    # Step 2: founder-assets (depends on identity + lived_experience + customer_direction)
    try:
        assets_struct = await extract_canonical("founder-assets", inputs)
        await _persist_tier_b(pool, student_id, "founder-assets", assets_struct)
    except Exception as exc:
        log.exception("founder-assets extract failed: %s", exc)

    # Step 3: founder-story (Opus, depends on identity + mission + lived_experience + why_statement)
    try:
        story_struct = await extract_canonical("founder-story", inputs)
        await _persist_tier_b(pool, student_id, "founder-story", story_struct)
    except Exception as exc:
        log.exception("founder-story extract failed: %s", exc)


async def _persist_tier_b(
    pool: asyncpg.Pool, student_id: UUID, file_key: str, structured: dict[str, Any],
) -> None:
    if structured.get("error"):
        payload = {
            "file_key": file_key,
            "error": structured["error"],
            "missing": structured.get("missing", []),
        }
        md = render_markdown(file_key, structured, student_id)
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
                   markdown_content, structured_data_json, version, status, generated_by)
                VALUES ($1, 1, $2, $3, 'canonical', 'B', 'core',
                        $4, $5::jsonb, $6, 'generation_failed', 'ai')
                """,
                student_id, file_key, f"{file_key}.md", md,
                json.dumps(structured, ensure_ascii=False), next_v,
            )
            await conn.execute(
                """
                INSERT INTO breakoutos.student_events
                  (student_id, event_type, source, level, payload_json)
                VALUES ($1, 'tier_b.generation_failed', 'ai', 1, $2::jsonb)
                """,
                student_id,
                json.dumps(payload, ensure_ascii=False),
            )
        log.warning(
            "tier_b generation_failed file_key=%s error=%s",
            file_key,
            structured["error"],
        )
        return

    md = render_markdown(file_key, structured, student_id)
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
            VALUES ($1, 1, $2, $3, 'canonical', 'B', 'core',
                    $4, $5::jsonb, $6, 'ai_generated', $7, $8)
            """,
            student_id, file_key, f"{file_key}.md", md,
            json.dumps(structured), next_v,
            "ai_haiku" if "founder-story" not in file_key else "ai_opus",
            sig,
        )
        # Update typed column in founder_profiles
        col_map = {
            "why-statement": "why_statement",
            "founder-assets": "founder_assets_json",
            "founder-story": "founder_story_json",
        }
        col = col_map.get(file_key)
        if col == "why_statement":
            await conn.execute(
                "UPDATE breakoutos.founder_profiles SET why_statement=$1 WHERE student_id=$2",
                structured.get("why_core", ""), student_id,
            )
        elif col:
            await conn.execute(
                f"UPDATE breakoutos.founder_profiles SET {col}=$1::jsonb WHERE student_id=$2",
                json.dumps(structured), student_id,
            )


def _json_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


@router.post("/extract/{file_key}")
async def rerun_tier_b_extraction(
    file_key: str,
    student_id: UUID,
    request: Request,
    sig: str = "",
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Re-run one failed or missing Tier B file from stored Founder Profile data."""
    require_student_signature(str(student_id), request_signature(request, sig))
    if file_key not in EXTRACTION_REGISTRY:
        raise HTTPException(404, f"Unknown Tier B file: {file_key}")

    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            """
            SELECT mission, vision, why_statement, identity, principles_json,
                   anti_vision_json, founder_assets_json
            FROM breakoutos.founder_profiles
            WHERE student_id=$1
            ORDER BY version DESC LIMIT 1
            """,
            student_id,
        )
    if not profile:
        raise HTTPException(404, "Founder Profile chưa tồn tại")

    lived_experience = "\n\n".join(
        part for part in [
            _json_text(profile["identity"]),
            _json_text(profile["mission"]),
            _json_text(profile["vision"]),
            _json_text(profile["founder_assets_json"]),
        ] if part
    )
    inputs = {
        "identity": _json_text(profile["identity"]),
        "mission": _json_text(profile["mission"]),
        "decision_principles": _json_text(profile["principles_json"]),
        "anti_vision": _json_text(profile["anti_vision_json"]),
        "customer_direction": "",
        "lived_experience": lived_experience,
        "why_statement": _json_text(profile["why_statement"]),
    }
    structured = await extract_canonical(file_key, inputs)
    await _persist_tier_b(pool, student_id, file_key, structured)
    if structured.get("error"):
        raise HTTPException(
            422,
            {
                "error": structured["error"],
                "message": "Chưa thể tạo file. Hãy thử lại hoặc bổ sung thông tin.",
                "missing": structured.get("missing", []),
            },
        )
    return {
        "status": "generated",
        "file_key": file_key,
        "next_step": (
            f"/sdl/students/{student_id}/output/L1?sig="
            f"{request_signature(request, sig)}"
        ),
    }


# ============================================================
# POST /sdl/l1/intake
# ============================================================
@router.post("/intake", status_code=202)
async def l1_intake(
    payload: L1IntakePayload,
    background: BackgroundTasks,
    request: Request,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Student submits Tier A 5 files. Triggers AI extraction Tier B 3 files async."""
    sig = request_signature(request)
    require_student_signature(str(payload.student_id), sig)
    await _ensure_baseline_or_412(pool, payload.student_id, sig)

    async with pool.acquire() as conn:
        results = await _save_tier_a_files(conn, payload.student_id, payload)

        # Update student current_level
        await conn.execute(
            "UPDATE breakoutos.students SET current_level=1, current_gate='gate_1_founder_pending', "
            "updated_at=now() WHERE id=$1",
            payload.student_id,
        )

        # Append event
        await conn.execute(
            """
            INSERT INTO breakoutos.student_events
              (student_id, event_type, source, level, payload_json)
            VALUES ($1, 'l1.intake.submitted', 'form', 1, $2::jsonb)
            """,
            payload.student_id, json.dumps({"tier_a_files": list(results.keys())}),
        )

    # Telegram alert Anna real-time
    try:
        from routes.telegram_alert import alert_l1_intake_submitted
        async with pool.acquire() as conn:
            meta = await conn.fetchrow(
                "SELECT email, full_name FROM breakoutos.students WHERE id=$1",
                payload.student_id,
            )
        if meta:
            alert_l1_intake_submitted(
                str(payload.student_id), meta["email"] or "", meta["full_name"] or "",
            )
    except Exception:
        pass

    # Trigger AI extraction in background (asyncpg pool re-acquire ok)
    background.add_task(_trigger_ai_extraction, pool, payload.student_id, payload)

    return {
        "status": "tier_a_saved_ai_extracting",
        "tier_a_files": results,
        "tier_b_pending": list(EXTRACTION_REGISTRY.keys()),
        "next_step": (
            f"/sdl/l1/canonical?student_id={payload.student_id}&sig={sig}"
        ),
    }


# ============================================================
# GET L1 canonical list
# ============================================================
@router.get("/canonical")
async def list_l1_canonical(
    student_id: UUID,
    request: Request,
    sig: str = "",
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """List all L1 canonical files current state."""
    request_sig = request_signature(request, sig)
    require_student_signature(str(student_id), request_sig)
    await _ensure_baseline_or_412(pool, student_id, request_sig)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (file_key) id, file_key, file_name, tier,
              status, version, generated_by, updated_at
            FROM breakoutos.canonical_files
            WHERE student_id=$1 AND level=1
            ORDER BY file_key, version DESC
            """,
            student_id,
        )
        expected = [
            ("life-mission", "A"), ("vision-statement", "A"), ("founder-identity", "A"),
            ("decision-principles", "A"), ("anti-vision", "A"),
            ("why-statement", "B"), ("founder-assets", "B"), ("founder-story", "B"),
        ]
        existing = {r["file_key"]: dict(r) for r in rows}
        canonical_state = []
        for key, tier in expected:
            if key in existing:
                canonical_state.append({"file_key": key, "tier": tier, **existing[key]})
            else:
                canonical_state.append({
                    "file_key": key, "tier": tier, "status": "missing", "version": 0,
                })
        return {
            "student_id": str(student_id),
            "level": 1,
            "canonical_files": canonical_state,
            "ready_for_gate_1": _ready_for_gate_1(canonical_state),
        }


# ============================================================
# Gate 1 validate + lock (wraps SDL routes gate lock)
# ============================================================
@router.post("/gate-1/lock")
async def lock_gate_1(
    student_id: UUID,
    background: BackgroundTasks,
    request: Request,
    sig: str = "",
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Lock Gate 1 + generate AI Context 3 files in background."""
    require_student_signature(str(student_id), request_signature(request, sig))
    from routes.sdl_routes import lock_gate as sdl_lock_gate
    result = await sdl_lock_gate(student_id, "gate_1_founder", pool)
    background.add_task(_generate_ai_context, pool, student_id)
    return result


async def _generate_ai_context(pool: asyncpg.Pool, student_id: UUID) -> None:
    """P0.4 (Anna 2026-06-12): Generate 3 AI Context files post Gate 1.
    Files: founder-dna.md, brand-voice.md, ai-instructions.md
    """
    import os as _os
    import anthropic as _anthropic
    client = _anthropic.AsyncAnthropic(api_key=_os.environ.get("ANTHROPIC_API_KEY"))

    async with pool.acquire() as conn:
        fp = await conn.fetchrow(
            "SELECT mission, vision, why_statement, identity, principles_json, "
            "anti_vision_json, founder_assets_json, founder_story_json "
            "FROM breakoutos.founder_profiles WHERE student_id=$1 ORDER BY version DESC LIMIT 1",
            student_id,
        )
    if not fp:
        log.warning("No founder_profile for student %s, skip AI Context gen", student_id)
        return

    prompt = f"""Bạn là chuyên gia synthesis Founder DNA + Brand Voice + AI Instructions.
Sinh 3 file JSON cho student dựa trên Founder Core đã lock.

INPUT:
Mission: {fp['mission']}
Vision: {fp['vision']}
Why: {fp['why_statement']}
Identity: {fp['identity']}
Principles: {fp['principles_json']}
Anti Vision: {fp['anti_vision_json']}
Story: {json.dumps(fp['founder_story_json'], ensure_ascii=False) if fp['founder_story_json'] else '(missing)'}

OUTPUT JSON 3 keys (Tiếng Việt thuần):
{{
  "founder_dna": {{
    "core_identity_one_line": "...",
    "core_values": [<list 3-5>],
    "unique_skills": [<list>],
    "ai_context_primer": "1 đoạn ~100 từ để mọi AI agent đọc đầu mỗi conversation"
  }},
  "brand_voice": {{
    "tone": "<conversational|formal|inspirational|...>",
    "register": "<casual|professional|...>",
    "signature_patterns": [<list 5-7 pattern câu Anna hay dùng>],
    "banned_phrases": [<list từ KHÔNG dùng>],
    "preferred_pronouns": "..."
  }},
  "ai_instructions": {{
    "system_prompt_template": "Template system prompt cho mọi AI agent",
    "always_do": [<list>],
    "never_do": [<list>],
    "escalation_rules": [<list>]
  }}
}}

Chỉ trả JSON."""

    try:
        resp = await client.messages.create(
            model="claude-haiku-4-5", max_tokens=3500,
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
        log.exception("AI Context gen failed: %s", exc)
        return

    file_map = {
        "founder-dna": data.get("founder_dna", {}),
        "brand-voice": data.get("brand_voice", {}),
        "ai-instructions": data.get("ai_instructions", {}),
    }
    async with pool.acquire() as conn:
        for file_key, structured in file_map.items():
            md = (
                f"---\nfile_key: {file_key}\nstudent_id: {student_id}\n"
                f"tier: B\nlock_type: core\nlocked: false\nai_generated: true\n"
                f"version: 1\nfolder: 04 AI Context\n---\n\n"
                f"# {file_key.replace('-', ' ').title()}\n\n"
                f"```json\n{json.dumps(structured, ensure_ascii=False, indent=2)}\n```\n"
            )
            sig = hashlib.sha256(md.encode()).hexdigest()
            prev_v = await conn.fetchval(
                "SELECT max(version) FROM breakoutos.canonical_files "
                "WHERE student_id=$1 AND file_key=$2", student_id, file_key,
            )
            next_v = (prev_v or 0) + 1
            await conn.execute(
                """
                INSERT INTO breakoutos.canonical_files
                  (student_id, level, file_key, file_name, file_type, tier, lock_type,
                   markdown_content, structured_data_json, version, status,
                   generated_by, ai_signature)
                VALUES ($1, 1, $2, $3, 'canonical', 'B', 'core',
                        $4, $5::jsonb, $6, 'ai_generated', 'ai_haiku', $7)
                """,
                student_id, file_key, f"{file_key}.md", md,
                json.dumps(structured, ensure_ascii=False), next_v, sig,
            )
    log.info("AI Context 3 files generated for %s", student_id)
