"""Day 3 Challenge standalone form.

Public flow (no BreakoutOS login):
- GET  /day3                       Form 5 inputs
- POST /day3/submit                Save + trigger discovery
- GET  /day3/report/{session_id}   View 9-section report

Per Anna 2026-06-13: học viên Day 3 không cần qua os.breakout.live full flow.
Nhập 5 input từ Day 1 + Day 2 thẳng vào form → nhận Discovery Report 9 section.
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
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from routes.sdl_routes import get_pool


router = APIRouter(tags=["day3-challenge"])
log = logging.getLogger("camas.day3")

_CLIENT: anthropic.AsyncAnthropic | None = None


def _client() -> anthropic.AsyncAnthropic:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _CLIENT


DAY3_PROMPT = """Bạn là Business Discovery Engine cho BreakoutOS, dành cho founder Việt phụ nữ văn phòng muốn 1 mình + AI xây kinh doanh.

# Day 1 + Day 2 inputs từ học viên

**Tôi là ai (Day 1)**:
{who_am_i}

**Năng lực cốt lõi của tôi (Day 1)**:
{core_skills}

**Tôi muốn phục vụ ai (Day 2)**:
{target_customer}

**Nỗi đau lớn nhất của khách (Day 2)**:
{customer_pain}

**Khát khao của khách (Day 2)**:
{customer_desire}

# Nhiệm vụ

Phân tích 5 input trên + thị trường Việt Nam + xu hướng AI 2026. Trả về JSON ĐÚNG schema dưới, KHÔNG markdown fence, KHÔNG text ngoài JSON.

QUY TẮC NỘI DUNG:
- Tiếng Việt, câu ngắn, không dấu "—".
- Bắt đầu từ founder thực + customer thực. KHÔNG bịa "80% phụ nữ Việt...".
- Mỗi idea phải dựa năng lực founder + pain khách. Idea generic = fail.
- Section 4: ≥5 idea mỗi loại (product, service, coaching, membership, ai_powered).
- Section 5 score 0-10 từng dim, total = sum 5 dim, sort total DESC.
- Section 7 One Page Offer: dùng TOP 1 từ section 6.
- Section 8: 5 idea mỗi channel.
- Section 9: 4 tuần, mỗi tuần 3-5 việc cụ thể.
- Suggested price: số nguyên VND (ví dụ 1500000 cho 1.5tr).

SCHEMA:
{{
  "section_1_founder_summary": {{
    "who_you_are": "câu",
    "your_unique_advantage": ["lợi thế 1", "lợi thế 2", "lợi thế 3"],
    "who_you_serve_best": "câu"
  }},
  "section_2_customer_reality": {{
    "top_pain": "câu",
    "top_desire": "câu",
    "most_urgent_problem": "câu",
    "pains_ranked": [{{"pain": "...", "severity": 1-10}}]
  }},
  "section_3_market_demand": [
    {{"keyword": "...", "search_intent": "informational|transactional|commercial",
      "trend_score": 1-10, "opportunity_score": 1-10, "data_source": "ai_inferred"}}
  ],
  "section_4_opportunity_ideas": {{
    "product": [{{"name": "...", "solves_pain": "...", "fit_founder": "...", "market_need": "..."}}],
    "service": [...],
    "coaching": [...],
    "membership": [...],
    "ai_powered": [...]
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


_CSS = """
:root{--red:#d63031;--ink:#0a0a0a;--paper:#fafaf7;--line:#e5dfd0;--muted:#5a5453;--ok:#27ae60}
*{box-sizing:border-box;margin:0;padding:0;font-family:'Be Vietnam Pro',system-ui}
body{background:var(--paper);color:var(--ink);padding:30px 20px;font-size:16px;line-height:1.7}
.container{max-width:780px;margin:0 auto}
.tag{display:inline-block;background:rgba(214,48,49,0.12);color:var(--red);padding:8px 18px;border-radius:999px;font-size:12px;letter-spacing:1.5px;text-transform:uppercase;font-weight:800;margin-bottom:14px}
h1{font-size:36px;font-weight:800;line-height:1.2;margin-bottom:12px}
.sub{font-size:18px;color:var(--muted);margin-bottom:30px}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:24px 26px;margin-bottom:18px}
.card h3{font-size:18px;margin-bottom:6px}
.card .hint{font-size:14px;color:var(--muted);margin-bottom:14px}
label{display:block;font-weight:700;margin-bottom:8px;font-size:14px}
input[type=text],input[type=email],textarea{width:100%;border:1.5px solid var(--line);border-radius:10px;padding:14px;font-size:16px;font-family:inherit;line-height:1.5}
textarea{min-height:100px;resize:vertical}
input:focus,textarea:focus{outline:none;border-color:var(--red)}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
button[type=submit]{display:block;width:100%;padding:22px;background:var(--red);color:#fff;border:none;border-radius:14px;font-size:20px;font-weight:800;cursor:pointer;margin-top:18px;box-shadow:0 8px 28px rgba(214,48,49,0.35)}
button[type=submit]:hover{background:#b71c1c}
button[type=submit]:disabled{opacity:0.5;cursor:wait}
.loader{display:none;text-align:center;padding:40px;background:#fff;border-radius:14px;margin-top:18px}
.loader.show{display:block}
.loader .spinner{width:50px;height:50px;border:5px solid var(--line);border-top-color:var(--red);border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 16px}
@keyframes spin{to{transform:rotate(360deg)}}
"""


@router.get("/day3", response_class=HTMLResponse)
@router.get("/day3/", response_class=HTMLResponse)
async def day3_form(cohort: str = "K2-2026-06") -> HTMLResponse:
    """Day 3 Challenge standalone form."""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Day 3 Challenge · Khám phá cơ hội kinh doanh của bạn</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{_CSS}</style></head>
<body><div class="container">

<div class="tag">Day 3 Challenge · Breakout K2</div>
<h1>Khám phá cơ hội kinh doanh của bạn</h1>
<p class="sub">Nhập kết quả Day 1 + Day 2 bạn đã làm. AI sẽ phân tích và trả về Business Discovery Report 9 phần: founder summary, customer reality, market demand, opportunity ideas, validation matrix, recommended offer, one-page offer sheet, content engine, 30-day action plan.</p>

<form id="day3-form" method="post" action="/day3/submit">
  <input type="hidden" name="cohort" value="{cohort}">

  <div class="card">
    <div class="row">
      <div>
        <label>Tên bạn (optional)</label>
        <input type="text" name="full_name" placeholder="Đào Thị Hằng">
      </div>
      <div>
        <label>Email (để nhận Report qua mail)</label>
        <input type="email" name="email" placeholder="ban@example.com">
      </div>
    </div>
  </div>

  <div class="card">
    <h3>1. Tôi là ai (Day 1)</h3>
    <p class="hint">Background + kinh nghiệm + bạn là người như thế nào.</p>
    <textarea name="who_am_i" required placeholder="VD: Tôi là người có 15 năm kinh nghiệm trong giáo dục và đào tạo. Mạnh nhất ở xây hệ thống học chủ động cho người lớn."></textarea>
  </div>

  <div class="card">
    <h3>2. Năng lực cốt lõi (Day 1)</h3>
    <p class="hint">Bạn giỏi nhất việc gì. 3-5 năng lực nổi bật.</p>
    <textarea name="core_skills" required placeholder="VD: Coaching, đào tạo, xây cộng đồng, tiếng Anh, design quy trình học chủ động."></textarea>
  </div>

  <div class="card">
    <h3>3. Tôi muốn phục vụ ai (Day 2)</h3>
    <p class="hint">Tệp khách cụ thể: tuổi, giới, nghề, hoàn cảnh.</p>
    <textarea name="target_customer" required placeholder="VD: Phụ nữ văn phòng 25-45 tuổi, đang đi làm full-time, muốn có thêm thu nhập thứ hai từ kỹ năng/đam mê của mình."></textarea>
  </div>

  <div class="card">
    <h3>4. Nỗi đau lớn nhất của khách (Day 2)</h3>
    <p class="hint">Điều khách thật sự đang khổ sở.</p>
    <textarea name="customer_pain" required placeholder="VD: Thiếu kỹ năng kinh doanh, thiếu tự tin chia sẻ giá trị mình có, không biết bắt đầu từ đâu, sợ thất bại trước mặt gia đình."></textarea>
  </div>

  <div class="card">
    <h3>5. Khát khao của khách (Day 2)</h3>
    <p class="hint">Điều khách muốn đạt được.</p>
    <textarea name="customer_desire" required placeholder="VD: Có nguồn thu nhập thứ hai ổn định, tự do thời gian, làm gương cho con, không phụ thuộc 1 công việc."></textarea>
  </div>

  <button type="submit" id="submit-btn">🚀 Khám phá cơ hội kinh doanh</button>
</form>

<div class="loader" id="loader">
  <div class="spinner"></div>
  <h3>AI đang phân tích...</h3>
  <p style="color:#5a5453;margin-top:8px">Đang tổng hợp founder profile + customer reality + market demand + sinh 9 phần report. 30-60 giây.</p>
</div>

</div>

<script>
document.getElementById('day3-form').addEventListener('submit', (e) => {{
  document.getElementById('submit-btn').disabled = true;
  document.getElementById('submit-btn').textContent = 'Đang gửi...';
  document.getElementById('loader').classList.add('show');
}});
</script>
</body></html>""")


async def _generate_day3_report(
    session_id: UUID, inputs: dict[str, str], pool: asyncpg.Pool,
) -> None:
    """Background: call Claude → save report_json."""
    started = time.time()
    prompt = DAY3_PROMPT.format(**inputs)
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
    except (anthropic.APIStatusError, anthropic.APIError, json.JSONDecodeError) as exc:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE breakoutos.day3_sessions
                SET status='failed', error_payload=$1::jsonb, ai_model=$2,
                    generation_seconds=$3, completed_at=now()
                WHERE id=$4
                """,
                json.dumps({"error": type(exc).__name__, "message": str(exc)[:500]}),
                model, time.time() - started, session_id,
            )
        log.exception("day3 generation failed")
        return

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE breakoutos.day3_sessions
            SET status='completed', report_json=$1::jsonb, ai_model=$2,
                generation_seconds=$3, completed_at=now()
            WHERE id=$4
            """,
            json.dumps(parsed, ensure_ascii=False), model,
            time.time() - started, session_id,
        )

    # Telegram alert
    try:
        from routes.telegram_alert import send_telegram_sync
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT email, full_name, cohort FROM breakoutos.day3_sessions WHERE id=$1",
                session_id,
            )
        top = parsed.get("section_6_recommended_offer", {}).get("top_pick_name", "?")
        send_telegram_sync(
            f"🚀 <b>DAY 3 CHALLENGE submitted</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Tên:</b> {row['full_name'] or '(no name)'}\n"
            f"<b>Email:</b> {row['email'] or '(no email)'}\n"
            f"<b>Cohort:</b> {row['cohort']}\n"
            f"<b>TOP 1 offer:</b> {top}\n"
            f"<b>Report:</b> https://os.breakout.live/day3/report/{session_id}"
        )
    except Exception:
        log.exception("day3 telegram alert fail (non-fatal)")


@router.post("/day3/submit")
async def day3_submit(
    request: Request,
    background: BackgroundTasks,
    pool: asyncpg.Pool = Depends(get_pool),
    who_am_i: str = Form(...),
    core_skills: str = Form(...),
    target_customer: str = Form(...),
    customer_pain: str = Form(...),
    customer_desire: str = Form(...),
    cohort: str = Form("K2-2026-06"),
    email: str = Form(""),
    full_name: str = Form(""),
):
    """Save inputs + trigger background discovery."""
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")[:500]
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO breakoutos.day3_sessions
              (email, full_name, cohort, who_am_i, core_skills, target_customer,
               customer_pain, customer_desire, ip, user_agent, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'pending')
            RETURNING id
            """,
            email or None, full_name or None, cohort,
            who_am_i, core_skills, target_customer, customer_pain, customer_desire,
            ip, ua,
        )
    session_id = row["id"]
    background.add_task(
        _generate_day3_report, session_id,
        {"who_am_i": who_am_i, "core_skills": core_skills,
         "target_customer": target_customer, "customer_pain": customer_pain,
         "customer_desire": customer_desire},
        pool,
    )
    return RedirectResponse(f"/day3/report/{session_id}?wait=1", status_code=303)
