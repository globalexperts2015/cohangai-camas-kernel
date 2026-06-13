"""Coaching Landing Page — Breakout Founder 12 tuần.

GET /coaching       Long-form sales page (Anna voice + Hormozi/Brunson stack)
GET /coaching/apply Application form (Tally embed or inline)
POST /coaching/apply Save application

Per Anna 2026-06-13 post-K2 Buổi 3 webinar:
"Tôi sẽ làm việc cùng họ sau 12 tuần sẽ có hệ thống này và họ vận hành với AI."

Target: Day 3 webinar attendees who saw Discovery Engine demo + want done-with-you
implementation 1-1 với Anna trong 12 tuần.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter(tags=["coaching-landing"])


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


@router.get("/coaching", response_class=HTMLResponse)
async def coaching_landing() -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Breakout Founder · 12 tuần · Vận hành 1 mình với AI</title>
<meta name="description" content="12 tuần. 1 mình. 1 AI Team. 1 hệ thống Founder OS bạn sở hữu mãi. Cap 10 founder. Application only.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{_CSS}</style></head>
<body>

<div class="container">

<div class="section">
  <div class="pre-headline">Breakout Founder Coaching · Cap 10</div>
  <h1 class="h1">12 tuần. <em>1 mình + 1 AI Team.</em> 1 hệ thống vận hành mãi của bạn.</h1>
  <p class="sub">Không phải khoá học để xem. Không phải template để tải về. Đây là chương trình done-with-you trong 12 tuần, sau đó bạn ra trường với một hệ thống Founder OS vận hành 24/7, một đội AI thay 5 vị trí team, và một dòng doanh thu thực đang chạy.</p>
</div>

<div class="callout dark">
  <strong style="font-size:18px;display:block;margin-bottom:14px">Bạn ở đây vì:</strong>
  <p style="margin-bottom:0">Đêm qua bạn ngồi với Hằng 90 phút. Bạn vừa thấy Discovery Engine bóc tách Day 1 + Day 2 của bạn thành 9 phần báo cáo. Bạn vừa thấy AI Twin Hằng + Wizard Đóng Gói Offer + Wizard Ra Mắt Cohort. Bạn nhìn thấy hệ thống và nghĩ: <em>"Đây là cái mình cần. Nhưng mình muốn có người đi cùng để dựng, không chỉ là demo."</em></p>
</div>

<div class="section">
  <h2 class="h2">Sự thật không ai nói với bạn</h2>

  <p><strong>80% người Việt mua khoá học rồi không bao giờ xây.</strong> Không phải vì khoá tệ. Vì khoá dạy <em>cái gì</em> nhưng không có ai đứng cạnh khi bạn lóng ngóng dựng <em>cái thứ nhất</em> của riêng bạn.</p>

  <p>Bạn xem 12 video. Bạn tải 5 template. Bạn đọc lại 3 lần. Rồi bạn ngồi xuống viết offer đầu tiên, gõ được 2 dòng rồi đóng máy.</p>

  <p>Đó không phải lỗi của bạn. Đó là lỗ hổng của ngành coaching. Họ bán cho bạn <em>kiến thức</em>, không bán cho bạn <em>kết quả</em>.</p>

  <p>Hằng đã 12 năm coaching 33,000+ học viên Speakout. Hằng đã nhìn quá đủ số người mua xong không xây. Lần này Hằng không bán bạn khoá học. Lần này Hằng bán bạn <strong>kết quả sau 12 tuần</strong>.</p>
</div>

<div class="section">
  <h2 class="h2">Kết quả Hằng cam kết sau 12 tuần</h2>

  <ul>
    <li><strong>Tuần 4:</strong> Bạn có 8 file Founder OS canonical (Sứ mệnh, Tầm nhìn, Bản sắc, Nguyên tắc, Anti Vision, Why Statement, Founder Assets, Founder Story). Đây là Tầng 1 của bạn, khóa cứng.</li>
    <li><strong>Tuần 6:</strong> Bạn có 11 file Customer Intelligence canonical (Statement Một Dòng 4 vế, Opportunity Map, Empathy Map, Demand Evidence, Conversation Evidence, Buying Journey, Buying Triggers, Customer Fit Score). Đây là Tầng 2, khóa cứng.</li>
    <li><strong>Tuần 8:</strong> Bạn có 8 file Value Proposition canonical (Core Offer 4 thành phần, Pricing Strategy, Transformation Promise, Positioning Statement, Offer Stack 5 tier, Financial Model, Value Equation Hormozi 4 lever, Guarantee Strategy 5 tier). Đây là Tầng 3, khóa cứng.</li>
    <li><strong>Tuần 10:</strong> Bạn có AI COO chạy sáng 6h, Night Audit 11pm, Weekly Review Chủ Nhật 8pm. Bạn có Business Vault 4 namespace. Bạn có 5 automation flow chạy thực, không phải doc trên giấy.</li>
    <li><strong>Tuần 12:</strong> Bạn có doanh thu thực từ Offer đầu tiên. Tối thiểu 1 khách hàng đã trả tiền + đang dùng + có testimonial. Bạn ra trường với <strong>một doanh nghiệp đang chạy</strong>, không phải kế hoạch trên slide.</li>
  </ul>

  <p>Đây không phải lời hứa. Đây là <strong>roadmap có lock cứng 5 cột mốc</strong>. Mỗi cột mốc Hằng và bạn cùng đứng, không qua được không đi tiếp.</p>
</div>

<div class="section">
  <h2 class="h2">Bạn nhận gì trong 12 tuần</h2>

  <h3 class="h3">1. BreakoutOS V3.5.7 — Hệ thống Founder OS bạn sở hữu mãi</h3>
  <p>Bạn dựng 6 tầng Founder OS đến Revenue Growth (L1-L5). Không phải template chung. Đây là phiên bản canonical riêng của bạn, build từ chính Day 1 + Day 2 + Discovery Engine output bạn đã làm.</p>

  <h3 class="h3">2. AI Team thay 5 vị trí trong tuần đầu tiên</h3>
  <p>Trợ Lý AI Đóng Gói Offer (output Grand Slam Offer 4 thành phần). Trợ Lý AI Ra Mắt Cohort (output MVO 30-day plan). AI Content Engine (1 nội dung gốc thành 50 assets). AI CSKH Haiku (trả khách 24/7). AI Night Audit (log mỗi đêm 11pm). Bạn không thuê, không quản lý nhân sự. Bạn chỉ giao việc qua chat.</p>

  <h3 class="h3">3. 1-1 Mentoring 1 buổi 60 phút mỗi tuần với Hằng</h3>
  <p>Lịch cố định mỗi tuần. Hằng nhìn vault canonical của bạn trước buổi, đến buổi không cần warm up. Hằng nói thẳng cái sai, sửa tại chỗ, không kéo dài.</p>

  <h3 class="h3">4. Done-with-you tuần đầu tiên: dựng Founder OS Tầng 1 cùng bạn</h3>
  <p>Hằng ngồi với bạn trong 1 buổi sáng dài tuần đầu, cùng nhau viết 5 file Tier A. Không phải bạn tự loay hoay. Không phải đợi đến buổi 60 phút kế tiếp. Trực tiếp đẩy bạn vượt qua "khúc giấy trắng" lần đầu.</p>

  <h3 class="h3">5. Group thực hành 6 founder khác cùng cohort</h3>
  <p>Cap 10 founder, chia 2 cohort 5 người. Mỗi tuần 1 buổi group 90 phút cùng nhau dựng. Không phải tự cô đơn. Bạn nhìn 4 founder khác lóng ngóng giống bạn, bạn thấy mình không phải người ngu duy nhất.</p>

  <h3 class="h3">6. Lifetime access vault Anna's Library</h3>
  <p>Bạn access toàn bộ vault Hằng đã ingest 12 năm: 50+ source, 130+ concept, 100+ people, framework Eagle Camp, Hormozi $100M Offers, Brunson Expert Secrets, Dan Lok HIC, Goldman Wealth Series, Strategyzer. Khi nào bạn cần research bạn search vault thay vì Google.</p>

  <h3 class="h3">7. Access AI Twin Hằng 24/7 trong và sau 12 tuần</h3>
  <p>Buổi tối bạn không ngủ được, đầu bạn loay hoay câu hỏi. Bạn mở AI Twin Hằng. Bạn gõ. Trả lời có voice + tư duy Hằng từ 50 source vault. Không phải ChatGPT generic.</p>
</div>

<div class="section">
  <h2 class="h2">Bạn KHÔNG nhận gì (cũng quan trọng để biết)</h2>
  <ul class="cross">
    <li>Không phải khoá học video bạn xem 1 lần rồi quên</li>
    <li>Không phải template Notion bạn tải về rồi để đó</li>
    <li>Không có lớp 200 người gõ chat hỗn loạn không ai để ý bạn</li>
    <li>Không có "lifetime access" video mà thực ra Hằng không cập nhật sau 6 tháng</li>
    <li>Không có promise "kiếm 100 triệu/tháng tháng đầu" vì Hằng không bịa</li>
    <li>Không có upsell sau khoá để bán bạn cái thứ hai. 50 triệu là 1 lần, end.</li>
  </ul>
</div>

<div class="section">
  <h2 class="h2">Chương trình này dành cho ai</h2>

  <h3 class="h3">PHÙ HỢP nếu bạn:</h3>
  <ul>
    <li>Đang có chuyên môn cứng (giáo dục, coaching, design, marketing, finance, healthcare, F&B, sales, HR, IT, ...) tối thiểu 5 năm</li>
    <li>Muốn xây 1 dòng thu nhập thứ hai 20-100 triệu/tháng vận hành 1 mình + AI, không tăng nhân sự</li>
    <li>Đã có ít nhất 1 lần thử bán (kể cả thất bại), không phải bắt đầu hoàn toàn từ zero</li>
    <li>Sẵn sàng dành 8-10 giờ/tuần trong 12 tuần để dựng thực, không phải để "ghi chú"</li>
    <li>Sẵn sàng nghe Hằng nói thẳng cái sai và sửa, không cần ai vuốt ve</li>
  </ul>

  <h3 class="h3">KHÔNG phù hợp nếu bạn:</h3>
  <ul class="cross">
    <li>Đang tìm "công thức làm giàu nhanh 30 ngày 100 triệu"</li>
    <li>Chưa có chuyên môn rõ, đang muốn "thử xem mình thích gì"</li>
    <li>Không có 8 giờ/tuần để cam kết</li>
    <li>Muốn người khác làm thay 100% còn bạn ngồi chờ kết quả</li>
    <li>Đang ở giai đoạn tài chính bấp bênh tới mức 50 triệu là số tiền sống còn của gia đình</li>
  </ul>

  <div class="callout red">
    <p style="margin-bottom:0"><strong>Hằng cap 10 founder vì lý do thực tế:</strong> Hằng 1 mình. Hằng làm 1-1 mentoring 60 phút × 10 founder × 12 tuần = 120 buổi. Cộng group 12 buổi. Cộng done-with-you 10 buổi. Tổng ~142 buổi trong 12 tuần. Đó là giới hạn vật lý.</p>
  </div>
</div>

<div class="section">
  <h2 class="h2">Vì sao là Hằng</h2>

  <p>Hằng tên thật Đào Thị Hằng. Sinh 1985 ở Triệu Phong, Quảng Trị, gia đình chài lưới nghèo trên sông Thạch Hãn. Thủ khoa đầu vào Đại học Nông Lâm Huế.</p>

  <p>2010: học bổng 112,000 AUD Bộ Ngoại giao Úc, Thạc sĩ Phát triển bền vững Đại học Adelaide.</p>

  <p>2014 đến nay: 12 năm Speakout, 33,000+ học viên tiếng Anh đã đi qua. Đại sứ quán Úc bình chọn 2019 cựu nữ sinh đóng góp nổi bật vào sự phát triển Việt Nam.</p>

  <p>2015-2023: dựng làng Hama (Lâm Đồng) thành farm hữu cơ + trung tâm đào tạo tiếng Anh nội trú. Báo chí gọi <em>"Nữ hoàng mắm mở làng vui khoẻ"</em>.</p>

  <p>2024 đến nay: build BMCorner Gold Coast từ 0 lên 50-60K AUD/tháng trong chưa đầy 12 tháng. Build Breakout từ 0 lên ~15K AUD/tháng trong chưa đầy 1 năm.</p>

  <p><strong>6 ventures hiện tại Hằng vận hành 1 mình + AI:</strong> Speakout (giáo dục), Breakout (Shopify System), Global Experts Migration (di trú), DAHAFA (sức khoẻ nội tiết), BMCorner (F&B), Đất Gia Nghĩa (BĐS).</p>

  <p>Tác giả "Lên Núi Học Tiếng Anh" (Tuổi Trẻ giới thiệu), "IELTS Thần Chưởng", "Nấu Ngon Chưa Đủ", "How to Speak English Confidently Without Going Abroad" (Amazon).</p>

  <p>Hằng không bán bạn lý thuyết. Hằng bán bạn <strong>thứ Hằng đang vận hành thực mỗi ngày cho 6 ventures của chính Hằng</strong>.</p>
</div>

<div class="section">
  <h2 class="h2">Đầu tư của bạn</h2>

  <div class="stack">
    <div class="stack-item"><div class="label">BreakoutOS V3.5.7 dựng riêng cho bạn (6 OS, 47 canonical files)</div><div class="val">30 triệu</div></div>
    <div class="stack-item"><div class="label">AI Team 5 vị trí setup + lifetime access</div><div class="val">15 triệu</div></div>
    <div class="stack-item"><div class="label">1-1 Mentoring 60 phút × 12 tuần với Hằng</div><div class="val">36 triệu</div></div>
    <div class="stack-item"><div class="label">Done-with-you Tuần 1 (4 giờ ngồi cùng Hằng)</div><div class="val">8 triệu</div></div>
    <div class="stack-item"><div class="label">Group cohort 90 phút × 12 tuần (max 5 người/cohort)</div><div class="val">12 triệu</div></div>
    <div class="stack-item"><div class="label">Lifetime access vault Anna's Library 50+ source</div><div class="val">10 triệu</div></div>
    <div class="stack-item"><div class="label">AI Twin Hằng 24/7 (trong và sau 12 tuần)</div><div class="val">12 triệu</div></div>
    <div class="stack-item"><div class="label"><strong>Tổng giá trị</strong></div><div class="val">123 triệu</div></div>
    <div class="stack-total"><span>Đầu tư của bạn</span><span>50 triệu</span></div>
  </div>

  <div class="price-card">
    <div class="anchor">Giá trị stack: 123,000,000 VND</div>
    <div class="price">50,000,000</div>
    <div class="unit">VND · trọn gói 12 tuần · 1 lần · không upsell</div>
  </div>

  <div class="scarcity">⚠️ Cap 10 founder cho cohort khai giảng 22/06/2026. Đăng ký bằng application form.</div>
</div>

<div class="section">
  <h2 class="h2">Cam kết hoàn tiền không hỏi lý do</h2>
  <p>Sau Tuần 2, nếu bạn cảm thấy chương trình không phù hợp, bạn nhắn Hằng 1 dòng. Hằng hoàn 100% tiền trong 7 ngày, không hỏi lý do, không kéo bạn ở lại "thuyết phục".</p>
  <p>Vì sao Hằng dám: vì Hằng tin tới Tuần 2 bạn đã có Tầng 1 hoàn chỉnh, đã thấy hệ thống chạy thật, đã đo được giá trị. Nếu bạn vẫn rời, thì không có gì Hằng nói thêm thuyết phục được. Cứ về thanh thản.</p>
</div>

<a href="/coaching/apply" class="cta-btn">Nộp đơn ứng tuyển ngay →</a>
<p class="cta-sub">Hằng review trong 24 giờ. Chỉ 10 suất.</p>

<div class="section">
  <h2 class="h2">Câu hỏi thường gặp</h2>

  <details class="faq-item">
    <summary>Tôi không rành công nghệ, tôi học được không?</summary>
    <p>Được. BreakoutOS được thiết kế để dùng qua chat + form + nút bấm. Bạn không cần code, không cần biết API. Hằng cũng không phải dev, Hằng tự xây hệ thống này cho 6 ventures của Hằng.</p>
  </details>

  <details class="faq-item">
    <summary>Tôi có thể đóng tiền nhiều đợt được không?</summary>
    <p>Có. 3 đợt: đợt 1 đóng 20 triệu (trước khai giảng), đợt 2 đóng 15 triệu (sau Tuần 4), đợt 3 đóng 15 triệu (sau Tuần 8). Mỗi đợt qua Sepay, không lãi suất, không phí ẩn.</p>
  </details>

  <details class="faq-item">
    <summary>12 tuần không xây xong tôi có được kéo dài không?</summary>
    <p>Được. Sau 12 tuần nếu bạn chưa hoàn thành Tầng 5, Hằng cho bạn 4 tuần grace miễn phí. Sau đó nếu vẫn cần tiếp, bạn gia hạn 1-1 với giá 4 triệu/tháng (chỉ 50% giá thị trường vì bạn đã là founding cohort).</p>
  </details>

  <details class="faq-item">
    <summary>Tôi không có ý tưởng kinh doanh, tôi vào được không?</summary>
    <p>Tuần 1 chương trình bắt đầu bằng Day 3 Discovery Engine (cái bạn vừa thấy demo). Bạn đưa Day 1 + Day 2 của bạn vào, AI trả về 25+ ý tưởng + TOP 1 recommended. Sau đó Hằng và bạn chọn 1 cái và build. Bạn không cần "có ý tưởng" trước.</p>
  </details>

  <details class="faq-item">
    <summary>Có Founder nào đã vào cohort trước chưa? Có testimonial không?</summary>
    <p>Cohort 1 khai giảng 22/06/2026. Bạn đang đọc trang này là ứng viên đợt founding 10 founder đầu tiên. Hằng không có testimonial cũ cho chương trình này vì Hằng không bán nó trước. Đây là lần đầu Hằng public.</p>
    <p>Nhưng Hằng có testimonial 12 năm từ 33,000+ học viên Speakout, và bạn có thể tự kiểm chứng case study Mắm Thuyền Nan, Hama Village, BMCorner, Đất Gia Nghĩa trên báo Tuổi Trẻ, Dân Trí, Giáo Dục Thời Đại 2004-2025.</p>
  </details>

  <details class="faq-item">
    <summary>Hằng có chắc tôi sẽ có khách đầu tiên trong 12 tuần không?</summary>
    <p>Hằng cam kết bạn sẽ <strong>có Offer hoàn chỉnh + đã chạy traffic + đã có ít nhất 1 cuộc trò chuyện bán hàng thực với khách thật</strong>. Liệu khách đó có chốt mua hay không, phụ thuộc vào nhiều yếu tố ngoài tầm Hằng kiểm soát (giá thị trường, timing khách, kỹ năng giao tiếp của bạn).</p>
    <p>Hằng cam kết hệ thống và quy trình. Hằng không cam kết kết quả tài chính cụ thể. Đó là sự thật, không phải hứa đại.</p>
  </details>
</div>

<a href="/coaching/apply" class="cta-btn">Nộp đơn ứng tuyển ngay →</a>
<p class="cta-sub">Application form 5 phút. Hằng review trong 24 giờ. Cap 10.</p>

<div class="ps">
  <strong>P.S.</strong>
  <p>Nếu bạn đã đọc đến đây, bạn không phải người "lướt". Bạn đang nghiêm túc cân nhắc.</p>
  <p>Hằng cũng nghiêm túc cân nhắc bạn. Hằng đọc kỹ application form. Hằng KHÔNG nhận 10 người đầu tiên click. Hằng nhận 10 người PHÙ HỢP nhất.</p>
  <p>Nếu bạn được nhận, bạn sẽ đi cùng Hằng và 4 founder khác trong 12 tuần. Bạn sẽ ra trường với hệ thống vận hành, không phải kế hoạch trên giấy.</p>
  <p>Nếu bạn không được nhận đợt này, Hằng email cho bạn lý do cụ thể, không phải reject template. Và bạn được ưu tiên cohort 2 (dự kiến Q3/2026).</p>
  <p>Tối đa <strong>24 giờ kể từ thời điểm này</strong>, application form đóng. Cohort 1 khai giảng 22/06/2026 5h sáng giờ Việt Nam.</p>
</div>

<a href="/coaching/apply" class="cta-btn">Nộp đơn ngay →</a>

<div class="footer">
  Breakout Founder Coaching · BreakoutOS V3.5.7 · Cohort 1 · 22/06/2026<br>
  Đào Thị Hằng (Anna) · Global Experts · ABN 99 668 347 939<br>
  Liên hệ: support@daothihang.com · Zalo 0932093593
</div>

</div>

</body></html>""")


@router.get("/coaching/apply", response_class=HTMLResponse)
async def coaching_apply() -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Application · Breakout Founder Coaching</title>
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{_CSS}
input,textarea{{width:100%;border:1.5px solid var(--line);border-radius:10px;padding:14px;font-size:16px;font-family:inherit;line-height:1.5;margin-bottom:18px}}
textarea{{min-height:90px;resize:vertical}}
label{{display:block;font-weight:700;margin-bottom:6px;font-size:14px}}
.hint{{font-size:13px;color:var(--muted);margin-top:-14px;margin-bottom:18px}}
</style></head>
<body><div class="container">

<a href="/coaching" style="color:var(--muted);text-decoration:none;font-size:14px">← Quay lại trang chương trình</a>

<div class="section" style="margin-top:20px">
  <div class="pre-headline">Application · Cap 10</div>
  <h1 class="h1">Nộp đơn Breakout Founder Cohort 1</h1>
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
