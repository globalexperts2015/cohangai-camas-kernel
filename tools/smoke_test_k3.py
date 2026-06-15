"""Smoke test Breakout Challenge K3 with 10 temporary profiles.

Uses the real Postgres schema and deterministic AI output. Integration outbox
is intentionally not processed. All smoke data is deleted at the end.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID

import asyncpg
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from routes.challenge_k3 import (  # noqa: E402
    Day1Request,
    Day2Request,
    Day3Request,
    IdeaSelectionRequest,
    OfferApprovalRequest,
    RegisterRequest,
    _complete_generation,
    approve_offer,
    register,
    select_idea,
    submit_day1,
    submit_day2,
    submit_day3,
)


async def _complete_job(pool: asyncpg.Pool, job_id: str) -> None:
    parsed_job_id = UUID(str(job_id))
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM breakout_challenge.generation_jobs WHERE id=$1",
            parsed_job_id,
        )
        await conn.execute(
            """
            UPDATE breakout_challenge.generation_jobs
            SET status='processing', attempts=attempts+1, started_at=now()
            WHERE id=$1
            """,
            parsed_job_id,
        )
    job = dict(row)
    job["attempts"] += 1
    await _complete_generation(pool, job)


async def run_profile(pool: asyncpg.Pool, index: int) -> None:
    email = f"k3-smoke-{index:02d}@daothihang.com"
    registration = await register(
        RegisterRequest(
            email=email,
            full_name=f"K3 Smoke {index:02d}",
            cohort_id="k3-smoke-2026-06",
            access_tier="vip" if index % 2 == 0 else "free",
        ),
        pool,
        f"smoke-register-{index}",
    )
    token = registration["token"]

    job = await submit_day1(
        token,
        Day1Request(
            lived_experience="Tôi có nhiều năm kinh nghiệm thực tế trong đào tạo và dịch vụ.",
            skills_and_proof="Tôi đã hướng dẫn khách hàng và có các kết quả thực tế.",
            assets_and_network="Tôi có network nhỏ và một nhóm khách hàng cũ.",
            energizing_topics="Tôi thích giúp người khác rõ ràng và hành động.",
            people_to_serve="Người mới muốn xây nguồn thu nhập độc lập.",
            lifestyle_and_time="Tôi có 10 giờ mỗi tuần và muốn vận hành tinh gọn.",
            anti_vision="Không muốn đội ngũ lớn hoặc phụ thuộc quảng cáo.",
        ),
        pool,
    )
    await _complete_job(pool, job["job_id"])
    await select_idea(token, IdeaSelectionRequest(idea_index=0), pool)

    job = await submit_day2(
        token,
        Day2Request(
            customer_hypothesis="Người đi làm muốn bắt đầu kinh doanh từ kỹ năng.",
            observed_evidence="Tôi đã nghe nhiều người hỏi cách chọn ý tưởng và tìm khách.",
            top_problem="Không biết chọn cơ hội nào phù hợp với bản thân.",
            desired_result="Có một offer nhỏ để kiểm chứng trong 30 ngày.",
            customer_channels="Facebook group và các cộng đồng nghề nghiệp.",
            keywords=["kinh doanh từ kỹ năng", "ý tưởng kinh doanh"],
            existing_alternatives="Khóa học chung và nội dung miễn phí.",
        ),
        pool,
    )
    await _complete_job(pool, job["job_id"])
    await approve_offer(token, OfferApprovalRequest(approved=True), pool)

    job = await submit_day3(
        token,
        Day3Request(
            sales_channel="Facebook cá nhân và tin nhắn trực tiếp",
            audience_size=500 + index,
            available_hours_per_week=10,
            launch_date=date.today() + timedelta(days=7),
            delivery_capacity=5,
        ),
        pool,
    )
    await _complete_job(pool, job["job_id"])

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.current_state,
                   (SELECT count(*) FROM breakout_challenge.artifacts a
                    WHERE a.session_id=s.id) AS artifacts,
                   (SELECT count(*) FROM breakout_challenge.events e
                    WHERE e.session_id=s.id) AS events
            FROM breakout_challenge.sessions s
            WHERE s.email_normalized=$1 AND s.cohort_id='k3-smoke-2026-06'
            """,
            email,
        )
    assert row["current_state"] == "completed"
    assert row["artifacts"] == 3
    assert row["events"] == 4


async def main() -> int:
    load_dotenv(ROOT.parents[2] / "cohangai/.env", override=False)
    dsn = os.getenv("CDP_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL or CDP_DATABASE_URL is required")
        return 1
    os.environ["K3_FAKE_AI"] = "1"
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    cleanup_sql = (
        "DELETE FROM breakout_challenge.integration_outbox WHERE session_id IN "
        "(SELECT id FROM breakout_challenge.sessions WHERE cohort_id='k3-smoke-2026-06');"
        "DELETE FROM breakout_challenge.sessions WHERE cohort_id='k3-smoke-2026-06'"
    )
    try:
        await pool.execute(cleanup_sql)
        for index in range(1, 11):
            await run_profile(pool, index)
            print(f"profile {index:02d}: passed")
        totals = await pool.fetchrow(
            """
            SELECT count(*) AS sessions,
                   count(*) FILTER (WHERE current_state='completed') AS completed
            FROM breakout_challenge.sessions
            WHERE cohort_id='k3-smoke-2026-06'
            """
        )
        assert totals["sessions"] == 10
        assert totals["completed"] == 10
        print("10/10 profiles completed")
    finally:
        await pool.execute(cleanup_sql)
        await pool.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
