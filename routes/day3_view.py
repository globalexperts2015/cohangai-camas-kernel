"""Day 3 Challenge Report view (public, no auth)."""
from __future__ import annotations

import json
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from routes.sdl_routes import get_pool


router = APIRouter(tags=["day3-view"])


def _ul(items: list[str]) -> str:
    return "".join(f"<li>{i}</li>" for i in items)


def _kv_table(items: list[dict], cols: list[tuple[str, str]]) -> str:
    head = "".join(f"<th>{label}</th>" for _, label in cols)
    rows = ""
    for item in items:
        cells = "".join(f"<td>{item.get(k, '')}</td>" for k, _ in cols)
        rows += f"<tr>{cells}</tr>"
    return f'<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>'


@router.get("/day3/report/{session_id}", response_class=HTMLResponse)
async def day3_report(
    session_id: UUID,
    wait: int = 0,
    pool: asyncpg.Pool = Depends(get_pool),
) -> HTMLResponse:
    """Public Day 3 Discovery Report. Auto-poll if wait=1."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM breakoutos.day3_sessions WHERE id=$1", session_id,
        )

    if not row:
        return HTMLResponse("<h1>Không tìm thấy session</h1>", status_code=404)

    css = """
:root{--red:#d63031;--ink:#0a0a0a;--paper:#fafaf7;--line:#e5dfd0;--muted:#5a5453;--ok:#27ae60}
*{box-sizing:border-box;margin:0;padding:0;font-family:'Be Vietnam Pro',system-ui}
body{background:var(--paper);color:var(--ink);padding:30px 20px;line-height:1.7;font-size:16px}
.container{max-width:920px;margin:0 auto}
.header{text-align:center;margin-bottom:30px}
h1{color:var(--red);font-size:34px;font-weight:800;margin-bottom:6px}
.subtitle{color:var(--muted);font-size:15px}
.section{background:#fff;border:1px solid var(--line);border-radius:14px;padding:26px 30px;margin-bottom:18px}
.section h2{color:var(--red);font-size:20px;font-weight:800;margin-bottom:14px;display:flex;align-items:center;gap:10px}
.section h2 .num{display:inline-block;background:var(--red);color:#fff;width:28px;height:28px;border-radius:50%;text-align:center;line-height:28px;font-size:14px}
.section h3{margin-top:18px;margin-bottom:8px;font-size:16px;color:var(--ink)}
.section h4{margin-top:14px;margin-bottom:6px;font-size:14px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px}
.section p{margin-bottom:8px}
ul,ol{padding-left:22px;margin-bottom:10px}
li{margin-bottom:4px}
table{width:100%;border-collapse:collapse;margin:10px 0;font-size:14px}
th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{background:#f5efe2;font-weight:700}
tr:nth-child(even) td{background:#fafaf7}
.callout{background:#fff5f5;border-left:4px solid var(--red);padding:14px 18px;border-radius:8px;margin:10px 0}
.score{display:inline-block;padding:3px 10px;border-radius:999px;font-weight:700;font-size:12px;background:#e5dfd0;color:#0a0a0a}
.score-0,.score-1{background:#f8d7da;color:#721c24}
.score-2,.score-3{background:#fff3cd;color:#856404}
.score-4,.score-5{background:#d4f1de;color:#1e7e34}
.offer-card{background:linear-gradient(135deg,#0a0a0a,#2d2d2d);color:#fff;border-radius:14px;padding:28px 30px;margin-bottom:18px}
.offer-card h2{color:#fff}
.offer-card h2 .num{background:#fff;color:#0a0a0a}
.offer-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px 24px;margin-top:14px}
.offer-grid .label{font-size:12px;color:#bbb;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px}
.offer-grid .value{font-size:15px}
.price{font-size:28px;font-weight:800;color:#fff}
.meta{color:var(--muted);font-size:13px;text-align:center;margin-top:30px}
.loader{text-align:center;padding:60px 20px;background:#fff;border-radius:14px;margin-top:30px}
.spinner{width:60px;height:60px;border:5px solid var(--line);border-top-color:var(--red);border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 24px}
@keyframes spin{to{transform:rotate(360deg)}}
.err-box{background:#f8d7da;border:1px solid #f5c6cb;border-radius:10px;padding:18px;color:#721c24}
"""

    if row["status"] == "pending":
        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Đang phân tích · BreakoutOS</title>
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{css}</style></head>
<body><div class="container">
<div class="header"><h1>🤖 AI đang phân tích...</h1></div>
<div class="loader">
  <div class="spinner"></div>
  <h3 style="margin-bottom:8px">Discovery Engine đang chạy</h3>
  <p style="color:#5a5453">Tổng hợp founder profile + customer reality + market demand + sinh 9 phần report.</p>
  <p style="color:#5a5453;margin-top:8px">Thường mất 30-60 giây. Trang tự reload.</p>
</div>
</div>
<script>setTimeout(() => location.reload(), 8000);</script>
</body></html>""")

    if row["status"] == "failed":
        err = json.loads(row["error_payload"]) if row["error_payload"] else {}
        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><title>Day 3 lỗi</title>
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{css}</style></head>
<body><div class="container">
<div class="header"><h1>Đã xảy ra lỗi</h1></div>
<div class="err-box">
<strong>Loại lỗi:</strong> {err.get('error', 'unknown')}<br>
<strong>Chi tiết:</strong> {err.get('message', '')[:300]}
</div>
<p style="margin-top:20px"><a href="/day3">← Quay về form Day 3</a></p>
</div></body></html>""", status_code=200)

    # status = completed
    r = json.loads(row["report_json"])
    s1 = r.get("section_1_founder_summary", {})
    s2 = r.get("section_2_customer_reality", {})
    s3 = r.get("section_3_market_demand", [])
    s4 = r.get("section_4_opportunity_ideas", {})
    s5 = r.get("section_5_validation_matrix", [])
    s6 = r.get("section_6_recommended_offer", {})
    s7 = r.get("section_7_one_page_offer", {})
    s8 = r.get("section_8_content_engine", {})
    s9 = r.get("section_9_action_plan", {})

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

    s2_pains_html = "".join(
        f'<tr><td>{p.get("pain", "")}</td><td><span class="score score-{min(int(p.get("severity", 0))//2, 5)}">{p.get("severity", 0)}/10</span></td></tr>'
        for p in s2.get("pains_ranked", [])
    )

    s3_html = _kv_table(s3, [
        ("keyword", "Keyword"), ("search_intent", "Intent"),
        ("trend_score", "Trend"), ("opportunity_score", "Opp Score"),
        ("data_source", "Source"),
    ])

    s5_html = _kv_table(s5, [
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
            s8_html += f"<h4>{ch_label}</h4><ol>{_ul(items)}</ol>"

    s9_html = ""
    for w in (1, 2, 3, 4):
        tasks = s9.get(f"week_{w}", [])
        if tasks:
            s9_html += f"<h4>Tuần {w}</h4><ul>{_ul(tasks)}</ul>"

    try:
        price_fmt = f"{int(s7.get('suggested_price_vnd', 0)):,}".replace(",", ".") + " VND"
    except (ValueError, TypeError):
        price_fmt = str(s7.get("suggested_price_vnd", ""))

    name_display = row["full_name"] or "Founder"

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Discovery Report · {name_display}</title>
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{css}</style></head>
<body><div class="container">

<div class="header">
  <h1>🚀 Business Discovery Report</h1>
  <p class="subtitle">Phân tích AI cho {name_display} · {row['completed_at'].strftime('%H:%M %d/%m/%Y') if row['completed_at'] else ''}</p>
</div>

<div class="section">
  <h2><span class="num">1</span>Founder Profile Summary</h2>
  <p><strong>Bạn là ai:</strong> {s1.get('who_you_are', '')}</p>
  <h3>Lợi thế độc nhất của bạn</h3>
  <ul>{_ul(s1.get('your_unique_advantage', []))}</ul>
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

<p class="meta">Generated by {row['ai_model']} · {row['generation_seconds']:.1f}s · Day 3 Challenge · BreakoutOS Discovery Engine</p>

</div></body></html>""")
