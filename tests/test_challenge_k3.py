from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from routes.challenge_k3 import (
    Day1Request,
    Day2Request,
    EVENT_CONFIG,
    K3_DAY3_MAX_TOKENS,
    RegisterRequest,
    _derive_token,
    _fake_output,
    _strip_json_response,
    _normalize_day3_output,
    _token_hash,
)


def test_derive_token_is_deterministic_per_session() -> None:
    sid = "4041d9e6-5ab6-417b-8fd2-fc40bf1cfbb2"
    # Cùng session_id → cùng token (đăng ký lại giữ nguyên link).
    assert _derive_token(sid) == _derive_token(sid)
    # Session khác → token khác.
    assert _derive_token(sid) != _derive_token("00000000-0000-0000-0000-000000000000")
    # URL-safe, không padding.
    assert "=" not in _derive_token(sid)
    assert "/" not in _derive_token(sid) and "+" not in _derive_token(sid)


def test_resume_token_is_hashed() -> None:
    token = "a" * 48
    digest = _token_hash(token)
    assert len(digest) == 64
    assert token not in digest


def test_register_contract_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(email="a@example.com", unknown=True)


def test_day1_fake_output_has_ten_hypotheses() -> None:
    inputs = Day1Request(
        lived_experience="Kinh nghiệm đào tạo thực tế trong nhiều năm.",
        skills_and_proof="Đã có khách hàng và kết quả triển khai.",
        assets_and_network="Có network và khách hàng cũ.",
        energizing_topics="Thích giúp người khác rõ ràng.",
        people_to_serve="Người mới kinh doanh.",
        lifestyle_and_time="Mười giờ mỗi tuần.",
        anti_vision="Không muốn đội ngũ lớn.",
    ).model_dump()
    output = _fake_output(1, inputs)
    assert len(output["ideas"]) == 10
    assert all(0 <= idea["provisional_total"] <= 30 for idea in output["ideas"])


def test_day2_score_uses_five_canonical_dimensions() -> None:
    inputs = Day2Request(
        customer_hypothesis="Người mới kinh doanh từ kỹ năng.",
        pain_evidence="Đã mất nhiều tháng tự học và vẫn không biết chọn hướng.",
        top_problem="Không biết chọn ý tưởng nào.",
        desired_result="Có offer để kiểm chứng.",
        keywords=["kinh doanh kỹ năng"],
        payment_evidence="Đã mua khóa học chung giá 3 triệu nhưng chưa ra offer.",
        founder_advantage="Có kinh nghiệm hướng dẫn người mới và network cộng đồng nhỏ.",
    ).model_dump()
    output = _fake_output(2, inputs, {"market_score": 6, "evidence_status": "partial"})
    framework = output["framework_score"]
    assert set(framework) == {
        "pain_real", "active_search", "payment_capacity",
        "founder_advantage", "verification_speed", "total",
    }
    assert framework["total"] == sum(value for key, value in framework.items() if key != "total")
    score = output["opportunity_score"]
    assert set(score) == {
        "founder_fit", "market_demand", "monetization",
        "ai_leverage", "confidence", "total",
    }
    assert score["total"] == sum(value for key, value in score.items() if key != "total")


def test_day3_output_contract_has_launch_assets() -> None:
    inputs = {
        "approved_offer": {
            "who": "Người mới kinh doanh từ kỹ năng.",
            "pain": "Không biết bắt đầu bán từ đâu.",
            "desired_identity": "Có offer nhỏ để kiểm chứng.",
            "vehicle": "Dịch vụ hướng dẫn và AI hỗ trợ",
            "deliverables": ["Để Ngày 3 đóng gói cụ thể"],
        },
        "sales_channel": "Facebook cá nhân",
        "audience_size": 500,
        "available_hours_per_week": 10,
        "launch_date": "2026-06-27",
        "delivery_capacity": 5,
    }
    output = _fake_output(3, inputs)
    assert len(output["launch_content"]) == 30
    assert len(output["email_sequence"]) == 10
    assert set(output["roadmap_30_days"]) == {"week_1", "week_2", "week_3", "week_4"}


def test_day3_normalizer_pads_missing_assets() -> None:
    output = _normalize_day3_output({
        "launch_content": [{"hook": "Một bài"}],
        "email_sequence": [{"subject": "Một email"}],
        "roadmap_30_days": {"week_1": ["Phỏng vấn khách"]},
    })
    assert len(output["launch_content"]) == 30
    assert len(output["email_sequence"]) == 10
    assert all(len(output["roadmap_30_days"][f"week_{week}"]) >= 5 for week in range(1, 5))


def test_day3_generation_has_larger_token_budget() -> None:
    # Day 3 JSON is much larger than Day 1/2: 30 posts + 10 emails + roadmap.
    assert K3_DAY3_MAX_TOKENS >= 8000


def test_strip_json_response_removes_markdown_fence() -> None:
    assert _strip_json_response("```json\n{\"ok\": true}\n```") == "{\"ok\": true}"


def test_student_dashboard_requires_signed_access() -> None:
    dashboard_routes = Path(__file__).resolve().parents[1] / "routes" / "dashboard_routes.py"
    source = dashboard_routes.read_text(encoding="utf-8")
    assert "require_student_signature(str(student_id)" in source
    assert "request_signature(request, sig)" in source


def test_completed_event_sets_day3_and_program_tags() -> None:
    config = EVENT_CONFIG["challenge.completed"]
    assert config["tags"] == [
        "BREAKOUT_K3_DAY3_COMPLETED",
        "BREAKOUT_K3_COMPLETED",
        "BREAKOUT_K3_FOUNDATION_READY",
    ]
    assert config["ghl_tags"] == [
        "breakout-k3-day3-completed",
        "breakout-k3-completed",
        "breakout-k3-foundation-ready",
    ]


def test_completed_event_tags_foundation_ready() -> None:
    # Hoàn thành Day 3 = primed cho Foundation upsell, gắn cả tag Fan Hub lẫn GHL.
    config = EVENT_CONFIG["challenge.completed"]
    assert "BREAKOUT_K3_FOUNDATION_READY" in config["tags"]
    assert "breakout-k3-foundation-ready" in config["ghl_tags"]


def test_generation_failed_event_config() -> None:
    config = EVENT_CONFIG["challenge.generation_failed"]
    assert config["ghl_tags"] == ["breakout-k3-generation-failed"]
    assert config["tags"] == ["BREAKOUT_K3_GENERATION_FAILED"]
    # Lỗi không phải cột mốc ăn mừng nên không tính milestone.
    assert config["milestone"] is False
