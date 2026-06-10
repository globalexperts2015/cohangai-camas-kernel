# Upsell Map, value ladder front-end → core → backend

Upsell = đưa khách hiện tại lên gói cao hơn. Đây là lever LTV mạnh nhất. Khách đã trust bạn → conversion lên gói cao 30-50%, gấp 5-10 lần cold traffic.

## Nguyên tắc gradient giá

Front-end : Core : Backend = 1 : 5-10 : 20-50

Ví dụ Breakout/Cohangai:
- Front-end (199k-3tr): khoá nền tự học
- Core (15tr): cohort + community + delivery có structure
- Backend (50tr+): 1-on-1 coaching 6 tháng + done-with-you

Ví dụ Speakout:
- Front-end (199k): webinar trial / workbook
- Core (6tr): khoá 10 tuần group
- Backend (30tr): mentoring 1-on-1 6 tháng

KHÔNG gap quá lớn (1:100) → khách không leo. KHÔNG quá gần (1:2) → backend không justify premium.

## Cấu trúc 3 tier ladder

### Front-end (Trip-wire / Foundation)
- Mục đích: convert cold lead → customer (first purchase)
- Price: 199k-3tr VND
- Margin thấp (40-60%) OK, focus convert
- Delivery: self-service, asset digital
- Time-to-value: 7-30 ngày
- Role trong ladder: prove giá trị, qualify cho upsell

### Core (Main offer)
- Mục đích: deliver transformation chính
- Price: 6-15tr VND
- Margin cao (70-85%)
- Delivery: cohort + group call + community
- Time-to-value: 60-90 ngày
- Role: nơi 70-80% revenue đến

### Backend (Ascension)
- Mục đích: serve top 5-10% khách willingness-to-pay cao nhất
- Price: 30-100tr VND
- Margin rất cao (85-95%)
- Delivery: 1-on-1 coaching + done-with-you + retreat
- Time-to-value: 90-180 ngày
- Role: bứt phá doanh thu KHÔNG cần thêm volume khách

## Transition triggers (khi nào pitch upsell)

### Front-end → Core
- Trigger 1: Completion >=70% modules + NPS >=7 (Day 30)
- Trigger 2: 1 win cụ thể shared (testimonial collected Day 30-45)
- Trigger 3: User active engagement >=5 lần/tuần trong cộng đồng

Pitch window: Day 30-60 sau front-end. Sau Day 90 retention drop, conversion thấp.

### Core → Backend
- Trigger 1: Đã complete >=2 cycle core (1 cohort + 1 follow-on)
- Trigger 2: Revenue student tăng X3+ since enrolling (proof transformation)
- Trigger 3: Student tự inquire about 1-on-1 (qualified intent)

Pitch window: Day 60-120 vào core. Backend cần investment time + tiền lớn.

## Bundle vs Sequential

### Bundle (cross-sell ngay lúc front-end checkout)
- Pros: ARPU cao ngay, không cần email sequence dài
- Cons: choice paralysis, conversion front-end drop 20-30%
- Khi dùng: offer phụ trợ (template pack, workbook, 1 month membership free trial)

### Sequential (upsell sau 30-90 ngày)
- Pros: trust đã build, conversion 30-50%
- Cons: cần GHL automation + email sequence dài
- Khi dùng: core + backend (major commitment)

Rule of thumb: dưới 50% giá front-end → bundle OK. Trên 200% giá front-end → sequential bắt buộc.

## Timing window (Day 30 sweet spot)

Day 30 là sweet spot cho upsell front-end → core vì:
- Khách đã có result đầu tiên (proof trust)
- Chưa có chance build resistance hoặc forget
- Còn momentum tốt
- Bonus: campaign Day 30 timing trùng next cohort intake → fill slot

Sequence:
- Day 28: Email "Bạn vừa hoàn thành module 1, đây là next step"
- Day 30: Call 15 phút (Coaching Qualify GHL calendar `qx869yEKHc3zUyAIhIcU`)
- Day 32: Email follow-up + offer link 48h flash
- Day 34: Close cart

Conversion expectation: 25-40% qualify call → enrol core.

## Repeat purchase strategy

Cùng khách mua nhiều lần (KHÔNG luôn upgrade tier):
- Cohort re-enrol (cùng tier, nội dung mới): 15-25% khách quay
- Add-on workshop (1 ngày 1.5tr): 30-40% khách mua
- Annual mastermind (30tr/năm): 5-10% khách top

Mục tiêu: 2-3 transaction/khách/năm trung bình. LTV gấp 2-3x first purchase.

## Automation cần setup

GHL workflow trigger conditions:
1. `tag:front_end_completed_70pct` + `tag:nps_7_plus` → email sequence core upsell
2. `tag:core_cohort_completed` + `revenue_increased_3x` → email sequence backend
3. `tag:backend_completed` → email sequence annual mastermind invite
4. `last_purchase_90d_ago` → re-engagement repeat sequence

## Pricing test

Nếu chưa biết price backend: start với 2 ghế pilot beta giá 50% off (vd 25tr thay 50tr) cho 2 khách hottest, gather case study, sau đó raise price + open public.

## Anti-pattern

- Upsell quá sớm (Day 7 chưa có result) → mất trust, refund
- Upsell quá muộn (Day 120+) → khách đã rời mental energy
- Gradient giá quá gần (front 6tr, core 9tr) → không lý do leo
- Backend không có scarcity (vô hạn slot 1-on-1) → khách không quyết
