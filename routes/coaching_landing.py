"""Mentoring Landing Page, Breakout Founder 12 tuần.

GET /mentoring       Canonical long-form sales page
GET /coaching        Backward-compatible route
GET /mentoring/apply Canonical application form
GET /coaching/apply  Backward-compatible route

Per Anna 2026-06-13 post-K2 Buổi 3 webinar:
"Tôi sẽ làm việc cùng họ sau 12 tuần sẽ có hệ thống này và họ vận hành với AI."

Target: Day 3 webinar attendees who saw Discovery Engine demo + want done-with-you
implementation 1-1 với Anna trong 12 tuần.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter(tags=["mentoring-landing"])


_CSS = """
:root{--red:#d63031;--red-deep:#b71c1c;--ink:#0a0a0a;--paper:#fafaf7;--line:#e5dfd0;--muted:#5a5453;--ok:#27ae60}
*{box-sizing:border-box;margin:0;padding:0;font-family:'Be Vietnam Pro',system-ui}
body{background:var(--paper);color:var(--ink);font-size:17px;line-height:1.75}
.container{max-width:780px;margin:0 auto;padding:30px 20px}
.section{margin-bottom:40px}

.pre-headline{display:inline-block;background:rgba(214,48,49,0.12);color:var(--red);padding:8px 18px;border-radius:999px;font-size:13px;letter-spacing:1.5px;text-transform:uppercase;font-weight:800;margin-bottom:16px}
.h1{font-size:42px;font-weight:800;line-height:1.2;margin-bottom:14px;color:var(--ink)}
.h1 em{color:var(--red);font-style:normal}
.sub{font-size:20px;color:var(--muted);margin-bottom:24px;line-height:1.6}

.h2{font-size:30px;font-weight:800;line-height:1.25;margin:36px 0 14px;color:var(--ink)}
.h3{font-size:22px;font-weight:700;line-height:1.3;margin:24px 0 10px;color:var(--ink)}

p{margin-bottom:16px}
strong{font-weight:700;color:var(--ink)}
em{font-style:italic;color:var(--red)}

ul{padding-left:0;list-style:none;margin-bottom:18px}
ul li{padding:10px 0 10px 36px;position:relative;border-bottom:1px solid var(--line)}
ul li:before{content:"✓";position:absolute;left:0;top:10px;width:24px;height:24px;background:var(--ok);color:#fff;border-radius:50%;text-align:center;line-height:24px;font-weight:800;font-size:14px}
ul.cross li:before{content:"✗";background:#999}

.callout{background:#fff;border:1.5px solid var(--line);border-radius:14px;padding:24px 28px;margin:24px 0}
.callout.red{border-color:var(--red);background:#fff5f5}
.callout.dark{background:linear-gradient(135deg,#0a0a0a,#2d2d2d);color:#fff;border:none}
.callout.dark strong{color:#fff}

blockquote{border-left:4px solid var(--red);padding:16px 24px;margin:24px 0;font-style:italic;color:var(--muted);background:#fff;border-radius:0 12px 12px 0}

.cta-btn{display:block;width:100%;text-align:center;background:var(--red);color:#fff;padding:24px;border-radius:14px;text-decoration:none;font-weight:800;font-size:22px;margin:30px 0;box-shadow:0 8px 28px rgba(214,48,49,0.4);transition:all 0.2s}
.cta-btn:hover{background:var(--red-deep);transform:translateY(-2px);box-shadow:0 12px 32px rgba(214,48,49,0.5)}
.cta-sub{text-align:center;font-size:14px;color:var(--muted);margin-top:-22px;margin-bottom:28px}

.stack{background:#fff;border:2px solid var(--ink);border-radius:14px;overflow:hidden;margin:24px 0}
.stack-item{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:14px}
.stack-item:last-child{border-bottom:none;background:#fff5f5}
.stack-item .label{font-weight:600;flex:1}
.stack-item .val{font-weight:800;color:var(--red);white-space:nowrap}
.stack-total{background:var(--ink);color:#fff;padding:20px 24px;display:flex;justify-content:space-between;font-size:20px;font-weight:800}

.price-card{background:linear-gradient(135deg,#0a0a0a,#2d2d2d);color:#fff;border-radius:18px;padding:36px;text-align:center;margin:30px 0;box-shadow:0 12px 36px rgba(0,0,0,0.25)}
.price-card .anchor{font-size:18px;text-decoration:line-through;color:#888;margin-bottom:6px}
.price-card .price{font-size:54px;font-weight:800;color:#fff;line-height:1}
.price-card .unit{font-size:16px;color:#bbb;margin-top:4px}

.scarcity{background:#fff3cd;border:1.5px dashed #f4a261;border-radius:10px;padding:14px 20px;text-align:center;font-weight:700;color:#856404;margin:18px 0}

.faq-item{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px 22px;margin-bottom:10px}
.faq-item summary{cursor:pointer;font-weight:700;font-size:17px;list-style:none}
.faq-item summary::-webkit-details-marker{display:none}
.faq-item summary:before{content:"+";display:inline-block;width:24px;color:var(--red);font-size:20px}
.faq-item[open] summary:before{content:"-"}
.faq-item p{margin-top:14px;color:var(--muted)}

.ps{background:#fff;border-left:5px solid var(--red);border-radius:0 12px 12px 0;padding:24px 28px;margin:30px 0}
.ps strong{display:block;margin-bottom:10px;font-size:18px;color:var(--red)}

.footer{text-align:center;color:var(--muted);font-size:13px;margin-top:60px;padding-top:20px;border-top:1px solid var(--line)}
"""


@router.get("/coaching", response_class=HTMLResponse, include_in_schema=False)
@router.get("/mentoring", response_class=HTMLResponse)
async def coaching_landing() -> HTMLResponse:
    from pathlib import Path as _P
    _f = _P(__file__).resolve().parent.parent / "static" / "coaching-landing.html"
    return HTMLResponse(_f.read_text(encoding="utf-8"))


@router.get("/coaching/apply", response_class=HTMLResponse, include_in_schema=False)
@router.get("/mentoring/apply", response_class=HTMLResponse)
async def coaching_apply() -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Application · Breakout Founder Mentoring</title>
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{_CSS}
input,textarea{{width:100%;border:1.5px solid var(--line);border-radius:10px;padding:14px;font-size:16px;font-family:inherit;line-height:1.5;margin-bottom:18px}}
textarea{{min-height:90px;resize:vertical}}
label{{display:block;font-weight:700;margin-bottom:6px;font-size:14px}}
.hint{{font-size:13px;color:var(--muted);margin-top:-14px;margin-bottom:18px}}
</style></head>
<body><div class="container">

<a href="/mentoring" style="color:var(--muted);text-decoration:none;font-size:14px">← Quay lại trang chương trình</a>

<div class="section" style="margin-top:20px">
  <div class="pre-headline">Application · Cap 10</div>
  <h1 class="h1">Nộp đơn Breakout Founder Mentoring Cohort 1</h1>
  <p class="sub">Hằng đọc kỹ từng đơn. Trả lời thẳng thắn, không cần đẹp. Hằng quan tâm bạn THẬT là ai và bạn muốn gì THẬT.</p>
</div>

<form method="post" action="/coaching/apply" id="apply-form">

  <label>Tên đầy đủ</label>
  <input type="text" name="full_name" required>

  <label>Email</label>
  <input type="email" name="email" required>

  <label>Số điện thoại (Zalo)</label>
  <input type="tel" name="phone" required>

  <label>Bạn đang sống ở đâu?</label>
  <input type="text" name="location" placeholder="Hà Nội / Sài Gòn / Đà Nẵng / Sydney / ..." required>

  <label>Chuyên môn cứng của bạn là gì? (5+ năm)</label>
  <textarea name="expertise" required placeholder="VD: 8 năm coach tiếng Anh IELTS, sở hữu trung tâm 50 học viên"></textarea>

  <label>Bạn đã thử bán cái gì chưa? Kết quả thế nào?</label>
  <textarea name="prior_attempts" required placeholder="Kể thật, kể cả thất bại. Hằng không judge."></textarea>

  <label>Bạn muốn build cái gì trong 12 tuần với Hằng?</label>
  <textarea name="goal" required placeholder="Cụ thể nhất có thể. Nếu chưa rõ, viết 'chưa rõ, muốn làm rõ trong 12 tuần'."></textarea>
  <p class="hint">Hằng OK với câu trả lời "chưa rõ". Hằng không OK với câu trả lời "tuỳ Hằng".</p>

  <label>8-10 giờ/tuần trong 12 tuần. Bạn cam kết được không?</label>
  <textarea name="commitment" required placeholder="Trả lời Có/Không + giải thích."></textarea>

  <label>50 triệu VND. Bạn có sẵn sàng đầu tư không?</label>
  <textarea name="investment_ready" required placeholder="Có / Cần thời gian / Cần chia đợt"></textarea>

  <label>Bạn biết đến Hằng từ đâu? (optional)</label>
  <input type="text" name="source" placeholder="K2 Webinar / FB / Bạn giới thiệu / ...">

  <label>Có gì muốn nói thêm với Hằng không? (optional)</label>
  <textarea name="notes"></textarea>

  <button type="submit" class="cta-btn" style="border:none;cursor:pointer;font-family:inherit">Gửi application →</button>
</form>

<p style="text-align:center;color:var(--muted);font-size:14px;margin-top:20px">Hằng đọc đơn của bạn trong 24 giờ. Trả lời qua email và Zalo.</p>

</div></body></html>""")
