from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from routes.challenge_k3 import (
    Day1Request,
    Day2Request,
    EVENT_CONFIG,
    RegisterRequest,
    _fake_output,
    _token_hash,
)


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
        observed_evidence="Đã nghe khách hàng hỏi nhiều lần.",
        top_problem="Không biết chọn ý tưởng nào.",
        desired_result="Có offer để kiểm chứng.",
        customer_channels="Facebook và cộng đồng.",
        keywords=["kinh doanh kỹ năng"],
        existing_alternatives="Khóa học chung.",
    ).model_dump()
    output = _fake_output(2, inputs, {"market_score": 6, "evidence_status": "partial"})
    score = output["opportunity_score"]
    assert set(score) == {
        "founder_fit", "market_demand", "monetization",
        "ai_leverage", "confidence", "total",
    }
    assert score["total"] == sum(value for key, value in score.items() if key != "total")


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
