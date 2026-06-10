"""Prompt + tool schema for E2 Scale Coach (BreakoutOS v3 Week 10).

Input: state hiện tại student (customers, revenue_vnd_30d, list_size, nps, ...).
Output: 90-day scale plan + recommended lever + templates + AI team + hire tree.

Decision logic:
- current_customers < 15 → REJECT (locked, return reason "Đạt 15 khách trả tiền trước khi scale")
- 15-30 → recommended_lever = "webinar" (Brunson Perfect Webinar funnel)
- 30-100 → recommended_lever = "referral" + "membership" combo (giữ + extend)
- 100+ → recommended_lever = "affiliate" + "partnership" (scale beyond network)

Style tiếng Việt, KHÔNG em-dash `—`, không emoji, conversational + có số.
"""
from __future__ import annotations

import json
from typing import Any


SUBMIT_SCALE_PLAN_TOOL: dict[str, Any] = {
    "name": "submit_scale_plan",
    "description": (
        "Submit BreakoutOS v3 Scale Plan 90 ngày. Lever chính "
        "(webinar/membership/referral/affiliate) chọn theo state hiện tại student. "
        "KHÔNG generic, phải tham chiếu state."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "plan_90day": {
                "type": "object",
                "properties": {
                    "month_1": {
                        "type": "object",
                        "properties": {
                            "theme": {"type": "string"},
                            "actions": {"type": "array", "items": {"type": "string"}},
                            "kpi_target": {"type": "object"},
                            "weekly_breakdown": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["theme", "actions", "kpi_target"],
                    },
                    "month_2": {
                        "type": "object",
                        "properties": {
                            "theme": {"type": "string"},
                            "actions": {"type": "array", "items": {"type": "string"}},
                            "kpi_target": {"type": "object"},
                            "weekly_breakdown": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["theme", "actions", "kpi_target"],
                    },
                    "month_3": {
                        "type": "object",
                        "properties": {
                            "theme": {"type": "string"},
                            "actions": {"type": "array", "items": {"type": "string"}},
                            "kpi_target": {"type": "object"},
                            "weekly_breakdown": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["theme", "actions", "kpi_target"],
                    },
                },
                "required": ["month_1", "month_2", "month_3"],
            },
            "recommended_lever": {
                "type": "string",
                "enum": ["webinar", "membership", "referral", "ads", "content_seo", "partnership"],
            },
            "recommended_lever_reasoning": {"type": "string"},
            "webinar_template": {
                "type": "object",
                "properties": {
                    "format": {"type": "string"},
                    "duration_min": {"type": "integer"},
                    "structure": {"type": "array", "items": {"type": "object"}},
                    "offer_position": {"type": "string"},
                    "expected_conversion": {"type": "string"},
                },
            },
            "membership_design": {
                "type": "object",
                "properties": {
                    "tier_count": {"type": "integer"},
                    "tiers": {"type": "array", "items": {"type": "object"}},
                    "monthly_price_vnd": {"type": "object"},
                    "deliverables_per_month": {"type": "array"},
                },
            },
            "referral_program_spec": {
                "type": "object",
                "properties": {
                    "trigger": {"type": "string"},
                    "incentive_structure": {"type": "object"},
                    "tracking_mechanism": {"type": "string"},
                    "tier_required": {"type": "integer"},
                },
            },
            "affiliate_program_spec": {
                "type": "object",
                "properties": {
                    "commission_percent": {"type": "number"},
                    "cookie_days": {"type": "integer"},
                    "payment_threshold_vnd": {"type": "integer"},
                    "ideal_affiliate_profile": {"type": "string"},
                },
            },
            "upsell_ladder": {
                "type": "object",
                "properties": {
                    "front_end": {"type": "object"},
                    "core": {"type": "object"},
                    "backend": {"type": "object"},
                    "transition_triggers": {"type": "array", "items": {"type": "string"}},
                },
            },
            "case_study_collection_form": {
                "type": "object",
                "properties": {
                    "trigger_day": {"type": "integer"},
                    "questions": {"type": "array", "items": {"type": "string"}},
                    "format": {"type": "string"},
                },
            },
            "repeat_purchase_strategy": {
                "type": "object",
                "properties": {
                    "frequency_per_year": {"type": "integer"},
                    "offer_match": {"type": "string"},
                    "automation_trigger": {"type": "string"},
                },
            },
            "ai_team_recommended": {
                "type": "object",
                "properties": {
                    "agents_to_activate": {"type": "array", "items": {"type": "string"}},
                    "cron_jobs_to_setup": {"type": "array", "items": {"type": "string"}},
                    "monthly_anthropic_budget_usd": {"type": "number"},
                },
            },
            "hire_decision_tree": {
                "type": "object",
                "properties": {
                    "first_hire_trigger": {"type": "string"},
                    "first_hire_role": {"type": "string"},
                    "second_hire_trigger": {"type": "string"},
                    "second_hire_role": {"type": "string"},
                    "ai_first_principle": {"type": "string"},
                },
            },
        },
        "required": [
            "plan_90day",
            "recommended_lever",
            "recommended_lever_reasoning",
            "ai_team_recommended",
            "hire_decision_tree",
        ],
    },
}


def pick_lever_from_state(current_customers: int) -> tuple[str, str]:
    """Deterministic lever pick rule, dùng để guide LLM trong prompt.

    Return (lever, reasoning_seed).
    """
    if current_customers < 15:
        return ("LOCKED", "Chưa đủ 15 khách trả tiền, scale là phản chỉ định")
    if current_customers < 30:
        return (
            "webinar",
            "15-30 khách = đã có proof, cần funnel scale tự động. Brunson Perfect Webinar evergreen biến 1 lần dạy = 100 lần bán.",
        )
    if current_customers < 100:
        return (
            "referral",
            "30-100 khách = network referral chưa được khai thác. Mỗi khách hiện tại = 1-2 khách mới qua giới thiệu. Combine với membership giữ khách hiện tại.",
        )
    return (
        "affiliate",
        "100+ khách = vượt network cá nhân. Affiliate program mở rộng qua content creator + partner có audience overlap.",
    )


def build_scale_plan_prompt(
    student_id: str,
    venture: str,
    state: dict[str, Any],
) -> str:
    """Build LLM prompt cho 90-day scale plan synthesis.

    state expected keys: current_customers, revenue_vnd_30d, list_size, nps,
        front_end_price_vnd, offer_name, top_persona_pain, capacity_hours_week.
    """
    current_customers = int(state.get("current_customers", 0) or 0)
    lever, lever_seed = pick_lever_from_state(current_customers)

    if lever == "LOCKED":
        return (
            f"State student {student_id} có current_customers={current_customers} < 15. "
            "Trả về tool submit_scale_plan với recommended_lever bất kỳ NHƯNG plan_90day "
            "thông báo lock + reason. Đây là gate, KHÔNG được override."
        )

    return f"""Bạn là Scale Coach của BreakoutOS v3, Week 10 module.

# Student
{student_id}

# Venture
{venture}

# State hiện tại (số liệu thực, KHÔNG bịa)
{json.dumps(state, ensure_ascii=False, indent=2, default=str)[:2500]}

# Quyết định lever (rule-based seed, giải thích thêm bằng số liệu state)
- Lever recommended: {lever}
- Lý do gốc: {lever_seed}

# Nhiệm vụ
Gọi tool submit_scale_plan với 10 nhóm output dưới đây.

## 1. plan_90day (3 month)
Mỗi tháng có:
- theme: 1 câu ngắn focus chính
- actions: 4-6 hành động concrete có chỉ số (vd "chạy 3 webinar live tuần", KHÔNG vague)
- kpi_target: object số tuần đo được (vd customers_added, revenue_vnd, list_growth)
- weekly_breakdown: 4 dòng tuần 1-4 mô tả deliverable

Pattern 90 ngày scale phổ biến:
- Month 1 = Foundation (proof + system + funnel asset)
- Month 2 = Activation (lever chính turn on, traffic vào funnel)
- Month 3 = Optimization (data review + scale spend + decide next 90d)

## 2. recommended_lever + recommended_lever_reasoning
Lever = "{lever}". Reasoning phải tham chiếu state ({current_customers} khách,
{state.get("revenue_vnd_30d", 0):,} VND/30d, list {state.get("list_size", 0)}).
KHÔNG copy seed, viết lại personal cho student.

## 3. webinar_template (nếu lever = webinar HOẶC plan dùng webinar)
- format: "live_weekly" | "evergreen_recorded" | "hybrid"
- duration_min: 90 mặc định
- structure: array of {{minute_range, segment_name, content_outline}}
  Reference: Brunson 5-phase (Origin/Big Idea/3 Secrets/Stack/Close)
- offer_position: minute slot mở offer (60-70 typical)
- expected_conversion: "8-15% live, 3-7% replay"

## 4. membership_design (nếu state cho thấy churn risk OR muốn LTV)
- tier_count: 2-3 tier
- tiers: array {{name, price_vnd, benefits_list, target_persona}}
- monthly_price_vnd: {{tier_1, tier_2, tier_3}}
- deliverables_per_month: array 4-6 món (live call, content drop, community, etc.)

## 5. referral_program_spec
- trigger: "Day 30 sau mua + NPS >= 8" hoặc tương tự
- incentive_structure: {{referrer_pct, referred_discount_pct}}
- tracking_mechanism: "UTM + Fan Hub" | "manual code" | "shared_service"
- tier_required: 4 (Fan) hoặc 5 (Ambassador) trong Fan Hub

## 6. affiliate_program_spec
- commission_percent: 30-50% front-end, 20% core, 10% backend (chọn 1 con số scalar primary)
- cookie_days: 60-90
- payment_threshold_vnd: 500k-2M VND
- ideal_affiliate_profile: persona cụ thể (vd "content creator finance + 5k+ follow IG")

## 7. upsell_ladder
- front_end: {{name, price_vnd, role}}
- core: {{name, price_vnd, role}}
- backend: {{name, price_vnd, role}}
- transition_triggers: array 3 trigger student tự động upsell (vd "Day 30 NPS>=8 + 1 win shared")
- Price gradient front:core:backend = 1:5:20 đến 1:10:50

## 8. case_study_collection_form
- trigger_day: 30 (sweet spot)
- questions: 5-7 câu Before/During/After + 3 specific results + permission to share
- format: "form_5_7_questions_text_plus_optional_video"

## 9. repeat_purchase_strategy
- frequency_per_year: 2-4 mua lại nếu offer cho phép
- offer_match: cohort tiếp theo / advanced module / mastermind / 1-on-1 coaching
- automation_trigger: GHL workflow trigger condition

## 10. ai_team_recommended (AI-first principle: trước khi hire người, hỏi AI agent có thể làm chưa)
- agents_to_activate: array BC/Pban name (chọn từ inventory: BC1-BC27, Pban01-10, cron jobs)
- cron_jobs_to_setup: 3-5 cron specific (morning_brief, lead_scoring, weekly_digest, monthly_memo, night_audit)
- monthly_anthropic_budget_usd: ước lượng theo customer count
  (Tham khảo: 50 customers ~30-50 USD/m, 100 customers ~50-100 USD/m, 500 customers ~200-400 USD/m)

## 11. hire_decision_tree
- first_hire_trigger: rule cụ thể (vd "Revenue >= 100M VND/tháng STABLE 3 tháng + Anna >70h/tuần")
- first_hire_role: thường là "VA chăm sóc inbox + onboard học viên"
- second_hire_trigger: tiếp sau first hire ổn định 3 tháng
- second_hire_role: thường là "Sales closer 1-on-1 calls"
- ai_first_principle: 1 câu nguyên tắc (vd "Mọi role mới hỏi trước: AI agent có làm được không? Nếu được, deploy agent trước, defer hire 90 ngày.")

# Quality requirements
- Tiếng Việt, câu ngắn, sự kiện
- KHÔNG em-dash `—`, không emoji
- Số liệu BẮT BUỘC tham chiếu state student, KHÔNG bịa
- KHÔNG generic kiểu "tăng cường marketing", phải cụ thể như "chạy 4 webinar live thứ 7 8pm tháng 1"
- KHÔNG buzzword (synergy, leverage, optimize without object)
- Pronoun: "bạn" cho student

Output qua tool submit_scale_plan.
"""


def build_locked_response(state: dict[str, Any]) -> dict[str, Any]:
    """Static response khi current_customers < 15 (Foundation lock)."""
    current = int(state.get("current_customers", 0) or 0)
    return {
        "locked": True,
        "reason": f"Đạt 15 khách trả tiền trước khi scale. Hiện tại {current} khách.",
        "next_action": "Quay lại Week 1-9 BreakoutOS, focus founder-led sales 1-on-1 đến đủ 15 khách proof.",
        "plan_90day": {
            "month_1": {
                "theme": "Foundation lock, focus close 15 khách đầu tiên",
                "actions": [
                    "DM trực tiếp 30 leads warm trong list mỗi tuần",
                    "Chạy 4 demo 1-on-1 mỗi tuần, mục tiêu close >=30% (~4 khách/tuần)",
                    "Thu testimonial 1 dòng từ mỗi khách đóng",
                    "KHÔNG run paid ads, KHÔNG webinar evergreen, KHÔNG affiliate",
                ],
                "kpi_target": {"customers_added": 15, "demos_run": 16, "testimonials_collected": 15},
                "weekly_breakdown": [
                    "Tuần 1: list 50 lead warm + script demo",
                    "Tuần 2: chạy demo + close 3-5 khách",
                    "Tuần 3: chạy demo + close 3-5 khách",
                    "Tuần 4: chạy demo + đạt 15 khách + collect testimonial",
                ],
            },
            "month_2": {
                "theme": "Lock, chưa unlock scale",
                "actions": ["Quay lại module Foundation"],
                "kpi_target": {"locked": True},
                "weekly_breakdown": [],
            },
            "month_3": {
                "theme": "Lock",
                "actions": ["Lock"],
                "kpi_target": {"locked": True},
                "weekly_breakdown": [],
            },
        },
        "recommended_lever": "content_seo",
        "recommended_lever_reasoning": (
            f"Hiện tại {current}/15 khách proof. Chưa đủ điều kiện scale. "
            "Lever scale (webinar/referral/affiliate) cần proof tối thiểu 15 khách "
            "để có testimonial + repeatable sales pattern."
        ),
        "ai_team_recommended": {
            "agents_to_activate": ["bc1_team_leader", "pban_05_thanh_toan"],
            "cron_jobs_to_setup": ["cron_morning_brief"],
            "monthly_anthropic_budget_usd": 10.0,
        },
        "hire_decision_tree": {
            "first_hire_trigger": "KHÔNG hire ở stage này",
            "first_hire_role": "Defer",
            "second_hire_trigger": "Defer",
            "second_hire_role": "Defer",
            "ai_first_principle": "Founder-led sales 1-on-1 đến 15 khách, KHÔNG outsource sales trước proof.",
        },
    }
