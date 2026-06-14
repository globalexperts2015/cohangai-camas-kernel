"""Coaching Landing Page, Breakout Founder 12 tuần.

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
<title>Breakout Founder Coaching · 12 tuần · 1-1 với Hằng</title>
<meta name="description" content="12 tuần 1-1 với Hằng để dựng Founder rõ, Khách hàng rõ, Hệ thống chạy được với hỗ trợ của các trợ lý AI sử dụng canonical context bạn đã duyệt. Cap 10 founder. Application only.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{_CSS}</style></head>
<body>

<div class="container">

<div class="section">
  <div class="pre-headline">Breakout Founder Coaching · Cap 10</div>
  <h1 class="h1">12 tuần 1-1 với Hằng để dựng <em>Founder rõ, Khách hàng rõ, Hệ thống chạy được</em>.</h1>
  <p class="sub">Không phải khoá học để xem. Không phải template để tải về. Đây là chương trình done-with-you 12 tuần. Sau 12 tuần bạn ra trường với hồ sơ Founder, hồ sơ khách hàng và một hệ thống marketing/bán hàng được hỗ trợ bởi các trợ lý AI sử dụng canonical context bạn đã viết và duyệt.</p>
</div>

<a href="/coaching/apply" class="cta-btn">Nộp đơn ứng tuyển ngay →</a>
<p class="cta-sub">Hằng đọc kỹ từng đơn. Cap 10 founder cohort 1 khai giảng 22/06/2026.</p>

<div class="callout dark">
  <strong style="font-size:18px;display:block;margin-bottom:14px">Bạn ở đây vì:</strong>
  <p style="margin-bottom:0">Đêm qua bạn vừa ngồi với Hằng 90 phút buổi 3 K2. Bạn vừa thấy Discovery Engine bóc tách Day 1 + Day 2 của bạn thành báo cáo nhiều phần. Bạn vừa thấy AI Twin Hằng, Wizard Đóng Gói Offer, Wizard Ra Mắt Cohort. Bạn nghĩ: <em>"Đây là cái mình cần. Nhưng mình muốn có người đi cùng để dựng, không chỉ xem demo."</em></p>
</div>

<div class="section">
  <h2 class="h2">Sự thật giữa kiến thức và hành động</h2>

  <p>Học để biết là một chuyện. Dựng được cái đầu tiên của riêng mình là chuyện khác.</p>

  <p>Bạn xem video, tải template, đọc lại 3 lần. Rồi bạn ngồi xuống viết offer đầu tiên, gõ được 2 dòng rồi đóng máy. Không phải lỗi của bạn. Đó là khoảng cách giữa kiến thức và hành động khi không có người đứng cạnh sửa tại chỗ.</p>

  <p>Hằng đã 12 năm xây Speakout. Cộng đồng hơn 33,000 contact, khoảng 5,000 học viên đã trả phí. Lần này Hằng không bán bạn khoá học để xem. Hằng bán thời gian 1-1, quy trình và công cụ để bạn build hệ thống của chính bạn trong 12 tuần.</p>
</div>

<div class="callout red">
  <p style="margin-bottom:0;font-size:18px"><strong>Khác biệt của BreakoutOS so với khoá kinh doanh thông thường:</strong></p>
  <p style="margin-top:10px;margin-bottom:0;font-size:17px">Các khoá khác dạy bạn marketing, content, bán hàng, chạy quảng cáo.</p>
  <p style="margin-top:6px;margin-bottom:0;font-size:17px">BreakoutOS giúp bạn dựng <strong>3 tài sản thật</strong> bằng chính dữ liệu của bạn: Founder rõ, Khách hàng rõ, Hệ thống có thể chạy. Các trợ lý AI làm việc trên canonical context mà bạn đã viết và duyệt để hỗ trợ bạn ở từng bước.</p>
</div>

<div class="section">
  <h2 class="h2">3 đầu ra cốt lõi sau 12 tuần</h2>
  <p>Đây là <strong>đầu ra học tập và tài sản kinh doanh</strong> mà chương trình cam kết, đồng thời là tiêu chuẩn áp dụng chính sách hoàn tiền.</p>

  <h3 class="h3">1. Founder rõ, bạn biết mình bán gì cho ai bằng năng lực gì</h3>
  <ul>
    <li><strong>Outcome:</strong> Statement Một Dòng có WHO + Current Pain + Desired Identity + Vehicle, cùng anti-vision và nguyên tắc quyết định</li>
    <li><strong>Evidence:</strong> bộ canonical files Tầng 1 (Founder identity, assets, story, anti-vision, mission, decision principles) do bạn viết và Hằng review</li>
    <li><strong>Deliverable:</strong> vượt Gate 1 trong BreakoutOS với hồ sơ Founder bạn ký duyệt và lưu trong vault của bạn</li>
  </ul>

  <h3 class="h3">2. Khách hàng rõ, hồ sơ khách dựa trên dữ liệu thật, không đoán</h3>
  <ul>
    <li><strong>Outcome:</strong> Customer Profile + Pain/Gain map + Buying Journey + Buying Triggers</li>
    <li><strong>Evidence:</strong> bộ canonical files Tầng 2 dựa trên survey, conversation và buying signal bạn thu thập trong cohort</li>
    <li><strong>Deliverable:</strong> vượt Gate 2A Soft và Gate 2B Hard sau khi Value Proposition được validate</li>
  </ul>

  <h3 class="h3">3. Hệ thống chạy được, có hỗ trợ từ các trợ lý AI</h3>
  <ul>
    <li><strong>Outcome:</strong> Core Offer + Value Equation + Sales Process + Ascension + Retention, có review định kỳ trên dữ liệu của bạn</li>
    <li><strong>Evidence:</strong> bộ canonical files Tầng 3 đến Tầng 5 do bạn duyệt từng file trước khi đưa vào hệ thống</li>
    <li><strong>Deliverable:</strong> có ít nhất 1 cuộc trò chuyện bán hàng thực với khách thật trước khi kết thúc 12 tuần</li>
  </ul>
</div>

<div class="callout">
  <p style="margin-bottom:10px;font-weight:700">Các trợ lý AI trong BreakoutOS</p>
  <p style="margin-bottom:8px">Không phải fine-tune model riêng. Là pipeline AI sử dụng context retrieval trên canonical files mà bạn đã viết và duyệt. Các trợ lý AI hỗ trợ bạn ở những nhóm việc như: hỏi đáp theo góc nhìn của Hằng, đóng gói offer, ra mắt cohort, hỗ trợ review định kỳ, hỗ trợ soạn nội dung marketing dùng canonical context của bạn.</p>
  <p style="margin-top:10px;margin-bottom:0">Bạn duyệt từng canonical file trước khi đưa vào hệ thống. Trợ lý AI sử dụng canonical context đã được bạn duyệt để hỗ trợ, không thay bạn quyết định. Danh sách trợ lý cụ thể cho cohort 1 sẽ được Hằng xác nhận khi onboarding.</p>
</div>

<a href="/coaching/apply" class="cta-btn">Nộp đơn ứng tuyển ngay →</a>
<p class="cta-sub">Cap 10 founder. Hằng phản hồi trong 24 giờ.</p>

<div class="section">
  <h2 class="h2">Cụ thể bạn nhận gì trong 12 tuần</h2>

  <h3 class="h3">1-1 Mentoring 60 phút × 12 tuần với Hằng</h3>
  <p>Lịch cố định mỗi tuần. Hằng đọc vault canonical của bạn trước buổi, đến buổi không cần warm up. Hằng nói thẳng chỗ sai, sửa tại chỗ.</p>

  <h3 class="h3">Done-with-you Tuần 1, dựng Tầng 1 cùng bạn</h3>
  <p>Hằng ngồi với bạn 4 giờ tuần đầu, cùng viết 5 file Tier A. Trực tiếp đẩy bạn vượt qua "khúc giấy trắng" lần đầu.</p>

  <h3 class="h3">Group cohort 90 phút × 12 tuần (tối đa 5 người/cohort)</h3>
  <p>Bạn nhìn các founder khác đi qua cùng giai đoạn. Bạn không phải người duy nhất trong hành trình này.</p>

  <h3 class="h3">Truy cập vault Anna's Library trong 12 tuần</h3>
  <p>50+ source, 130+ concept, framework Eagle Camp, Hormozi $100M Offers, Brunson Expert Secrets, Dan Lok HIC, Strategyzer. Truy cập trong 12 tuần active delivery của cohort.</p>

  <h3 class="h3">Truy cập các trợ lý AI và AI Twin Hằng trong 12 tuần</h3>
  <p>Sử dụng trong 12 tuần active delivery của cohort. Trả lời dựa trên canonical context bạn đã duyệt, không phải ChatGPT generic.</p>

  <h3 class="h3">Quyền giữ canonical files bạn build</h3>
  <p>Toàn bộ canonical files do bạn viết và duyệt trong 12 tuần là tài sản của bạn. Bạn export ra Markdown + JSON và lưu trong vault riêng của bạn để dùng lại sau cohort.</p>
</div>

<div class="section">
  <h2 class="h2">Bạn KHÔNG nhận gì (cũng quan trọng để biết)</h2>
  <ul class="cross">
    <li>Không phải khoá học video bạn xem 1 lần rồi quên</li>
    <li>Không phải template Notion bạn tải về rồi để đó</li>
    <li>Không có lớp 200 người gõ chat hỗn loạn không ai để ý bạn</li>
    <li>Không có promise "kiếm 100 triệu/tháng tháng đầu" vì Hằng không bịa</li>
    <li>Không cam kết doanh thu, lợi nhuận, số đơn hay số khách hàng cụ thể</li>
  </ul>
</div>

<div class="section">
  <h2 class="h2">Chương trình này dành cho ai</h2>

  <h3 class="h3">PHÙ HỢP nếu bạn:</h3>
  <ul>
    <li>Đang có chuyên môn cứng (giáo dục, coaching, design, marketing, finance, healthcare, F&B, sales, HR, IT, ...) tối thiểu 5 năm</li>
    <li>Đã có ít nhất 1 lần thử bán (kể cả thất bại), không phải bắt đầu hoàn toàn từ zero</li>
    <li>Muốn xây 1 dòng thu nhập thứ hai vận hành 1 mình cùng AI, không tăng nhân sự</li>
    <li>Sẵn sàng dành 8-10 giờ/tuần trong 12 tuần để dựng thật, không phải để "ghi chú"</li>
    <li>Sẵn sàng nghe Hằng nói thẳng chỗ sai và sửa, không cần ai vuốt ve</li>
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
    <p style="margin-bottom:0"><strong>Cap 10 founder vì lý do thực tế:</strong> Hằng làm 1 mình. 10 founder × 12 tuần × 1-1 60 phút = 120 buổi. Cộng group 12 buổi. Cộng done-with-you 10 buổi. Tổng khoảng 142 buổi trong 12 tuần. Đó là giới hạn vật lý.</p>
  </div>
</div>

<div class="section">
  <h2 class="h2">Vì sao là Hằng</h2>

  <p>Hằng tên thật Đào Thị Hằng. Sinh 1985 ở Triệu Phong, Quảng Trị, gia đình chài lưới trên sông Thạch Hãn. Thủ khoa đầu vào Đại học Nông Lâm Huế.</p>

  <p>2010: học bổng 112,000 AUD Bộ Ngoại giao Úc, Thạc sĩ Phát triển bền vững Đại học Adelaide.</p>

  <p>2014 đến nay: 12 năm xây Speakout. Cộng đồng hơn 33,000 contact, khoảng 5,000 học viên đã trả phí.</p>

  <p>2015-2023: dựng làng Hama (Lâm Đồng) thành farm hữu cơ và trung tâm đào tạo tiếng Anh nội trú.</p>

  <p>2024 đến nay: build BMCorner tại Úc đạt 50,000-60,000 AUD/tháng. Build Breakout đạt khoảng 15,000 AUD/tháng.</p>

  <p><strong>6 ventures hiện tại Hằng vận hành 1 mình cùng AI:</strong> Speakout (giáo dục), Breakout (Shopify System), Global Experts Migration (di trú), DAHAFA (sức khoẻ nội tiết), BMCorner (F&B), Đất Gia Nghĩa (BĐS).</p>

  <p>Tác giả: "Lên Núi Học Tiếng Anh" (Tuổi Trẻ giới thiệu), "IELTS Thần Chưởng", "Nấu Ngon Chưa Đủ", "How to Speak English Confidently Without Going Abroad" (Amazon).</p>

  <p>Hằng không bán bạn lý thuyết. Hằng bán bạn <strong>thứ Hằng đang vận hành thật mỗi ngày cho 6 ventures của chính Hằng</strong>.</p>
</div>

<div class="section">
  <h2 class="h2">Đầu tư của bạn</h2>

  <p>Trọn gói 12 tuần coaching, bao gồm:</p>
  <ul>
    <li>1-1 Mentoring 60 phút × 12 tuần với Hằng</li>
    <li>Done-with-you Tuần 1 (4 giờ ngồi cùng Hằng dựng Tầng 1)</li>
    <li>Group cohort 90 phút × 12 tuần (tối đa 5 người/cohort)</li>
    <li>Truy cập BreakoutOS V3.5.7 trong 12 tuần active delivery</li>
    <li>Truy cập các trợ lý AI và AI Twin Hằng trong 12 tuần active delivery</li>
    <li>Truy cập vault Anna's Library trong 12 tuần active delivery</li>
    <li>Quyền giữ canonical files bạn build (export Markdown + JSON)</li>
  </ul>

  <div class="price-card">
    <div class="price">50,000,000</div>
    <div class="unit">VND · trọn gói 12 tuần · đóng 1 lần hoặc 3 đợt</div>
  </div>

  <div class="scarcity">Cap 10 founder cho cohort khai giảng 22/06/2026. Đăng ký bằng application form.</div>
</div>

<div class="section">
  <h2 class="h2">Chính sách hoàn tiền</h2>
  <p>Thời hạn yêu cầu hoàn tiền là <strong>14 ngày</strong> kể từ ngày bạn được cấp quyền truy cập chương trình.</p>
  <p>Nếu trong thời hạn này bạn đã hoàn thành phần nội dung và bài thực hành bắt buộc, áp dụng đúng hướng dẫn, tham gia một lần hỗ trợ sửa nhưng nội dung vẫn không giúp bạn tạo được đầu ra cốt lõi đã công bố ở trên, Hằng hoàn 100% học phí.</p>
  <p>Chính sách này đánh giá hiệu quả của nội dung và phương pháp được dạy. Chính sách <strong>không đảm bảo doanh thu, lợi nhuận, số đơn hoặc số khách hàng</strong>.</p>
  <p>Điều kiện hoàn tiền:</p>
  <ul>
    <li>Hoàn thành nội dung bắt buộc và bài thực hành bắt buộc trong thời hạn 14 ngày kể từ ngày được cấp quyền truy cập</li>
    <li>Áp dụng đúng hướng dẫn vào trường hợp thực tế của bạn và gửi bằng chứng thực hiện</li>
    <li>Nêu rõ đầu ra cốt lõi chưa đạt được, kèm bài làm, ảnh chụp hoặc dữ liệu liên quan</li>
    <li>Cho Breakout một lần hỗ trợ sửa hoặc hướng dẫn lại. Nếu sau lần hỗ trợ này nội dung vẫn không giúp bạn tạo được đầu ra cốt lõi, Hằng hoàn 100% học phí</li>
  </ul>
  <p>Gửi yêu cầu qua email <strong>support@daothihang.com</strong> với tiêu đề "REFUND Coaching [Họ tên]". Hằng phản hồi trong 3 ngày làm việc. Khi đủ điều kiện, khoản hoàn được xử lý qua kênh thanh toán gốc trong 7 ngày tiếp theo.</p>
  <p>Chính sách này là cam kết tự nguyện bổ sung, không giới hạn quyền bắt buộc của khách hàng theo luật bảo vệ người tiêu dùng hiện hành.</p>
</div>

<a href="/coaching/apply" class="cta-btn">Nộp đơn ứng tuyển ngay →</a>
<p class="cta-sub">Hằng review trong 24 giờ. Chỉ 10 suất.</p>

<div class="section">
  <h2 class="h2">Câu hỏi thường gặp</h2>

  <details class="faq-item">
    <summary>Tôi không rành công nghệ, tôi học được không?</summary>
    <p>Được. BreakoutOS dùng qua chat, form và nút bấm. Bạn không cần code, không cần biết API. Hằng cũng không phải dev, Hằng dựng hệ thống này cho 6 ventures của Hằng.</p>
  </details>

  <details class="faq-item">
    <summary>Tôi có thể đóng tiền nhiều đợt được không?</summary>
    <p>Có. 3 đợt qua Sepay: đợt 1 đóng 20 triệu (trước khai giảng), đợt 2 đóng 15 triệu (sau Tuần 4), đợt 3 đóng 15 triệu (sau Tuần 8). Không lãi suất, không phí ẩn.</p>
  </details>

  <details class="faq-item">
    <summary>12 tuần không xây xong tôi có được kéo dài không?</summary>
    <p>Phạm vi cam kết của chương trình là 12 tuần active delivery. Hết 12 tuần Hằng không tự động gia hạn. Các phương án hỗ trợ thêm sau cohort, nếu có, sẽ được Hằng thông báo riêng cho từng học viên dựa trên tiến độ thực tế.</p>
    <p>Trong mọi trường hợp, canonical files bạn đã build trong 12 tuần là tài sản của bạn (export Markdown + JSON), bạn tiếp tục dùng được sau khi cohort kết thúc.</p>
  </details>

  <details class="faq-item">
    <summary>Tôi không có ý tưởng kinh doanh, tôi vào được không?</summary>
    <p>Tuần 1 chương trình bắt đầu bằng Day 3 Discovery Engine (cái bạn vừa thấy demo). Bạn đưa Day 1 + Day 2 của bạn vào, AI trả về danh sách ý tưởng kèm gợi ý ưu tiên. Sau đó Hằng và bạn chọn 1 ý tưởng và build. Bạn không cần "có ý tưởng" trước.</p>
  </details>

  <details class="faq-item">
    <summary>Có Founder nào đã vào cohort trước chưa? Có testimonial không?</summary>
    <p>Cohort 1 khai giảng 22/06/2026 là cohort đầu tiên của Breakout Founder Coaching. Bạn đang đọc trang này là ứng viên đợt founding 10 founder đầu tiên. Hằng <strong>không có testimonial</strong> cho chương trình Coaching này vì đây là lần đầu Hằng public.</p>
    <p>Hằng không mượn testimonial từ Speakout làm proof cho kết quả BreakoutOS vì hai chương trình khác đối tượng, khác đầu ra. Bạn đánh giá Hằng qua phương pháp được dạy, qua thứ Hằng đang vận hành thật cho 6 ventures, và qua chính sách hoàn tiền theo đầu ra cốt lõi ở trên.</p>
  </details>

  <details class="faq-item">
    <summary>Hằng có chắc tôi sẽ có khách đầu tiên trong 12 tuần không?</summary>
    <p>Hằng cam kết bạn sẽ <strong>có Offer hoàn chỉnh, đã chạy traffic và đã có ít nhất 1 cuộc trò chuyện bán hàng thực với khách thật</strong>, nếu bạn thực hiện đúng tiến độ chương trình.</p>
    <p>Khách đó có chốt mua hay không phụ thuộc nhiều yếu tố ngoài tầm Hằng kiểm soát (giá thị trường, timing khách, kỹ năng giao tiếp của bạn). Hằng cam kết hệ thống, quy trình và đầu ra học tập. Hằng không cam kết doanh thu hay số khách hàng cụ thể.</p>
  </details>
</div>

<a href="/coaching/apply" class="cta-btn">Nộp đơn ứng tuyển ngay →</a>
<p class="cta-sub">Application form 5 phút. Hằng review trong 24 giờ. Cap 10.</p>

<div class="ps">
  <strong>P.S.</strong>
  <p>Nếu bạn đã đọc đến đây, bạn không phải người "lướt". Bạn đang nghiêm túc cân nhắc.</p>
  <p>Hằng cũng nghiêm túc cân nhắc bạn. Hằng đọc kỹ application form và KHÔNG nhận 10 người đầu tiên click. Hằng nhận 10 người PHÙ HỢP nhất.</p>
  <p>Nếu bạn được nhận, bạn sẽ đi cùng Hằng và các founder khác trong 12 tuần và ra trường với hệ thống vận hành, không phải kế hoạch trên giấy.</p>
  <p>Nếu bạn không được nhận đợt này, Hằng email cho bạn lý do cụ thể, không phải reject template. Và bạn được ưu tiên cohort kế tiếp.</p>
  <p>Cohort 1 khai giảng <strong>22/06/2026</strong>. Form đóng khi đủ 10 founder phù hợp.</p>
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
