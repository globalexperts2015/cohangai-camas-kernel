# Testimonial Engine, hệ thống thu testimonial chất lượng cao

Testimonial là asset reuse nhiều lần: sales page, FB ads, email, social proof, webinar case study. 1 testimonial chất lượng = 50-100 testimonial generic. Hệ thống thu cần process, không hỏi vu vơ.

## Khi nào trigger collection

Day 30 sau mua là sweet spot:
- Khách đã thấy result đầu tiên
- Còn momentum tốt
- Trí nhớ Before/After còn fresh
- Chưa có time để forget specific detail

Tránh Day 7 (chưa result), tránh Day 90+ (đã forget).

Trigger có thể:
- Manual: founder check NPS >=8 ở Day 30 + send form
- Automation GHL: `tag:day_30_active` + `nps_score >=8` → workflow gửi email
- Trigger sau win: khách post FB khoe result → DM "Bạn share testimonial form được không?"

## Form 5-7 câu (core)

### Câu 1: Before state (trước khi mua)
"Bạn ở đâu 30 ngày trước? Pain cụ thể là gì? Đã thử cách nào trước đó nhưng không work?"

### Câu 2: Trigger mua
"Điều gì khiến bạn quyết định mua [Product]? Bạn đã do dự gì? Vượt qua thế nào?"

### Câu 3: During state (trải nghiệm)
"30 ngày qua bạn làm gì? Module/feature nào valuable nhất? Bạn đã apply như thế nào?"

### Câu 4: Specific result 1 (số liệu cứng)
"1 con số cụ thể đã thay đổi? Ví dụ doanh thu, khách, time saved, score, weight, etc."

### Câu 5: Specific result 2 (cảm xúc)
"1 thay đổi cảm xúc/mindset? Bạn cảm thấy khác như thế nào về bản thân/công việc?"

### Câu 6: Specific result 3 (relationship/impact)
"Tác động lên người xung quanh (gia đình, team, khách)? Ai notice change?"

### Câu 7: Recommendation
"Nếu giới thiệu cho 1 người bạn, bạn sẽ nói gì với họ?"

### Permission section (BẮT BUỘC)
- [ ] Tôi đồng ý chia sẻ testimonial này public trên website, social, ads
- [ ] Tôi đồng ý sử dụng tên + ảnh đại diện
- [ ] Tôi đồng ý quay video 60-90 giây nếu được yêu cầu

KHÔNG dùng testimonial chưa có permission. Lưu permission record trong DB.

## Format thu thập

### Tier 1: Text form (default, cho tất cả)
- Google Form / Tally embedded trong email
- Tally Pro Anna có, dùng Tally.so cho consistency
- Time fill 10-15 phút, completion rate 30-50% nếu Day 30 timing

### Tier 2: Voice memo (cho khách engagement cao)
- Loom/Vimeo record 90 giây
- Prompt: "Kể tôi nghe trong 90 giây hành trình của bạn"
- Time fill 5 phút, completion rate 60-80% nếu khách top tier

### Tier 3: Video testimonial (cho case study đỉnh)
- 5-10 phút interview, Anna hoặc Pban02 phỏng vấn qua Zoom
- Fathom record + transcript
- Reuse cho sales page, webinar, ads
- 1 video tốt = 10 text testimonial về impact

## Incentive (để boost completion rate)

Khách thường lazy fill form. Incentive:
- Tier 1 text: 1 month membership free OR 500k credit
- Tier 2 voice: 3 month membership free OR template pack
- Tier 3 video: 1-on-1 call 30 phút với founder OR 30% off next purchase

KHÔNG offer cash (perception fake testimonial).

## Reuse asset (1 testimonial → 10+ asset)

1 testimonial chất lượng tạo được:
- 1 sales page section (1 trong 5-10 testimonial)
- 1 FB ad creative (testimonial quote + photo)
- 1 LinkedIn post (case study format)
- 1 email (subject: "Cách [Name] đạt [Result]")
- 1 webinar slide (case study minute 45-55)
- 1 podcast guest slot (mời lên show kể chi tiết)
- 1 short video reel (15-30 giây hook)
- 1 social proof badge website (logo + 1 line)

## Quality bar

Testimonial reusable phải có:
- Tên thật + ảnh thật (không "Mr. M from HCMC")
- Specific number (KHÔNG generic "tăng doanh thu", phải "tăng từ 10tr lên 35tr/tháng")
- Before/After contrast rõ ràng
- Permission lưu trữ documented

Testimonial vague kiểu "Khoá này rất hay, cảm ơn cô" → KHÔNG dùng. Hỏi follow-up cụ thể.

## Forecast 90 ngày

100 khách front-end, NPS >=8 = 60 khách qualify:
- Send form 60: completion 40% = 24 testimonial text
- Voice memo offer cho top 20: completion 60% = 12 voice
- Video interview top 5: 4 done

Total asset: 24 text + 12 voice + 4 video = 40 testimonial asset reusable.

Phân phối: 5 sales page rotation + 10 FB ads creative + 15 email subjects + 10 social proof slot.

## Storage + tagging

- File: Google Drive folder `testimonials/[year]/[student-id]/`
- Naming: `YYYYMMDD-name-result-headline.md`
- DB record: GHL custom field `testimonial_status: collected | published | featured`
- Backup: ANNA SECOND BRAIN vault `wiki/content/testimonials/`

## Anti-pattern

- Hỏi quá sớm (Day 7) → result chưa có
- Form quá dài (>10 câu) → drop-off 80%
- Không có permission → litigation risk
- Edit testimonial quá nhiều (mất tính authentic) → reader smell fake
- Lưu trên 1 nơi không backup → mất khi laptop hỏng
