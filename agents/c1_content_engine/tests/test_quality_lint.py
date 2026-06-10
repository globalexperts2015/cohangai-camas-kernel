"""Unit tests for C1 Content Engine quality_lint.

Run with: pytest agents/c1_content_engine/tests/test_quality_lint.py
"""
from __future__ import annotations

from agents.c1_content_engine.quality_lint import lint_content_pack


def _clean_pack() -> dict:
    return {
        "pillars": [
            {"id": "p1", "name": "Tư duy founder", "core_idea": "Bán cá khô Quảng Trị 70 nhân sự"}
        ],
        "reel_ideas": [
            {"pillar_id": "p1", "hook": "Tôi mất 3 năm mới hiểu", "story": "Mắm Thuyền Nan", "cta": "Inbox Hằng"}
        ],
        "cta_by_awareness": {"unaware": "Đọc bài này 5 phút"},
    }


def test_clean_pack_passes() -> None:
    passed, violations = lint_content_pack(_clean_pack())
    assert passed is True
    assert violations == []


def test_generic_phrase_caught() -> None:
    pack = _clean_pack()
    pack["pillars"][0]["core_idea"] = "Giải pháp toàn diện cho khách hàng tiềm năng"
    passed, violations = lint_content_pack(pack)
    assert passed is False
    assert any("khách hàng tiềm năng" in v for v in violations)
    assert any("giải pháp toàn diện" in v for v in violations)


def test_em_dash_caught() -> None:
    pack = _clean_pack()
    pack["pillars"][0]["core_idea"] = "Bán cá khô — Quảng Trị"
    passed, violations = lint_content_pack(pack)
    assert passed is False
    assert any("em-dash" in v for v in violations)


def test_emoji_caught() -> None:
    pack = _clean_pack()
    pack["pillars"][0]["name"] = "Founder \U0001F525 tư duy"
    passed, violations = lint_content_pack(pack)
    assert passed is False
    assert any("emoji" in v for v in violations)


def test_case_insensitive_generic() -> None:
    pack = _clean_pack()
    pack["pillars"][0]["core_idea"] = "ROI tăng nhờ ĐỘT PHÁ TƯ DUY"
    passed, violations = lint_content_pack(pack)
    assert passed is False
    assert any("roi tăng" in v for v in violations)
    assert any("đột phá" in v for v in violations)


def test_filler_cta_caught() -> None:
    pack = _clean_pack()
    pack["reel_ideas"][0]["cta"] = "Tìm hiểu thêm tại link bio"
    passed, violations = lint_content_pack(pack)
    assert passed is False
    assert any("tìm hiểu thêm" in v for v in violations)
