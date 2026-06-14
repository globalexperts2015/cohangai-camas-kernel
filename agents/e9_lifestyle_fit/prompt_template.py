"""Prompt + tool schema cho E9 Lifestyle Fit Engine.

BreakoutOS CHỌN module Engine 7: Simulate "ý tưởng này thành công gấp 10 lần" và
test xem founder có còn muốn làm mỗi ngày không. Output Lifestyle Fit Score 0-100.

3 lifestyle choices:
- solo_ai: 1 người + AI agents, <30h/tuần, family/health priority
- lean_team: 3-5 nhân viên, <40h/tuần, balance
- growth_team: 10+ nhân viên, 50h+/tuần, scale-to-exit
"""
from __future__ import annotations

import json
from typing import Any


SUBMIT_LIFESTYLE_FIT_TOOL: dict[str, Any] = {
    "name": "submit_lifestyle_fit",
    "description": (
        "Submit Lifestyle Fit Score 0-100 + 10x simulation breakdown. Test scenario "
        "'opportunity thành công gấp 10 lần' và assess fit với lifestyle target của founder."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "lifestyle_fit_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "0-100 fit giữa 10x scenario và lifestyle_choice.",
            },
            "verdict": {
                "type": "string",
                "enum": ["PERFECT_MATCH", "STRONG_MATCH", "ACCEPTABLE", "CONCERNING", "REJECT"],
            },
            "ten_x_scenario": {
                "type": "object",
                "properties": {
                    "scenario_description": {"type": "string", "description": "Mô tả opportunity ở scale 10x"},
                    "estimated_team_size": {"type": "integer", "minimum": 0, "maximum": 500},
                    "estimated_hours_per_week": {"type": "integer", "minimum": 0, "maximum": 100},
                    "ops_complexity": {"type": "string", "enum": ["low", "medium", "high", "very_high"]},
                    "customer_support_volume": {"type": "string", "enum": ["low", "medium", "high", "very_high"]},
                    "warehouse_required": {"type": "boolean"},
                    "location_lock": {"type": "boolean", "description": "Cần ở 1 location cụ thể không"},
                    "travel_required": {"type": "string", "enum": ["none", "rare", "monthly", "weekly"]},
                },
                "required": [
                    "scenario_description", "estimated_team_size", "estimated_hours_per_week",
                    "ops_complexity", "customer_support_volume", "warehouse_required",
                    "location_lock", "travel_required",
                ],
            },
            "lifestyle_match_breakdown": {
                "type": "object",
                "properties": {
                    "time_match": {"type": "integer", "minimum": 0, "maximum": 100},
                    "team_match": {"type": "integer", "minimum": 0, "maximum": 100},
                    "location_match": {"type": "integer", "minimum": 0, "maximum": 100},
                    "complexity_match": {"type": "integer", "minimum": 0, "maximum": 100},
                    "identity_match": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Founder có MUỐN làm việc này mỗi ngày không"},
                },
                "required": ["time_match", "team_match", "location_match", "complexity_match", "identity_match"],
            },
            "deal_breakers": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": "Liệt kê deal-breaker (vd: cần warehouse 500m2 nhưng founder muốn solo+AI)",
            },
            "pivots_to_consider": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
                "description": "Nếu lifestyle fit yếu, gợi ý pivot opportunity để fit hơn",
            },
            "lifestyle_report": {
                "type": "string",
                "description": (
                    "Báo cáo markdown 400-600 từ tiếng Việt. ## 10x scenario + ## 5 match dimensions + "
                    "## Deal breakers + ## Pivot gợi ý + ## Verdict. KHÔNG em-dash."
                ),
            },
        },
        "required": [
            "lifestyle_fit_score", "verdict", "ten_x_scenario",
            "lifestyle_match_breakdown", "deal_breakers", "lifestyle_report",
        ],
    },
}


def build_lifestyle_fit_prompt(
    student_id: str,
    opportunity_hypothesis: str,
    solution_design: dict[str, Any],
    lifestyle_choice: str,
    founder_profile: dict[str, Any],
) -> str:
    opp_clean = (opportunity_hypothesis or "").strip()[:1500]
    sol_json = json.dumps(solution_design or {}, ensure_ascii=False, indent=2)[:1500]
    fp_json = json.dumps(founder_profile or {}, ensure_ascii=False, indent=2)[:1500]

    lifestyle_specs = {
        "solo_ai": "1 người + AI agents, <30h/tuần work, family/health priority, no team, can travel/relocate",
        "lean_team": "3-5 nhân viên + AI, <40h/tuần, balance work/family, some accountability for team",
        "growth_team": "10+ nhân viên, 50h+/tuần, scale-to-exit mindset, full-time hustle, location-flexible",
    }

    return f"""Bạn là E9 Lifestyle Fit Engine trong BreakoutOS CHỌN module.

Nhiệm vụ: Simulate scenario "opportunity dưới đây thành công GẤP 10 LẦN" và assess fit với lifestyle target của founder.

# Student ID
{student_id}

# Opportunity Hypothesis
{opp_clean}

# Solution Design (Engine 5)
```json
{sol_json}
```

# Founder Profile
```json
{fp_json}
```

# Lifestyle Target
**{lifestyle_choice}**: {lifestyle_specs.get(lifestyle_choice, "")}

# Framework đánh giá

1. Simulate scenario 10x:
   - Doanh thu × 10
   - Khách × 10
   - Team size cần để serve
   - Hours/week founder phải đầu tư
   - Ops complexity (kho hàng, logistics, customer support, compliance)
   - Location lock (cần ở 1 chỗ hay flexible)
   - Travel requirements

2. So sánh 10x scenario với lifestyle_choice:
   - solo_ai mismatch nếu cần 30 nhân viên + kho hàng
   - lean_team mismatch nếu cần 50+ nhân viên hoặc 80h/tuần
   - growth_team mismatch nếu solo founder không thể scale ra team

3. 5 match dimensions 0-100:
   - time_match: hours/week tại 10x vs lifestyle limit
   - team_match: team size 10x vs lifestyle target
   - location_match: location lock vs founder flexibility
   - complexity_match: ops complexity vs founder skill+preference
   - identity_match: founder có MUỐN làm cái này mỗi ngày trong 5 năm không

4. Identity_match là CRITICAL. Nếu founder hate làm việc này mỗi ngày → score 30, dù time/team match tốt.

# Rules

1. Honest simulation. KHÔNG soften deal breakers để keep score cao.
2. Deal breakers chỉ list nếu THẬT incompatible (vd: warehouse 500m2 vs solo_ai = deal breaker).
3. Pivot suggestion concrete (vd: "service 1-1 thay vì physical product để skip warehouse").
4. Verdict REJECT nếu identity_match <40 (founder hate scale này).
5. Tiếng Việt thuần, câu ngắn, KHÔNG em-dash.

Output qua tool submit_lifestyle_fit đầy đủ 6 fields.
"""
