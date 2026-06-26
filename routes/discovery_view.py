"""Discovery Report HTML view."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from routes._auth import request_signature, require_student_signature
from routes.sdl_routes import get_pool, require_level_access


router = APIRouter(tags=["discovery-view"])


def _render_list(items: list[str]) -> str:
    return "".join(f"<li>{i}</li>" for i in items)


def _render_kv_table(items: list[dict], cols: list[tuple[str, str]]) -> str:
    """cols = [(key, label), ...]"""
    head = "".join(f"<th>{label}</th>" for _, label in cols)
    rows = ""
    for item in items:
        cells = "".join(f"<td>{item.get(k, '')}</td>" for k, _ in cols)
        rows += f"<tr>{cells}</tr>"
    return f'<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>'


@router.get("/sdl/students/{student_id}/discovery/report", response_class=HTMLResponse)
async def discovery_report(
    student_id: UUID,
    request: Request,
    sig: str = "",
    pool: asyncpg.Pool = Depends(get_pool),
) -> HTMLResponse:
    """Render latest Discovery Report HTML."""
    require_student_signature(str(student_id), request_signature(request, sig))
    await require_level_access(pool, student_id, 3, "Discovery Report")
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM breakoutos.discovery_reports
            WHERE student_id=$1
            ORDER BY created_at DESC LIMIT 1
            """,
            student_id,
        )

    if not row:
        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><title>Chưa có Discovery Report</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font-family:'Be Vietnam Pro',system-ui;background:#fafaf7;padding:60px 20px;text-align:center;color:#0a0a0a}}
h1{{color:#d63031}}button{{background:#d63031;color:#fff;border:none;padding:18px 32px;border-radius:12px;font-weight:800;font-size:17px;cursor:pointer;margin-top:20px}}</style></head>
<body><h1>Chưa có Discovery Report</h1>
<p>Bạn cần hoàn thành Tầng 1 + Tầng 2 trước, rồi nhấn "Khám phá cơ hội kinh doanh".</p>
    <form method="post" action="/sdl/discovery/run?student_id={student_id}&sig={sig}">
<button type="submit">🚀 Khám phá cơ hội kinh doanh</button></form>
</body></html>""", status_code=200)

    if row["status"] == "generation_failed":
        err = json.loads(row["error_payload"]) if row["error_payload"] else {}
        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><title>Discovery Engine lỗi</title>
<style>body{{font-family:'Be Vietnam Pro',system-ui;background:#fafaf7;padding:40px 20px;color:#0a0a0a;max-width:780px;margin:0 auto}}
h1{{color:#d63031}}.err{{background:#f8d7da;border:1px solid #f5c6cb;border-radius:10px;padding:18px;margin:20px 0;color:#721c24}}</style></head>
<body><h1>Discovery Engine gặp lỗi</h1>
<div class="err"><strong>Lỗi:</strong> {err.get('error', 'unknown')}<br><strong>Chi tiết:</strong> {err.get('message', '') or err.get('raw_head', '')}</div>
<p><a href="/sdl/students/{student_id}/discovery/report?sig={sig}">Thử lại</a></p>
</body></html>""", status_code=200)

    s1 = json.loads(row["section_1_founder_summary_json"]) if row["section_1_founder_summary_json"] else {}
    s2 = json.loads(row["section_2_customer_reality_json"]) if row["section_2_customer_reality_json"] else {}
    s3 = json.loads(row["section_3_market_demand_json"]) if row["section_3_market_demand_json"] else []
    s4 = json.loads(row["section_4_opportunity_ideas_json"]) if row["section_4_opportunity_ideas_json"] else {}
    s5 = json.loads(row["section_5_validation_matrix_json"]) if row["section_5_validation_matrix_json"] else []
    s6 = json.loads(row["section_6_recommended_offer_json"]) if row["section_6_recommended_offer_json"] else {}
    s7 = json.loads(row["section_7_one_page_offer_json"]) if row["section_7_one_page_offer_json"] else {}
    s8 = json.loads(row["section_8_content_engine_json"]) if row["section_8_content_engine_json"] else {}
    s9 = json.loads(row["section_9_action_plan_json"]) if row["section_9_action_plan_json"] else {}

    # Section 4 categories
    s4_html = ""
    for cat_key, cat_label in [
        ("product", "Sản phẩm"), ("service", "Dịch vụ"), ("coaching", "Coaching"),
        ("membership", "Membership"), ("ai_powered", "AI-powered"),
    ]:
        items = s4.get(cat_key, [])
        if items:
            rows_html = ""
            for it in items:
                rows_html += (
                    f"<tr><td><strong>{it.get('name', '')}</strong></td>"
                    f"<td>{it.get('solves_pain', '')}</td>"
                    f"<td>{it.get('fit_founder', '')}</td>"
                    f"<td>{it.get('market_need', '')}</td></tr>"
                )
            s4_html += f"""
<h3>{cat_label}</h3>
<table><thead><tr><th>Tên</th><th>Giải quyết pain</th><th>Founder fit</th><th>Market need</th></tr></thead>
<tbody>{rows_html}</tbody></table>"""

    s2_pains = s2.get("pains_ranked", [])
    s2_pains_html = "".join(
        f'<tr><td>{p.get("pain", "")}</td><td><span class="score score-{min(int(p.get("severity", 0))//2, 5)}">{p.get("severity", 0)}/10</span></td></tr>'
        for p in s2_pains
    )

    s3_html = _render_kv_table(s3, [
        ("keyword", "Keyword"), ("search_intent", "Intent"),
        ("trend_score", "Trend"), ("opportunity_score", "Opp Score"),
        ("data_source", "Source"),
    ])

    s5_html = _render_kv_table(s5, [
        ("idea_name", "Ý tưởng"),
        ("founder_fit", "Founder"), ("customer_fit", "Customer"),
        ("market_demand", "Market"), ("profit_potential", "Profit"),
        ("ai_leverage", "AI"), ("total", "Tổng /50"),
    ])

    s8_html = ""
    for ch_key, ch_label in [
        ("content_post", "Content Post"), ("video_short", "Video Short"),
        ("fb_post", "FB Post"), ("youtube", "YouTube"), ("lead_magnet", "Lead Magnet"),
    ]:
        items = s8.get(ch_key, [])
        if items:
            s8_html += f"<h4>{ch_label}</h4><ol>{_render_list(items)}</ol>"

    s9_html = ""
    for w in (1, 2, 3, 4):
        tasks = s9.get(f"week_{w}", [])
        if tasks:
            s9_html += f"<h4>Tuần {w}</h4><ul>{_render_list(tasks)}</ul>"

    price_vnd = s7.get("suggested_price_vnd", 0)
    try:
        price_fmt = f"{int(price_vnd):,}".replace(",", ".") + " VND"
    except (ValueError, TypeError):
        price_fmt = str(price_vnd)

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Business Discovery Report · BreakoutOS</title>
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{{--red:#d63031;--ink:#0a0a0a;--paper:#fafaf7;--line:#e5dfd0;--muted:#5a5453;--ok:#27ae60}}
*{{box-sizing:border-box;margin:0;padding:0;font-family:'Be Vietnam Pro',system-ui}}
body{{background:var(--paper);color:var(--ink);padding:30px 20px;line-height:1.7;font-size:16px}}
.container{{max-width:920px;margin:0 auto}}
.header{{text-align:center;margin-bottom:30px}}
h1{{color:var(--red);font-size:34px;font-weight:800;margin-bottom:6px}}
.subtitle{{color:var(--muted);font-size:15px}}
.section{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:26px 30px;margin-bottom:18px}}
.section h2{{color:var(--red);font-size:20px;font-weight:800;margin-bottom:14px;display:flex;align-items:center;gap:10px}}
.section h2 .num{{display:inline-block;background:var(--red);color:#fff;width:28px;height:28px;border-radius:50%;text-align:center;line-height:28px;font-size:14px}}
.section h3{{margin-top:18px;margin-bottom:8px;font-size:16px;color:var(--ink)}}
.section h4{{margin-top:14px;margin-bottom:6px;font-size:14px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px}}
.section p{{margin-bottom:8px}}
ul,ol{{padding-left:22px;margin-bottom:10px}}
li{{margin-bottom:4px}}
table{{width:100%;border-collapse:collapse;margin:10px 0;font-size:14px}}
th,td{{border:1px solid var(--line);padding:8px 10px;text-align:left}}
th{{background:#f5efe2;font-weight:700}}
tr:nth-child(even) td{{background:#fafaf7}}
.callout{{background:#fff5f5;border-left:4px solid var(--red);padding:14px 18px;border-radius:8px;margin:10px 0}}
.score{{display:inline-block;padding:3px 10px;border-radius:999px;font-weight:700;font-size:12px;background:#e5dfd0;color:#0a0a0a}}
.score-0,.score-1{{background:#f8d7da;color:#721c24}}
.score-2,.score-3{{background:#fff3cd;color:#856404}}
.score-4,.score-5{{background:#d4f1de;color:#1e7e34}}
.offer-card{{background:linear-gradient(135deg,#0a0a0a,#2d2d2d);color:#fff;border-radius:14px;padding:28px 30px;margin-bottom:18px}}
.offer-card h2{{color:#fff}}
.offer-card h2 .num{{background:#fff;color:#0a0a0a}}
.offer-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px 24px;margin-top:14px}}
.offer-grid .label{{font-size:12px;color:#bbb;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px}}
.offer-grid .value{{font-size:15px}}
.price{{font-size:28px;font-weight:800;color:#fff}}
.meta{{color:var(--muted);font-size:13px;text-align:center;margin-top:30px}}
</style></head>
<body><div class="container">

<div class="header">
  <h1>🚀 Business Discovery Report</h1>
  <p class="subtitle">Phân tích AI dựa trên Tầng 1 + Tầng 2 của bạn · {row['created_at'].strftime('%H:%M %d/%m/%Y')}</p>
</div>

<div class="section">
  <h2><span class="num">1</span>Founder Profile Summary</h2>
  <p><strong>Bạn là ai:</strong> {s1.get('who_you_are', '')}</p>
  <h3>Lợi thế độc nhất của bạn</h3>
  <ul>{_render_list(s1.get('your_unique_advantage', []))}</ul>
  <p><strong>Bạn phục vụ ai tốt nhất:</strong> {s1.get('who_you_serve_best', '')}</p>
</div>

<div class="section">
  <h2><span class="num">2</span>Customer Reality Report</h2>
  <div class="callout"><strong>Pain lớn nhất:</strong> {s2.get('top_pain', '')}</div>
  <div class="callout"><strong>Desire lớn nhất:</strong> {s2.get('top_desire', '')}</div>
  <div class="callout"><strong>Vấn đề cấp bách nhất:</strong> {s2.get('most_urgent_problem', '')}</div>
  <h3>Pain ưu tiên theo severity</h3>
  <table><thead><tr><th>Pain</th><th>Mức độ</th></tr></thead><tbody>{s2_pains_html}</tbody></table>
</div>

<div class="section">
  <h2><span class="num">3</span>Market Demand Analysis</h2>
  {s3_html}
  <p class="meta">Lưu ý: external API (Google Trends, AnswerThePublic, Reddit, YouTube) sẽ tích hợp dần, dữ liệu hiện AI inferred.</p>
</div>

<div class="section">
  <h2><span class="num">4</span>Business Opportunity Ideas</h2>
  {s4_html}
</div>

<div class="section">
  <h2><span class="num">5</span>Product Validation Matrix</h2>
  {s5_html}
</div>

<div class="section">
  <h2><span class="num">6</span>Recommended First Offer</h2>
  <h3>TOP 1: {s6.get('top_pick_name', '')}</h3>
  <p><strong>Vì sao:</strong> {s6.get('why', '')}</p>
  <p><strong>Rủi ro chính:</strong> {s6.get('main_risk', '')}</p>
  <p><strong>Thời gian triển khai:</strong> {s6.get('timeline_days', '?')} ngày</p>
  <p><strong>Cách bán đầu tiên:</strong> {s6.get('first_sale_strategy', '')}</p>
</div>

<div class="offer-card">
  <h2><span class="num">7</span>One Page Offer Sheet</h2>
  <h3 style="color:#fff;margin-top:10px;font-size:22px">{s7.get('product_name', '')}</h3>
  <div class="offer-grid">
    <div><div class="label">Khách hàng</div><div class="value">{s7.get('customer', '')}</div></div>
    <div><div class="label">Vấn đề</div><div class="value">{s7.get('problem', '')}</div></div>
    <div><div class="label">Giải pháp</div><div class="value">{s7.get('solution', '')}</div></div>
    <div><div class="label">Kết quả</div><div class="value">{s7.get('result', '')}</div></div>
    <div><div class="label">Giá đề xuất</div><div class="value price">{price_fmt}</div></div>
    <div><div class="label">Cam kết</div><div class="value">{s7.get('guarantee', '')}</div></div>
    <div><div class="label">Kênh bán</div><div class="value">{s7.get('sales_channel', '')}</div></div>
    <div><div class="label">CTA</div><div class="value">{s7.get('cta', '')}</div></div>
  </div>
</div>

<div class="section">
  <h2><span class="num">8</span>Content Opportunity Engine</h2>
  {s8_html}
</div>

<div class="section">
  <h2><span class="num">9</span>30-Day Action Plan</h2>
  {s9_html}
  <div class="callout" style="margin-top:14px"><strong>🎯 Mục tiêu:</strong> {s9.get('goal', 'Có khách hàng đầu tiên.')}</div>
</div>

<p class="meta">Generated by {row['ai_model']} · {row['generation_seconds']:.1f}s · BreakoutOS Discovery Engine</p>

</div></body></html>""")
