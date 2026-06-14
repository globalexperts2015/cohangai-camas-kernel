# BreakoutOS Build Assumptions Log

Per Anna's explicit command 2026-06-12: "If any information is missing, make the safest assumption, document the assumption in ASSUMPTIONS.md, then continue coding."

Source of truth: `wiki/concepts/breakoutos-master-architecture.md` V3.5.7 LOCKED.

## A1. Tech stack (chốt bằng existing repo)

KHÔNG dùng default Anna's command (Next.js + FastAPI separate apps). Lý do: existing infrastructure đã ship đầy đủ:
- Backend: **camas-kernel** Railway FastAPI Python (already LIVE `os.breakout.live`)
- Database: **Postgres** Railway (shared schemas: public, cdp, breakoutos)
- Frontend: **HTML/CSS embedded** trong FastAPI routes (current landing pattern). Phase 2 có thể tách Next.js sau khi core flow validated.
- AI: **Anthropic Claude** Haiku 4.5 default + Opus 4.7 cho narrative tasks (`founder-story`, `positioning`, `offer-validation`)
- Deployment: **Railway** auto-deploy từ `railway up`

Rationale: Anna's command said "If repo structure exists, adapt to existing." Existing camas-kernel + breakout-app + breakout-zns đang LIVE phục vụ K2 cohort. Tăng tốc bằng cách extend, KHÔNG rebuild from scratch.

## A2. Auth strategy

Phase 1: Magic link **deferred**. Dùng email-based login với token (existing `verify_token` pattern trong cohort_widget_routes).
Phase 2: Sepay webhook tạo student auto + Telegram alert Anna → Anna gửi link via Zalo manually.
Phase 3: Magic link Brevo (sau khi 10-student validation pass).

## A3. T0 baseline form

Mandatory pre-L1 access per spec. Implementation:
- Table `breakoutos.founder_freedom_score` với composite key (student_id, measured_at)
- Endpoint `GET /sdl/students/{id}/baseline-status` → returns 200 nếu fill, 412 nếu missing
- HTML form embed tại `/foundation/baseline` (Tally form alternative dùng FastAPI)
- L1 wizard endpoint `/sdl/l1/start` check baseline first, return 412 + redirect

## A4. Markdown + JSON dual

Per spec mandatory. Implementation pattern:
```python
def generate_canonical(student_id, file_key, structured_data):
    # Generate markdown via Jinja2 template
    md = render_template(f"templates/{file_key}.md.j2", structured_data)
    # Save dual
    db.execute("INSERT INTO canonical_files (...) VALUES (markdown_content, structured_data_json, ...)")
    return {"markdown": md, "json": structured_data}
```

Markdown templates trong `cohangai/services/camas-kernel/templates/canonical/{file_key}.md.j2`.

## A5. Obsidian sync

Phase 1: **Markdown export endpoint** `GET /sdl/students/{id}/vault/export.zip` → student download manually.
Phase 2: Vault sync webhook (defer per Anna's command "If Obsidian sync is complex, implement Markdown export first").

## A6. UI scope Cohort 1

Per Anna 4 amendments + Section 29 Master Architecture:
- Show **Tier A 15 files** primary in UI
- Tier B 16 files sinh ngầm, hiển thị optional panel "AI Generated"
- Tier C 16 files locked until Gate 3 pass

Frontmatter `tier_visibility: cohort_1` filter applied trong `setup_second_brain()`.

## A7. AI Extraction model routing

Per memory `feedback-model-routing-haiku-vs-opus`:
- **Haiku 4.5 default** (extraction từ raw text, structured JSON schema-constrained)
- **Opus 4.7** cho: `founder-story` (3-act narrative), `positioning-statement` (strategic), `offer-validation` (reasoning), `business-strategy-synthesis`

Cost estimate per student L1+L2:
- 8 Tier A files student fills → 0 LLM cost
- 16 Tier B files AI gen: 13 Haiku ($0.06/call × 13 = $0.78) + 3 Opus ($0.86/call × 3 = $2.58) = ~$3.36/student
- 10-student validation total ~$34

## A8. Cron infrastructure for AI COO L4

Anna's command: "If cron infrastructure is not available locally, implement job table + manual trigger endpoints + documented cron schedule."

Existing: 6 cron-job.org → CAMAS Kernel `/kernel/execute` (Job IDs 7756272-7756282).
Plan L4:
- Add 3 new cron jobs in cron-job.org:
  - `cron_ai_coo_daily_brief` 6am AWST → POST /sdl/l4/coo/daily-brief
  - `cron_ai_coo_night_audit` 11pm AWST → POST /sdl/l4/coo/night-audit (extends existing bc8_night_audit)
  - `cron_ai_coo_weekly_review` Sun 8pm AWST → POST /sdl/l4/coo/weekly-review

## A9. Customer Fit Score formula

Per Anna's command + Master architecture V3.5:
```
fit_score = (
    lived_experience * 30 +
    empathy * 20 +
    credibility * 15 +
    pain * 15 +
    reach * 10 +
    wtp * 10
) / 100
```
Each component 0-10 student fills. Total 0-100. Gate 2A threshold ≥60.

## A10. Module CHỌN E1-E9 home

Per Anna V3.5.5 spec:
- E1-E5 pre-module phase (L1+L2 context, no separate UI)
- E6-E9 = L3 Value Proposition home (existing Module CHỌN UI at `/cohort/chon-module/`)

Wire `check_gate_passed(student_id, 'gate_2_customer_soft')` BEFORE running Module CHỌN.

## A11. Gate snapshot folder

Per Master architecture Section 7 + 28:
- `05 Canonical Outputs/final-vision.md` (post Gate 1)
- `05 Canonical Outputs/final-founder-identity.md` (post Gate 1)
- `05 Canonical Outputs/final-customer-direction.md` (post Gate 2B)
- `05 Canonical Outputs/final-statement-mot-dong.md` (post Gate 2B)
- `05 Canonical Outputs/final-offer.md` (post Gate 3)

Lock signature: SHA256(content_concat).

## A12. Day 1 + Day 2 webinar readiness

Per Anna's command:
- Day 1 (Thứ Hai 22/6 5h sáng VN): L1 intake + AI extraction + 8 canonical files + output link
- Day 2 (Thứ Tư 24/6 5h sáng VN): L2 intake + Customer Fit + 11 canonical files + output link

Hard deadline: working flow ready 7 ngày trước = 15/6.

## A13. Telegram alert pattern

Per memory `feedback-alert-only-critical`:
- Sepay Foundation 3M paid → alert immediate (existing wire)
- Gate 1 / Gate 2 / Gate 3 pass → alert immediate (Anna 1-1 Zalo follow)
- AI extraction fail (3 retries) → alert immediate
- Student stuck >24h same step → alert

Use existing `_notify_zalo_alert(text)` helper in breakout-app + duplicate pattern in camas-kernel.

## A14. Admin Dashboard

Add `/sdl/admin` route with bearer auth (env `BREAKOUTOS_ADMIN_KEY`).
View student list + cohort filter + level/gate status + freedom score + canonical completion + blocked students.

## A15. Output link sharing

Per Anna's command Phase 1: **Private signed URL**.
Pattern: `https://os.breakout.live/sdl/students/{id}/output/{level}?token={signed_jwt}`
JWT signed with `SDL_OUTPUT_SECRET` env, expires 30 days.
Public share defer Phase 2.

---

## CHANGELOG

| Date | Update |
|---|---|
| 2026-06-12 | Initial assumptions log. Anna command V1 received. Existing infrastructure analysis. |
