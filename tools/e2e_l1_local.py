"""Run the isolated L1 E2E flow against a disposable PostgreSQL database.

Required environment:
  DATABASE_URL
  HMAC_SECRET
  ANTHROPIC_API_KEY
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes import freedom_score_routes, intake_forms, l1_routes, l2_routes, l3_routes, sdl_routes
from routes._auth import SIGNATURE_HEADER, sign_student


def _check(response, expected: int, step: str) -> dict:
    if response.status_code != expected:
        raise AssertionError(
            f"{step}: expected HTTP {expected}, got {response.status_code}: "
            f"{response.text[:1000]}"
        )
    if not response.content:
        return {}
    content_type = response.headers.get("content-type", "")
    return response.json() if "application/json" in content_type else {}


async def _noop_background(*args, **kwargs) -> None:
    """Keep this E2E focused on T0 and the eight L1 canonical files."""


async def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    os.environ["HMAC_SECRET"]
    os.environ["ANTHROPIC_API_KEY"]

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)

    async def override_pool():
        return pool

    app = FastAPI()
    for router in (
        sdl_routes.router,
        freedom_score_routes.router,
        l1_routes.router,
        l2_routes.router,
        l3_routes.router,
        intake_forms.router,
    ):
        app.include_router(router)
    app.dependency_overrides[sdl_routes.get_pool] = override_pool

    # T0 report and post-Gate AI Context are separate background products.
    freedom_score_routes._generate_freedom_report = _noop_background
    l1_routes._generate_ai_context = _noop_background

    results: list[dict] = []
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://e2e.local",
        follow_redirects=False,
        timeout=180,
    ) as client:
        run_suffix = uuid4().hex[:8]
        student_response = await client.post(
            "/sdl/students",
            json={
                "email": f"l1-e2e-{run_suffix}@example.test",
                "full_name": "L1 E2E Student",
                "phone": "0400000000",
                "program_id": "foundation",
                "cohort_id": "pilot_10",
            },
        )
        student = _check(student_response, 201, "create_student")
        student_id = student["id"]
        signature = sign_student(student_id)
        auth_headers = {SIGNATURE_HEADER: signature}
        results.append({"step": "create_student", "status": "pass", "student_id": student_id})

        preflight = await client.get(
            f"/foundation/l1?student={student_id}&sig={signature}",
        )
        _check(preflight, 303, "l1_preflight_without_t0")
        expected_redirect = f"/foundation/baseline?student={student_id}&sig={signature}"
        assert preflight.headers["location"] == expected_redirect
        results.append({
            "step": "l1_preflight_without_t0",
            "status": "pass",
            "endpoint": f"/foundation/l1?student={student_id}&sig=<redacted>",
            "redirect": expected_redirect.replace(signature, "<redacted>"),
        })

        baseline = await client.post(
            f"/sdl/students/{student_id}/freedom-score",
            headers=auth_headers,
            json={
                "source": "self_baseline",
                "q1_income": 5,
                "q2_profit": 5,
                "q3_time_free": 4,
                "q4_peace": 6,
                "q5_clarity": 6,
                "q6_customer": 5,
                "q7_system_ai": 4,
                "q8_independence": 3,
                "q9_growth": 4,
                "q10_meaning": 8,
            },
        )
        baseline_data = _check(baseline, 201, "t0_baseline")
        results.append({
            "step": "t0_baseline",
            "status": "pass",
            "score": baseline_data["total_score"],
        })

        l1_page = await client.get(
            f"/foundation/l1?student={student_id}&sig={signature}",
        )
        _check(l1_page, 200, "l1_form_after_t0")
        assert SIGNATURE_HEADER in l1_page.text
        results.append({"step": "l1_form_after_t0", "status": "pass"})

        intake = await client.post(
            "/sdl/l1/intake",
            headers=auth_headers,
            json={
                "student_id": student_id,
                "life_mission": (
                    "Giúp chủ doanh nghiệp nhỏ xây hệ thống đơn giản để có thêm "
                    "thời gian cho gia đình."
                ),
                "vision_statement": (
                    "Trong 5 năm tôi vận hành một doanh nghiệp có lợi nhuận ổn định, "
                    "làm việc 4 giờ mỗi ngày."
                ),
                "founder_identity": (
                    "Tôi là người xây hệ thống thực tế, biến kinh nghiệm phức tạp "
                    "thành quy trình dễ làm."
                ),
                "decision_principles": [
                    "Chỉ dùng dữ liệu đã kiểm chứng",
                    "Đơn giản trước khi tự động hóa",
                    "Không đổi tự do lấy tăng trưởng",
                    "Khách hàng phải nhận được kết quả đo được",
                    "Mỗi quyết định phải có giới hạn rủi ro",
                ],
                "anti_vision": [
                    "Làm việc 12 giờ mỗi ngày",
                    "Phụ thuộc vào một khách hàng",
                    "Dùng số liệu không kiểm chứng",
                    "Xây bộ máy quá lớn",
                    "Bán sản phẩm không tạo kết quả",
                ],
                "lived_experience": (
                    "Năm 2012 tôi nhận bằng MBA và bắt đầu vai trò quản lý. "
                    "Năm 2018 tôi vận hành dự án với 25 khách hàng trả phí. "
                    "Năm 2023 tôi chuẩn hóa 12 quy trình và giảm 10 giờ làm mỗi tuần."
                ),
                "customer_direction": (
                    "Chủ doanh nghiệp dịch vụ nhỏ muốn giảm phụ thuộc vào chính mình."
                ),
            },
        )
        intake_data = _check(intake, 202, "l1_intake_and_ai_generation")
        assert len(intake_data["tier_a_files"]) == 5
        results.append({
            "step": "l1_intake_and_ai_generation",
            "status": "pass",
            "tier_a": 5,
            "tier_b_requested": len(intake_data["tier_b_pending"]),
        })

        canonical = await client.get(
            f"/sdl/l1/canonical?student_id={student_id}&sig={signature}",
        )
        canonical_data = _check(canonical, 200, "canonical_8_generated")
        files = canonical_data["canonical_files"]
        assert len(files) == 8
        missing = [item["file_key"] for item in files if item["status"] == "missing"]
        assert not missing, f"Missing Tier B files: {missing}"
        assert canonical_data["ready_for_gate_1"] is False
        results.append({
            "step": "canonical_8_generated",
            "status": "pass",
            "statuses": {item["file_key"]: item["status"] for item in files},
        })

        for item in files:
            approved = await client.post(
                f"/sdl/students/{student_id}/canonical-files/{item['file_key']}/approve",
            )
            approved_data = _check(
                approved,
                200,
                f"approve_{item['file_key']}",
            )
            assert approved_data["status"] == "reviewed"
        results.append({"step": "approve_all_8", "status": "pass", "count": 8})

        reviewed = await client.get(
            f"/sdl/l1/canonical?student_id={student_id}&sig={signature}",
        )
        reviewed_data = _check(reviewed, 200, "gate_1_readiness")
        assert reviewed_data["ready_for_gate_1"] is True
        results.append({"step": "gate_1_readiness", "status": "pass"})

        gate = await client.post(
            f"/sdl/l1/gate-1/lock?student_id={student_id}&sig={signature}",
        )
        gate_data = _check(gate, 200, "gate_1_lock")
        assert gate_data["locked"] is True
        assert gate_data["file_count"] == 8
        results.append({
            "step": "gate_1_lock",
            "status": "pass",
            "lock_status": gate_data["lock_status"],
            "file_count": gate_data["file_count"],
        })

        passed = await client.get(
            f"/sdl/students/{student_id}/gates/gate_1_founder/passed",
        )
        passed_data = _check(passed, 200, "gate_1_passed")
        assert passed_data["passed"] is True

        l2_page = await client.get(
            f"/foundation/l2?student={student_id}&sig={signature}",
        )
        _check(l2_page, 200, "l2_unlocked")
        results.append({
            "step": "l2_unlocked",
            "status": "pass",
            "endpoint": f"/foundation/l2?student={student_id}&sig=<redacted>",
        })

    async with pool.acquire() as conn:
        failed_events = await conn.fetch(
            """
            SELECT payload_json FROM breakoutos.student_events
            WHERE student_id=$1 AND event_type='tier_b.generation_failed'
            """,
            UUID(student_id),
        )
        assert not failed_events, f"Unexpected generation failures: {failed_events}"

    await pool.close()
    output = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "database": "local disposable PostgreSQL",
        "student_id": student_id,
        "result": "pass",
        "steps": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
