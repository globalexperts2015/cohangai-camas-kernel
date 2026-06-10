# Membership Continuity, mô hình giữ khách định kỳ

Membership = subscription hàng tháng cho ongoing support. Khác one-shot course (bán xong là xong). Membership tạo MRR (Monthly Recurring Revenue), bền hơn doanh thu 1 lần.

## Khi nào Membership phù hợp

- Audience cần ongoing support, KHÔNG xong 1 khoá là hết nhu cầu
- Nội dung có thể drop monthly (case study mới, market change, Q&A trực tiếp)
- Bạn đã có >=30 khách front-end (audience đủ lớn để chia tier)
- Bạn cam kết deliver content monthly liên tục (đừng start nếu không sustain)

## Khi nào KHÔNG nên Membership

- Audience hardcore B2C bình dân (giá thấp + churn cao)
- Bạn solo + đã >70h/tuần (membership thêm gánh delivery)
- Offer 1-shot transform mạnh hơn (vd "thi đỗ visa" thì khách xong là rời)

## Cấu trúc 3 tier mặc định

### Tier 1: Community Member (199k VND/tháng)
- Truy cập Discord/Skool community
- 1 group call/tháng 60 phút
- Library replay 100% nội dung cũ
- Target: học viên cũ muốn quay lại học thêm

### Tier 2: Active Member (490k VND/tháng)
- Toàn bộ Tier 1
- 2 group call/tháng (1 Q&A + 1 case study breakdown)
- Monthly Playbook PDF mới
- Direct message access trong office hours (Thứ 3 + Thứ 5)
- Target: founder serious đang implement

### Tier 3: Inner Circle (1.9tr VND/tháng)
- Toàn bộ Tier 2
- 1 personal call 30 phút/tháng
- Direct line WhatsApp/Zalo trong office hours
- Quarterly retreat (virtual hoặc in-person)
- Target: 5-10 khách top, willingness to pay cao nhất

## Pricing math (cần BEAT front-end LTV)

Front-end course 6tr VND, LTV ~6tr (1 lần mua).

Membership 490k/tháng, churn 8%/tháng → LTV ~6.1tr (12.5 tháng x 490k).

Membership Inner Circle 1.9tr/tháng, churn 5%/tháng → LTV ~38tr (20 tháng x 1.9tr).

LTV membership > front-end → upgrade path đáng dõi.

## Monthly deliverables (bắt buộc deliver consistent)

Mỗi tháng tối thiểu:
1. 1 live group call 60-90 phút (record replay)
2. 1 content drop (playbook PDF / video module / template pack)
3. Community engagement (post 2-3 lần/tuần seed discussion)
4. Office hours (2 buổi/tuần, mỗi buổi 60 phút trong Discord voice/text)

## Churn prevention touchpoint

- Day 7 sau enrol: Welcome call/video personal "Mục tiêu 30 ngày của bạn là gì?"
- Day 30: Check-in qua DM "Bạn đang stuck ở đâu?"
- Day 60: Highlight 1 win của member khác để inspire
- Day 90: Re-onboard, upgrade pitch lên tier cao hơn nếu phù hợp

Churn lý do số 1: member không thấy progress sau 60 ngày. Touchpoint Day 30 + 60 catch trước khi cancel.

## Cancel flow

- Cancel button có, KHÔNG hide (TOS yêu cầu)
- Trước khi xác nhận cancel: 1 form 3 câu (Lý do? Đề xuất cải thiện? Quay lại nếu có gì?)
- Offer pause 30 ngày thay vì cancel (giữ ~20% saver)

## Tech stack

- Stripe Recurring + GHL Membership tag để gate access
- Skool.com hoặc Discord cho community (Skool có gate built-in, dễ hơn)
- Sepay Recurring (nếu thị trường VN không Stripe)

## Forecast doanh thu

30 khách front-end, convert 30% lên Tier 2 = 9 member x 490k = 4.4tr/tháng MRR.

100 khách, convert 25% lên Tier 2 + 5% Tier 3 = 25 x 490k + 5 x 1.9tr = 21.8tr/tháng MRR.

200 khách, convert 25% Tier 2 + 7% Tier 3 = 50 x 490k + 14 x 1.9tr = 51tr/tháng MRR.
