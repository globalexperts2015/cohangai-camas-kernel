"""Breakout Challenge K3, three-day draft sprint.

Challenge artifacts are hypotheses, not BreakoutOS canonical files. The router
uses hashed resume tokens, a Postgres generation queue and a reliable
integration outbox for Fan Hub and GHL.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import anthropic
import asyncpg
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse

from routes._auth import require_service_key
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agents.e6_market_demand.agent import compute_demand_score
from agents.e6_market_demand.external_apis import (
    answerthepublic_questions,
    dataforseo_search_volume,
    google_trends_growth,
    youtube_search_count,
)
from routes.sdl_routes import get_pool


log = logging.getLogger("camas.challenge_k3")
router = APIRouter(tags=["challenge-k3"])

MODEL = os.getenv("K3_AI_MODEL", "claude-sonnet-4-6")
MODEL_FREE = os.getenv("K3_AI_MODEL_FREE", "claude-haiku-4-5-20251001")
MODEL_VIP = os.getenv("K3_AI_MODEL_VIP", MODEL)
K3_LLM_MAX_TOKENS = int(os.getenv("K3_LLM_MAX_TOKENS", "6000"))
K3_DAY3_MAX_TOKENS = int(os.getenv("K3_DAY3_MAX_TOKENS", "8000"))
PUBLIC_BASE_URL = os.getenv("K3_PUBLIC_BASE_URL", "https://os.breakout.live").rstrip("/")

# Pricing constants (USD per 1M tokens) - update khi model price thay doi
_MODEL_PRICING_USD = {
    "claude-haiku-4-5-20251001": {"in": 1.0, "out": 5.0},
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0},
    "claude-opus-4-7": {"in": 15.0, "out": 75.0},
}
_DATAFORSEO_COST_PER_KW = 0.003  # USD per keyword search volume call
_YOUTUBE_COST_PER_CALL = 0.0  # free tier
_TRENDS_COST_PER_CALL = 0.0  # pytrends free
_CLIENT: anthropic.AsyncAnthropic | None = None


def _client() -> anthropic.AsyncAnthropic:
    global _CLIENT
    if _CLIENT is None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        _CLIENT = anthropic.AsyncAnthropic(api_key=api_key)
    return _CLIENT


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _derive_token(session_id: Any) -> str:
    """Resume token xác định từ session_id (HMAC). Cùng session luôn ra cùng token,
    nên đăng ký lại KHÔNG đổi link. Không lưu plaintext, chỉ lưu hash để lookup.
    """
    secret = os.getenv("HMAC_SECRET", "").encode()
    if len(secret) < 32:
        raise RuntimeError("HMAC_SECRET must be set (>=32 bytes) for resume token derivation")
    digest = hmac.new(secret, str(session_id).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


# RFC 6761 reserved + IETF documentation TLDs + common test domains.
# Chặn TRƯỚC khi enqueue outbox/sync Fan Hub để giữ production pipeline sạch.
_RESERVED_TEST_TLDS = {".invalid", ".test", ".example", ".localhost"}
_RESERVED_TEST_DOMAINS = {
    "example.com", "example.org", "example.net",
    "test.com", "localhost", "nowhere.invalid",
    "nowhere.test", "nowhere.example",
}


def _normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise ValueError("Email không hợp lệ")
    try:
        local, domain = normalized.rsplit("@", 1)
    except ValueError:
        raise ValueError("Email không hợp lệ")
    if not domain or "." not in domain:
        raise ValueError("Email không hợp lệ")
    # Block RFC 6761 reserved + documentation TLDs
    for tld in _RESERVED_TEST_TLDS:
        if domain.endswith(tld):
            raise ValueError("Email thuộc dải test reserved, không nhận")
    if domain in _RESERVED_TEST_DOMAINS:
        raise ValueError("Email thuộc danh sách test reserved, không nhận")
    return normalized


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    cohort_id: str = Field(default="k3-2026-06", max_length=50)
    access_tier: str = Field(default="free", pattern="^(free|vip)$")
    ghl_contact_id: str | None = Field(default=None, max_length=255)
    consent: bool = True

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalize_email(value)


class Day1Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lived_experience: str = Field(min_length=10, max_length=4000)
    skills_and_proof: str = Field(min_length=10, max_length=4000)
    assets_and_network: str = Field(min_length=3, max_length=3000)
    energizing_topics: str = Field(min_length=3, max_length=2000)
    people_to_serve: str = Field(min_length=3, max_length=2000)
    lifestyle_and_time: str = Field(min_length=3, max_length=1500)
    anti_vision: str = Field(min_length=3, max_length=1500)


class IdeaSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idea_index: int = Field(ge=0, le=9)


class Day2Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # K3 Day 2 schema migration 2026-06-20:
    # old artifact rows keep legacy JSON fields; new submissions use framework-aligned fields.
    customer_hypothesis: str = Field(
        min_length=5,
        max_length=2500,
        description="Khách hàng đầu tiên là ai, tuổi, nghề, hoàn cảnh",
    )
    pain_evidence: str = Field(
        min_length=5,
        max_length=3000,
        description="Khách đã mất tiền/thời gian/kết quả gì vì vấn đề này",
    )
    top_problem: str = Field(
        min_length=5,
        max_length=2500,
        description="Vấn đề lớn nhất và mức đau 1-10",
    )
    desired_result: str = Field(
        min_length=5,
        max_length=2500,
        description="Kết quả khách muốn đạt được",
    )
    keywords: list[str] = Field(
        min_length=1,
        max_length=5,
        description="1-5 từ khóa khách search về vấn đề",
    )
    payment_evidence: str = Field(
        min_length=5,
        max_length=2500,
        description="Khách đang dùng giải pháp gì và đã trả bao nhiêu",
    )
    founder_advantage: str = Field(
        min_length=5,
        max_length=2000,
        description="Founder có mạng lưới, kinh nghiệm, brand gì để tiếp cận nhóm này",
    )

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        result = [value.strip()[:100] for value in values if value.strip()]
        if not result:
            raise ValueError("Cần ít nhất một từ khóa")
        return list(dict.fromkeys(result))[:5]


class OfferApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool = True


class Day3Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sales_channel: str = Field(min_length=2, max_length=1000)
    audience_size: int = Field(default=0, ge=0, le=100000000)
    available_hours_per_week: int = Field(ge=1, le=80)
    launch_date: date
    delivery_capacity: int = Field(ge=1, le=10000)


async def _session_by_token(pool: asyncpg.Pool, token: str) -> asyncpg.Record:
    if len(token) < 32:
        raise HTTPException(status_code=404, detail="Link không hợp lệ")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM breakout_challenge.sessions
            WHERE resume_token_hash=$1
              AND (expires_at IS NULL OR expires_at > now())
            """,
            _token_hash(token),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Link không hợp lệ hoặc đã hết hạn")
    return row


async def _latest_artifact(
    conn: asyncpg.Connection,
    session_id: UUID,
    artifact_type: str,
) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT * FROM breakout_challenge.artifacts
        WHERE session_id=$1 AND artifact_type=$2
        ORDER BY version DESC LIMIT 1
        """,
        session_id,
        artifact_type,
    )


# Domain test/reserved (RFC 2606/6761): Fan Hub validate EmailStr -> 422 -> dead job.
# Chặn tại nguồn, KHÔNG enqueue sync Fan Hub cho email loại này (GHL vẫn sync).
_RESERVED_EMAIL_RE = re.compile(r"@(?:.*\.)?(?:invalid|test|example|localhost)$", re.I)


def _is_reserved_email(email: str | None) -> bool:
    e = (email or "").strip().lower()
    if "@" not in e:
        return True
    dom = e.rsplit("@", 1)[1]
    return bool(_RESERVED_EMAIL_RE.search("@" + dom)) or dom in (
        "example.com", "example.org", "example.net")


async def _enqueue_outbox(
    conn: asyncpg.Connection,
    session_id: UUID,
    key: str,
    target: str,
    operation: str,
    payload: dict[str, Any],
) -> None:
    # Gate: không đẩy sang Fan Hub nếu email là domain test/reserved (tránh 422 -> dead).
    if target == "fanhub" and _is_reserved_email(payload.get("email")):
        return
    await conn.execute(
        """
        INSERT INTO breakout_challenge.integration_outbox
          (idempotency_key, session_id, target, operation, payload_json)
        VALUES ($1,$2,$3,$4,$5::jsonb)
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        key,
        session_id,
        target,
        operation,
        json.dumps(payload, ensure_ascii=False),
    )


EVENT_CONFIG: dict[str, dict[str, Any]] = {
    "challenge.registered": {
        "title": "Đăng ký Breakout Challenge K3",
        "tags": ["BREAKOUT_K3_REGISTERED"],
        "ghl_tags": ["breakout-challenge-k3-registered"],
        "milestone": False,
    },
    "challenge.day1.idea_selected": {
        "title": "Hoàn thành K3 ngày 1",
        "tags": ["BREAKOUT_K3_DAY1_COMPLETED"],
        "ghl_tags": ["breakout-k3-day1-completed"],
        "milestone": True,
    },
    "challenge.day2.offer_approved": {
        "title": "Hoàn thành K3 ngày 2",
        "tags": ["BREAKOUT_K3_DAY2_COMPLETED"],
        "ghl_tags": ["breakout-k3-day2-completed"],
        "milestone": True,
    },
    "challenge.completed": {
        "title": "Hoàn thành Breakout Challenge K3",
        "tags": [
            "BREAKOUT_K3_DAY3_COMPLETED",
            "BREAKOUT_K3_COMPLETED",
            "BREAKOUT_K3_FOUNDATION_READY",
        ],
        "ghl_tags": [
            "breakout-k3-day3-completed",
            "breakout-k3-completed",
            "breakout-k3-foundation-ready",
        ],
        "milestone": True,
    },
    "challenge.generation_failed": {
        "title": "Lỗi tạo kết quả K3 (cần hỗ trợ)",
        "tags": ["BREAKOUT_K3_GENERATION_FAILED"],
        "ghl_tags": ["breakout-k3-generation-failed"],
        "milestone": False,
    },
}


async def _record_event(
    conn: asyncpg.Connection,
    session: asyncpg.Record | dict[str, Any],
    event_type: str,
    payload: dict[str, Any],
) -> UUID:
    session_id = session["id"]
    event_key = f"{session_id}:{event_type}"
    event_id = await conn.fetchval(
        """
        INSERT INTO breakout_challenge.events
          (idempotency_key, session_id, fanhub_person_id, event_type, payload_json)
        VALUES ($1,$2,$3,$4,$5::jsonb)
        ON CONFLICT (idempotency_key) DO UPDATE
          SET payload_json=EXCLUDED.payload_json
        RETURNING id
        """,
        event_key,
        session_id,
        session["fanhub_person_id"],
        event_type,
        json.dumps(payload, ensure_ascii=False),
    )
    config = EVENT_CONFIG.get(event_type)
    if config:
        fanhub_tags = list(dict.fromkeys([
            *config["tags"],
            *payload.get("fan_tags", []),
        ]))
        ghl_tags = list(dict.fromkeys([
            *config["ghl_tags"],
            *payload.get("ghl_tags", []),
        ]))
        result_url = f"{PUBLIC_BASE_URL}/sprint/k3/{payload.get('resume_token', '')}"
        fanhub_payload = {
            "event_id": str(event_id),
            "person_id": str(session["fanhub_person_id"]) if session["fanhub_person_id"] else None,
            "email": session["email_normalized"],
            "event_type": event_type,
            "event_category": "engagement",
            "source": "breakout_challenge",
            "venture_slug": "breakout",
            "delta_points": 5 if config["milestone"] else 1,
            "title": config["title"],
            "description": payload.get("summary"),
            "action_url": result_url if payload.get("resume_token") else None,
            "is_milestone": config["milestone"],
            "tags": fanhub_tags,
            "metadata": {
                key: value
                for key, value in payload.items()
                if key not in {"resume_token", "fan_tags", "ghl_tags", "ghl_fields"}
            },
        }
        await _enqueue_outbox(
            conn,
            session_id,
            f"fanhub:event:{event_id}",
            "fanhub",
            "event.ingest",
            fanhub_payload,
        )
        await _enqueue_outbox(
            conn,
            session_id,
            f"ghl:event:{event_id}",
            "ghl",
            "contact.sync",
            {
                "email": session["email_normalized"],
                "full_name": session["full_name"],
                "phone": session["phone"],
                "ghl_contact_id": session["ghl_contact_id"],
                "tags": ghl_tags,
                "fields": payload.get("ghl_fields", {}),
            },
        )
    return event_id


@router.post("/challenge/k3/register", status_code=201, dependencies=[Depends(require_service_key)])
async def register(
    body: RegisterRequest,
    pool: asyncpg.Pool = Depends(get_pool),
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
) -> dict[str, Any]:
    token = secrets.token_urlsafe(36)
    token_hash = _token_hash(token)
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO breakout_challenge.sessions
                  (email_normalized, full_name, phone, cohort_id, access_tier,
                   ghl_contact_id, resume_token_hash, consent_json,
                   expires_at, metadata_json)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,now()+INTERVAL '12 months',$9::jsonb)
                ON CONFLICT (email_normalized, cohort_id) DO UPDATE
                  SET full_name=COALESCE(EXCLUDED.full_name, breakout_challenge.sessions.full_name),
                      phone=COALESCE(EXCLUDED.phone, breakout_challenge.sessions.phone),
                      access_tier=CASE
                        WHEN EXCLUDED.access_tier='vip' THEN 'vip'
                        ELSE breakout_challenge.sessions.access_tier
                      END,
                      ghl_contact_id=COALESCE(EXCLUDED.ghl_contact_id, breakout_challenge.sessions.ghl_contact_id),
                      expires_at=EXCLUDED.expires_at,
                      updated_at=now()
                RETURNING *
                """,
                body.email,
                body.full_name,
                body.phone,
                body.cohort_id,
                body.access_tier,
                body.ghl_contact_id,
                token_hash,
                json.dumps({"challenge_data": body.consent}),
                json.dumps({"registration_idempotency_key": idempotency_key or None}),
            )
            # Resume token xác định từ session_id: đăng ký lại giữ NGUYÊN link
            # (token ngẫu nhiên ở INSERT chỉ là giá trị tạm cho hàng mới).
            token = _derive_token(row["id"])
            token_hash = _token_hash(token)
            if row["resume_token_hash"] != token_hash:
                await conn.execute(
                    "UPDATE breakout_challenge.sessions SET resume_token_hash=$1 WHERE id=$2",
                    token_hash,
                    row["id"],
                )
            await _enqueue_outbox(
                conn,
                row["id"],
                f"fanhub:person:{row['id']}",
                "fanhub",
                "person.resolve",
                {
                    "email": body.email,
                    "display_name": body.full_name,
                    "phone": body.phone,
                    "source": "breakout_challenge",
                    "ghl_contact_id": body.ghl_contact_id,
                },
            )
            await _record_event(
                conn,
                row,
                "challenge.registered",
                {
                    "cohort": body.cohort_id,
                    "access_tier": body.access_tier,
                    "fan_tags": ["BREAKOUT_K3_VIP"] if body.access_tier == "vip" else [],
                    "ghl_tags": ["breakout-k3-vip"] if body.access_tier == "vip" else [],
                    "resume_token": token,
                    "summary": "Bắt đầu hành trình 3 ngày.",
                    "ghl_fields": {
                        "k3_resume_url": f"{PUBLIC_BASE_URL}/sprint/k3/{token}",
                        "k3_current_day": "0",
                        "k3_last_active_at": datetime.now(timezone.utc).isoformat(),
                    },
                },
            )
    return {
        "session_id": str(row["id"]),
        "state": row["current_state"],
        "resume_url": f"{PUBLIC_BASE_URL}/sprint/k3/{token}",
        "token": token,
    }


def _k3_config_checks() -> dict[str, Any]:
    """Kiểm credential/config bắt buộc cho luồng K3 (không trả giá trị secret)."""
    def has(key: str, minlen: int = 1) -> bool:
        return len(os.getenv(key, "")) >= minlen
    try:
        ghl_fields = len(json.loads(os.getenv("GHL_K3_CUSTOM_FIELD_IDS", "") or "{}"))
    except Exception:
        ghl_fields = 0
    try:
        import pytrends.request  # noqa: F401
        pytrends_available = True
    except Exception:
        pytrends_available = False
    return {
        "hmac_secret": has("HMAC_SECRET", 32),
        "internal_service_key": has("INTERNAL_SERVICE_KEY"),
        "fan_hub_url": has("FAN_HUB_INTERNAL_URL"),
        "ghl_api_key": has("GHL_API_KEY"),
        "ghl_location_id": has("GHL_LOCATION_ID"),
        "ghl_custom_fields": ghl_fields,
        "webinarkit_api_key": has("WEBINARKIT_API_KEY"),
        "webinarkit_webinar_id": has("WEBINARKIT_WEBINAR_ID"),
        "dataforseo_login": has("DATAFORSEO_LOGIN"),
        "dataforseo_password": has("DATAFORSEO_PASSWORD"),
        "youtube_api_key": has("YOUTUBE_API_KEY"),
        "pytrends_available": pytrends_available,
        "answerthepublic_api_key": has("ANSWERTHEPUBLIC_API_KEY"),
    }


async def _fan_hub_reachable() -> bool:
    base = os.getenv("FAN_HUB_INTERNAL_URL", "").strip()
    if not base:
        return False
    root = base.split("/internal", 1)[0].rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"{root}/health")
            return r.status_code == 200
    except Exception:
        return False


@router.get("/challenge/k3/readiness")
async def k3_readiness(pool: asyncpg.Pool = Depends(get_pool)) -> dict[str, Any]:
    """Launch-readiness gate THẬT (item 13): kiểm credential + integration + outbox/jobs.
    ready chỉ true khi ĐỦ config VÀ Fan Hub reachable VÀ không có dead/stuck.
    Public, không trả PII hay giá trị secret.
    """
    cfg = _k3_config_checks()
    async with pool.acquire() as conn:
        ob = {r["status"]: r["n"] for r in await conn.fetch(
            "SELECT status, count(*) n FROM breakout_challenge.integration_outbox GROUP BY status"
        )}
        stuck = await conn.fetchval(
            "SELECT count(*) FROM breakout_challenge.integration_outbox "
            "WHERE status='queued' AND scheduled_at < now() - INTERVAL '10 minutes'"
        )
        jb = {r["status"]: r["n"] for r in await conn.fetch(
            "SELECT status, count(*) n FROM breakout_challenge.generation_jobs GROUP BY status"
        )}
        sessions = await conn.fetchval("SELECT count(*) FROM breakout_challenge.sessions")
        completed = await conn.fetchval(
            "SELECT count(*) FROM breakout_challenge.sessions WHERE current_state='completed'"
        )
        # API spend rollup (D): aggregate tu sessions.metadata_json.api_spend_log
        spend_rollup = await conn.fetchrow(
            """
            WITH spend_entries AS (
              SELECT
                s.access_tier,
                (entry->>'kind') AS kind,
                ((entry->>'cost_usd')::numeric) AS cost_usd
              FROM breakout_challenge.sessions s,
              jsonb_array_elements(COALESCE(s.metadata_json->'api_spend_log', '[]'::jsonb)) entry
            )
            SELECT
              COALESCE(SUM(cost_usd), 0)::float AS total_usd,
              COALESCE(SUM(cost_usd) FILTER (WHERE access_tier='free'), 0)::float AS free_usd,
              COALESCE(SUM(cost_usd) FILTER (WHERE access_tier='vip'), 0)::float AS vip_usd,
              COALESCE(SUM(cost_usd) FILTER (WHERE kind LIKE 'llm_%%'), 0)::float AS llm_usd,
              COALESCE(SUM(cost_usd) FILTER (WHERE kind='dataforseo'), 0)::float AS dataforseo_usd
            FROM spend_entries
            """
        )
    outbox_dead = int(ob.get("dead", 0))
    outbox_stuck = int(stuck or 0)
    jobs_dead = int(jb.get("dead", 0))
    fanhub_ok = await _fan_hub_reachable()
    config_ok = (
        cfg["hmac_secret"] and cfg["internal_service_key"] and cfg["fan_hub_url"]
        and cfg["ghl_api_key"] and cfg["ghl_location_id"] and cfg["ghl_custom_fields"] >= 6
        and cfg["webinarkit_api_key"] and cfg["webinarkit_webinar_id"]
        and cfg["dataforseo_login"] and cfg["dataforseo_password"]
        and cfg["youtube_api_key"] and cfg["pytrends_available"]
    )
    pipeline_ok = outbox_dead == 0 and outbox_stuck == 0 and jobs_dead == 0
    ready = bool(config_ok and pipeline_ok and fanhub_ok)
    return {
        "ready": ready,
        "config_ok": config_ok,
        "pipeline_ok": pipeline_ok,
        "fan_hub_reachable": fanhub_ok,
        "checks": {
            **cfg,
            "outbox_dead": outbox_dead,
            "outbox_stuck": outbox_stuck,
            "outbox_completed": int(ob.get("completed", 0)),
            "jobs_dead": jobs_dead,
            "sessions_total": int(sessions or 0),
            "sessions_completed": int(completed or 0),
        },
        "api_spend_usd": {
            "total": round(spend_rollup["total_usd"], 4),
            "free_tier": round(spend_rollup["free_usd"], 4),
            "vip_tier": round(spend_rollup["vip_usd"], 4),
            "llm": round(spend_rollup["llm_usd"], 4),
            "dataforseo": round(spend_rollup["dataforseo_usd"], 4),
            "per_completed_session": round(
                spend_rollup["total_usd"] / max(int(completed or 0), 1), 4
            ) if completed else None,
        },
    }


@router.get("/challenge/k3/market-readiness", dependencies=[Depends(require_service_key)])
async def k3_market_readiness(
    keyword: str = "kinh doanh online",
    access_tier: str = "vip",
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    """Internal live probe for Day 2 market APIs. Uses real API calls, so keep protected.

    access_tier query param controls which sources run:
      - "vip" (default for admin testing): 4 source (DataForSEO + YouTube + Trends + ATP)
      - "free": 3 source (no ATP)
    """
    keyword = (keyword or "kinh doanh online").strip()[:80]
    access_tier = (access_tier or "vip").lower()
    if access_tier not in ("free", "vip"):
        access_tier = "vip"
    market = await _market_signals(pool, [keyword], access_tier=access_tier)
    signals = market.get("signals") or {}
    volume_data = signals.get("volume_data") or {}
    youtube_data = signals.get("youtube_data") or {}
    trends_data = signals.get("trends_data") or {}
    atp_data = signals.get("atp_data") or {}
    youtube_one = youtube_data.get(keyword) or {}
    trends_one = trends_data.get(keyword) or {}
    atp_one = atp_data.get(keyword) or {}
    dataforseo_ok = bool(volume_data.get(keyword))
    youtube_ok = isinstance(youtube_one, dict) and "_error" not in youtube_one
    google_trends_ok = isinstance(trends_one, dict) and "_error" not in trends_one
    atp_ok = isinstance(atp_one, dict) and "_error" not in atp_one
    return {
        "ready": bool(dataforseo_ok and youtube_ok and google_trends_ok and atp_ok),
        "keyword": keyword,
        "market_score": market.get("market_score"),
        "raw_score": market.get("raw_score"),
        "verdict": market.get("verdict"),
        "evidence_status": market.get("evidence_status"),
        "available_sources": market.get("available_sources"),
        "sources": {
            "dataforseo": {
                "ok": dataforseo_ok,
                "volume_present": bool((volume_data.get(keyword) or {}).get("volume") is not None),
                "competition_present": bool((volume_data.get(keyword) or {}).get("competition_index") is not None),
            },
            "youtube": {
                "ok": youtube_ok,
                "result_count_present": bool(youtube_one.get("total_results_estimated") is not None),
                "error": None if youtube_ok else str(youtube_one.get("_error", "unknown"))[:120],
            },
            "google_trends": {
                "ok": google_trends_ok,
                "growth_present": bool(trends_one.get("growth_pct_12m") is not None),
                "error": None if google_trends_ok else str(trends_one.get("_error", "unknown"))[:160],
            },
            "answerthepublic": {
                "ok": atp_ok,
                "suggestion_count": len(atp_one.get("top_suggestions", []) or []) if atp_ok else 0,
                "error": None if atp_ok else str(atp_one.get("_error", "unknown"))[:160],
            },
        },
        "flags": market.get("flags") or [],
    }


async def _advance_session_state(conn: asyncpg.Connection, session_id: UUID, next_state: str) -> None:
    # Generation jobs can finish out of order; never let an older day move a learner backwards.
    await conn.execute(
        """
        UPDATE breakout_challenge.sessions
        SET current_state=$1
        WHERE id=$2
          AND CASE current_state
                WHEN 'registered' THEN 0
                WHEN 'd1_generating' THEN 1
                WHEN 'd1_ready' THEN 2
                WHEN 'd1_selected' THEN 3
                WHEN 'd2_generating' THEN 4
                WHEN 'd2_ready' THEN 5
                WHEN 'd2_offer_approved' THEN 6
                WHEN 'd3_generating' THEN 7
                WHEN 'completed' THEN 8
                ELSE 0
              END <= CASE $1
                WHEN 'registered' THEN 0
                WHEN 'd1_generating' THEN 1
                WHEN 'd1_ready' THEN 2
                WHEN 'd1_selected' THEN 3
                WHEN 'd2_generating' THEN 4
                WHEN 'd2_ready' THEN 5
                WHEN 'd2_offer_approved' THEN 6
                WHEN 'd3_generating' THEN 7
                WHEN 'completed' THEN 8
                ELSE 0
              END
        """,
        next_state,
        session_id,
    )


async def _enqueue_generation(
    pool: asyncpg.Pool,
    session: asyncpg.Record,
    day_number: int,
    artifact_type: str,
    inputs: dict[str, Any],
) -> UUID:
    key_source = json.dumps(inputs, ensure_ascii=False, sort_keys=True)
    key = f"{session['id']}:{artifact_type}:{hashlib.sha256(key_source.encode()).hexdigest()[:16]}"
    state = {1: "d1_generating", 2: "d2_generating", 3: "d3_generating"}[day_number]
    async with pool.acquire() as conn:
        async with conn.transaction():
            job_id = await conn.fetchval(
                """
                INSERT INTO breakout_challenge.generation_jobs
                  (idempotency_key, session_id, day_number, artifact_type, input_json)
                VALUES ($1,$2,$3,$4,$5::jsonb)
                ON CONFLICT (idempotency_key) DO UPDATE
                  SET scheduled_at=now(),
                      status=CASE WHEN breakout_challenge.generation_jobs.status='dead'
                                  THEN 'queued' ELSE breakout_challenge.generation_jobs.status END,
                      attempts=CASE WHEN breakout_challenge.generation_jobs.status='dead'
                                    THEN 0 ELSE breakout_challenge.generation_jobs.attempts END,
                      error=CASE WHEN breakout_challenge.generation_jobs.status='dead'
                                 THEN NULL ELSE breakout_challenge.generation_jobs.error END,
                      started_at=CASE WHEN breakout_challenge.generation_jobs.status='dead'
                                      THEN NULL ELSE breakout_challenge.generation_jobs.started_at END
                RETURNING id
                """,
                key,
                session["id"],
                day_number,
                artifact_type,
                json.dumps(inputs, ensure_ascii=False),
            )
            await _advance_session_state(conn, session["id"], state)
    return job_id


# Bài tập mỗi ngày chỉ mở lúc 20:00 giờ VN của đúng ngày đó (=13:00 UTC).
# Chặn học viên cày dồn / tọc mạch thử trước khi LIVE dạy cách làm.
_K3_DAY_UNLOCK_UTC = {
    1: os.getenv("K3_DAY1_UNLOCK_UTC", "2026-06-18T13:00:00+00:00"),
    2: os.getenv("K3_DAY2_UNLOCK_UTC", "2026-06-19T13:00:00+00:00"),
    3: os.getenv("K3_DAY3_UNLOCK_UTC", "2026-06-20T13:00:00+00:00"),
}
_K3_DAY_UNLOCK_LABEL = {1: "20:00 ngày 18/06", 2: "20:00 ngày 19/06", 3: "20:00 ngày 20/06"}


def _guard_day_unlocked(day: int) -> None:
    iso = _K3_DAY_UNLOCK_UTC.get(day)
    if not iso:
        return
    try:
        unlock = datetime.fromisoformat(iso)
    except ValueError:
        return
    if datetime.now(timezone.utc) < unlock:
        raise HTTPException(
            status_code=403,
            detail=f"Bài tập Ngày {day} sẽ mở lúc {_K3_DAY_UNLOCK_LABEL.get(day, '')} (giờ Việt Nam). Hãy quay lại sau nhé.",
        )


@router.post("/challenge/k3/session/{token}/day/1", status_code=202)
async def submit_day1(
    token: str,
    body: Day1Request,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    _guard_day_unlocked(1)
    session = await _session_by_token(pool, token)
    if session["current_state"] not in ("registered", "d1_generating"):
        raise HTTPException(status_code=409, detail="Ngày 1 đã được xử lý")
    job_id = await _enqueue_generation(pool, session, 1, "idea_shortlist", body.model_dump())
    return {"job_id": str(job_id), "state": "d1_generating"}


@router.post("/challenge/k3/session/{token}/day/1/select")
async def select_idea(
    token: str,
    body: IdeaSelectionRequest,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    session = await _session_by_token(pool, token)
    async with pool.acquire() as conn:
        async with conn.transaction():
            artifact = await _latest_artifact(conn, session["id"], "idea_shortlist")
            if not artifact or artifact["status"] != "generated":
                raise HTTPException(status_code=409, detail="Kết quả ngày 1 chưa sẵn sàng")
            output = _json(artifact["output_json"]) or {}
            ideas = output.get("ideas", [])
            if body.idea_index >= len(ideas):
                raise HTTPException(status_code=422, detail="Ý tưởng không tồn tại")
            selected = ideas[body.idea_index]
            await conn.execute(
                """
                UPDATE breakout_challenge.sessions
                SET selected_idea_json=$1::jsonb, current_state='d1_selected'
                WHERE id=$2
                """,
                json.dumps(selected, ensure_ascii=False),
                session["id"],
            )
            current = dict(session)
            current["selected_idea_json"] = selected
            await _record_event(
                conn,
                current,
                "challenge.day1.idea_selected",
                {
                    "summary": selected.get("name", "Đã chọn một ý tưởng"),
                    "resume_token": token,
                    "ghl_fields": {
                        "k3_current_day": "1",
                        "k3_last_active_at": datetime.now(timezone.utc).isoformat(),
                    },
                },
            )
    return {"state": "d1_selected", "selected_idea": selected}


@router.post("/challenge/k3/session/{token}/day/2", status_code=202)
async def submit_day2(
    token: str,
    body: Day2Request,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    _guard_day_unlocked(2)
    session = await _session_by_token(pool, token)
    if session["current_state"] not in ("d1_selected", "d2_generating"):
        raise HTTPException(status_code=409, detail="Hãy chọn ý tưởng ngày 1 trước")
    inputs = body.model_dump()
    inputs["selected_idea"] = _json(session["selected_idea_json"])
    job_id = await _enqueue_generation(pool, session, 2, "validated_offer_v0", inputs)
    return {"job_id": str(job_id), "state": "d2_generating"}


@router.post("/challenge/k3/session/{token}/day/2/approve")
async def approve_offer(
    token: str,
    body: OfferApprovalRequest,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    if not body.approved:
        raise HTTPException(status_code=422, detail="Offer chưa được xác nhận")
    session = await _session_by_token(pool, token)
    async with pool.acquire() as conn:
        async with conn.transaction():
            artifact = await _latest_artifact(conn, session["id"], "validated_offer_v0")
            if not artifact or artifact["status"] != "generated":
                raise HTTPException(status_code=409, detail="Kết quả ngày 2 chưa sẵn sàng")
            output = _json(artifact["output_json"]) or {}
            offer = output.get("offer_v0", {})
            await conn.execute(
                "UPDATE breakout_challenge.artifacts SET status='approved' WHERE id=$1",
                artifact["id"],
            )
            await conn.execute(
                """
                UPDATE breakout_challenge.sessions
                SET selected_offer_json=$1::jsonb, current_state='d2_offer_approved'
                WHERE id=$2
                """,
                json.dumps(offer, ensure_ascii=False),
                session["id"],
            )
            score = output.get("opportunity_score", {}).get("total", 0)
            evidence_status = artifact["evidence_status"]
            current = dict(session)
            current["selected_offer_json"] = offer
            await _record_event(
                conn,
                current,
                "challenge.day2.offer_approved",
                {
                    "summary": offer.get("name", "Offer v0"),
                    "opportunity_score": score,
                    "evidence_status": evidence_status,
                    "resume_token": token,
                    "ghl_fields": {
                        "k3_current_day": "2",
                        "k3_opportunity_score": str(score),
                        "k3_evidence_status": evidence_status,
                        "k3_offer_readiness": "approved_v0",
                        "k3_last_active_at": datetime.now(timezone.utc).isoformat(),
                    },
                },
            )
    return {"state": "d2_offer_approved", "offer": offer}


@router.post("/challenge/k3/session/{token}/day/3", status_code=202)
async def submit_day3(
    token: str,
    body: Day3Request,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    _guard_day_unlocked(3)
    session = await _session_by_token(pool, token)
    if session["current_state"] not in ("d2_offer_approved", "d3_generating"):
        raise HTTPException(status_code=409, detail="Hãy xác nhận offer ngày 2 trước")
    inputs = body.model_dump(mode="json")
    inputs["selected_idea"] = _json(session["selected_idea_json"])
    inputs["approved_offer"] = _json(session["selected_offer_json"])
    job_id = await _enqueue_generation(pool, session, 3, "sales_experiment_kit", inputs)
    return {"job_id": str(job_id), "state": "d3_generating"}


@router.get("/challenge/k3/jobs/{job_id}")
async def job_status(
    job_id: UUID,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, status, attempts, error, result_artifact_id, completed_at
            FROM breakout_challenge.generation_jobs WHERE id=$1
            """,
            job_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Job không tồn tại")
    return dict(row)


DAY1_PROMPT = """Bạn là BreakoutOS Opportunity Coach.
Từ dữ liệu founder dưới đây, tạo đúng 10 giả thuyết kinh doanh.
Đây chỉ là giả thuyết ngày 1, không được tuyên bố đã kiểm chứng thị trường.
Mỗi ý tưởng phải cụ thể và phù hợp mô hình một người cộng tác với AI.

Input:
{inputs}

Trả JSON thuần:
{{
  "founder_summary": "2-3 câu",
  "ideas": [
    {{
      "name": "...",
      "customer_hypothesis": "...",
      "problem_hypothesis": "...",
      "business_model": "service|digital_product|coaching|membership|ai_powered",
      "founder_fit": 0,
      "ai_leverage": 0,
      "constraint_fit": 0,
      "provisional_total": 0,
      "why": "...",
      "assumption_to_validate": "..."
    }}
  ],
  "warning": "Các ý tưởng chưa được kiểm chứng nhu cầu thị trường."
}}

Score từng trường từ 0 đến 10. Sort giảm dần theo provisional_total.
Không bịa số liệu. Viết tiếng Việt, câu ngắn, không dùng dấu gạch ngang dài."""

DAY2_PROMPT = """Bạn là Trợ lý Khách hàng và Định hướng Giải pháp của BreakoutOS.
Tạo Chân dung Khách hàng, Điểm Cơ hội và Định hướng Giải pháp Sơ khởi.

QUY TẮC NGÔN NGỮ TUYỆT ĐỐI (BẮT BUỘC TUÂN THỦ):

1. **OUTPUT 100% TIẾNG VIỆT.** Học viên Việt Nam ít rành thuật ngữ tiếng Anh.

2. **KHÔNG dùng thuật ngữ tiếng Anh khi có từ Việt tương đương**:
   - "score" → "điểm"
   - "verify" → "kiểm chứng"
   - "validate" → "xác thực"
   - "confidence" → "độ tin cậy"
   - "framework" → "khung", "khung lọc"
   - "monetization" → "khả năng kiếm tiền"
   - "retention" → "tỷ lệ giữ chân"
   - "upgrade" → "nâng cấp"
   - "demo" → "thử nghiệm" hoặc "trình bày"
   - "test" → "thử"
   - "draft" → "bản nháp"
   - "input" → "đầu vào", "dữ liệu"
   - "service" → "dịch vụ"
   - "session" → "buổi"
   - "subscription" → "gói thuê bao theo tháng"
   - "mood board" → "bảng cảm hứng phong cách"
   - "search volume" → "lượng người tìm kiếm"
   - "active search" → "đang tự tìm"
   - "pain" → "đau", "nỗi đau"
   - "founder" → "người sáng lập" (hoặc dùng "bạn")
   - "customer" → "khách hàng"
   - "TBD" → "Sẽ làm ở Ngày 3"
   - "hybrid" → "kết hợp"
   - "fit" → "phù hợp"

3. **Tên công cụ external giữ nguyên + chú thích tiếng Việt lần đầu**: ví dụ "AnswerThePublic (công cụ thu thập câu hỏi khách thật)", "DataForSEO (công cụ đo lượng tìm kiếm)", "Google Trends (xu hướng tìm kiếm theo thời gian)". Sau lần đầu có thể dùng tên gọi tắt tiếng Việt.

4. **Tránh dẫn thương hiệu nước ngoài** trong ví dụ trừ khi học viên đã nhắc trong input. Ưu tiên ví dụ thương hiệu Việt Nam hoặc context Việt Nam.

5. **Các trường JSON key (customer_hypothesis, framework_score, etc.) GIỮ NGUYÊN tiếng Anh** vì đây là tên field code, không phải nội dung khách đọc. Nhưng GIÁ TRỊ trong mỗi field phải 100% tiếng Việt.

6. **Câu ngắn, không dùng dấu gạch ngang dài "—"**, dùng dấu phẩy hoặc xuống dòng.

7. **Không dùng emoji** trừ khi học viên đã dùng trong input.

Input gồm 7 trường data học viên cung cấp, mỗi trường tương ứng 1 câu hỏi framework:
- customer_hypothesis: WHO, khách là ai
- pain_evidence: Câu 1 ĐAU THẬT, khách mất gì
- top_problem: vấn đề lớn nhất và mức đau 1-10
- desired_result: WHAT desired, kết quả khách muốn
- keywords: Câu 2 TỰ TÌM, từ khóa khách search
- payment_evidence: Câu 3 TRẢ TIỀN, giải pháp cũ và giá đã trả
- founder_advantage: Câu 4 LỢI THẾ TIẾP CẬN, advantage của founder

External signals bổ sung Câu 5 KIỂM CHỨNG (số lượng nguồn phụ thuộc access_tier):
- volume_data: DataForSEO search volume, CPC, competition (cả 2 tier đều có)
- youtube_data: số kết quả video (cả 2 tier đều có)
- trends_data: Google Trends 12 tháng growth (cả 2 tier đều có)
- atp_data: AnswerThePublic autocomplete suggestions từ khách thật (CHỈ VIP TIER)

Tier gating:
- Free tier (signals.access_tier="free"): 3 nguồn. atp_data sẽ có "_error":"vip_only" → max evidence_status là "partial".
- VIP tier (signals.access_tier="vip"): 4 nguồn (+ ATP). 4/4 source available → evidence_status có thể "verified".

Nếu signals.access_tier="free" và atp_data có "_error":"vip_only", AI phải ghi trong verification_speed_rationale: "Chấm theo 3 nguồn data thật cho tier free. VIP tier có thêm AnswerThePublic enrichment (autocomplete + search volume khách thật) để chấm chính xác hơn câu 5 KIỂM CHỨNG." KHÔNG bịa số ATP cho free tier.

Market demand phải dùng đúng external_signals đã cung cấp.
Nếu external_signals thiếu, nói rõ chưa đủ bằng chứng.

Input:
{inputs}

External signals:
{signals}

Market demand score đã tính: {market_score}/10.

Trả JSON thuần:
{{
  "customer_snapshot": {{
    "who": "...",
    "pain_evidence_summary": "...",
    "top_problem": "...",
    "desired_identity": "...",
    "buying_context": "infer từ payment_evidence + founder_advantage",
    "alternatives": ["từ payment_evidence"]
  }},
  "framework_score": {{
    "pain_real": 0,
    "active_search": 0,
    "payment_capacity": 0,
    "founder_advantage": 0,
    "verification_speed": 0,
    "total": 0
  }},
  "evidence_summary": {{
    "status": "insufficient|user_reported|partial|verified",
    "what_we_know": ["..."],
    "what_is_missing": ["..."]
  }},
  "opportunity_score": {{
    "founder_fit": 0,
    "market_demand": {market_score},
    "monetization": 0,
    "ai_leverage": 0,
    "confidence": 0,
    "total": 0
  }},
  "offer_v0": {{
    "label": "Định hướng giải pháp sơ khởi (NHÁP, sẽ đóng gói full ở Ngày 3)",
    "name": "Định hướng sản phẩm cho nhóm khách + vấn đề trên (1 câu mô tả)",
    "who": "(nhắc lại nhóm khách từ customer_hypothesis)",
    "pain": "(nhắc lại top_problem)",
    "desired_identity": "(nhắc lại desired_result)",
    "vehicle": "(format giải pháp: 1-1 / nhóm / digital / hybrid, KHÔNG đóng gói chi tiết)",
    "deliverables": ["Để Ngày 3 đóng gói cụ thể"],
    "price_range_vnd": {{"min": 0, "max": 0}},
    "price_note": "(BẮT BUỘC: ghi rõ source con số từ payment_evidence học viên cung cấp, HOẶC ghi 'Chưa có dữ liệu giá thật từ khách, cần phỏng vấn 5-10 khách trước Ngày 3'. TUYỆT ĐỐI KHÔNG bịa giá từ assumption_to_validate Day 1 hoặc projection customer profile.)",
    "proof_or_risk": "(rủi ro lớn nhất cần verify với khách thật trước khi đóng gói)",
    "cta": "Verify với 5-10 cuộc trò chuyện khách thật trong 7-14 ngày trước Ngày 3"
  }},
  "next_validation_actions": ["..."]
}}

QUAN TRỌNG về offer_v0: Đây KHÔNG phải sản phẩm đóng gói. Đây chỉ là ĐỊNH HƯỚNG GIẢI PHÁP SƠ KHỞI dựa trên 1 nhóm khách + 1 vấn đề học viên vừa chọn. Triết lý Ngày 2 là KHÁCH TRƯỚC, SẢN PHẨM SAU. Ngày 3 mới đóng gói sản phẩm thật (sales_experiment_kit) với landing/content/script/30-day plan. offer_v0 chỉ là direction để Ngày 3 build lên. KHÔNG bịa deliverables chi tiết.

QUY TẮC GIÁ TUYỆT ĐỐI (đọc kỹ, vi phạm là output bị từ chối):

1. **CHỈ ĐƯỢC ĐẶT price_range_vnd KHI payment_evidence CỦA HỌC VIÊN CÓ CON SỐ THẬT.**
   Con số thật = học viên đã ghi rõ "khách đã trả X đồng cho dịch vụ Y" hoặc "tôi đã bán Z đồng cho khách trước đó".

2. **KHÔNG dùng assumption_to_validate từ selected_idea (Day 1) làm bằng chứng giá.**
   assumption_to_validate là GIẢ THUYẾT AI tự đặt ra ở Day 1 để CHỜ KIỂM CHỨNG, không phải data. Nếu bạn lấy số từ đó làm price_range_vnd, bạn đang bịa.

3. **KHÔNG suy diễn giá từ customer profile** (vd: "phụ nữ Melbourne tự tin thì có thể trả X"). Đây là projection, không phải evidence.

4. **Nếu payment_evidence KHÔNG có con số thật**:
   - Set `price_range_vnd: {{"min": 0, "max": 0}}`
   - Set `price_note`: "Chưa có dữ liệu giá thật từ khách. Học viên cần phỏng vấn 5-10 khách thật + hỏi 'bạn đã từng trả bao nhiêu cho giải pháp tương tự?' trước Ngày 3."
   - framework_score.payment_capacity tối đa 5/10 (không thể chấm cao khi chưa có evidence trả tiền).

5. **Nếu payment_evidence CÓ con số thật** (vd "khách trả 500k/tháng ChatGPT Plus, 50tr cho coach 1-1"):
   - price_range_vnd dựa trên con số đó ±30%.
   - price_note: ghi rõ con số nào của khách là source.
   - framework_score.payment_capacity có thể chấm 7-10.

6. **price_note BẮT BUỘC** có trong offer_v0. Nếu thiếu, output không hợp lệ.

framework_score chấm 0-10 mỗi tiêu chí, tổng 0-50. Đây là 5 câu hỏi framework Hằng đã dạy.
opportunity_score giữ cấu trúc cũ cho backward compat dashboard hiển thị.
Mỗi score 0 đến 10.
Không bịa search volume, xu hướng hoặc bằng chứng."""

DAY3_PROMPT = """Bạn là BreakoutOS Minimum Viable Sales Coach.
Từ offer đã duyệt và nguồn lực founder, tạo Business Launch Kit đầu tiên.
Không hứa doanh thu. Không dùng dấu gạch ngang dài. Viết tiếng Việt rõ ràng.

Input:
{inputs}

HỢP ĐỒNG OUTPUT BẮT BUỘC:
- launch_content phải có ĐÚNG 30 ý tưởng bài social/Facebook.
- email_sequence phải có ĐÚNG 10 email marketing.
- roadmap_30_days phải có 4 tuần, mỗi tuần 5-7 việc cụ thể.
- Nếu chưa đủ dữ liệu, vẫn tạo bản nháp conservative dựa trên offer đã duyệt, không bịa kết quả.

Trả JSON thuần:
{{
  "one_page_offer": {{
    "headline": "...",
    "customer": "...",
    "problem": "...",
    "promise": "...",
    "vehicle": "...",
    "deliverables": ["..."],
    "price": "...",
    "cta": "..."
  }},
  "landing_page": {{
    "hero": "...",
    "problem": "...",
    "solution": "...",
    "proof": "...",
    "cta": "..."
  }},
  "launch_content": [
    {{"day": 1, "hook": "...", "body": "...", "cta": "..."}}
  ],
  "email_sequence": [
    {{"email": 1, "subject": "...", "preview": "...", "body": "...", "cta": "..."}}
  ],
  "dm_script": "...",
  "follow_up_messages": ["...", "...", "..."],
  "lead_magnet_concept": "...",
  "validation_sprint_7_days": [
    {{"day": 1, "action": "...", "evidence_to_capture": "..."}}
  ],
  "roadmap_30_days": {{
    "week_1": ["..."],
    "week_2": ["..."],
    "week_3": ["..."],
    "week_4": ["..."]
  }},
  "validation_targets": {{
    "customer_conversations": 5,
    "expressions_of_interest": 3,
    "paid_pilot_target": 1
  }}
}}

KIỂM TRA TRƯỚC KHI TRẢ:
- Count launch_content = 30.
- Count email_sequence = 10.
- Có roadmap_30_days.week_1 đến week_4.
- JSON parse được, không markdown fence."""


def _strip_json_response(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0].strip()
    return raw


def _usage_cost_usd(response: Any, model: str) -> float:
    try:
        usage = getattr(response, "usage", None)
        if usage:
            in_tok = getattr(usage, "input_tokens", 0) or 0
            out_tok = getattr(usage, "output_tokens", 0) or 0
            pricing = _MODEL_PRICING_USD.get(model, {"in": 3.0, "out": 15.0})
            return (in_tok * pricing["in"] + out_tok * pricing["out"]) / 1_000_000
    except Exception:
        pass
    return 0.0


async def _repair_json_once(raw: str, model: str) -> tuple[dict[str, Any], float]:
    response = await _client().messages.create(
        model=model,
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": (
                "Sửa đoạn dưới thành JSON thuần parse được. "
                "Không thêm markdown, không giải thích, không đổi ngôn ngữ nội dung.\n\n"
                f"{raw[:30000]}"
            ),
        }],
    )
    repaired = _strip_json_response(response.content[0].text)
    return json.loads(repaired), _usage_cost_usd(response, model)


async def _llm_json(prompt: str, model: str | None = None, max_tokens: int | None = None) -> tuple[dict[str, Any], float]:
    """Goi LLM, return (parsed_json, cost_usd). Cost tinh tu usage tokens."""
    use_model = model or MODEL
    response = await _client().messages.create(
        model=use_model,
        max_tokens=max_tokens or K3_LLM_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = _strip_json_response(response.content[0].text)
    cost = _usage_cost_usd(response, use_model)
    try:
        return json.loads(raw), cost
    except json.JSONDecodeError:
        if getattr(response, "stop_reason", "") == "max_tokens":
            raise
        repaired, repair_cost = await _repair_json_once(raw, use_model)
        return repaired, cost + repair_cost


async def _track_api_spend(pool: asyncpg.Pool, session_id, kind: str, cost_usd: float, meta: dict | None = None) -> None:
    """Append spend log vao sessions.metadata_json.api_spend_log."""
    if cost_usd <= 0 and not meta:
        return
    entry = {
        "kind": kind,  # "llm_day1" | "llm_day2" | "llm_day3" | "dataforseo" | "youtube" | "trends"
        "cost_usd": round(cost_usd, 6),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if meta:
        entry["meta"] = meta
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE breakout_challenge.sessions
            SET metadata_json = jsonb_set(
                COALESCE(metadata_json, '{}'::jsonb),
                '{api_spend_log}',
                COALESCE(metadata_json->'api_spend_log', '[]'::jsonb) || $1::jsonb,
                true
            )
            WHERE id=$2
            """,
            json.dumps(entry, ensure_ascii=False),
            session_id,
        )


def _fake_output(day_number: int, inputs: dict[str, Any], signals: dict[str, Any] | None = None) -> dict[str, Any]:
    """Deterministic smoke-test generator. Never enabled by default."""
    if day_number == 1:
        return {
            "founder_summary": "Founder có kinh nghiệm thực tế và muốn xây mô hình tinh gọn.",
            "ideas": [
                {
                    "name": f"Giải pháp thử nghiệm {index + 1}",
                    "customer_hypothesis": inputs["people_to_serve"],
                    "problem_hypothesis": "Khách hàng thiếu lộ trình rõ ràng.",
                    "business_model": "service",
                    "founder_fit": max(1, 10 - index // 2),
                    "ai_leverage": 8,
                    "constraint_fit": 8,
                    "provisional_total": max(10, 26 - index),
                    "why": "Tận dụng kinh nghiệm và tài sản hiện có.",
                    "assumption_to_validate": "Khách hàng có sẵn sàng trả tiền hay không.",
                }
                for index in range(10)
            ],
            "warning": "Các ý tưởng chưa được kiểm chứng nhu cầu thị trường.",
        }
    if day_number == 2:
        market_score = int((signals or {}).get("market_score", 5))
        framework_score = {
            "pain_real": 8,
            "active_search": market_score,
            "payment_capacity": 7,
            "founder_advantage": 8,
            "verification_speed": 6,
        }
        framework_score["total"] = sum(framework_score.values())
        scores = {
            "founder_fit": 8,
            "market_demand": market_score,
            "monetization": 7,
            "ai_leverage": 8,
            "confidence": 6,
        }
        scores["total"] = sum(scores.values())
        return {
            "customer_snapshot": {
                "who": inputs["customer_hypothesis"],
                "pain_evidence_summary": inputs["pain_evidence"],
                "top_problem": inputs["top_problem"],
                "desired_identity": inputs["desired_result"],
                "buying_context": inputs["founder_advantage"],
                "alternatives": [inputs["payment_evidence"]],
            },
            "framework_score": framework_score,
            "evidence_summary": {
                "status": (signals or {}).get("evidence_status", "user_reported"),
                "what_we_know": [inputs["pain_evidence"], inputs["payment_evidence"]],
                "what_is_missing": ["Phỏng vấn và tín hiệu thanh toán thật."],
            },
            "opportunity_score": scores,
            "offer_v0": {
                "label": "Định hướng giải pháp sơ khởi (NHÁP, sẽ đóng gói full ở Ngày 3)",
                "name": "Pilot giải pháp 7 ngày",
                "who": inputs["customer_hypothesis"],
                "pain": inputs["top_problem"],
                "desired_identity": inputs["desired_result"],
                "vehicle": "Dịch vụ hướng dẫn và AI hỗ trợ",
                "deliverables": ["Để Ngày 3 đóng gói cụ thể"],
                "price_range_vnd": {"min": 0, "max": 0},
                "price_note": "Chưa có dữ liệu giá thật từ khách. Phỏng vấn 5-10 khách + hỏi 'bạn đã từng trả bao nhiêu cho giải pháp tương tự' trước Ngày 3.",
                "proof_or_risk": "Chưa kiểm chứng nhu cầu trả tiền của khách. Cần phỏng vấn khách thật.",
                "cta": "Verify với 5-10 cuộc trò chuyện khách thật trong 7-14 ngày trước Ngày 3.",
            },
            "next_validation_actions": ["Phỏng vấn 5 khách", "Mời 1 khách pilot trả phí"],
        }
    return {
        "one_page_offer": {
            "headline": "Từ bối rối đến kế hoạch hành động rõ ràng",
            "customer": inputs["approved_offer"]["who"],
            "problem": inputs["approved_offer"]["pain"],
            "promise": inputs["approved_offer"]["desired_identity"],
            "vehicle": inputs["approved_offer"]["vehicle"],
            "deliverables": inputs["approved_offer"]["deliverables"],
            "price": "Giá pilot theo offer đã duyệt",
            "cta": "Đặt lịch trao đổi.",
        },
        "landing_page": {
            "hero": "Một bước nhỏ để kiểm chứng ý tưởng.",
            "problem": inputs["approved_offer"]["pain"],
            "solution": inputs["approved_offer"]["vehicle"],
            "proof": "Chương trình pilot giới hạn.",
            "cta": "Đặt lịch trao đổi.",
        },
        "launch_content": [
            {
                "day": i + 1,
                "hook": f"Nội dung {i + 1}",
                "body": "Chia sẻ vấn đề thật, phản chiếu nỗi đau và mời trò chuyện.",
                "cta": "Nhắn tin để trao đổi.",
            }
            for i in range(30)
        ],
        "email_sequence": [
            {
                "email": i + 1,
                "subject": f"Email {i + 1}: kiểm chứng offer nhỏ",
                "preview": "Một bước nhỏ để hiểu khách thật.",
                "body": "Chia sẻ vấn đề, giải pháp thử nghiệm và lời mời phản hồi.",
                "cta": "Reply email này nếu bạn muốn trao đổi.",
            }
            for i in range(10)
        ],
        "dm_script": "Chào bạn, tôi đang thử nghiệm một giải pháp nhỏ cho vấn đề này.",
        "follow_up_messages": ["Bạn đã xem thông tin chưa?", "Điều gì khiến bạn còn phân vân?", "Tôi đóng nhóm pilot hôm nay."],
        "lead_magnet_concept": "Checklist chẩn đoán vấn đề trong 10 phút",
        "validation_sprint_7_days": [
            {"day": day, "action": "Thực hiện một cuộc trò chuyện hoặc follow-up.", "evidence_to_capture": "Câu nói, phản hồi và hành động."}
            for day in range(1, 8)
        ],
        "roadmap_30_days": {
            "week_1": ["Phỏng vấn 5 khách"],
            "week_2": ["Chạy pilot"],
            "week_3": ["Cải tiến offer"],
            "week_4": ["Mở vòng bán tiếp theo"],
        },
        "validation_targets": {
            "customer_conversations": 5,
            "expressions_of_interest": 3,
            "paid_pilot_target": 1,
        },
    }


def _normalize_day3_output(output: dict[str, Any]) -> dict[str, Any]:
    """Enforce the K3 Day 3 hard artifact contract before saving."""
    result = dict(output or {})

    launch_content = result.get("launch_content")
    if not isinstance(launch_content, list):
        launch_content = []
    normalized_posts: list[dict[str, Any]] = []
    for idx, item in enumerate(launch_content[:30]):
        if isinstance(item, dict):
            post = dict(item)
        else:
            post = {"body": str(item)}
        post.setdefault("day", idx + 1)
        post.setdefault("hook", f"Nội dung {idx + 1}")
        post.setdefault("body", "Chia sẻ một vấn đề thật của khách hàng và cách giải pháp thử nghiệm có thể giúp họ đi bước đầu.")
        post.setdefault("cta", "Nhắn tin để trao đổi.")
        normalized_posts.append(post)
    while len(normalized_posts) < 30:
        idx = len(normalized_posts)
        normalized_posts.append({
            "day": idx + 1,
            "hook": f"Nội dung {idx + 1}: một vấn đề khách đang gặp",
            "body": "Viết một bài ngắn phản chiếu nỗi đau cụ thể của khách, kể một tình huống thật, rồi mời họ nhắn tin nếu muốn được hỏi thêm.",
            "cta": "Nhắn tin cho tôi nếu bạn đang gặp tình huống này.",
        })
    result["launch_content"] = normalized_posts

    email_sequence = result.get("email_sequence")
    if not isinstance(email_sequence, list):
        email_sequence = []
    normalized_emails: list[dict[str, Any]] = []
    for idx, item in enumerate(email_sequence[:10]):
        if isinstance(item, dict):
            email = dict(item)
        else:
            email = {"body": str(item)}
        email.setdefault("email", idx + 1)
        email.setdefault("subject", f"Email {idx + 1}: bước tiếp theo cho vấn đề này")
        email.setdefault("preview", "Một góc nhìn ngắn để bạn quyết định rõ hơn.")
        email.setdefault("body", "Nói về vấn đề của khách, một góc nhìn mới, giải pháp thử nghiệm và lời mời phản hồi.")
        email.setdefault("cta", "Reply email này nếu bạn muốn trao đổi.")
        normalized_emails.append(email)
    while len(normalized_emails) < 10:
        idx = len(normalized_emails)
        normalized_emails.append({
            "email": idx + 1,
            "subject": f"Email {idx + 1}: thử một bước nhỏ trước",
            "preview": "Không cần làm lớn ngay, hãy kiểm chứng bằng một bước nhỏ.",
            "body": "Chia sẻ nỗi đau cụ thể, lý do nên kiểm chứng nhỏ trước, và mời khách trả lời nếu họ muốn tham gia pilot.",
            "cta": "Reply email này để trao đổi thêm.",
        })
    result["email_sequence"] = normalized_emails

    roadmap = result.get("roadmap_30_days")
    if not isinstance(roadmap, dict):
        roadmap = {}
    for week in range(1, 5):
        key = f"week_{week}"
        items = roadmap.get(key)
        if not isinstance(items, list):
            items = []
        items = [str(item) for item in items[:7] if str(item).strip()]
        while len(items) < 5:
            if week == 1:
                items.append("Phỏng vấn thêm một khách thật và ghi lại đúng câu chữ họ dùng.")
            elif week == 2:
                items.append("Đăng một nội dung kiểm chứng và theo dõi phản hồi thật.")
            elif week == 3:
                items.append("Mời một khách phù hợp vào pilot nhỏ và hỏi điều kiện họ sẵn sàng trả tiền.")
            else:
                items.append("Tổng kết dữ liệu, chỉnh offer và quyết định bước bán tiếp theo.")
        roadmap[key] = items
    result["roadmap_30_days"] = roadmap

    return result


async def _market_signals(
    pool: asyncpg.Pool,
    keywords: list[str],
    access_tier: str = "free",
) -> dict[str, Any]:
    """Pull external signals for Day 2 Market Validation.

    Tier gating (2026-06-19):
      - Free tier: 3 source (DataForSEO + YouTube + Google Trends). NO ATP.
        Evidence status max: partial (cần phỏng vấn khách thật để verified).
      - VIP tier: 4 source (+ AnswerThePublic). Differentiator của Premium AI Model.
        Evidence status max: verified (khi 4/4 source available).

    ATP cache 60 ngày trong market_signal_cache. Nếu free user search cùng keyword VIP user
    đã pull, cache hit không tốn budget — nhưng free user vẫn KHÔNG được dùng cache đó vì
    gate access_tier, chỉ VIP user mới đọc atp_data từ cache.
    """
    volume = await dataforseo_search_volume(pool, keywords)
    is_vip = (access_tier or "").lower() == "vip"

    # ATP chỉ chạy cho VIP tier. Free tier skip hoàn toàn (tiết kiệm budget 100/day).
    if is_vip:
        # ATP budget tiết kiệm: chỉ pull cho keyword đầu tiên (tránh 5x cost với 100/day cap).
        atp_keywords = keywords[:1]
        youtube_results, trends_results, atp_results_first = await asyncio.gather(
            asyncio.gather(*(youtube_search_count(pool, keyword) for keyword in keywords)),
            asyncio.gather(*(google_trends_growth(pool, keyword) for keyword in keywords)),
            asyncio.gather(*(answerthepublic_questions(pool, keyword) for keyword in atp_keywords)),
        )
        atp = dict(zip(atp_keywords, atp_results_first))
    else:
        youtube_results, trends_results = await asyncio.gather(
            asyncio.gather(*(youtube_search_count(pool, keyword) for keyword in keywords)),
            asyncio.gather(*(google_trends_growth(pool, keyword) for keyword in keywords)),
        )
        # Free tier: atp gated, expose vip_only marker để AI prompt biết và communicate đúng.
        atp = {kw: {"_error": "vip_only", "_body": "ATP enrichment chỉ có cho VIP tier"} for kw in keywords[:1]}

    youtube = dict(zip(keywords, youtube_results))
    trends = dict(zip(keywords, trends_results))
    clean_volume = {} if "_error" in volume else volume
    signals = {
        "volume_data": clean_volume,
        "youtube_data": youtube,
        "trends_data": trends,
        "atp_data": atp,
        "access_tier": access_tier,
    }
    raw_score, verdict, flags = compute_demand_score(signals)
    available_sources = 0
    if clean_volume:
        available_sources += 1
    if any("_error" not in value for value in youtube.values()):
        available_sources += 1
    if any("_error" not in value for value in trends.values()):
        available_sources += 1
    if is_vip and any("_error" not in value for value in atp.values()):
        available_sources += 1

    # Evidence status mapping khác nhau tier:
    #   Free: max 3 source (DataForSEO + YouTube + Trends). Top tier max là "partial" vì
    #         cần phỏng vấn khách thật + ATP để verified.
    #   VIP: max 4 source. 4/4 source = "verified".
    if is_vip:
        evidence_status = {
            0: "user_reported",
            1: "partial",
            2: "partial",
            3: "partial",
            4: "verified",
        }[available_sources]
    else:
        evidence_status = {
            0: "user_reported",
            1: "partial",
            2: "partial",
            3: "partial",
        }[available_sources]

    return {
        "signals": signals,
        "raw_score": raw_score,
        "market_score": max(0, min(10, round(raw_score / 10))),
        "verdict": verdict,
        "flags": flags,
        "evidence_status": evidence_status,
        "available_sources": available_sources,
        "access_tier": access_tier,
    }


async def _generate_for_job(
    pool: asyncpg.Pool,
    job: dict[str, Any],
    access_tier: str = "free",
) -> tuple[dict[str, Any], dict[str, Any], str, float | None]:
    inputs = _json(job["input_json"])
    evidence: dict[str, Any] = {}
    evidence_status = "not_checked"
    confidence: float | None = None
    fake_ai = os.getenv("K3_FAKE_AI", "").lower() in ("1", "true", "yes")

    # Tier-based model: free -> Haiku, vip -> Sonnet (or per MODEL_VIP env)
    model_for_tier = MODEL_VIP if access_tier == "vip" else MODEL_FREE
    sid = job["session_id"]

    if job["day_number"] == 1:
        if fake_ai:
            output = _fake_output(1, inputs)
        else:
            output, cost = await _llm_json(
                DAY1_PROMPT.format(inputs=json.dumps(inputs, ensure_ascii=False, indent=2)),
                model=model_for_tier,
            )
            await _track_api_spend(pool, sid, "llm_day1", cost, {"model": model_for_tier, "tier": access_tier})
        confidence = 0.4
    elif job["day_number"] == 2:
        # VIP-gate market signals: free user -> skip API calls, use user_reported fallback
        if fake_ai:
            market = {"signals": {}, "market_score": 5, "evidence_status": "user_reported"}
        elif access_tier == "vip":
            market = await _market_signals(pool, inputs["keywords"], access_tier="vip")
            # Track DataForSEO spend (5 keywords typical)
            kw_count = len(inputs.get("keywords", []))
            ds_cost = kw_count * _DATAFORSEO_COST_PER_KW
            if ds_cost > 0:
                await _track_api_spend(pool, sid, "dataforseo", ds_cost, {"keywords": kw_count})
        else:
            # FREE tier: skip DataForSEO/YouTube/Trends, use neutral score
            market = {
                "signals": {},
                "market_score": 5,
                "evidence_status": "user_reported",
                "skipped_reason": "free_tier_no_external_apis",
            }
        evidence = market
        evidence_status = market["evidence_status"]
        if fake_ai:
            output = _fake_output(2, inputs, market)
        else:
            output, cost = await _llm_json(
                DAY2_PROMPT.format(
                    inputs=json.dumps(inputs, ensure_ascii=False, indent=2),
                    signals=json.dumps(market, ensure_ascii=False, indent=2)[:10000],
                    market_score=market["market_score"],
                ),
                model=model_for_tier,
            )
            await _track_api_spend(pool, sid, "llm_day2", cost, {"model": model_for_tier, "tier": access_tier})
        confidence = float(output.get("opportunity_score", {}).get("confidence", 0)) / 10
    else:
        if fake_ai:
            output = _fake_output(3, inputs)
        else:
            try:
                output, cost = await _llm_json(
                    DAY3_PROMPT.replace("{inputs}", json.dumps(inputs, ensure_ascii=False, indent=2)),
                    model=model_for_tier,
                    max_tokens=K3_DAY3_MAX_TOKENS,
                )
                await _track_api_spend(pool, sid, "llm_day3", cost, {"model": model_for_tier, "tier": access_tier})
            except json.JSONDecodeError as exc:
                log.warning("K3 Day 3 JSON parse failed, using conservative fallback: %s", exc)
                output = _fake_output(3, inputs)
                output["_generation_fallback"] = {
                    "reason": "llm_json_parse_failed",
                    "detail": str(exc)[:200],
                }
                await _track_api_spend(
                    pool,
                    sid,
                    "llm_day3_fallback",
                    0.0,
                    {"model": model_for_tier, "tier": access_tier, "error": str(exc)[:200]},
                )
        output = _normalize_day3_output(output)
        confidence = 0.6
    return output, evidence, evidence_status, confidence


async def _claim_generation(pool: asyncpg.Pool) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT * FROM breakout_challenge.generation_jobs
                WHERE status='queued' AND scheduled_at <= now()
                ORDER BY scheduled_at, created_at
                FOR UPDATE SKIP LOCKED LIMIT 1
                """
            )
            if not row:
                return None
            await conn.execute(
                """
                UPDATE breakout_challenge.generation_jobs
                SET status='processing', attempts=attempts+1, started_at=now()
                WHERE id=$1
                """,
                row["id"],
            )
            result = dict(row)
            result["attempts"] += 1
            return result


async def _complete_generation(pool: asyncpg.Pool, job: dict[str, Any]) -> None:
    # Lookup session access_tier de quyet dinh model + bat API ngoai
    async with pool.acquire() as conn:
        access_tier = await conn.fetchval(
            "SELECT access_tier FROM breakout_challenge.sessions WHERE id=$1",
            job["session_id"],
        )
    access_tier = (access_tier or "free").lower()
    output, evidence, evidence_status, confidence = await _generate_for_job(pool, job, access_tier=access_tier)
    next_state = {1: "d1_ready", 2: "d2_ready", 3: "completed"}[job["day_number"]]
    async with pool.acquire() as conn:
        async with conn.transaction():
            artifact_id = await conn.fetchval(
                """
                INSERT INTO breakout_challenge.artifacts
                  (session_id, day_number, artifact_type, input_json, output_json,
                   evidence_json, evidence_status, confidence_score, status, generated_by)
                VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb,$7,$8,'generated',$9)
                ON CONFLICT (session_id, artifact_type, version) DO UPDATE
                  SET input_json=EXCLUDED.input_json,
                      output_json=EXCLUDED.output_json,
                      evidence_json=EXCLUDED.evidence_json,
                      evidence_status=EXCLUDED.evidence_status,
                      confidence_score=EXCLUDED.confidence_score,
                      status='generated',
                      generated_by=EXCLUDED.generated_by,
                      updated_at=now()
                RETURNING id
                """,
                job["session_id"],
                job["day_number"],
                job["artifact_type"],
                json.dumps(_json(job["input_json"]), ensure_ascii=False),
                json.dumps(output, ensure_ascii=False),
                json.dumps(evidence, ensure_ascii=False),
                evidence_status,
                confidence,
                "deterministic_smoke" if os.getenv("K3_FAKE_AI") else MODEL,
            )
            await conn.execute(
                """
                UPDATE breakout_challenge.generation_jobs
                SET status='completed', completed_at=now(), result_artifact_id=$1
                WHERE id=$2
                """,
                artifact_id,
                job["id"],
            )
            await _advance_session_state(conn, job["session_id"], next_state)
            if job["day_number"] == 3:
                session = await conn.fetchrow(
                    "SELECT * FROM breakout_challenge.sessions WHERE id=$1",
                    job["session_id"],
                )
                await _record_event(
                    conn,
                    session,
                    "challenge.completed",
                    {
                        "summary": "Đã tạo Sales Experiment Kit và kế hoạch kiểm chứng 30 ngày.",
                        "ghl_fields": {
                            "k3_current_day": "3",
                            "k3_offer_readiness": "sales_experiment_ready",
                            "k3_last_active_at": datetime.now(timezone.utc).isoformat(),
                        },
                    },
                )


async def _fail_generation(pool: asyncpg.Pool, job: dict[str, Any], exc: Exception) -> None:
    dead = job["attempts"] >= job["max_attempts"]
    status = "dead" if dead else "queued"
    delay = min(300, 15 * (2 ** job["attempts"]))
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                f"""
                UPDATE breakout_challenge.generation_jobs
                SET status=$1, error=$2,
                    scheduled_at=CASE WHEN $1='queued'
                      THEN now()+INTERVAL '{delay} seconds' ELSE scheduled_at END
                WHERE id=$3
                """,
                status,
                f"{type(exc).__name__}: {str(exc)[:800]}",
                job["id"],
            )
            if dead:
                # Job đã chết hẳn: gắn tag để Anna + automation theo dõi và hỗ trợ.
                # Event idempotent theo session nên không spam tag dù nhiều job dead.
                session = await conn.fetchrow(
                    "SELECT * FROM breakout_challenge.sessions WHERE id=$1",
                    job["session_id"],
                )
                if session is not None:
                    await _record_event(
                        conn,
                        session,
                        "challenge.generation_failed",
                        {
                            "summary": (
                                f"Lỗi tạo kết quả ngày {job['day_number']} "
                                f"sau {job['attempts']} lần thử."
                            ),
                            "day_number": job["day_number"],
                            "ghl_fields": {
                                "k3_last_active_at": datetime.now(timezone.utc).isoformat(),
                            },
                        },
                    )
    log.exception("K3 generation job failed id=%s", job["id"])


async def _claim_outbox(pool: asyncpg.Pool) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT * FROM breakout_challenge.integration_outbox
                WHERE status='queued' AND scheduled_at <= now()
                ORDER BY scheduled_at, created_at
                FOR UPDATE SKIP LOCKED LIMIT 1
                """
            )
            if not row:
                return None
            await conn.execute(
                """
                UPDATE breakout_challenge.integration_outbox
                SET status='processing', attempts=attempts+1 WHERE id=$1
                """,
                row["id"],
            )
            result = dict(row)
            result["attempts"] += 1
            return result


async def _sync_fanhub(pool: asyncpg.Pool, item: dict[str, Any]) -> None:
    base = os.getenv("FAN_HUB_INTERNAL_URL", "https://fan.daothihang.com").rstrip("/")
    key = os.getenv("INTERNAL_SERVICE_KEY", "")
    if not key:
        raise RuntimeError("INTERNAL_SERVICE_KEY not configured")
    payload = _json(item["payload_json"])
    endpoint = (
        "/internal/v1/persons/resolve"
        if item["operation"] == "person.resolve"
        else "/internal/v1/events"
    )
    payload.setdefault("tenant_slug", os.getenv("FAN_HUB_TENANT_SLUG", "hangdao"))
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{base}{endpoint}",
            json=payload,
            headers={"X-Internal-Service-Key": key},
        )
    response.raise_for_status()
    data = response.json()
    if item["operation"] == "person.resolve":
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE breakout_challenge.sessions
                SET fanhub_person_id=$1 WHERE id=$2
                """,
                UUID(data["person_id"]),
                item["session_id"],
            )


async def _ghl_contact_id(
    email: str,
    existing_id: str | None,
    full_name: str | None = None,
    phone: str | None = None,
) -> str:
    if existing_id:
        return existing_id
    api_key = os.getenv("GHL_API_KEY", "")
    location_id = os.getenv("GHL_LOCATION_ID", "")
    if not api_key or not location_id:
        raise RuntimeError("GHL credentials not configured")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Version": "2021-07-28",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://services.leadconnectorhq.com/contacts/search",
            headers=headers,
            json={
                "locationId": location_id,
                "page": 1,
                "pageLimit": 1,
                "filters": [{"field": "email", "operator": "eq", "value": email}],
            },
        )
    response.raise_for_status()
    contacts = response.json().get("contacts", [])
    if contacts:
        return contacts[0]["id"]

    upsert_payload = {"locationId": location_id, "email": email}
    if full_name:
        upsert_payload["name"] = full_name
    if phone:
        upsert_payload["phone"] = phone
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://services.leadconnectorhq.com/contacts/upsert",
            headers=headers,
            json=upsert_payload,
        )
    response.raise_for_status()
    contact = response.json().get("contact") or response.json()
    if not contact.get("id"):
        raise RuntimeError("GHL upsert did not return contact id")
    return contact["id"]


async def _sync_ghl(pool: asyncpg.Pool, item: dict[str, Any]) -> None:
    payload = _json(item["payload_json"])
    contact_id = await _ghl_contact_id(
        payload["email"],
        payload.get("ghl_contact_id"),
        payload.get("full_name"),
        payload.get("phone"),
    )
    api_key = os.getenv("GHL_API_KEY", "")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Version": "2021-07-28",
        "Content-Type": "application/json",
    }
    field_ids = json.loads(os.getenv("GHL_K3_CUSTOM_FIELD_IDS", "{}") or "{}")
    custom_fields = [
        {"id": field_ids[key], "field_value": value}
        for key, value in payload.get("fields", {}).items()
        if key in field_ids and value is not None
    ]
    async with httpx.AsyncClient(timeout=20) as client:
        tags = payload.get("tags", [])
        if tags:
            response = await client.post(
                f"https://services.leadconnectorhq.com/contacts/{contact_id}/tags",
                headers=headers,
                json={"tags": tags},
            )
            response.raise_for_status()
        if custom_fields:
            response = await client.put(
                f"https://services.leadconnectorhq.com/contacts/{contact_id}",
                headers=headers,
                json={"customFields": custom_fields},
            )
            response.raise_for_status()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE breakout_challenge.sessions SET ghl_contact_id=$1 WHERE id=$2",
            contact_id,
            item["session_id"],
        )


async def _process_outbox(pool: asyncpg.Pool, item: dict[str, Any]) -> None:
    try:
        if item["target"] == "fanhub":
            await _sync_fanhub(pool, item)
        else:
            await _sync_ghl(pool, item)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE breakout_challenge.integration_outbox
                SET status='completed', completed_at=now(), error=NULL WHERE id=$1
                """,
                item["id"],
            )
    except Exception as exc:
        dead = item["attempts"] >= item["max_attempts"]
        status = "dead" if dead else "queued"
        delay = min(900, 30 * (2 ** item["attempts"]))
        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                UPDATE breakout_challenge.integration_outbox
                SET status=$1, error=$2,
                    scheduled_at=CASE WHEN $1='queued'
                      THEN now()+INTERVAL '{delay} seconds' ELSE scheduled_at END
                WHERE id=$3
                """,
                status,
                f"{type(exc).__name__}: {str(exc)[:800]}",
                item["id"],
            )
        log.warning("K3 outbox failed id=%s target=%s: %r", item["id"], item["target"], exc)


async def challenge_worker_loop(stop_event: asyncio.Event) -> None:
    """Process generation and integration jobs until application shutdown."""
    pool = await get_pool()
    log.info("K3 worker started")
    while not stop_event.is_set():
        worked = False
        try:
            job = await _claim_generation(pool)
            if job:
                worked = True
                try:
                    await _complete_generation(pool, job)
                except Exception as exc:
                    await _fail_generation(pool, job, exc)
            item = await _claim_outbox(pool)
            if item:
                worked = True
                await _process_outbox(pool, item)
        except asyncpg.UndefinedTableError:
            log.warning("K3 migration not applied yet, worker waiting")
        except Exception:
            log.exception("K3 worker loop error")
        if not worked:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass
    log.info("K3 worker stopped")


def _pretty(value: Any) -> str:
    return html.escape(json.dumps(_json(value), ensure_ascii=False, indent=2))


@router.get("/challenge/k3/session/{token}")
async def get_session(
    token: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict[str, Any]:
    session = await _session_by_token(pool, token)
    async with pool.acquire() as conn:
        artifacts = await conn.fetch(
            """
            SELECT day_number, artifact_type, input_json, output_json, evidence_json, evidence_status,
                   confidence_score, status, updated_at
            FROM breakout_challenge.artifacts
            WHERE session_id=$1 ORDER BY day_number
            """,
            session["id"],
        )
    return {
        "session_id": str(session["id"]),
        "state": session["current_state"],
        "access_tier": session["access_tier"],
        "selected_idea": _json(session["selected_idea_json"]),
        "selected_offer": _json(session["selected_offer_json"]),
        "artifacts": [
            {
                **dict(row),
                "input_json": _json(row["input_json"]),
                "output_json": _json(row["output_json"]),
                "evidence_json": _json(row["evidence_json"]),
            }
            for row in artifacts
        ],
    }


@router.get("/sprint/k3/{token}", response_class=HTMLResponse)
async def resume_page(
    token: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> HTMLResponse:
    session = await _session_by_token(pool, token)
    async with pool.acquire() as conn:
        d1 = await _latest_artifact(conn, session["id"], "idea_shortlist")
        d2 = await _latest_artifact(conn, session["id"], "validated_offer_v0")
        d3 = await _latest_artifact(conn, session["id"], "sales_experiment_kit")

    state = session["current_state"]
    content = ""
    if state == "registered":
        content = """
        <h2>Ngày 1: Chọn cơ hội phù hợp</h2>
        <form id="day1">
          <textarea name="lived_experience" placeholder="Kinh nghiệm sống và chuyên môn" required></textarea>
          <textarea name="skills_and_proof" placeholder="Kỹ năng, thành tựu và bằng chứng" required></textarea>
          <textarea name="assets_and_network" placeholder="Tài sản, network và audience" required></textarea>
          <textarea name="energizing_topics" placeholder="Chủ đề tạo năng lượng" required></textarea>
          <textarea name="people_to_serve" placeholder="Nhóm người bạn hiểu và muốn phục vụ" required></textarea>
          <textarea name="lifestyle_and_time" placeholder="Lối sống mong muốn và thời gian mỗi tuần" required></textarea>
          <textarea name="anti_vision" placeholder="Những điều bạn không muốn" required></textarea>
          <button>Phân tích 10 ý tưởng</button>
        </form>"""
    elif state in ("d1_generating", "d2_generating", "d3_generating"):
        content = "<h2>Hệ thống đang tạo kết quả</h2><p>Trang sẽ tự cập nhật sau vài giây.</p><script>setTimeout(()=>location.reload(),4000)</script>"
    elif state == "d1_ready" and d1:
        ideas = (_json(d1["output_json"]) or {}).get("ideas", [])
        cards = "".join(
            f"""<button class="choice" onclick="selectIdea({index})">
            <strong>{html.escape(idea.get('name',''))}</strong>
            <span>{html.escape(idea.get('why',''))}</span>
            <small>{idea.get('provisional_total',0)}/30, điểm tạm thời</small>
            </button>"""
            for index, idea in enumerate(ideas)
        )
        content = f"<h2>Chọn một ý tưởng để kiểm chứng</h2><p>Đây là giả thuyết, chưa phải kết luận thị trường.</p><div class='choices'>{cards}</div>"
    elif state == "d1_selected":
        content = """
        <h2>Ngày 2: 5 câu hỏi lọc ý tưởng</h2>
        <form id="day2">
          <textarea name="customer_hypothesis" placeholder="Khách hàng đầu tiên là ai" required></textarea>
          <textarea name="pain_evidence" placeholder="Khách đã mất tiền, thời gian hoặc kết quả gì" required></textarea>
          <textarea name="top_problem" placeholder="Vấn đề lớn nhất và mức đau 1-10" required></textarea>
          <textarea name="desired_result" placeholder="Kết quả hoặc phiên bản mới khách mong muốn" required></textarea>
          <input name="keywords" placeholder="Từ khóa, phân cách bằng dấu phẩy" required>
          <textarea name="payment_evidence" placeholder="Giải pháp khách đang dùng và đã trả bao nhiêu" required></textarea>
          <textarea name="founder_advantage" placeholder="Lợi thế tiếp cận của bạn với nhóm khách này" required></textarea>
          <button>Kiểm chứng và tạo Offer v0</button>
        </form>"""
    elif state == "d2_ready" and d2:
        output = _json(d2["output_json"]) or {}
        content = f"""
        <h2>Offer v0</h2>
        <p>Evidence status: <strong>{html.escape(d2['evidence_status'])}</strong></p>
        <pre>{_pretty(output)}</pre>
        <button onclick="approveOffer()">Xác nhận Offer v0</button>"""
    elif state == "d2_offer_approved":
        content = """
        <h2>Ngày 3: Minimum Viable Sales Experiment</h2>
        <form id="day3">
          <input name="sales_channel" placeholder="Kênh bán chính" required>
          <input name="audience_size" type="number" min="0" placeholder="Quy mô audience" required>
          <input name="available_hours_per_week" type="number" min="1" max="80" placeholder="Số giờ mỗi tuần" required>
          <input name="launch_date" type="date" required>
          <input name="delivery_capacity" type="number" min="1" placeholder="Số khách có thể phục vụ" required>
          <button>Tạo Sales Experiment Kit</button>
        </form>"""
    elif state == "completed" and d3:
        content = f"""
        <h2>Bạn đã hoàn thành K3</h2>
        <p>Kết quả là bản nháp để kiểm chứng. Foundation sẽ giúp review và chuyển thành hệ thống canonical.</p>
        <pre>{_pretty(d3['output_json'])}</pre>"""

    return HTMLResponse(f"""<!doctype html><html lang="vi"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Breakout Challenge K3</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#faf8f2;color:#181512;font-family:Arial,sans-serif;line-height:1.55}}
main{{max-width:820px;margin:0 auto;padding:32px 18px 80px}} .top{{border-bottom:1px solid #ddd4c5;margin-bottom:24px;padding-bottom:18px}}
h1{{font-size:30px;margin:0 0 8px}} h2{{font-size:23px}} .state{{color:#7a1f1f;font-weight:700}}
form{{display:grid;gap:12px}} textarea,input{{width:100%;padding:14px;border:1px solid #cfc5b5;border-radius:9px;font:inherit}}
textarea{{min-height:100px}} button{{padding:14px 18px;border:0;border-radius:9px;background:#b4232c;color:white;font-weight:700;cursor:pointer}}
.choices{{display:grid;gap:12px}} .choice{{text-align:left;background:white;color:#181512;border:1px solid #ddd4c5;display:grid;gap:6px}}
.choice span,.choice small{{font-weight:400;color:#625b52}} pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:white;border:1px solid #ddd4c5;padding:16px;border-radius:9px}}
#msg{{margin-top:16px;color:#7a1f1f;font-weight:700}}
</style></head><body><main>
<div class="top"><h1>Breakout Challenge K3</h1><div class="state">Trạng thái: {html.escape(state)}</div></div>
{content}<div id="msg"></div>
</main><script>
const token={json.dumps(token)};
async function send(path,data){{
  const r=await fetch('/challenge/k3/session/'+token+path,{{
    method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(data)
  }});
  const result=await r.json();
  if(!r.ok) throw new Error(result.detail||'Có lỗi');
  location.reload();
}}
function values(form){{
  const data=Object.fromEntries(new FormData(form).entries());
  for(const key of ['audience_size','available_hours_per_week','delivery_capacity']) if(key in data) data[key]=Number(data[key]);
  if(data.keywords) data.keywords=data.keywords.split(',').map(x=>x.trim()).filter(Boolean);
  return data;
}}
const d1=document.getElementById('day1'); if(d1)d1.onsubmit=e=>{{e.preventDefault();send('/day/1',values(d1)).catch(show)}};
const d2=document.getElementById('day2'); if(d2)d2.onsubmit=e=>{{e.preventDefault();send('/day/2',values(d2)).catch(show)}};
const d3=document.getElementById('day3'); if(d3)d3.onsubmit=e=>{{e.preventDefault();send('/day/3',values(d3)).catch(show)}};
function selectIdea(index){{send('/day/1/select',{{idea_index:index}}).catch(show)}}
function approveOffer(){{send('/day/2/approve',{{approved:true}}).catch(show)}}
function show(error){{document.getElementById('msg').textContent=error.message}}
</script></body></html>""")


@router.get("/challenge/k3/result/{token}", response_class=HTMLResponse)
async def result_page(
    token: str,
    pool: asyncpg.Pool = Depends(get_pool),
) -> HTMLResponse:
    session = await _session_by_token(pool, token)
    if session["current_state"] != "completed":
        raise HTTPException(status_code=409, detail="Challenge chưa hoàn thành")
    async with pool.acquire() as conn:
        artifacts = await conn.fetch(
            """
            SELECT day_number, artifact_type, output_json, evidence_status
            FROM breakout_challenge.artifacts
            WHERE session_id=$1 ORDER BY day_number
            """,
            session["id"],
        )
    sections = "".join(
        f"<h2>Ngày {row['day_number']}</h2><p>Evidence: {html.escape(row['evidence_status'])}</p><pre>{_pretty(row['output_json'])}</pre>"
        for row in artifacts
    )
    return HTMLResponse(
        f"<!doctype html><html lang='vi'><meta charset='utf-8'><title>Kết quả K3</title>"
        f"<body style='font-family:Arial;max-width:900px;margin:30px auto;padding:0 16px'>"
        f"<h1>Kết quả Breakout Challenge K3</h1>{sections}</body></html>"
    )
