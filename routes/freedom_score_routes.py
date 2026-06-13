"""Founder Freedom Score V3.6 (Chỉ Số Tự Do Founder).

Per Anna BREAKOUTOS V3.6 (2026-06-12 đêm):
- 10 questions × 0-10 = total 100 (KHÔNG weighted 18/13/10)
- 5 classifications (tim_loi_di / thu_nghiem / dang_van_hanh / co_he_thong / tu_do)
- AI-generated Founder Freedom Report sau submit (7 sections)
- Layer integration: mapping mỗi layer tăng score câu nào

10 questions canonical:
Q1 Income      - Thu nhập vs mục tiêu cá nhân
Q2 Profit      - Lợi nhuận sau chi phí
Q3 Time Free   - Thời gian tự do mỗi tuần
Q4 Peace       - Bình an nội tâm
Q5 Clarity     - Sự rõ ràng đang xây dựng
Q6 Customer    - Biết rõ phục vụ ai
Q7 System AI   - % công việc automated
Q8 Independence- Vắng N ngày biz còn chạy (0/3/5/7/10 = 1/3/7/30/90 ngày)
Q9 Growth      - Doanh nghiệp tăng trưởng ổn định
Q10 Meaning    - Đúng giá trị + sứ mệnh
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from routes._auth import request_signature, require_student_signature, sign_student
from routes.sdl_routes import get_pool


log = logging.getLogger("camas.freedom_score")
router = APIRouter(tags=["freedom-score"])


# ============================================================
# Schemas V3.6
# ============================================================
class FreedomScoreV2Create(BaseModel):
    source: str = Field(..., examples=["self_baseline", "self_weekly", "ai_compute"])
    q1_income:       int = Field(..., ge=0, le=10)
    q2_profit:       int = Field(..., ge=0, le=10)
    q3_time_free:    int = Field(..., ge=0, le=10)
    q4_peace:        int = Field(..., ge=0, le=10)
    q5_clarity:      int = Field(..., ge=0, le=10)
    q6_customer:     int = Field(..., ge=0, le=10)
    q7_system_ai:    int = Field(..., ge=0, le=10)
    q8_independence: int = Field(..., ge=0, le=10)
    q9_growth:       int = Field(..., ge=0, le=10)
    q10_meaning:     int = Field(..., ge=0, le=10)
    notes_json: dict[str, Any] = Field(default_factory=dict)


CLASSIFICATION_LABELS = {
    "tim_loi_di":     "NGƯỜI ĐANG TÌM LỐI ĐI",
    "thu_nghiem":     "NGƯỜI ĐANG THỬ NGHIỆM",
    "dang_van_hanh":  "FOUNDER ĐANG VẬN HÀNH",
    "co_he_thong":    "FOUNDER CÓ HỆ THỐNG",
    "tu_do":          "FOUNDER TỰ DO",
}
CLASSIFICATION_BLURB = {
    "tim_loi_di":     "Bạn chưa có nền tảng rõ ràng. Bắt đầu Tầng 1 Hiểu Mình.",
    "thu_nghiem":     "Bạn đang khám phá mô hình phù hợp. Tập trung Tầng 2 Hiểu Khách.",
    "dang_van_hanh":  "Đã có nền tảng nhưng còn phụ thuộc nhiều vào bản thân. Build Tầng 4 Hệ Thống.",
    "co_he_thong":    "Doanh nghiệp bắt đầu hoạt động ổn định. Tối ưu Tầng 5 Tăng Trưởng.",
    "tu_do":          "Doanh nghiệp phục vụ bạn thay vì bạn phục vụ doanh nghiệp. Tự Do Sáng Lập.",
}

QUESTION_LABELS = {
    # V3.6.3 reorder cảm xúc + tách Hệ thống/AI (Anna 2026-06-12 đêm muộn).
    # Column names KHÔNG đổi (giữ schema), chỉ đổi semantic:
    #   q7_system_ai  → Hệ thống ONLY
    #   q9_growth     → AI (repurposed, drop "growth")
    "q1_income":       "Thu nhập",
    "q2_profit":       "Dòng tiền",
    "q3_time_free":    "Thời gian tự do",
    "q4_peace":        "Bình an",
    "q5_clarity":      "Sự rõ ràng",
    "q6_customer":     "Khách hàng",
    "q7_system_ai":    "Hệ thống",
    "q8_independence": "Độc lập doanh nghiệp",
    "q9_growth":       "AI",
    "q10_meaning":     "Ý nghĩa",
}

LAYER_IMPACT = {
    "L1 Hiểu Mình":         ["q10_meaning", "q5_clarity", "q4_peace"],
    "L2 Hiểu Khách":        ["q6_customer", "q5_clarity"],
    "L3 Đóng Gói Offer":    ["q6_customer", "q1_income", "q2_profit"],
    "L4 Hệ Thống Vận Hành": ["q7_system_ai", "q9_growth"],  # q9_growth = AI
    "L5 Tăng Trưởng":       ["q1_income", "q2_profit"],
    "L6 Tự Do Sáng Lập":    ["q8_independence", "q3_time_free", "q4_peace"],
}


# ============================================================
# AI Report generator
# ============================================================
async def _generate_freedom_report(pool: asyncpg.Pool, score_id, student_id: UUID,
                                   scores: dict, total: int, classification: str) -> None:
    """Generate Founder Freedom Report (7 sections) via Claude Haiku."""
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    scores_text = "\n".join(
        f"- {QUESTION_LABELS[k]}: {scores[k]}/10"
        for k in ["q1_income","q2_profit","q3_time_free","q4_peace","q5_clarity",
                  "q6_customer","q7_system_ai","q8_independence","q9_growth","q10_meaning"]
    )

    prompt = f"""Bạn là Coach BreakoutOS phân tích Chỉ Số Tự Do Founder của 1 người sáng lập solo.

INPUT điểm tự đánh giá (0-10 mỗi câu, T0):
{scores_text}

TỔNG ĐIỂM (weighted formula): {total}/100
PHÂN LOẠI: {CLASSIFICATION_LABELS[classification]}

══════════════════════════════════════════════════════
QUY TẮC NỘI DUNG BẮT BUỘC (Anna 2026-06-13)
══════════════════════════════════════════════════════

1. NGÔN NGỮ VIỆT HOÁ — BẮT BUỘC thay các từ này:
   • "founder"     → "người sáng lập"  (giữ "Founder" CHỈ trong tên thương hiệu "Founder Freedom Score")
   • "build"       → "xây dựng"
   • "refactor"    → "sắp xếp lại"
   • "fix"         → "cải thiện"
   • "team"        → "người hỗ trợ"
   • "scale"       → "mở rộng mà không tăng tải"
   • "bandwidth"   → "thời gian và năng lực"
   • "customer journey" → "hành trình phục vụ khách hàng"
   • KHÔNG dùng "—" (dấu em-dash). Thay bằng "," hoặc xuống dòng.
   • KHÔNG dùng từ "dạy". Thay bằng "hướng dẫn" hoặc "chỉ".

2. ĐỊNH HƯỚNG DOANH NGHIỆP MỘT NGƯỜI — KHÔNG được dùng các cụm sau:
   ✗ "giao cho nhân viên"
   ✗ "onboarding cho team"
   ✗ "delegation"
   ✗ "nhân hoá" / "scale lên 10 người"
   ✗ "không thể scale"
   ✗ "founder phải làm chiến lược, bán hàng"

   THỨ TỰ ƯU TIÊN khi đề xuất giải pháp (theo đúng thứ tự này):
   1) LOẠI BỎ việc không cần thiết
   2) ĐƠN GIẢN HOÁ quy trình
   3) CHUẨN HOÁ việc lặp lại (viết SOP)
   4) GIAO CHO AI làm
   5) TỰ ĐỘNG HOÁ
   6) Chỉ thuê người hỗ trợ khi thật sự cần (cuối cùng)

3. NGÔN NGỮ THẬN TRỌNG — KHÔNG nói chắc hơn dữ liệu cho phép:
   ✗ "Điểm 8/10 chứng tỏ X" / "Điểm 7/10 cho thấy đã có Y"
   ✓ "Câu trả lời của bạn cho thấy..."
   ✓ "Có dấu hiệu..."
   ✓ "Cần kiểm chứng thêm bằng dữ liệu thực tế..."
   Đây là T0 TỰ ĐÁNH GIÁ, chưa kiểm chứng. Mọi kết luận phải mở.

4. KHÔNG CAM KẾT ĐIỂM TĂNG CỤ THỂ:
   ✗ "+2 điểm Độc lập"
   ✗ "có thể nhảy lên 70-75"
   ✗ "expected_score_lift: +N điểm câu X"
   ✓ "Tác động dự kiến: cải thiện mức độc lập, thời gian tự do và sự bình an."
   ✓ "Kết quả thực tế sẽ được xác nhận khi đo lại."

5. KHÔNG ĐỀ XUẤT NHẢY TẦNG:
   • next_layer_recommended.layer LUÔN viết NGUYÊN VĂN: "L1 Hiểu Mình"
   • next_layer_recommended.reason: chỉ trả 1 câu giới thiệu duy nhất:
     "Bạn vẫn bắt đầu từ Tầng 1 để xác định điều mình muốn xây."
     ĐỪNG nhắc tới điểm nghẽn ở đây (Python sẽ tự nối câu thứ 2 dựa trên bottleneck).

6. CÂU KHÁCH HÀNG (q6_customer) = chẩn đoán, KHÔNG tính vào FFS. Có thể nhắc trong phân tích nhưng đừng làm trọng tâm.

══════════════════════════════════════════════════════
OUTPUT JSON SCHEMA (strict, chỉ trả JSON, không markdown wrapper)
══════════════════════════════════════════════════════
{{
  "summary": "1-2 câu mô tả tín hiệu chính từ bài tự đánh giá, ≤40 từ, dùng giọng thận trọng",
  "top_3_strengths": [
    {{"question": "<tên câu>", "explanation": "Câu trả lời của bạn cho thấy... (~30 từ, thận trọng)"}}
  ],
  "top_3_weaknesses": [
    {{"question": "<tên câu>", "explanation": "Có dấu hiệu... (~30 từ, thận trọng)"}}
  ],
  "biggest_bottleneck": {{
    "question": "<tên câu yếu nhất>",
    "why": "~60 từ giải thích đây là tín hiệu cần ưu tiên kiểm chứng, KHÔNG tuyên bố cứng",
    "impact": "Tác động dự kiến (định tính, không số): cải thiện điểm nghẽn này có thể nâng các phần liên quan như ..."
  }},
  "action_priority_90_days": [
    {{"week": "1-2",  "action": "Hành động cụ thể theo thứ tự ưu tiên LOẠI BỎ→ĐƠN GIẢN→CHUẨN HOÁ→AI→TỰ ĐỘNG HOÁ"}},
    {{"week": "3-4",  "action": "..."}},
    {{"week": "5-8",  "action": "..."}},
    {{"week": "9-12", "action": "..."}}
  ],
  "next_layer_recommended": {{
    "layer": "L1 Hiểu Mình",
    "reason": "Bạn vẫn bắt đầu từ Tầng 1. Khi đến Tầng X (tầng của điểm nghẽn), BreakoutOS sẽ tập trung sâu vào điểm nghẽn này."
  }},
  "encouragement": "~50 từ động viên dựa trên điểm mạnh, giọng ấm, không phán xét"
}}"""

    try:
        resp = await client.messages.create(
            model="claude-haiku-4-5", max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw
            if raw.endswith("```"): raw = raw.rsplit("```", 1)[0]
            raw = raw.strip()
        if raw.startswith("json"): raw = raw[4:].strip()
        report = json.loads(raw)

        # Post-process: enforce L1 + deterministic "khi đến Tầng X" sentence based on bottleneck Q.
        _BOTTLENECK_DEEP_LAYER = {
            "Ý nghĩa": "Tầng 1 (Hiểu Mình)",
            "Bình an": "Tầng 1 (Hiểu Mình)",
            "Sự rõ ràng": "Tầng 1 (Hiểu Mình)",
            "Khách hàng": "Tầng 2 (Hiểu Khách)",
            "Thu nhập": "Tầng 3 (Đóng Gói Offer)",
            "Dòng tiền": "Tầng 3 (Đóng Gói Offer)",
            "Hệ thống": "Tầng 4 (Hệ Thống Vận Hành)",
            "AI": "Tầng 4 (Hệ Thống Vận Hành)",
            "AI & Tự động hóa": "Tầng 4 (Hệ Thống Vận Hành)",
            "Độc lập doanh nghiệp": "Tầng 6 (Tự Do Sáng Lập)",
            "Thời gian tự do": "Tầng 6 (Tự Do Sáng Lập)",
        }
        bb_q = (report.get("biggest_bottleneck") or {}).get("question", "") or ""
        # AI có thể trả "Độc lập doanh nghiệp (1/10)" → strip phần ngoặc
        bb_key = bb_q.split("(")[0].strip()
        deep_layer = _BOTTLENECK_DEEP_LAYER.get(bb_key, "tầng tương ứng")
        report["next_layer_recommended"] = {
            "layer": "L1 Hiểu Mình",
            "reason": (
                "Bạn vẫn bắt đầu từ Tầng 1 để xác định điều mình muốn xây. "
                f"Khi đến {deep_layer}, BreakoutOS sẽ tập trung sâu vào điểm nghẽn này."
            ),
        }
    except Exception as exc:
        log.exception("Freedom Score Report gen fail: %s", exc)
        report = {"error": str(exc)[:300]}

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE breakoutos.founder_freedom_score SET report_json = $1::jsonb WHERE id = $2",
            json.dumps(report, ensure_ascii=False), score_id,
        )


# ============================================================
# POST V3.6 measurement
# ============================================================
@router.post("/sdl/students/{student_id}/freedom-score", status_code=201)
async def append_freedom_score(
    student_id: UUID, body: FreedomScoreV2Create,
    background: BackgroundTasks,
    request: Request,
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """V3.6: 10 questions × 0-10 = 100. Generate Founder Freedom Report background."""
    sig = request_signature(request)
    if body.source == "self_baseline":
        require_student_signature(str(student_id), sig)

    async with pool.acquire() as conn:
        student = await conn.fetchrow(
            "SELECT id, email, full_name FROM breakoutos.students WHERE id=$1", student_id,
        )
        if not student:
            raise HTTPException(404, "Student not found")

        row = await conn.fetchrow(
            """
            INSERT INTO breakoutos.founder_freedom_score
              (student_id, source,
               q1_income, q2_profit, q3_time_free, q4_peace, q5_clarity,
               q6_customer, q7_system_ai, q8_independence, q9_growth, q10_meaning,
               notes_json)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb)
            RETURNING id, measured_at, total_v2, classification_v2
            """,
            student_id, body.source,
            body.q1_income, body.q2_profit, body.q3_time_free, body.q4_peace, body.q5_clarity,
            body.q6_customer, body.q7_system_ai, body.q8_independence, body.q9_growth, body.q10_meaning,
            json.dumps(body.notes_json),
        )

    # Trigger AI report generation background
    scores = body.dict()
    background.add_task(
        _generate_freedom_report, pool, row["id"], student_id,
        scores, row["total_v2"], row["classification_v2"],
    )

    # Telegram alert
    if body.source == "self_baseline":
        try:
            from routes.telegram_alert import alert_baseline_filled
            alert_baseline_filled(
                str(student_id), student["email"] or "", student["full_name"] or "",
                row["total_v2"],
            )
        except Exception:
            pass

    return {
        "id": row["id"],
        "measured_at": row["measured_at"].isoformat(),
        "total_score": row["total_v2"],
        "classification": row["classification_v2"],
        "classification_label": CLASSIFICATION_LABELS.get(row["classification_v2"], ""),
        "classification_blurb": CLASSIFICATION_BLURB.get(row["classification_v2"], ""),
        "report_status": "generating_background",
        "report_url": (
            f"/sdl/students/{student_id}/freedom-score/{row['id']}/report"
            f"?sig={sig}"
        ),
        "source": body.source,
    }


# ============================================================
# GET latest + report
# ============================================================
@router.get("/sdl/students/{student_id}/freedom-score/latest")
async def get_freedom_score_latest(
    student_id: UUID, pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM breakoutos.v_freedom_score_latest WHERE student_id=$1",
            student_id,
        )
        if not row:
            raise HTTPException(404, "No score yet")
        d = dict(row)
        if d.get("classification_v2"):
            d["classification_label"] = CLASSIFICATION_LABELS.get(d["classification_v2"], "")
            d["classification_blurb"] = CLASSIFICATION_BLURB.get(d["classification_v2"], "")
        return d


@router.get("/sdl/students/{student_id}/freedom-score/{score_id}/report-html", response_class=HTMLResponse)
async def get_freedom_report_html(
    student_id: UUID,
    score_id: UUID,
    request: Request,
    sig: str = "",
    pool: asyncpg.Pool = Depends(get_pool),
) -> HTMLResponse:
    """Render báo cáo Founder Freedom Score thành trang HTML dành cho học viên xem lại + share."""
    request_sig = request_signature(request, sig)
    require_student_signature(str(student_id), request_sig)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, total_v2, classification_v2, report_json, measured_at, source "
            "FROM breakoutos.founder_freedom_score WHERE id=$1 AND student_id=$2",
            score_id, student_id,
        )
        student = await conn.fetchrow(
            "SELECT email, full_name FROM breakoutos.students WHERE id=$1", student_id,
        )
    if not row:
        raise HTTPException(404, "Score not found")
    report_raw = row["report_json"]
    if isinstance(report_raw, str):
        report = json.loads(report_raw)
    else:
        report = report_raw or {}

    if "error" in report:
        return HTMLResponse(
            f"<h1>Báo cáo chưa sẵn sàng</h1><p>AI đang sinh báo cáo, vui lòng refresh sau 30 giây.</p>"
        )

    classification = row["classification_v2"]
    label = CLASSIFICATION_LABELS.get(classification, "")
    blurb = CLASSIFICATION_BLURB.get(classification, "")
    student_name = student["full_name"] if student else "(no name)"

    def _li_list(items, prefix="✓ "):
        return "".join(
            f'<li><strong>{i.get("question","")}</strong>: {i.get("explanation","")}</li>'
            for i in (items or [])
        )

    def _action_li(a):
        lift = a.get("expected_score_lift", "")
        lift_html = f' <span class="lift">({lift})</span>' if lift else ''
        return f'<li><strong>Tuần {a.get("week","?")}:</strong> {a.get("action","")}{lift_html}</li>'
    actions = "".join(_action_li(a) for a in (report.get("action_priority_90_days") or []))
    bb = report.get("biggest_bottleneck") or {}
    nl = report.get("next_layer_recommended") or {}

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Báo cáo Chỉ Số Tự Do Founder · {student_name}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0;-webkit-font-smoothing:antialiased}}
body{{font-family:'Be Vietnam Pro',system-ui;background:#fafaf7;color:#0a0a0a;line-height:1.7;padding:30px 20px 80px}}
.container{{max-width:760px;margin:0 auto}}
.hero{{background:linear-gradient(135deg,#0a0a0a,#2d2d2d);color:#fff;border-radius:20px;padding:40px 32px;margin-bottom:24px;text-align:center}}
.hero .tag{{display:inline-block;background:rgba(212,162,74,0.2);color:#d4a24a;padding:8px 18px;border-radius:999px;font-size:12px;letter-spacing:1.5px;font-weight:800;text-transform:uppercase;margin-bottom:18px}}
.hero h1{{font-size:24px;color:#fff;margin-bottom:8px}}
.hero .name{{font-size:14px;color:rgba(255,255,255,0.7);margin-bottom:18px}}
.score-big{{font-size:96px;font-weight:800;color:#d4a24a;line-height:1;margin:8px 0}}
.score-total{{opacity:0.85;font-size:16px;margin-bottom:14px}}
.level-badge{{display:inline-block;background:#d63031;color:#fff;padding:10px 20px;border-radius:999px;font-weight:800;letter-spacing:1px;font-size:13px;text-transform:uppercase}}
.level-blurb{{font-size:16px;opacity:0.9;margin-top:14px;max-width:520px;margin-left:auto;margin-right:auto}}
.section{{background:#fff;border:1px solid #e5dfd0;border-radius:14px;padding:24px 26px;margin-bottom:14px}}
.section h2{{font-size:14px;color:#d63031;text-transform:uppercase;letter-spacing:1.5px;font-weight:800;margin-bottom:14px}}
.section p{{font-size:16px;color:#2a2a2a}}
.section ul{{list-style:none;padding:0}}
.section li{{padding:8px 0;font-size:15px;color:#2a2a2a;line-height:1.6;border-bottom:1px solid #f0eee5}}
.section li:last-child{{border-bottom:none}}
.section li strong{{color:#0a0a0a;display:inline-block;min-width:120px}}
.bottleneck{{background:#fff5f3;border-left:5px solid #d63031;border-radius:0 14px 14px 0}}
.bottleneck h3{{font-size:18px;color:#d63031;margin-bottom:10px}}
.bottleneck p{{margin-bottom:8px}}
.bottleneck .impact{{background:#fff;border-radius:10px;padding:14px 16px;margin-top:12px;font-size:14px;color:#5a5453}}
.next-layer{{background:linear-gradient(135deg,#fff5f3,#fff);border:2px solid #d63031;border-radius:14px;padding:24px 26px;text-align:center}}
.next-layer .layer-name{{font-size:22px;font-weight:800;color:#d63031;margin-bottom:8px}}
.encouragement{{background:#fffbeb;border-left:5px solid #d4a24a;border-radius:0 14px 14px 0;font-style:italic;color:#5a4a14}}
.lift{{color:#0a8700;font-weight:700;font-size:13px}}
.actions{{display:flex;gap:12px;margin-top:24px;flex-wrap:wrap}}
.actions a{{flex:1;min-width:200px;padding:18px;background:#d63031;color:#fff;border-radius:12px;text-decoration:none;font-weight:700;text-align:center}}
.actions a.outline{{background:transparent;border:2px solid #d63031;color:#d63031}}
.meta{{text-align:center;font-size:13px;color:#888;margin-top:30px}}
@media(max-width:600px){{
  .hero{{padding:30px 22px}}
  .score-big{{font-size:64px}}
  .actions{{flex-direction:column}}
}}
</style></head><body>
<div class="container">
  <div class="hero">
    <div class="tag">Founder Freedom Score™</div>
    <h1>Báo cáo Chỉ Số Tự Do Founder</h1>
    <div class="name">{student_name}</div>
    <div class="score-big">{row['total_v2']}</div>
    <div class="score-total">/ 100 điểm</div>
    <div><span class="level-badge">{label}</span></div>
    <p class="level-blurb">{blurb}</p>
  </div>

  <div class="section">
    <h2>Tóm tắt</h2>
    <p>{report.get('summary','')}</p>
  </div>

  <div class="section">
    <h2>3 điểm mạnh nhất</h2>
    <ul>{_li_list(report.get('top_3_strengths'))}</ul>
  </div>

  <div class="section">
    <h2>3 điểm yếu nhất</h2>
    <ul>{_li_list(report.get('top_3_weaknesses'))}</ul>
  </div>

  <div class="section bottleneck">
    <h2>Điểm nghẽn lớn nhất</h2>
    <h3>{bb.get('question','')}</h3>
    <p><strong>Vì sao quan trọng nhất:</strong> {bb.get('why','')}</p>
    <div class="impact"><strong>Hiệu ứng dây chuyền nếu fix:</strong> {bb.get('impact','')}</div>
  </div>

  <div class="section">
    <h2>Ưu tiên hành động 90 ngày</h2>
    <ul>{actions}</ul>
  </div>

  <div class="section next-layer">
    <h2>Tầng tiếp theo nên học</h2>
    <div class="layer-name">{nl.get('layer','')}</div>
    <p>{nl.get('reason','')}</p>
  </div>

  <div class="section encouragement">
    <h2>Lời động viên</h2>
    <p>{report.get('encouragement','')}</p>
  </div>

  <div class="actions">
    <a href="/foundation/l1?student={student_id}&sig={request_sig}">Bắt đầu Tầng 1 Hiểu Mình →</a>
    <a href="/sdl/student/{student_id}/dashboard" class="outline">Vào Dashboard</a>
  </div>

  <div class="meta">
    Báo cáo được tạo từ bài tự đánh giá ngày {(row['measured_at'].strftime('%d/%m/%Y') if row['measured_at'] else '')}.<br>
    Kết quả mang tính định hướng và sẽ được kiểm chứng trong quá trình học.
  </div>
</div>
</body></html>""")


@router.get("/sdl/students/{student_id}/freedom-score/{score_id}/report")
async def get_freedom_report(
    student_id: UUID,
    score_id: UUID,
    request: Request,
    sig: str = "",
    pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    """Fetch Founder Freedom Report (may be null if AI still generating)."""
    require_student_signature(str(student_id), request_signature(request, sig))
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, total_v2, classification_v2, report_json, measured_at, source "
            "FROM breakoutos.founder_freedom_score WHERE id=$1 AND student_id=$2",
            score_id, student_id,
        )
    if not row:
        raise HTTPException(404, "Score not found")
    return {
        "id": row["id"],
        "total_score": row["total_v2"],
        "classification": row["classification_v2"],
        "classification_label": CLASSIFICATION_LABELS.get(row["classification_v2"], ""),
        "classification_blurb": CLASSIFICATION_BLURB.get(row["classification_v2"], ""),
        "measured_at": row["measured_at"].isoformat() if row["measured_at"] else None,
        "source": row["source"],
        "report": row["report_json"],
        "report_ready": row["report_json"] is not None and "error" not in (row["report_json"] or {}),
    }


@router.get("/sdl/students/{student_id}/freedom-score/baseline")
async def get_freedom_score_baseline(
    student_id: UUID, pool: asyncpg.Pool = Depends(get_pool),
) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM breakoutos.v_freedom_score_baseline WHERE student_id=$1",
            student_id,
        )
        if not row:
            signature = sign_student(str(student_id))
            raise HTTPException(412, {
                "error": "T0 baseline missing",
                "action": "fill_baseline",
                "redirect": (
                    f"/foundation/baseline?student={student_id}&sig={signature}"
                ),
            })
        return {
            "student_id": str(student_id),
            "baseline_at": row["baseline_at"].isoformat(),
            "baseline_score": row["baseline_score"],
            "baseline_classification": row.get("baseline_classification"),
        }


@router.get("/sdl/students/{student_id}/freedom-score/history")
async def get_freedom_score_history(
    student_id: UUID, limit: int = 20,
    pool: asyncpg.Pool = Depends(get_pool),
) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT measured_at, source, total_v2, classification_v2,
                   q1_income, q2_profit, q3_time_free, q4_peace, q5_clarity,
                   q6_customer, q7_system_ai, q8_independence, q9_growth, q10_meaning
            FROM breakoutos.founder_freedom_score
            WHERE student_id=$1 AND schema_version='v2'
            ORDER BY measured_at DESC LIMIT $2
            """,
            student_id, limit,
        )
        return [dict(r) for r in rows]


# ============================================================
# Helper for L1 gate check
# ============================================================
async def has_baseline(pool: asyncpg.Pool, student_id: UUID) -> bool:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM breakoutos.founder_freedom_score "
            "WHERE student_id=$1 AND source='self_baseline')",
            student_id,
        )


# ============================================================
# HTML form V3.6 — 10 questions, 0-10 scale, radar chart preview
# ============================================================
@router.get("/foundation/baseline", response_class=HTMLResponse)
async def baseline_form(
    student: str | None = None,
    sig: str = "",
    retake: int = 0,
    pool: asyncpg.Pool = Depends(get_pool),
):
    """V3.6.5: nếu student đã có baseline → auto-redirect tới view kết quả.
    retake=1 để vẫn show form (cho phép làm lại)."""
    student_id = student or ""
    try:
        require_student_signature(student_id, sig)
        UUID(student_id)
    except (HTTPException, ValueError):
        return HTMLResponse(
            "<h1>Không thể mở trang</h1>"
            "<p>Đường link không hợp lệ. Liên hệ Hằng qua Zalo.</p>",
            status_code=403,
        )

    if student_id and not retake:
        try:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT id FROM breakoutos.founder_freedom_score "
                    "WHERE student_id = $1::uuid AND source = 'self_baseline' "
                    "ORDER BY measured_at DESC LIMIT 1",
                    student_id,
                )
                if row:
                    return RedirectResponse(
                        url=(
                            f"/sdl/students/{student_id}/freedom-score/"
                            f"{row['id']}/report-html?sig={sig}"
                        ),
                        status_code=302,
                    )
        except Exception as exc:
            log.warning("baseline_form auto-detect skipped: %s", exc)
    return HTMLResponse(_render_baseline_form_v36(student_id, sig))


def _render_baseline_form_v36(student_id: str, sig: str) -> str:
    # V3.6.3 reorder cảm xúc + tách Hệ thống/AI (Anna 2026-06-12 đêm muộn).
    # Hành trình: Tôi là ai → Tôi sống thế nào → Tôi kiếm tiền thế nào → Tôi có hệ thống không → Tôi có tự do không.
    # DB column name KHÔNG đổi (q1_income, q2_profit, ...) để giữ schema; chỉ đổi semantic + display order.
    #   q7_system_ai  → Hệ thống ONLY (drop "& AI")
    #   q9_growth     → repurposed thành AI (drop "growth")
    questions = [
        # 1. Ý nghĩa
        {
            "name": "q10_meaning", "label": "Ý nghĩa",
            "hint": "Công việc này có thực sự phản ánh con người bạn, hay chỉ là cái nghề bạn đang làm?",
            "left": "Mất kết nối", "right": "Hoàn toàn đồng nhất sứ mệnh",
            "anchors": {0: "Hoàn toàn mất kết nối", 3: "Làm vì tiền, ít ý nghĩa",
                        5: "Một phần phù hợp giá trị", 8: "Phần lớn việc làm có ý nghĩa",
                        10: "Hoàn toàn đồng nhất với sứ mệnh"},
        },
        # 2. Bình an (frame 14 ngày)
        {
            "name": "q4_peace", "label": "Bình an",
            "hint": "Trong 14 ngày gần nhất, mỗi sáng thức dậy bạn hào hứng hay lo lắng về công việc?",
            "left": "Căng thẳng liên tục", "right": "Bình an, kiểm soát tốt",
            "anchors": {0: "Lo lắng liên tục, mất ngủ", 3: "Căng thẳng thường xuyên",
                        5: "Cân bằng, đôi lúc áp lực", 8: "Bình an phần lớn thời gian",
                        10: "Hoàn toàn an tâm với hệ thống"},
        },
        # 3. Sự rõ ràng
        {
            "name": "q5_clarity", "label": "Sự rõ ràng",
            "hint": "Bạn có biết chính xác mình đang xây gì, hay vẫn đang dò đường?",
            "left": "Mơ hồ hoàn toàn", "right": "Rõ tầm 10-20 năm",
            "anchors": {0: "Không biết xây gì, không biết đi đâu", 3: "Có ý tưởng nhưng lúc đổi lúc giữ",
                        5: "Rõ trong 3-6 tháng tới", 8: "Rõ tầm 2-3 năm tới",
                        10: "Rõ cả sứ mệnh 10-20 năm"},
        },
        # 4. Khách hàng (DIAGNOSTIC — không tính vào FFS, dùng tìm điểm nghẽn)
        {
            "name": "q6_customer", "label": "Khách hàng",
            "diagnostic": True,
            "hint": "Bạn có biết rõ mình phục vụ ai, hay vẫn đang bán cho bất kỳ ai trả tiền?",
            "left": "Bán cho bất kỳ ai", "right": "Mô tả đầy đủ khách + hành trình",
            "anchors": {0: "Bán cho bất kỳ ai", 3: "Có nhóm rộng nhưng mơ hồ",
                        5: "Có persona cơ bản", 8: "Customer Profile chi tiết + Buying Journey",
                        10: "Bạn mô tả rõ khách hàng, vấn đề cấp thiết, hành trình mua và lý do họ chọn bạn"},
        },
        # 5. Thu nhập (TB 3 tháng)
        {
            "name": "q1_income", "label": "Thu nhập",
            "hint": "Trung bình 3 tháng gần nhất, doanh nghiệp đang trả lương cho bạn xứng đáng chưa so với mục tiêu cá nhân?",
            "left": "Chưa có thu nhập", "right": "Vượt mục tiêu",
            "anchors": {0: "Chưa có thu nhập từ DN", 3: "Có ít, chưa đủ sống",
                        5: "Đủ sống cá nhân", 8: "Đạt mục tiêu thu nhập", 10: "Vượt mục tiêu"},
        },
        # 6. Dòng tiền (TB 3 tháng)
        {
            "name": "q2_profit", "label": "Dòng tiền",
            "hint": "Trung bình 3 tháng gần nhất, sau khi trả mọi chi phí, doanh nghiệp đang đặt tiền vào túi bạn hay đang đốt tiền của bạn?",
            "left": "Đang lỗ", "right": "Vượt kỳ vọng",
            "anchors": {0: "Lỗ liên tục", 3: "Hoà vốn", 5: "Có lời nhưng chưa ổn định",
                        8: "Lợi nhuận tốt, biên khoẻ", 10: "Vượt kỳ vọng lợi nhuận"},
        },
        # 7. Hệ thống
        {
            "name": "q7_system_ai", "label": "Hệ thống",
            "hint": "Doanh nghiệp có quy trình rõ ràng hay mọi thứ vẫn nằm trong đầu bạn?",
            "left": "Mọi thứ nằm trong đầu", "right": "Người khác vận hành được",
            "anchors": {0: "Mọi thứ nằm trong đầu bạn", 3: "Vài SOP rời rạc",
                        5: "Quy trình core đã viết ra (~30%)", 8: "SOP đầy đủ cho 70% hoạt động",
                        10: "Một người đã được hướng dẫn có thể vận hành các quy trình cốt lõi mà không cần hỏi founder"},
        },
        # 8. AI & Tự động hóa (text radio: số giờ tiết kiệm/tuần)
        {
            "name": "q9_growth", "label": "AI & Tự động hóa",
            "options_text": True,
            "hint": "AI và các tự động hóa đang giúp bạn tiết kiệm bao nhiêu giờ làm việc mỗi tuần?",
            "radio_options": [
                (0,  "0 giờ"),
                (3,  "2 giờ"),
                (5,  "5 giờ"),
                (8,  "10 giờ"),
                (10, "Trên 15 giờ"),
            ],
        },
        # 9. Độc lập doanh nghiệp (text radio, mapping V3.6.5: 0/1/4/7/10)
        {
            "name": "q8_independence", "label": "Độc lập doanh nghiệp",
            "options_text": True,
            "hint": "Nếu bạn nghỉ hoàn toàn không xem điện thoại, doanh nghiệp vẫn chạy được bao lâu?",
            "radio_options": [
                (0,  "Dừng ngay"),
                (1,  "Chạy được 3 ngày"),
                (4,  "Chạy được 7 ngày"),
                (7,  "Chạy được 30 ngày"),
                (10, "Chạy được 90 ngày"),
            ],
        },
        # 10. Thời gian tự do (hỏi cụ thể số giờ/ngày/tuần)
        {
            "name": "q3_time_free", "label": "Thời gian tự do",
            "hint": "Mỗi tuần, bạn có bao nhiêu thời gian thực sự KHÔNG phải xử lý công việc doanh nghiệp (không email, không Zalo, không lo nghĩ)?",
            "left": "0 giờ/tuần", "right": "Cả tuần tự do",
            "anchors": {0: "Hầu như không có (<2 giờ/tuần)", 3: "Vài giờ rải rác (~5 giờ/tuần)",
                        5: "1 ngày/tuần thực sự tự do (~8 giờ)", 8: "2-3 ngày/tuần (~20 giờ)",
                        10: "Tự do hoàn toàn, làm khi muốn"},
        },
    ]

    cards = []
    for idx, q in enumerate(questions, 1):
        diag_badge = '<span class="diag-badge">Câu chẩn đoán</span>' if q.get("diagnostic") else ''
        diag_footnote = ('<p class="diag-note">Câu hỏi chẩn đoán bổ sung, '
                         'không tính trực tiếp vào Chỉ Số Tự Do Founder.</p>') if q.get("diagnostic") else ''

        if q.get("options_text"):
            options_html = "".join(
                f'<label class="opt-row"><input type="radio" name="{q["name"]}" value="{v}" required>'
                f'<span class="opt-text">{txt}</span></label>'
                for v, txt in q["radio_options"]
            )
            cards.append(f"""
            <div class="q-card" data-q="{q['name']}">
              <div class="q-header"><span class="q-num">{idx}/10</span><h3>{q['label']}</h3>{diag_badge}</div>
              <p class="hint">{q['hint']}</p>
              <div class="opt-group">{options_html}</div>
              {diag_footnote}
            </div>""")
            continue

        scale_items = []
        for i in range(0, 11):
            anchor = q["anchors"].get(i, "")
            tooltip = f' data-anchor="{anchor}"' if anchor else ''
            scale_items.append(
                f'<label{tooltip}><input type="radio" name="{q["name"]}" value="{i}" required><span>{i}</span></label>'
            )
        scale_html = "".join(scale_items)
        anchor_lines = "".join(
            f'<div class="anchor-line"><span class="anchor-num">{n}</span><span class="anchor-text">{txt}</span></div>'
            for n, txt in sorted(q["anchors"].items())
        )
        cards.append(f"""
        <div class="q-card{' q-diagnostic' if q.get('diagnostic') else ''}" data-q="{q['name']}">
          <div class="q-header"><span class="q-num">{idx}/10</span><h3>{q['label']}</h3>{diag_badge}</div>
          <p class="hint">{q['hint']}</p>
          <div class="scale">{scale_html}</div>
          <div class="scale-labels"><span>{q['left']}</span><span>{q['right']}</span></div>
          <div class="anchor-guide" data-default-open="false">
            <button type="button" class="anchor-toggle" onclick="toggleAnchor(this)">▼ Xem mốc tham chiếu</button>
            <div class="anchor-list">{anchor_lines}</div>
          </div>
          {diag_footnote}
        </div>""")

    cards_html = "".join(cards)

    return f"""<!DOCTYPE html>
<html lang="vi"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Chỉ Số Tự Do Founder (Founder Freedom Score™) · BreakoutOS</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{{--red:#d63031;--red-deep:#b71c1c;--ink:#0a0a0a;--ink-soft:#2a2a2a;
  --paper:#fafaf7;--line:#e5dfd0;--muted:#5a5453;--gold:#d4a24a}}
*{{box-sizing:border-box;margin:0;padding:0;-webkit-font-smoothing:antialiased}}
body{{font-family:'Be Vietnam Pro',system-ui;line-height:1.75;color:var(--ink);
  background:var(--paper);font-weight:400;font-size:17px;padding:30px 20px 100px}}
.container{{max-width:760px;margin:0 auto}}
.hero{{text-align:center;margin-bottom:30px}}
.tag{{display:inline-block;background:rgba(214,48,49,0.12);color:var(--red);padding:8px 18px;
  border-radius:999px;font-size:12px;letter-spacing:1.5px;text-transform:uppercase;font-weight:800;margin-bottom:16px}}
h1{{font-size:36px;line-height:1.25;font-weight:800;margin-bottom:14px}}
h1 .trademark{{font-size:20px;color:var(--muted);font-weight:600;display:block;margin-top:6px}}
.sub{{font-size:18px;color:var(--ink-soft);max-width:620px;margin:0 auto;line-height:1.6}}

.progress-sticky{{position:sticky;top:0;background:var(--paper);padding:16px 0;z-index:10;border-bottom:1px solid var(--line);margin:-30px -20px 24px;box-shadow:0 4px 14px rgba(0,0,0,0.04)}}
.progress-wrap{{max-width:760px;margin:0 auto;padding:0 20px}}
.progress-row{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}}
.progress-label{{font-size:13px;color:var(--muted);font-weight:600;letter-spacing:0.5px;text-transform:uppercase}}
.progress-value{{font-size:32px;font-weight:800;color:var(--red);line-height:1}}
.progress-value .total{{font-size:16px;color:var(--muted);font-weight:600}}
.progress-level{{font-size:14px;color:var(--muted);font-weight:700}}
.progress-level.level-red{{color:#d63031}}
.progress-level.level-orange{{color:#f4a261}}
.progress-level.level-yellow{{color:#d4a24a}}
.progress-level.level-green{{color:#2a9d8f}}
.progress-level.level-emerald{{color:#0a8700}}
.progress-bar{{height:10px;background:#fff;border:1px solid var(--line);border-radius:999px;overflow:hidden;margin-top:4px}}
.progress-fill{{height:100%;background:linear-gradient(90deg,#d63031 0%,#d63031 20%,#f4a261 40%,#d4a24a 60%,#2a9d8f 80%,#0a8700 100%);width:0%;transition:width 0.4s ease}}

.hook{{text-align:center;margin-bottom:20px}}
.hook-line-1{{font-size:22px;color:var(--muted);font-weight:600;margin-bottom:4px}}
.hook-line-2{{font-size:28px;color:var(--ink);font-weight:800;line-height:1.3}}
.hook-line-2 strong{{color:var(--red)}}

.anchor-guide{{margin-top:12px}}
.anchor-toggle{{background:transparent;border:none;color:var(--muted);cursor:pointer;font-size:13px;padding:6px 0;font-family:inherit;font-weight:600}}
.anchor-toggle:hover{{color:var(--red)}}
.anchor-list{{display:none;margin-top:8px;background:#fafaf7;border-radius:10px;padding:14px 16px;border:1px solid var(--line)}}
.anchor-list.open{{display:block}}
.anchor-line{{display:flex;align-items:flex-start;gap:12px;padding:6px 0;font-size:14px}}
.anchor-num{{display:inline-block;min-width:24px;background:var(--red);color:#fff;text-align:center;border-radius:6px;font-weight:800;padding:2px 0;font-size:13px}}
.anchor-text{{color:var(--ink-soft);line-height:1.5}}

/* Q8 option group (text radio thay vì scale) */
.opt-group{{display:flex;flex-direction:column;gap:10px;margin-top:10px}}
.opt-row{{display:flex;align-items:center;gap:16px;cursor:pointer;border:1.5px solid var(--line);border-radius:10px;padding:16px 22px;font-size:17px;background:#fafaf7;transition:all 0.15s}}
.opt-row:hover{{border-color:var(--red);background:#fff5f3}}
.opt-row:has(input:checked){{border-color:var(--red);background:#fff5f3;color:var(--red);font-weight:700}}
.opt-row input{{margin:0;accent-color:var(--red);width:18px;height:18px}}

/* 5 Levels box (Anna 2026-06-12 đêm muộn) */
.levels-box{{background:#fff;border:1px solid var(--line);border-radius:16px;padding:24px 26px;margin-bottom:30px}}
.levels-title{{font-size:17px;color:var(--red);text-transform:uppercase;letter-spacing:1.5px;font-weight:800;margin-bottom:18px;text-align:center}}
.levels-grid{{display:flex;flex-direction:column;gap:8px;max-width:540px;margin:0 auto}}
.level-row{{display:flex;align-items:center;gap:16px;padding:12px 16px;border-radius:10px;background:#fafaf7}}
.level-range{{display:inline-block;min-width:72px;background:var(--ink);color:#fff;border-radius:6px;padding:5px 10px;font-weight:800;font-size:15px;text-align:center}}
.level-dot{{font-size:22px}}
.level-name{{font-size:18px;color:var(--ink-soft);font-weight:600}}
.levels-target{{text-align:center;margin-top:20px;font-size:17px;color:var(--ink-soft);font-style:italic}}
.levels-target strong{{color:var(--red);font-style:normal}}

.intro{{background:#fff;border-left:5px solid var(--red);border-radius:0 16px 16px 0;padding:28px 32px;margin-bottom:34px}}
.intro p{{margin-bottom:14px;font-size:21px;line-height:1.55}}
.intro p:last-child{{margin-bottom:0;font-size:18px;color:var(--ink-soft);line-height:1.6}}
.intro strong{{color:var(--ink);font-weight:800}}
.intro .headline{{font-size:24px;font-weight:800;color:var(--ink);line-height:1.4}}
.intro .headline em{{color:var(--red);font-style:normal}}
.intro .t0-note{{display:inline-block;margin-top:10px;font-size:14px;color:var(--muted);background:#fafaf7;padding:4px 12px;border-radius:999px;font-style:normal}}

.diag-badge{{display:inline-block;background:#fff5f3;color:var(--red);border:1px solid var(--red);
  border-radius:999px;padding:3px 10px;font-size:11px;letter-spacing:0.5px;font-weight:800;text-transform:uppercase;margin-left:8px;vertical-align:middle}}
.q-diagnostic{{border-style:dashed}}
.diag-note{{margin-top:12px;font-size:13px;color:var(--muted);font-style:italic;background:#fafaf7;padding:8px 12px;border-radius:8px}}

.q-card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:22px 26px;margin-bottom:14px}}
.q-card.answered{{border-color:var(--red);background:#fff5f3}}
.q-header{{display:flex;align-items:baseline;gap:12px;margin-bottom:4px}}
.q-num{{font-size:13px;font-weight:800;color:var(--red);letter-spacing:1px}}
.q-card h3{{font-size:22px;font-weight:700;color:var(--ink);line-height:1.35}}
.q-card .hint{{font-size:17px;color:var(--muted);margin-bottom:18px;line-height:1.6}}
.scale{{display:flex;gap:6px;flex-wrap:wrap}}
.scale label{{flex:1;min-width:42px;text-align:center;cursor:pointer;border:1.5px solid var(--line);
  border-radius:8px;padding:13px 4px;font-weight:700;background:#fafaf7;transition:all 0.15s;font-size:17px}}
.scale label:hover{{border-color:var(--red);color:var(--red)}}
.scale label:has(input:checked){{border-color:var(--red);background:var(--red);color:#fff}}
.scale input{{display:none}}
.scale-labels{{display:flex;justify-content:space-between;font-size:13px;color:var(--muted);margin-top:10px}}
.q8-legend{{font-size:12px;color:var(--muted);margin-top:8px;text-align:center;background:#fafaf7;padding:8px 12px;border-radius:8px}}

button[type=submit]{{display:block;width:100%;padding:22px;background:var(--red);color:#fff;border:none;
  border-radius:14px;font-size:20px;font-weight:800;cursor:pointer;margin-top:30px;
  box-shadow:0 8px 28px rgba(214,48,49,0.35);font-family:inherit;letter-spacing:0.2px}}
button[type=submit]:hover{{background:var(--red-deep)}}
button[type=submit]:disabled{{opacity:0.5;cursor:wait}}

.result{{display:none;background:linear-gradient(135deg,#0a0a0a,#2d2d2d);color:#fff;
  border-radius:20px;padding:40px 32px;margin-top:30px}}
.result.show{{display:block}}
.result h2{{color:#fff;font-size:28px;margin-bottom:6px}}
.result .score-big{{font-size:96px;font-weight:800;color:var(--gold);line-height:1;text-align:center;margin:24px 0 4px}}
.result .score-total{{text-align:center;font-size:18px;opacity:0.85;margin-bottom:18px}}
.result .level-badge{{display:inline-block;background:var(--red);color:#fff;padding:10px 20px;border-radius:999px;font-weight:800;letter-spacing:1px;font-size:14px;text-transform:uppercase}}
.result .level-blurb{{font-size:17px;opacity:0.9;margin:14px 0 24px;line-height:1.6}}

.report-section{{background:rgba(255,255,255,0.05);border-radius:12px;padding:20px 22px;margin-bottom:14px}}
.report-section h4{{color:var(--gold);font-size:14px;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:10px;font-weight:800}}
.report-section ul{{list-style:none;padding:0}}
.report-section li{{padding:10px 0;color:rgba(255,255,255,0.9);font-size:15px;line-height:1.65;border-bottom:1px solid rgba(255,255,255,0.06)}}
.report-section li:last-child{{border-bottom:none}}
.report-section li strong{{color:#fff;font-size:16px}}
.report-section .report-exp{{display:block;margin-top:4px;color:rgba(255,255,255,0.65);font-size:14px;line-height:1.55}}
.report-loader{{display:flex;flex-direction:column;align-items:center;padding:40px 20px;text-align:center;color:rgba(255,255,255,0.8)}}
.report-loader p{{margin-top:20px;font-size:15px;line-height:1.6}}
.report-loader .loader-sub{{font-size:13px;color:rgba(255,255,255,0.55)}}
.loader-spinner{{width:36px;height:36px;border:3px solid rgba(255,255,255,0.15);border-top-color:var(--gold);border-radius:50%;animation:spin 0.9s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.report-section p{{color:rgba(255,255,255,0.9);font-size:15px;line-height:1.65}}
.report-loading{{text-align:center;padding:24px;color:rgba(255,255,255,0.7);font-style:italic}}

.cta-after{{margin-top:30px;text-align:center}}
.cta-after a{{display:inline-block;background:var(--red);color:#fff;padding:18px 32px;border-radius:14px;font-weight:800;text-decoration:none;font-size:17px}}

@media(max-width:600px){{
  body{{padding:20px 14px 100px}}
  h1{{font-size:26px}}
  .scale label{{min-width:32px;font-size:13px;padding:8px 2px}}
  .progress-value{{font-size:22px}}
  .result{{padding:28px 22px}}
  .result .score-big{{font-size:64px}}
}}
</style>
</head>
<body>
<div class="container">

<div class="progress-sticky">
  <div class="progress-wrap">
    <div class="progress-row">
      <span class="progress-label">Chỉ Số Tự Do Founder</span>
      <span class="progress-value"><span id="live-score">—</span><span class="total">/100</span></span>
    </div>
    <div class="progress-row" style="margin-top:6px">
      <span class="progress-level" id="live-level">Chưa có kết quả</span>
      <span class="progress-label" id="answered-count">0/10 câu đã trả lời</span>
    </div>
    <div class="progress-bar"><div class="progress-fill" id="progress-fill"></div></div>
  </div>
</div>

<div class="hero">
  <div class="hook">
    <p class="hook-line-1">Hầu hết founder nghĩ mình thiếu khách hàng.</p>
    <p class="hook-line-2">Thực tế họ thiếu <strong>tự do</strong>.</p>
  </div>
  <div class="tag" style="margin-top:18px">Đo Điểm Khởi Đầu T0 · Founder Freedom Score™</div>
  <h1>Bạn đang sở hữu doanh nghiệp,<br>hay doanh nghiệp đang sở hữu bạn?</h1>
  <p class="sub">10 câu hỏi · 3 phút · Báo cáo AI sinh ngay sau khi bạn trả lời xong.</p>
</div>

<div class="intro">
  <p class="headline">BreakoutOS bán <em>sự gia tăng Chỉ Số Tự Do Founder</em>.</p>
  <p>Đây là chỉ số trung tâm xuyên toàn bộ hệ thống. Cuối khoá đo lại để thấy bạn đã tăng bao nhiêu điểm.</p>
  <span class="t0-note">Đây là T0 tự đánh giá · chưa kiểm chứng bằng dữ liệu vận hành</span>
</div>

<div class="levels-box">
  <div class="levels-title">Điểm hiện tại của bạn nằm ở đâu?</div>
  <div class="levels-grid">
    <div class="level-row"><span class="level-range">0-20</span><span class="level-dot">🔴</span><span class="level-name">Đang tìm lối đi</span></div>
    <div class="level-row"><span class="level-range">21-40</span><span class="level-dot">🟠</span><span class="level-name">Đang thử nghiệm</span></div>
    <div class="level-row"><span class="level-range">41-60</span><span class="level-dot">🟡</span><span class="level-name">Founder vận hành</span></div>
    <div class="level-row"><span class="level-range">61-80</span><span class="level-dot">🟢</span><span class="level-name">Founder có hệ thống</span></div>
    <div class="level-row"><span class="level-range">81-100</span><span class="level-dot">✨</span><span class="level-name">Founder tự do</span></div>
  </div>
  <p class="levels-target">Mục tiêu của BreakoutOS: đưa bạn từ điểm hiện tại lên <strong>trên 70</strong>.</p>
</div>

<form id="baseline-form">
  <input type="hidden" name="student_id" value="{student_id}">
  <input type="hidden" name="signature" value="{sig}">
  {cards_html}
  <button type="submit" id="submit-btn">Xem Điểm Tự Do Founder của tôi →</button>
</form>

<div class="result" id="result">
  <div class="tag" style="background:rgba(212,162,74,0.2);color:var(--gold);display:inline-block">Founder Freedom Score™</div>
  <div class="score-big" id="result-score">0</div>
  <div class="score-total">/ 100 điểm</div>
  <div style="text-align:center;margin-bottom:14px"><span class="level-badge" id="level-badge">—</span></div>
  <p class="level-blurb" id="level-blurb">—</p>

  <div id="report-content">
    <div class="report-loading">Báo cáo cá nhân hoá đang được AI sinh, chờ ~10-20 giây...</div>
  </div>

  <div class="cta-after">
    <a id="next-cta" href="#">Tiếp tục Tầng 1 Hiểu Mình →</a>
  </div>
</div>

</div>

<script>
const Q_KEYS = ['q1_income','q2_profit','q3_time_free','q4_peace','q5_clarity',
                'q6_customer','q7_system_ai','q8_independence','q9_growth','q10_meaning'];

function getLevel(total) {{
  if (total <= 20) return {{label: '🔴 Người đang tìm lối đi', color: 'level-red'}};
  if (total <= 40) return {{label: '🟠 Người đang thử nghiệm', color: 'level-orange'}};
  if (total <= 60) return {{label: '🟡 Founder đang vận hành', color: 'level-yellow'}};
  if (total <= 80) return {{label: '🟢 Founder có hệ thống', color: 'level-green'}};
  return {{label: '✨ Founder tự do', color: 'level-emerald'}};
}}

// V3.6.5 weighted FFS (mirror Postgres trigger). q6_customer là diagnostic, KHÔNG cộng.
function computeWeightedFFS(s) {{
  return Math.round(
      (s.q10_meaning     || 0) * 1.8
    + (s.q4_peace        || 0) * 1.3
    + (s.q5_clarity      || 0) * 1.3
    + ((s.q1_income      || 0) + (s.q2_profit  || 0)) * 0.9
    + ((s.q7_system_ai   || 0) + (s.q9_growth  || 0)) * 0.5
    + (s.q8_independence || 0) * 1.0
    + (s.q3_time_free    || 0) * 1.8
  );
}}

function recompute() {{
  const fd = new FormData(document.getElementById('baseline-form'));
  const scores = {{}};
  let answered = 0;
  for (const k of Q_KEYS) {{
    const raw = fd.get(k);
    if (raw !== null && raw !== '') {{
      scores[k] = parseInt(raw);
      answered++;
    }}
  }}
  const scoreEl = document.getElementById('live-score');
  const fillEl = document.getElementById('progress-fill');
  const levelEl = document.getElementById('live-level');
  document.getElementById('answered-count').textContent = answered + '/10 câu đã trả lời';
  fillEl.style.width = (answered / 10 * 100) + '%';

  if (answered < 10) {{
    scoreEl.textContent = '—';
    levelEl.textContent = answered === 0 ? 'Chưa có kết quả' : 'Tiếp tục trả lời để xem kết quả';
    levelEl.className = 'progress-level';
  }} else {{
    const total = computeWeightedFFS(scores);
    scoreEl.textContent = total;
    const lv = getLevel(total);
    levelEl.textContent = lv.label;
    levelEl.className = 'progress-level ' + lv.color;
  }}
  for (const k of Q_KEYS) {{
    const card = document.querySelector(`[data-q="${{k}}"]`);
    if (card) card.classList.toggle('answered', fd.get(k) !== null && fd.get(k) !== '');
  }}
}}

function toggleAnchor(btn) {{
  const list = btn.nextElementSibling;
  list.classList.toggle('open');
  btn.textContent = list.classList.contains('open')
    ? '▲ Ẩn mốc tham chiếu'
    : '▼ Xem mốc tham chiếu';
}}

// Bao quát cả scale (.scale input) và options text (.opt-row input)
document.querySelectorAll('input[type=radio]').forEach(el => el.addEventListener('change', recompute));

document.getElementById('baseline-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const btn = document.getElementById('submit-btn');
  btn.disabled = true; btn.textContent = 'Đang lưu...';
  const fd = new FormData(e.target);
  const sid = fd.get('student_id');
  const sig = fd.get('signature');
  if (!sid) {{ alert('Thiếu student_id'); btn.disabled=false; btn.textContent='Hoàn tất'; return; }}
  const payload = {{ source: 'self_baseline' }};
  for (const k of Q_KEYS) payload[k] = parseInt(fd.get(k) || 0);

  try {{
    const r = await fetch(`/sdl/students/${{sid}}/freedom-score`, {{
      method: 'POST', headers: {{
        'Content-Type':'application/json',
        'X-Student-Signature': sig,
      }}, body: JSON.stringify(payload),
    }});
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();

    // Show result panel
    document.getElementById('result-score').textContent = d.total_score;
    document.getElementById('level-badge').textContent = d.classification_label;
    document.getElementById('level-blurb').textContent = d.classification_blurb;
    document.getElementById('next-cta').href =
      `/foundation/l1?student=${{sid}}&sig=${{encodeURIComponent(sig)}}`;

    e.target.style.display = 'none';
    document.querySelector('.progress-sticky').style.display = 'none';
    document.getElementById('result').classList.add('show');
    window.scrollTo({{top:0, behavior:'smooth'}});

    // Show loader trong khi AI sinh báo cáo
    document.getElementById('report-content').innerHTML =
      '<div class="report-loader"><div class="loader-spinner"></div>'
      + '<p>AI đang phân tích 10 câu trả lời của bạn...<br>'
      + '<span class="loader-sub">Báo cáo chi tiết 7 phần sẽ hiển thị sau ~30-60 giây.</span></p></div>';

    // Poll report (max 120s)
    let gotReport = false;
    for (let i = 0; i < 40; i++) {{
      await new Promise(res => setTimeout(res, 3000));
      try {{
        const rep = await fetch(
          `/sdl/students/${{sid}}/freedom-score/${{d.id}}/report?sig=${{encodeURIComponent(sig)}}`
        ).then(r => r.json());
        if (rep.report_ready && rep.report) {{
          renderReport(rep.report);
          gotReport = true;
          break;
        }}
      }} catch (e) {{}}
    }}
    if (!gotReport) {{
      document.getElementById('report-content').innerHTML =
        '<div class="report-section"><h4>Báo cáo đang sinh</h4>'
        + '<p>AI đang phân tích sâu hơn. Refresh trang sau 1-2 phút để xem đầy đủ.</p>'
        + '<p><button onclick="location.reload()" style="background:var(--gold);border:none;padding:10px 18px;border-radius:8px;color:#000;cursor:pointer;font-weight:700;margin-top:8px">↻ Tải lại</button></p></div>';
    }}
  }} catch(err) {{
    alert('Lỗi: '+err.message);
    btn.disabled=false; btn.textContent='Hoàn tất';
  }}
}});

function renderReport(r) {{
  // Normalize strengths/weaknesses: AI có thể trả string HOẶC object dạng question + explanation.
  const renderItem = (s, icon) => {{
    if (typeof s === 'string') return '<li>'+icon+' '+s+'</li>';
    if (s && typeof s === 'object') {{
      const q = s.question || s.label || '';
      const exp = s.explanation || s.reason || s.detail || '';
      return '<li>'+icon+' <strong>'+q+'</strong>'+(exp ? '<br><span class="report-exp">'+exp+'</span>' : '')+'</li>';
    }}
    return '';
  }};
  const html = `
    <div class="report-section">
      <h4>Tóm tắt</h4>
      <p>${{r.summary || ''}}</p>
    </div>
    <div class="report-section">
      <h4>3 điểm mạnh nhất</h4>
      <ul class="report-list">${{(r.top_3_strengths||[]).map(s => renderItem(s, '✓')).join('')}}</ul>
    </div>
    <div class="report-section">
      <h4>3 điểm yếu nhất</h4>
      <ul class="report-list">${{(r.top_3_weaknesses||[]).map(s => renderItem(s, '⚠')).join('')}}</ul>
    </div>
    <div class="report-section">
      <h4>Điểm nghẽn lớn nhất</h4>
      <p><strong>${{(r.biggest_bottleneck||{{}}).question||''}}</strong></p>
      <p>${{(r.biggest_bottleneck||{{}}).why||''}}</p>
      <p><em>Tác động:</em> ${{(r.biggest_bottleneck||{{}}).impact||''}}</p>
    </div>
    <div class="report-section">
      <h4>Ưu tiên hành động 90 ngày</h4>
      <ul class="report-list">${{(r.action_priority_90_days||[]).map(a => '<li><strong>Tuần '+(a.week||'?')+':</strong> '+(a.action||'')+(a.expected_score_lift ? ' <em>('+a.expected_score_lift+')</em>' : '')+'</li>').join('')}}</ul>
    </div>
    <div class="report-section">
      <h4>Tầng tiếp theo nên học</h4>
      <p><strong>${{(r.next_layer_recommended||{{}}).layer||''}}</strong></p>
      <p>${{(r.next_layer_recommended||{{}}).reason||''}}</p>
    </div>
    <div class="report-section">
      <h4>Động viên</h4>
      <p>${{r.encouragement || ''}}</p>
    </div>
  `;
  document.getElementById('report-content').innerHTML = html;
}}
</script>
</body></html>"""
