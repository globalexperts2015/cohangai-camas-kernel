"""Day 3 Business Discovery Engine.

POST /sdl/discovery/run        Trigger AI Discovery Engine on student L1+L2 data
GET  /sdl/students/{id}/discovery/report   Latest report HTML
GET  /sdl/students/{id}/discovery/history  List all reports

Per Anna 2026-06-13 spec: 9-section report aggregating L1 + L2 canonical files.
External APIs (Google Trends/ATP/Reddit) deferred → mock layer ready when integrated.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any
from uuid import UUID

import anthropic
import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from routes._auth import _verify_hmac
from routes.sdl_routes import get_pool


router = APIRouter(prefix="/sdl/discovery", tags=["sdl-discovery"])
log = logging.getLogger("camas.discovery")

_CLIENT: anthropic.AsyncAnthropic | None = None


def _client() -> anthropic.AsyncAnthropic:
    global _CLIENT
    if _CLIENT is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _CLIENT = anthropic.AsyncAnthropic(api_key=api_key)
    return _CLIENT


async def _gather_canonical(
    conn: asyncpg.Connection, student_id: UUID,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pull latest L1 + L2 canonical files as nested dicts."""
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (file_key) level, file_key, markdown_content,
          structured_data_json
        FROM breakoutos.canonical_files
        WHERE student_id=$1 AND level IN (1, 2)
        ORDER BY file_key, version DESC
        """,
        student_id,
    )
    l1, l2 = {}, {}
    for r in rows:
        target = l1 if r["level"] == 1 else l2
        target[r["file_key"]] = {
            "markdown": r["markdown_content"],
            "structured": json.loads(r["structured_data_json"]) if r["structured_data_json"] else {},
        }
    return l1, l2


DISCOVERY_PROMPT = """Bạn là Business Discovery Engine cho BreakoutOS, hỗ trợ founder Việt phụ nữ văn phòng.

Đầu vào: dữ liệu canonical Day 1 (L1 Founder OS) + Day 2 (L2 Customer Intelligence) của 1 học viên.

# L1 Founder OS canonical files
{l1_data}

# L2 Customer Intelligence canonical files
{l2_data}

Nhiệm vụ: trả về MỘT JSON object đúng schema dưới. Không thêm text ngoài JSON. Không markdown fence.

QUY TẮC SINH NỘI DUNG:
- Tiếng Việt, câu ngắn, không dấu "—" (dùng phẩy).
- Bắt đầu từ founder thực + customer thực. KHÔNG bịa số, không claim "80% người Việt".
- Mỗi idea phải dựa trên L1 năng lực + L2 pain. Idea generic = không pass.
- Section 5 score 0-10 cho từng dimension. Tổng = sum 5 dim. Sort theo tổng giảm dần.
- Section 4: ≥5 idea mỗi loại (product, service, coaching, membership, ai_powered). Pilot nhỏ MVP, có thể mở rộng sau.
- Section 7 One Page Offer: dùng TOP 1 từ section 6, viết như Anna ngồi với founder pha trà.
- Section 8: 5 idea mỗi channel (content_post, video_short, fb_post, youtube, lead_magnet). MVP, scale sau.
- Section 9: 4 tuần action cụ thể, mỗi tuần 3-5 việc. Mục tiêu: khách đầu tiên cuối tuần 4.

SCHEMA JSON (trả về CHÍNH XÁC keys + types này):
{{
  "section_1_founder_summary": {{
    "who_you_are": "câu",
    "your_unique_advantage": ["lợi thế 1", "lợi thế 2", "..."],
    "who_you_serve_best": "câu"
  }},
  "section_2_customer_reality": {{
    "top_pain": "câu",
    "top_desire": "câu",
    "most_urgent_problem": "câu",
    "pains_ranked": [{{"pain": "...", "severity": 1-10}}]
  }},
  "section_3_market_demand": [
    {{"keyword": "...", "search_intent": "informational|navigational|transactional|commercial",
      "trend_score": 1-10, "opportunity_score": 1-10, "data_source": "mocked|google_trends|youtube|reddit"}}
  ],
  "section_4_opportunity_ideas": {{
    "product": [{{"name": "...", "solves_pain": "...", "fit_founder": "...", "market_need": "..."}}],
    "service": [{{...}}],
    "coaching": [{{...}}],
    "membership": [{{...}}],
    "ai_powered": [{{...}}]
  }},
  "section_5_validation_matrix": [
    {{"idea_name": "...", "founder_fit": 0-10, "customer_fit": 0-10,
      "market_demand": 0-10, "profit_potential": 0-10, "ai_leverage": 0-10, "total": 0-50}}
  ],
  "section_6_recommended_offer": {{
    "top_pick_name": "...",
    "why": "câu",
    "main_risk": "câu",
    "timeline_days": <int>,
    "first_sale_strategy": "câu"
  }},
  "section_7_one_page_offer": {{
    "product_name": "...",
    "customer": "...",
    "problem": "...",
    "solution": "...",
    "result": "...",
    "suggested_price_vnd": <int>,
    "guarantee": "...",
    "sales_channel": "...",
    "cta": "..."
  }},
  "section_8_content_engine": {{
    "content_post": ["idea 1", "..."],
    "video_short": ["idea 1", "..."],
    "fb_post": ["idea 1", "..."],
    "youtube": ["idea 1", "..."],
    "lead_magnet": ["idea 1", "..."]
  }},
  "section_9_action_plan": {{
    "week_1": ["việc 1", "..."],
    "week_2": ["việc 1", "..."],
    "week_3": ["việc 1", "..."],
    "week_4": ["việc 1", "..."],
    "goal": "Có khách hàng đầu tiên cuối tuần 4."
  }}
}}"""


async def _generate_discovery(
    student_id: UUID, pool: asyncpg.Pool,
) -> None:
    """Background task: run AI discovery + persist report."""
    started = time.time()
    async with pool.acquire() as conn:
        l1, l2 = await _gather_canonical(conn, student_id)
        if not l1 or not l2:
            await conn.execute(
                """
                INSERT INTO breakoutos.discovery_reports
                  (student_id, founder_profile_snapshot_json, customer_profile_snapshot_json,
                   status, error_payload, generation_seconds)
                VALUES ($1, $2::jsonb, $3::jsonb, 'generation_failed', $4::jsonb, $5)
                """,
                student_id, json.dumps(l1), json.dumps(l2),
                json.dumps({"error": "missing_canonical", "l1_count": len(l1), "l2_count": len(l2)}),
                time.time() - started,
            )
            log.warning("discovery generation_failed: missing L1/L2 canonical")
            return

        prompt = DISCOVERY_PROMPT.format(
            l1_data=json.dumps(l1, ensure_ascii=False, indent=2)[:8000],
            l2_data=json.dumps(l2, ensure_ascii=False, indent=2)[:8000],
        )
        model = "claude-sonnet-4-6"
        try:
            resp = await _client().messages.create(
                model=model,
                max_tokens=8000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw
                if raw.endswith("```"):
                    raw = raw.rsplit("```", 1)[0]
                raw = raw.strip()
            parsed = json.loads(raw)
        except (anthropic.APIStatusError, anthropic.APIError) as exc:
            await conn.execute(
                """
                INSERT INTO breakoutos.discovery_reports
                  (student_id, founder_profile_snapshot_json, customer_profile_snapshot_json,
                   status, error_payload, generation_seconds, ai_model)
                VALUES ($1, $2::jsonb, $3::jsonb, 'generation_failed', $4::jsonb, $5, $6)
                """,
                student_id, json.dumps(l1), json.dumps(l2),
                json.dumps({"error": "api_error", "message": str(exc)}),
                time.time() - started, model,
            )
            log.exception("discovery API error")
            return
        except json.JSONDecodeError as exc:
            await conn.execute(
                """
                INSERT INTO breakoutos.discovery_reports
                  (student_id, founder_profile_snapshot_json, customer_profile_snapshot_json,
                   status, error_payload, generation_seconds, ai_model)
                VALUES ($1, $2::jsonb, $3::jsonb, 'generation_failed', $4::jsonb, $5, $6)
                """,
                student_id, json.dumps(l1), json.dumps(l2),
                json.dumps({"error": "json_decode", "raw_head": raw[:500] if 'raw' in dir() else ""}),
                time.time() - started, model,
            )
            log.exception("discovery JSON decode error")
            return

        await conn.execute(
            """
            INSERT INTO breakoutos.discovery_reports
              (student_id, founder_profile_snapshot_json, customer_profile_snapshot_json,
               section_1_founder_summary_json,
               section_2_customer_reality_json,
               section_3_market_demand_json,
               section_4_opportunity_ideas_json,
               section_5_validation_matrix_json,
               section_6_recommended_offer_json,
               section_7_one_page_offer_json,
               section_8_content_engine_json,
               section_9_action_plan_json,
               generation_method, ai_model, generation_seconds, status)
            VALUES ($1, $2::jsonb, $3::jsonb,
                    $4::jsonb, $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb,
                    $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb,
                    'ai', $13, $14, 'completed')
            """,
            student_id, json.dumps(l1), json.dumps(l2),
            json.dumps(parsed.get("section_1_founder_summary", {})),
            json.dumps(parsed.get("section_2_customer_reality", {})),
            json.dumps(parsed.get("section_3_market_demand", [])),
            json.dumps(parsed.get("section_4_opportunity_ideas", {})),
            json.dumps(parsed.get("section_5_validation_matrix", [])),
            json.dumps(parsed.get("section_6_recommended_offer", {})),
            json.dumps(parsed.get("section_7_one_page_offer", {})),
            json.dumps(parsed.get("section_8_content_engine", {})),
            json.dumps(parsed.get("section_9_action_plan", {})),
            model, time.time() - started,
        )
        # Telegram alert
        try:
            from routes.telegram_alert import send_telegram_sync, _student_meta_block, sign_student
            meta = await conn.fetchrow(
                "SELECT email, full_name FROM breakoutos.students WHERE id=$1",
                student_id,
            )
            sig = sign_student(str(student_id))
            top = parsed.get("section_6_recommended_offer", {}).get("top_pick_name", "?")
            send_telegram_sync(
                f"🚀 <b>DISCOVERY ENGINE DONE</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{_student_meta_block(str(student_id), meta['email'] if meta else '', meta['full_name'] if meta else '')}\n"
                f"<b>TOP 1:</b> {top}\n"
                f"<b>Report:</b> https://os.breakout.live/sdl/students/{student_id}/discovery/report?sig={sig}"
            )
        except Exception:
            log.exception("telegram alert fail (non-fatal)")


@router.post("/run", status_code=202)
async def run_discovery(
    student_id: UUID,
    background: BackgroundTasks,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Trigger Discovery Engine for student. AI runs background."""
    background.add_task(_generate_discovery, student_id, pool)
    return {"status": "discovery_running", "student_id": str(student_id),
            "estimated_seconds": 45,
            "next": f"/sdl/students/{student_id}/discovery/report"}


@router.get("/students/{student_id}/discovery/history", include_in_schema=True)
async def discovery_history(
    student_id: UUID,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, status, ai_model, generation_seconds, created_at,
              error_payload
            FROM breakoutos.discovery_reports
            WHERE student_id=$1
            ORDER BY created_at DESC
            """,
            student_id,
        )
    return {"student_id": str(student_id),
            "reports": [dict(r) | {"id": str(r["id"]),
                                   "created_at": r["created_at"].isoformat(),
                                   "error_payload": json.loads(r["error_payload"]) if r["error_payload"] else None}
                       for r in rows]}
