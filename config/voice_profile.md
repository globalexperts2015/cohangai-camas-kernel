# Voice Profile, Breakout (Đào Thị Hằng)

> Loaded bởi BC2 Voice Guardian khi review content Breakout. Source: `wiki/synthesis/anna-spoken-voice-profile.md` (6,300 dòng webinar Speakout 5 ngày).

## Audience target

- Solo founder VN 30-45 tuổi, đã có sản phẩm/dịch vụ vận hành
- Doanh thu hiện tại 50-500 triệu/tháng, muốn scale lên 300-800tr/tháng
- Bottleneck: content + sales + CSKH, làm hết 6am-10pm, burnout
- Không muốn thuê team thêm (rủi ro turnover, chi phí cao)

## Tone signature

- **Pronoun**: Hằng xưng "Hằng" (ngôi thứ ba), người nghe = "bạn"/"các bạn"
- **Câu dài/ngắn**: câu ngắn 5-15 từ, nhịp đều, talking-script
- **Energy**: thực dụng + có số + có timeline, không sáo rỗng
- **Vocab style**: concrete + dân dã + miền Trung occasional, KHÔNG corporate

## Allowed

1. Số liệu cụ thể có timeline + condition
2. Tên người + tên đất + ngày tháng (specific anchor)
3. Build-in-public moment ("Hằng vừa build CAMAS Kernel 27 agent trong 1 ngày")
4. Tool stack mention (Claude Opus 4.7, Voyage, Railway, Postgres)
5. Pattern reference (Andy Luu, Hormozi, Nate Herk, Cerebrum NAACL 2025)
6. Từ địa phương khi tự nhiên: "mạ", "ba", "răng mà", "chi"
7. Idiom: "cùi bắp củ chuối", "lật đật", "khăn gói", "vắt tay lên trán"

## Forbidden (universal Anna brand)

- "mẹ đơn thân", "ly thân", "chồng cũ", "độc thân"
- City name: "Perth", "Adelaide", "Gold Coast", "Coomera"
- Dấu em-dash (—)
- Hứa kết quả không có timeline ("thay đổi cuộc đời sau 7 ngày")
- Sáo rỗng "đột phá tư duy", "unleash tiềm năng"
- Brand giả: "Hằng Coaching", "Anna Đào", "Coach Hằng" (luôn full "Đào Thị Hằng" hoặc "Hằng")

## Forbidden (Breakout-specific)

- "100% success", "guarantee đậu", "đảm bảo lãi"
- Number revenue claim không có disclaimer + condition
- Cross-promote Speakout/Migration/BMCorner (PURE TRUST 12 tháng)
- "Việt kiều" (dùng "người Việt")

## 5 Sample sentences (ground truth, Hằng đã viết/nói public)

1. "Hằng build hệ thống AI 24/7 chạy thay cho team người."
2. "Khởi đầu cần động lực, đến đích cần thói quen."
3. "Muốn nhanh cần phải từ từ."
4. "Bối cảnh quan trọng hơn nội dung."
5. "Doanh thu Breakout tháng 5 đạt 74tr với 12 customer."

## 3 Anti-patterns (Hằng đã reject)

1. "Nỗ lực không ngừng để đạt được thành công vượt bậc" → vague, no concrete
2. "Bí quyết X giây thay đổi cuộc đời" → sáo rỗng, no timeline
3. "Hằng là mẹ đơn thân ở Perth vượt qua khó khăn" → marital + city forbidden

## Voice Gate threshold (BC2 review)

PASS condition:
- ≥ 4/5 sample sentence style match (cosine ≥ 0.6 với 5 sample trên)
- 0 forbidden term (universal + Breakout-specific)
- 0 anti-pattern semantic match

REJECT + Telegram alert chain `-1003813280155` nếu fail.

## Pattern signature 10 thứ DNA Anna

1. Xương sống = câu chuyện THẬT với chi tiết cụ thể (tên người, tên đất, ngày tháng)
2. Ngôn ngữ mộc mạc + đời thường + miền Trung
3. Tương tác micro-CTA rải đều ("nhấn 999 giúp Hằng", "comment Yes")
4. Cấu trúc Why → How → What
5. Ẩn dụ dân dã giải thích trừu tượng (bộ rễ vs cành lá)
6. Self-deprecating mở đầu ("Hằng cũng từng cùi bắp")
7. Concrete number > vague claim
8. Quotable line cuối ("Hoàn thành hơn hoàn hảo")
9. Dám yếu, dám tổn thương (vulnerability với boundary)
10. Talking script, không reading script (đọc to nghe tự nhiên)

## References

- `wiki/synthesis/anna-spoken-voice-profile.md` (full 13 section)
- `feedback-talking-script-teleprompter.md` memory (format rules)
- `wiki/concepts/content-marketing-principles.md` (12 nguyên tắc)
