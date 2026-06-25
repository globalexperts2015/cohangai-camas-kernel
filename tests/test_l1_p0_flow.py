"""Regression tests for the BreakoutOS L1 P0 pre-launch fixes."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from agents.l1_extraction import extract as extract_module
from routes import intake_forms
from routes._auth import _verify_hmac, sign_student
from routes.l1_routes import _persist_tier_b, _ready_for_gate_1


TEST_SECRET = "0123456789abcdef0123456789abcdef"


class EventConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple]] = []

    async def fetchval(self, sql: str, *args):
        self.executions.append((sql, args))
        return None

    async def execute(self, sql: str, *args):
        self.executions.append((sql, args))
        return "INSERT 0 1"


class EventPool:
    def __init__(self) -> None:
        self.connection = EventConnection()

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def test_hmac_sign_and_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAC_SECRET", TEST_SECRET)
    student_id = str(uuid4())
    signature = sign_student(student_id)

    assert len(signature) == 16
    assert _verify_hmac(student_id, signature)
    assert not _verify_hmac(student_id, "0" * 16)
    assert not _verify_hmac(str(uuid4()), signature)


def test_hmac_requires_32_byte_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAC_SECRET", "too-short")
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        sign_student(str(uuid4()))


@pytest.mark.asyncio
async def test_l1_get_rejects_invalid_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HMAC_SECRET", TEST_SECRET)
    response = await intake_forms.l1_form(
        student=str(uuid4()),
        sig="invalid",
        pool=object(),
    )

    assert response.status_code == 403
    assert "Đường link không hợp lệ" in response.body.decode()


@pytest.mark.asyncio
async def test_l1_get_redirects_to_signed_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HMAC_SECRET", TEST_SECRET)
    student_id = str(uuid4())
    signature = sign_student(student_id)

    async def no_baseline(pool, parsed_student_id):
        assert str(parsed_student_id) == student_id
        return False

    monkeypatch.setattr(intake_forms, "has_baseline", no_baseline)
    response = await intake_forms.l1_form(
        student=student_id,
        sig=signature,
        pool=object(),
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        f"/foundation/baseline?student={student_id}&sig={signature}"
    )


@pytest.mark.asyncio
async def test_l1_get_renders_signed_post_and_412_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HMAC_SECRET", TEST_SECRET)
    student_id = str(uuid4())
    signature = sign_student(student_id)

    async def has_t0(pool, parsed_student_id):
        return True

    monkeypatch.setattr(intake_forms, "has_baseline", has_t0)
    response = await intake_forms.l1_form(
        student=student_id,
        sig=signature,
        pool=object(),
    )
    html = response.body.decode()

    assert response.status_code == 200
    assert f'name="signature" value="{signature}"' in html
    assert "'X-Student-Signature': sig" in html
    assert "r.status === 412" in html
    assert "window.location.href = redirect" in html


def test_founder_story_can_generate_with_partial_evidence() -> None:
    result = extract_module._precheck_evidence(
        "founder-story",
        {
            "identity": "Founder hệ thống",
            "mission": "Giúp chủ doanh nghiệp nhỏ",
            "lived_experience": "Có kinh nghiệm vận hành nhưng thiếu năm cụ thể.",
            "why_statement": "Tạo tự do",
        },
    )

    assert result is None


@pytest.mark.asyncio
async def test_founder_assets_requires_two_concrete_evidence_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        extract_module,
        "_client",
        lambda: pytest.fail("LLM must not be called without enough evidence"),
    )
    result = await extract_module.extract_canonical(
        "founder-assets",
        {
            "identity": "Founder hệ thống",
            "lived_experience": "Tôi có kinh nghiệm vận hành.",
            "customer_direction": "Chủ doanh nghiệp nhỏ",
        },
    )

    assert result["error"] == "insufficient_evidence"
    assert "≥2 số liệu cụ thể hoặc credential" in result["missing"][0]


@pytest.mark.asyncio
async def test_failed_tier_b_is_visible_and_logged() -> None:
    pool = EventPool()
    student_id = uuid4()

    await _persist_tier_b(
        pool,
        student_id,
        "founder-story",
        {
            "error": "insufficient_evidence",
            "missing": ["≥3 năm cụ thể trong lived_experience"],
        },
    )

    assert len(pool.connection.executions) == 3
    assert "max(version)" in pool.connection.executions[0][0]
    assert "canonical_files" in pool.connection.executions[1][0]
    assert "generation_failed" in pool.connection.executions[1][0]
    sql, args = pool.connection.executions[2]
    assert "tier_b.generation_failed" in sql
    payload = json.loads(args[1])
    assert payload == {
        "file_key": "founder-story",
        "error": "insufficient_evidence",
        "missing": ["≥3 năm cụ thể trong lived_experience"],
    }


def test_gate_1_ready_requires_exactly_eight_reviewed_or_locked_files() -> None:
    reviewed = [{"status": "reviewed"} for _ in range(8)]
    assert _ready_for_gate_1(reviewed)
    assert _ready_for_gate_1(
        [{"status": "locked"}, *[{"status": "reviewed"} for _ in range(7)]]
    )
    assert not _ready_for_gate_1([{"status": "reviewed"} for _ in range(7)])
    assert not _ready_for_gate_1(
        [{"status": "ai_generated"}, *[{"status": "reviewed"} for _ in range(7)]]
    )
    assert not _ready_for_gate_1(
        [{"status": "draft"}, *[{"status": "reviewed"} for _ in range(7)]]
    )


def test_output_page_shows_missing_l1_file_and_retry_action() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "routes" / "dashboard_routes.py"
    ).read_text(encoding="utf-8")

    assert '("founder-story", "B")' in source
    assert 'status": "missing"' in source
    assert 'class="retry-btn"' in source
    assert "/sdl/l1/extract/${{fk}}" in source
