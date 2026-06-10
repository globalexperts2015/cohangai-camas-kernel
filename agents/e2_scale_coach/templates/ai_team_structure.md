# AI Team Structure, đội ngũ AI agent thay thế nhân sự

Nguyên tắc AI-first BreakoutOS v3: trước khi hire người, hỏi AI agent có làm được không. Nếu được, deploy agent trước, defer hire 90 ngày để verify capacity gap thật.

## Inventory 27 BC agents (CAMAS Kernel canonical)

### Founder layer (BC1)
- **BC1 Team Leader**: orchestrator, decide nào agent nào dùng cho 1 task

### Voice + identity layer (BC2)
- **BC2 Voice Guardian**: enforce Anna Voice DNA 4 register (hang_webinar / minh_lennui / toi_nauon / anna_bmcorner)

### Feedback layer (BC3 family)
- **BC3 Feedback Loop**: collect + parse student feedback
- **BC3 Profile Extractor**: extract persona từ conversation
- **BC3 Task Tracker**: track todos cohort student

### Launch + delivery (BC4, BC10)
- **BC4 K2 Launch**: webinar launch orchestrator (Speakout/Breakout K2-K4)
- **BC10 Coaching Delivery**: 1-on-1 coaching session prep + follow-up

### Data + monitoring (BC5, BC8)
- **BC5 CDP Monitor**: customer data platform health
- **BC8 Night Audit**: 11pm Perth daily audit 6 ventures, email Anna

### Customer support (BC6, BC7)
- **BC6 CSKH FAQ Haiku**: auto-reply FAQ qua Haiku model (cheap, fast)
- **BC7 FB Autoreply**: Facebook Messenger autoreply

### Compliance + persona (BC9, BC11-BC18)
- **BC9 Compliance Officer**: TOS check FB/Google/MARA
- **BC11 VPC Builder**: Value Proposition Canvas student
- **BC12 Consciousness Tracker**: track awareness level (Schwartz 5 stages)
- **BC13 Pain Scorer**: rank persona pain severity
- **BC14 Joy Mapper**: map desired future state
- **BC15 Character Builder**: founder persona development
- **BC16 Value Ladder**: design value ladder front-end → core → backend
- **BC17 Grand Slam Offer**: Hormozi GSO scoring
- **BC18 Value Equation**: dream outcome / perceived likelihood / time delay / effort sacrifice

### Funnel + copy (BC19-BC20)
- **BC19 Funnel Architect**: design funnel multi-stage
- **BC20 Copy Stack**: stack Brunson copy formula

## 10 Pban (Phòng ban) cho sales operations

- **Pban01 Quảng cáo**: FB Ads + Google Ads creative + scaling
- **Pban02 Nội dung**: long-form content (blog, sales page, email)
- **Pban03 Landing Webinar**: design landing + webinar reg page
- **Pban04 Phiếu Comms**: email broadcast + nurture sequence
- **Pban05 Thanh toán**: Sepay + Stripe + checkout flow
- **Pban06 CSKH FAQ Haiku**: customer support tier 1 (alias BC6)
- **Pban07 Hoàn tiền**: refund processing + escalation
- **Pban08 Dữ liệu**: data extraction + reporting
- **Pban09 Tuân thủ**: compliance check pre-publish
- **Pban10 Chiến lược**: weekly debate + decision synthesis

## 5 cron jobs core (mọi venture cần)

1. **cron_morning_brief**: 6am Perth daily → Telegram Breakout Ops, key metric ngày qua
2. **cron_lead_scoring**: 5am daily → score Hot/Warm/Cold contact, top 20 hot → Telegram
3. **cron_dedupe_contact**: 2am Sunday → dedupe GHL contacts
4. **cron_stale_alert**: 7am Monday → flag contact >30 ngày không tương tác
5. **cron_night_audit**: 11pm daily → BC8 audit, email summary

Cron job 6 (advanced): **cron_amem_weekly**: weekly memory consolidation cho CAMAS Kernel.

## Activation order theo customer count

### 5-15 khách (Foundation, LOCKED)
- BC1 Team Leader (orchestrator)
- BC6 CSKH FAQ Haiku (auto support)
- Pban05 Thanh toán (checkout)
- cron_morning_brief

Anthropic budget: $10-20/tháng

### 15-30 khách (Webinar scale)
+ BC4 K2 Launch (webinar)
+ BC19 Funnel Architect
+ BC20 Copy Stack
+ Pban03 Landing Webinar
+ Pban04 Phiếu Comms
+ cron_lead_scoring

Anthropic budget: $30-50/tháng

### 30-100 khách (Referral + Membership)
+ BC2 Voice Guardian
+ BC10 Coaching Delivery
+ BC11 VPC Builder + BC16 Value Ladder
+ Pban02 Nội dung
+ Pban09 Tuân thủ
+ cron_dedupe_contact + cron_stale_alert

Anthropic budget: $50-100/tháng

### 100-500 khách (Affiliate + scale)
+ BC5 CDP Monitor
+ BC7 FB Autoreply
+ BC9 Compliance Officer
+ Pban01 Quảng cáo (FB+Google Ads automation)
+ Pban08 Dữ liệu (reporting)
+ Pban10 Chiến lược (weekly strategy synthesis)
+ cron_night_audit + cron_amem_weekly

Anthropic budget: $100-300/tháng

### 500+ khách (Mature operations)
+ Toàn bộ 27 BC + 10 Pban
+ Tất cả 6 cron jobs
+ Custom agent venture-specific

Anthropic budget: $300-800/tháng

## Hire decision tree (AI-first principle)

### Câu hỏi #1 trước mọi hire
"Task này có agent nào trong inventory làm được không?"
- Nếu có → activate agent, defer hire 90 ngày
- Nếu không → câu hỏi #2

### Câu hỏi #2
"Có thể build agent mới trong 2 tuần không?"
- Yes (workflow + tool + LLM) → build agent, save 2-5 năm salary
- No (need human judgment / relationship / physical presence) → hire

### Trigger first hire (KHÔNG sớm hơn)
- Revenue >=100tr VND/tháng STABLE 3 tháng (consistent KHÔNG spike)
- Founder >70h/tuần (burnout risk verified)
- AI agent + cron đã cover 70% automation possible
- Specific role gap không thể AI (vd: physical event ops, in-person sales meeting)

First hire thường: VA chăm sóc inbox + onboard học viên (10-15h/tuần freelance, 5-8tr VND/tháng)

### Second hire trigger
- First hire ổn định >=3 tháng
- Revenue >=300tr VND/tháng STABLE
- 1-on-1 sales calls >20h/tuần (overflow)

Second hire thường: Sales closer 1-on-1 (commission-based, 10-15% per close)

### Anti-pattern hire
- Hire trước khi revenue stable 3 tháng → bị overhead, layoff đau đớn
- Hire FT khi part-time đủ → fixed cost trap
- Hire role AI làm được (vd: copywriter cơ bản, designer cơ bản) → waste, AI cheaper 95%
- Hire skill founder chưa làm chủ → không train được, quit sớm

## Budget anthropic theo scale

| Customer count | Agent active | Budget USD/month |
|---|---|---|
| 0-15 | 4 agent + 1 cron | $10-20 |
| 15-30 | 9 agent + 2 cron | $30-50 |
| 30-100 | 15 agent + 4 cron | $50-100 |
| 100-500 | 22 agent + 6 cron | $100-300 |
| 500+ | 27 agent + 10 pban + 6 cron | $300-800 |

So với hire team người tương đương:
- 5 nhân sự FT VN (8-15tr/người) = 40-75tr/tháng (~$1,600-3,000 USD)
- AI team equivalent ở 100 customers = $50-100 USD
- Saving 95-97% chi phí, 24/7 uptime, không turnover

## Setup canonical

Activate agent qua CAMAS Kernel `/kernel/execute` endpoint hoặc admin dashboard `os.breakout.live`. Mỗi venture có config riêng theo BreakoutOS pattern "1 Kernel + 5 config per venture".

Source: `cohangai/services/camas-kernel/agents/` (27 BC subfolder), `cohangai/services/breakoutos/` (template config).
