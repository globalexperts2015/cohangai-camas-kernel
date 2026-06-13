"""BreakoutOS Student Data Layer (SDL) routes.

Endpoint prefix: /sdl
Schemas: routes/sdl_schemas.py
Migration: migrations/006_sdl_breakoutos_schema.sql
Spec: wiki/concepts/breakoutos-student-data-layer-spec.md
Master: wiki/concepts/breakoutos-master-architecture.md

Anna amendments 2026-06-12:
1. SDL is prerequisite infrastructure before Module CHỌN production rollout
2. Opportunity 5 fields: founder_fit + market_demand + monetization + ai_leverage + confidence
3. Gate policy: G1 Hard / G2 Soft @ T4 / G2 Hard @ T5+ after L3 Offer Validation
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from routes._auth import sign_student
from routes.sdl_schemas import (
    GATE_REQUIREMENTS,
    CanonicalFileCreate,
    CanonicalLockCreate,
    CustomerProfileCreate,
    FounderProfileCreate,
    GateValidation,
    OfferCreate,
    OpportunityMapCreate,
    PositioningProfileCreate,
    StudentCreate,
    StudentEventCreate,
)


log = logging.getLogger("camas.sdl")
router = APIRouter(prefix="/sdl", tags=["sdl"])


# ============================================================
# DB pool helper (module-level lazy singleton)
# ============================================================
_POOL: asyncpg.Pool | None = None
_POOL_LOCK = __import__("asyncio").Lock()


async def get_pool() -> asyncpg.Pool:
    """Lazy-create asyncpg pool. Reused across requests."""
    global _POOL
    if _POOL is not None:
        return _POOL
    async with _POOL_LOCK:
        if _POOL is not None:
            return _POOL
        dsn = os.environ.get("DATABASE_URL") or os.environ.get("CDP_DATABASE_URL")
        if not dsn:
            raise HTTPException(503, "DATABASE_URL not configured")
        _POOL = await asyncpg.create_pool(
            dsn, min_size=1, max_size=5, command_timeout=15,
        )
        log.info("SDL pool created (min=1 max=5)")
        return _POOL


def _decode_jsonb(value: Any) -> Any:
    """asyncpg returns JSONB as str sometimes. Decode if needed."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


# ============================================================
# 1. Student lifecycle
# ============================================================
@router.post("/students", status_code=201)
async def create_student(body: StudentCreate, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    """Create new student. Upsert by email when person_id null."""
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO breakoutos.students
                  (person_id, fanhub_person_id, program_id, cohort_id, archetype,
                   email, full_name, phone)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id, person_id, email, program_id, cohort_id, status,
                          current_level, current_gate, archetype, created_at
                """,
                body.person_id, body.fanhub_person_id,
                body.program_id, body.cohort_id, body.archetype,
                body.email, body.full_name, body.phone,
            )
            return dict(row)
        except asyncpg.UniqueViolationError:
            existing = await conn.fetchrow(
                """
                SELECT id, person_id, email, program_id, cohort_id, status,
                       current_level, current_gate
                FROM breakoutos.students
                WHERE lower(email) = lower($1) AND program_id=$2 AND cohort_id=$3
                """,
                body.email, body.program_id, body.cohort_id,
            )
            if existing:
                return {"status": "already_exists", **dict(existing)}
            raise HTTPException(409, "Student already exists")


@router.get("/students/by-email/{email}")
async def get_student_by_email(
    email: str, program_id: str = "foundation", cohort_id: str = "cohort_1",
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Lookup student by email + program + cohort. Used by Sepay webhook + admin."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, person_id, email, full_name, phone, program_id, cohort_id,
                   status, current_level, current_gate, archetype, created_at
            FROM breakoutos.students
            WHERE lower(email)=lower($1) AND program_id=$2 AND cohort_id=$3
            """,
            email, program_id, cohort_id,
        )
        if not row:
            raise HTTPException(404, f"No student for email={email} program={program_id} cohort={cohort_id}")
        return dict(row)


@router.post("/webhooks/payment-completed", status_code=201)
async def webhook_payment_completed(
    body: dict, pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Called by breakout-app Sepay webhook after payment confirmed.

    Payload:
      email (required), full_name, phone, product (program_id), amount_vnd,
      order_code, paid_at, sepay_payload (optional raw)

    Action:
      1. Upsert breakoutos.students by email+program+cohort
      2. Insert student_events purchase.completed
    """
    email = (body.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(400, "email required")
    product = body.get("product", "foundation")
    cohort_id = body.get("cohort_id", "cohort_1")
    full_name = body.get("full_name") or body.get("name", "")
    phone = body.get("phone", "")
    amount_vnd = int(body.get("amount_vnd") or body.get("amount") or 0)
    order_code = body.get("order_code", "")

    async with pool.acquire() as conn:
        # Upsert student (lookup first because ON CONFLICT with partial unique index
        # requires exact predicate match; simpler: SELECT then INSERT/UPDATE explicit)
        existing = await conn.fetchval(
            "SELECT id FROM breakoutos.students "
            "WHERE lower(email)=lower($1) AND program_id=$2 AND cohort_id=$3",
            email, product, cohort_id,
        )
        if existing:
            student_id = existing
            await conn.execute(
                """
                UPDATE breakoutos.students
                SET full_name = COALESCE(NULLIF($1, ''), full_name),
                    phone    = COALESCE(NULLIF($2, ''), phone),
                    updated_at = now()
                WHERE id = $3
                """,
                full_name, phone, student_id,
            )
        else:
            student_id = await conn.fetchval(
                """
                INSERT INTO breakoutos.students
                  (program_id, cohort_id, email, full_name, phone, status, metadata_json)
                VALUES ($1, $2, $3, $4, $5, 'active', $6::jsonb)
                RETURNING id
                """,
                product, cohort_id, email, full_name, phone,
                json.dumps({"source": "sepay_webhook", "order_code": order_code}),
            )

        # Insert purchase event
        await conn.execute(
            """
            INSERT INTO breakoutos.student_events
              (student_id, event_type, source, level, payload_json)
            VALUES ($1, 'purchase.completed', 'sepay', 0, $2::jsonb)
            """,
            student_id,
            json.dumps({
                "email": email, "amount_vnd": amount_vnd, "order_code": order_code,
                "product": product, "paid_at": body.get("paid_at"),
            }),
        )

    student_id_text = str(student_id)
    signature = sign_student(student_id_text)
    return {
        "status": "student_upserted",
        "student_id": student_id_text,
        "email": email,
        "program_id": product,
        "cohort_id": cohort_id,
        "next_step": (
            f"/foundation/baseline?student={student_id_text}&sig={signature}"
        ),
    }


@router.get("/students/{student_id}")
async def get_student(student_id: UUID, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM breakoutos.students WHERE id = $1", student_id
        )
        if not row:
            raise HTTPException(404, "Student not found")
        return {**dict(row), "metadata_json": _decode_jsonb(row["metadata_json"])}


@router.get("/students/{student_id}/progress")
async def get_student_progress(student_id: UUID, pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    """Summary: gates passed + files locked + freedom score (when L6a active)."""
    async with pool.acquire() as conn:
        student = await conn.fetchrow(
            "SELECT * FROM breakoutos.students WHERE id = $1", student_id
        )
        if not student:
            raise HTTPException(404, "Student not found")

        gates = await conn.fetch(
            """
            SELECT gate_key, lock_status, locked_at, unlocked_at
            FROM breakoutos.canonical_locks
            WHERE student_id = $1 AND unlocked_at IS NULL
            ORDER BY locked_at DESC
            """,
            student_id,
        )

        files_count = await conn.fetchval(
            """
            SELECT count(*) FROM breakoutos.canonical_files
            WHERE student_id = $1 AND status IN ('reviewed', 'locked')
            """,
            student_id,
        )

        return {
            "student_id": str(student_id),
            "current_level": student["current_level"],
            "current_gate": student["current_gate"],
            "gates_locked": [
                {"gate_key": g["gate_key"], "lock_status": g["lock_status"],
                 "locked_at": g["locked_at"].isoformat()}
                for g in gates
            ],
            "canonical_files_complete": files_count,
        }


# ============================================================
# 2. Canonical Files
# ============================================================
@router.post("/students/{student_id}/canonical-files", status_code=201)
async def create_canonical_file(
    student_id: UUID, body: CanonicalFileCreate,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    if body.student_id != student_id:
        raise HTTPException(400, "student_id mismatch")
    async with pool.acquire() as conn:
        # Determine next version
        prev = await conn.fetchval(
            """
            SELECT max(version) FROM breakoutos.canonical_files
            WHERE student_id = $1 AND file_key = $2
            """,
            student_id, body.file_key,
        )
        next_version = (prev or 0) + 1

        row = await conn.fetchrow(
            """
            INSERT INTO breakoutos.canonical_files
              (student_id, level, file_key, file_name, file_type,
               tier, lock_type, markdown_content, structured_data_json,
               version, status, generated_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, 'draft', $11)
            RETURNING id, file_key, version, status, created_at
            """,
            student_id, body.level, body.file_key, body.file_name,
            body.file_type, body.tier, body.lock_type,
            body.markdown_content,
            json.dumps(body.structured_data_json) if body.structured_data_json else None,
            next_version, body.generated_by,
        )
        return dict(row)


@router.get("/students/{student_id}/canonical-files")
async def list_canonical_files(
    student_id: UUID,
    level: int | None = Query(None, ge=1, le=6),
    tier: str | None = Query(None, pattern="^[ABC]$"),
    status: str | None = None,
    cohort_filter: bool = Query(True, description="P0.3 Cohort 1 shows Tier A only by default"),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[dict]:
    """List latest version per file_key with optional filters.

    P0.3 (Anna 2026-06-12): Cohort 1 default filter Tier A only.
    Override with cohort_filter=false to see all 47 files.
    """
    async with pool.acquire() as conn:
        # Lookup student cohort_id
        cohort_id = await conn.fetchval(
            "SELECT cohort_id FROM breakoutos.students WHERE id=$1", student_id,
        )

        # Apply Cohort 1 visibility filter
        effective_tier = tier
        if cohort_filter and cohort_id == "cohort_1" and not tier:
            effective_tier = "A"

        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (file_key) id, file_key, file_name, level, tier,
              lock_type, status, version, updated_at
            FROM breakoutos.canonical_files
            WHERE student_id = $1
              AND ($2::int IS NULL OR level = $2)
              AND ($3::text IS NULL OR tier = $3)
              AND ($4::text IS NULL OR status = $4)
            ORDER BY file_key, version DESC
            """,
            student_id, level, effective_tier, status,
        )
        return [dict(r) for r in rows]


@router.get("/students/{student_id}/canonical-files/{file_key}")
async def get_canonical_file_latest(
    student_id: UUID, file_key: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM breakoutos.canonical_files
            WHERE student_id = $1 AND file_key = $2
            ORDER BY version DESC LIMIT 1
            """,
            student_id, file_key,
        )
        if not row:
            raise HTTPException(404, f"Canonical file {file_key} not found")
        return {**dict(row), "structured_data_json": _decode_jsonb(row["structured_data_json"])}


@router.post("/students/{student_id}/canonical-files/{file_key}/approve")
async def approve_canonical_file(
    student_id: UUID, file_key: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Student approves canonical file → status='reviewed' + reviewed_by."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE breakoutos.canonical_files
            SET status = 'reviewed', reviewed_by = $1
            WHERE student_id = $1 AND file_key = $2
              AND version = (
                SELECT max(version) FROM breakoutos.canonical_files
                WHERE student_id = $1 AND file_key = $2
              )
            RETURNING id, file_key, status, version
            """,
            student_id, file_key,
        )
        if not row:
            raise HTTPException(404, "File not found")
        return dict(row)


# ============================================================
# 3. Gate validation + lock
# ============================================================
async def _check_gate_files(
    conn: asyncpg.Connection, student_id: UUID, required_files: list[str],
) -> tuple[list[str], list[dict]]:
    """Returns (missing_file_keys, file_records)."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (file_key) id, file_key, status, version,
          markdown_content, structured_data_json
        FROM breakoutos.canonical_files
        WHERE student_id = $1 AND file_key = ANY($2::text[])
        ORDER BY file_key, version DESC
        """,
        student_id, required_files,
    )
    found = {r["file_key"]: r for r in rows if r["status"] in ("reviewed", "locked")}
    missing = [f for f in required_files if f not in found]
    return missing, [dict(found[k]) for k in required_files if k in found]


@router.get("/students/{student_id}/gates/{gate_key}/validate", response_model=GateValidation)
async def validate_gate(
    student_id: UUID, gate_key: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> GateValidation:
    """Check if gate ready to lock."""
    if gate_key not in GATE_REQUIREMENTS:
        raise HTTPException(404, f"Unknown gate {gate_key}")

    req = GATE_REQUIREMENTS[gate_key]
    warnings: list[str] = []

    async with pool.acquire() as conn:
        if "required_files" in req:
            missing, files = await _check_gate_files(conn, student_id, req["required_files"])

            # Additional validations per gate
            if gate_key == "gate_2_customer_soft" and "min_total_opportunity_score" in req:
                om = await conn.fetchrow(
                    """
                    SELECT total_score FROM breakoutos.opportunity_maps
                    WHERE student_id = $1
                    ORDER BY version DESC LIMIT 1
                    """,
                    student_id,
                )
                if om and om["total_score"] < req["min_total_opportunity_score"]:
                    warnings.append(
                        f"Total Opportunity Score {om['total_score']} < "
                        f"{req['min_total_opportunity_score']}"
                    )
                elif not om:
                    warnings.append("opportunity-map chưa có data")

            return GateValidation(
                gate_key=gate_key,
                passed=len(missing) == 0 and len(warnings) == 0,
                missing=missing,
                warnings=warnings,
                metadata={"file_count": len(files), "lock_type": req["lock_type"]},
            )

        # Gates without required_files (e.g., gate_2_customer_hard depends on L3 validation)
        if gate_key == "gate_2_customer_hard":
            l3_completed = await conn.fetchval(
                """
                SELECT count(*) > 0 FROM breakoutos.canonical_locks
                WHERE student_id = $1 AND gate_key = 'gate_3_value_proposition'
                  AND lock_status = 'hard' AND unlocked_at IS NULL
                """,
                student_id,
            )
            if not l3_completed:
                return GateValidation(
                    gate_key=gate_key, passed=False,
                    missing=["L3 Offer Validation chưa pass"],
                    warnings=["Gate 2 HARD chỉ escalate sau khi L3 Gate 3 lock"],
                )
            return GateValidation(gate_key=gate_key, passed=True)

        raise HTTPException(400, f"Gate {gate_key} validation not implemented")


@router.post("/students/{student_id}/gates/{gate_key}/lock")
async def lock_gate(
    student_id: UUID, gate_key: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Execute gate lock (Soft or Hard per Anna amendment 2026-06-12)."""
    if gate_key not in GATE_REQUIREMENTS:
        raise HTTPException(404, f"Unknown gate {gate_key}")

    req = GATE_REQUIREMENTS[gate_key]

    async with pool.acquire() as conn:
        # Validate first
        validation = await validate_gate(student_id, gate_key, pool)  # type: ignore[arg-type]
        if not validation.passed:
            raise HTTPException(
                412,
                {
                    "error": "Gate not ready",
                    "missing": validation.missing,
                    "warnings": validation.warnings,
                },
            )

        # Build snapshot
        if "required_files" in req:
            _, files = await _check_gate_files(conn, student_id, req["required_files"])
            snapshot = {
                f["file_key"]: {
                    "content": f["markdown_content"],
                    "data": _decode_jsonb(f["structured_data_json"]),
                    "version": f["version"],
                }
                for f in files
            }
            file_ids = [str(f["id"]) for f in files]
        else:
            snapshot = {}
            file_ids = []

        signature = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, default=str).encode()
        ).hexdigest()

        async with conn.transaction():
            # Insert lock record
            lock_row = await conn.fetchrow(
                """
                INSERT INTO breakoutos.canonical_locks
                  (student_id, gate_key, level, locked_files_json, lock_status,
                   locked_by, signature, snapshot_json)
                VALUES ($1, $2, $3, $4::jsonb, $5, $1, $6, $7::jsonb)
                RETURNING id, gate_key, lock_status, locked_at, signature
                """,
                student_id, gate_key, req.get("level", 0),
                json.dumps(file_ids), req["lock_type"],
                signature, json.dumps(snapshot, default=str),
            )

            # Update canonical_files status
            if file_ids:
                await conn.execute(
                    "UPDATE breakoutos.canonical_files SET status = 'locked' "
                    "WHERE id = ANY($1::uuid[])",
                    [UUID(f) for f in file_ids],
                )

            # Update student state
            await conn.execute(
                "UPDATE breakoutos.students SET current_gate = $1, "
                "current_level = GREATEST(current_level, $2) WHERE id = $3",
                gate_key, req.get("level", 1), student_id,
            )

            # P0.4 (Anna 2026-06-12): Copy snapshot → 05 Canonical Outputs/final-*.md
            snapshot_targets = req.get("snapshot_to", [])
            for final_key in snapshot_targets:
                # Compose final markdown from snapshot
                final_md_parts = [
                    f"---\nfile_key: {final_key}\nstudent_id: {student_id}\n"
                    f"tier: A\nlock_type: core\nlocked: true\nai_generated: false\n"
                    f"version: 1\nfolder: 05 Canonical Outputs\n"
                    f"snapshot_of_gate: {gate_key}\nsnapshot_signature: {signature}\n---\n\n"
                    f"# {final_key.replace('-', ' ').title()}\n\n"
                    f"> Gold copy snapshot sau khi Gate `{gate_key}` lock.\n"
                    f"> Bao gồm {len(snapshot)} canonical files đã chốt.\n\n"
                ]
                for fkey, fdata in snapshot.items():
                    final_md_parts.append(f"\n## {fkey}\n\n{fdata.get('content', '')}\n\n---\n")
                final_md = "".join(final_md_parts)
                await conn.execute(
                    """
                    INSERT INTO breakoutos.canonical_files
                      (student_id, level, file_key, file_name, file_type, tier, lock_type,
                       markdown_content, structured_data_json, version, status, generated_by,
                       ai_signature)
                    VALUES ($1, $2, $3, $4, 'snapshot', 'A', 'core',
                            $5, $6::jsonb, 1, 'locked', 'gate_snapshot', $7)
                    ON CONFLICT (student_id, file_key, version) DO UPDATE
                    SET markdown_content = EXCLUDED.markdown_content,
                        updated_at = now()
                    """,
                    student_id, req.get("level", 0), final_key, f"{final_key}.md",
                    final_md, json.dumps({"snapshot": snapshot, "gate": gate_key}, default=str),
                    signature,
                )

        # Telegram alert Anna real-time
        try:
            from routes.telegram_alert import alert_gate_locked
            meta = await conn.fetchrow(
                "SELECT email, full_name FROM breakoutos.students WHERE id=$1", student_id,
            )
            if meta:
                alert_gate_locked(str(student_id), gate_key,
                                  meta["email"] or "", meta["full_name"] or "")
        except Exception:
            pass

        return {
            "locked": True,
            "gate_key": gate_key,
            "lock_status": req["lock_type"],
            "signature": signature[:16] + "...",
            "unlock_next": req.get("unlock_next", []),
            "file_count": len(file_ids),
            "snapshot_files_created": req.get("snapshot_to", []),
        }


@router.get("/students/{student_id}/gates")
async def list_gates(student_id: UUID, pool: asyncpg.Pool = Depends(get_pool)) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT gate_key, level, lock_status, locked_at, unlocked_at, recert_required
            FROM breakoutos.canonical_locks
            WHERE student_id = $1
            ORDER BY locked_at DESC
            """,
            student_id,
        )
        return [dict(r) for r in rows]


# ============================================================
# 4. Downstream check helper (called by Module CHỌN, L3-L5 wizards)
# ============================================================
async def check_gate_passed(
    pool: asyncpg.Pool, student_id: UUID, gate_key: str,
) -> bool:
    """Returns True if gate locked and not unlocked."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT lock_status, unlocked_at FROM breakoutos.canonical_locks
            WHERE student_id = $1 AND gate_key = $2
            ORDER BY locked_at DESC LIMIT 1
            """,
            student_id, gate_key,
        )
        if not row:
            return False
        return row["unlocked_at"] is None and row["lock_status"] in ("soft", "hard")


@router.get("/students/{student_id}/gates/{gate_key}/passed")
async def gate_passed_check(
    student_id: UUID, gate_key: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    passed = await check_gate_passed(pool, student_id, gate_key)
    return {"student_id": str(student_id), "gate_key": gate_key, "passed": passed}


# ============================================================
# 5. Events ledger
# ============================================================
@router.post("/events", status_code=201)
async def append_event(
    body: StudentEventCreate, pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Webhook receiver. Append raw event for later AI extraction."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO breakoutos.student_events
              (student_id, person_id, event_type, source, level, payload_json)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            RETURNING id, event_type, source, created_at
            """,
            body.student_id, body.person_id, body.event_type, body.source,
            body.level, json.dumps(body.payload_json),
        )
        return dict(row)


@router.get("/students/{student_id}/events")
async def list_events(
    student_id: UUID,
    source: str | None = None,
    event_type: str | None = None,
    limit: int = Query(50, le=200),
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, event_type, source, level, extraction_status, created_at
            FROM breakoutos.student_events
            WHERE student_id = $1
              AND ($2::text IS NULL OR source = $2)
              AND ($3::text IS NULL OR event_type = $3)
            ORDER BY created_at DESC LIMIT $4
            """,
            student_id, source, event_type, limit,
        )
        return [dict(r) for r in rows]


# ============================================================
# 6. Health check
# ============================================================
@router.get("/health")
async def sdl_health(pool: asyncpg.Pool = Depends(get_pool)) -> dict:
    """SDL health: table counts."""
    async with pool.acquire() as conn:
        counts = {}
        for table in [
            "students", "founder_profiles", "customer_profiles",
            "opportunity_maps", "offers", "positioning_profiles",
            "canonical_files", "canonical_locks", "student_events",
        ]:
            counts[table] = await conn.fetchval(
                f"SELECT count(*) FROM breakoutos.{table}"
            )
    return {"status": "ok", "schema": "breakoutos", "tables": counts}
