"""Sprint 5 System-Wide Personalization test suite.

Chạy:
    cd cohangai/services/camas-kernel
    /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python \\
        tests/test_personalization.py

5 test (ưu tiên unit + mock, không phụ thuộc Postgres + Voyage):
  1. MemoryLayer.retrieve hỗ trợ filter `category` + `categories` (SQL build)
  2. Scheduler._auto_inject sinh 4 tier group khi mock memory pre-seeded
  3. BC10 fast path skip _fetch_customer_feedback khi Profile+Task injected
  4. BC10 slow path fallback khi không có pre-processed memory
  5. BC6 fast vs slow path tương tự
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    env_path = ROOT.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.memory_layer import MemoryLayer, MemoryRecord  # noqa: E402
from kernel.scheduler import Scheduler, SchedulerConfig  # noqa: E402


# ============================================================
# Test 1: MemoryLayer.retrieve category filter
# ============================================================
async def test_retrieve_category_filter() -> bool:
    """Verify retrieve() accepts category + categories kwargs without raising.

    Không cần DB thật: mock embedder + pool, assert SQL build chứa filter clause.
    """
    print("\n[TEST 1] retrieve category filter SQL build")
    captured_sql: dict[str, Any] = {}

    embedder = MagicMock()
    embedder.ready = True
    embedder.embed = AsyncMock(return_value=[[0.0] * 1024])

    memory = MemoryLayer(dsn="postgres://fake", embedder=embedder)

    # Mock pool.acquire().__aenter__() returning conn with fetch
    class FakeConn:
        async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
            captured_sql["sql"] = sql
            captured_sql["args"] = args
            return []

    class FakeAcquireCtx:
        async def __aenter__(self) -> FakeConn:
            return FakeConn()

        async def __aexit__(self, *a: Any) -> None:
            return None

    class FakePool:
        def acquire(self) -> FakeAcquireCtx:
            return FakeAcquireCtx()

        async def close(self) -> None:
            return None

    memory._pool = FakePool()  # type: ignore[assignment]

    # Case A: single category
    await memory.retrieve(query="test", k=5, category="profile", customer_id=42)
    assert "category = $" in captured_sql["sql"], (
        f"SQL không có category clause:\n{captured_sql['sql']}"
    )
    assert "profile" in captured_sql["args"], "params không truyền 'profile'"
    print("  OK single category filter built")

    # Case B: IN list categories
    await memory.retrieve(
        query="test",
        k=8,
        categories=["pricing", "brand", "policy"],
        venture="breakout",
    )
    sql = captured_sql["sql"]
    assert "category = ANY(" in sql, (
        f"SQL không có category IN ANY clause:\n{sql}"
    )
    print("  OK categories list IN clause built")

    return True


# ============================================================
# Test 2: Scheduler._auto_inject 4 tier
# ============================================================
async def test_scheduler_auto_inject_tiers() -> bool:
    """Mock MemoryLayer trả Profile + Task + Conversation + Canonical record,
    expect _auto_inject sinh 4 group trong injected_memories."""
    print("\n[TEST 2] Scheduler._auto_inject 4 tier")

    # Build fake MemoryLayer ready
    memory = MemoryLayer(dsn="postgres://fake")
    memory._pool = MagicMock()  # type: ignore[assignment]
    embedder = MagicMock()
    embedder.ready = True
    embedder.model = "voyage-3"
    memory.embedder = embedder

    profile_rec = MemoryRecord(
        agent_name="bc3_profile",
        content="Coachee Nguyễn Test, stage S2 has product, target 100tr/tháng.",
        venture="breakout",
        customer_id=99999,
        category="profile",
    )
    task_rec = MemoryRecord(
        agent_name="bc3_task",
        content="Tuần này coachee chạy ads 200k/ngày test ROAS.",
        venture="breakout",
        customer_id=99999,
        category="task",
    )
    conv_rec = MemoryRecord(
        agent_name="bc6_cskh_faq_haiku",
        content="Coachee hỏi giá khoá Coaching 50tr.",
        venture="breakout",
        customer_id=99999,
        category="conversation",
    )
    canon_rec = MemoryRecord(
        agent_name="bc3_profile",
        content="Breakout Coaching 50tr 6 tháng, ladder tier cao nhất.",
        venture="breakout",
        category="pricing",
    )

    async def fake_retrieve(
        query: str,
        *,
        k: int = 10,
        agent_name: Optional[str] = None,
        venture: Optional[str] = None,
        customer_id: Optional[int] = None,
        category: Optional[str] = None,
        categories: Optional[list[str]] = None,
        max_age_days: Optional[int] = None,
    ) -> list[MemoryRecord]:
        if category == "profile":
            return [profile_rec]
        if category == "task":
            return [task_rec]
        if category == "conversation":
            return [conv_rec]
        if categories:
            return [canon_rec]
        return []

    memory.retrieve = fake_retrieve  # type: ignore[assignment]

    scheduler = Scheduler(config=SchedulerConfig(), memory=memory)
    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        user_id="99999",
        venture_context="breakout",
        trigger_event="coaching.pre_call",
        payload={"content": "weekly session focus chạy ads"},
    )
    new_ctx = await scheduler._auto_inject(ctx)
    sources = [g["source"] for g in new_ctx.injected_memories]
    print(f"  injected_memories sources={sources}")
    expected = {"profile", "task", "conversation", "canonical"}
    ok = expected.issubset(set(sources))
    assert ok, f"Missing tier(s): {expected - set(sources)}"
    print("  OK 4 tier injected (profile + task + conversation + canonical)")
    return True


# ============================================================
# Test 3 + 4: BC10 fast / slow path
# ============================================================
async def test_bc10_fast_path() -> bool:
    """Pre-seed Profile + Task vào ctx → BC10 fast path, NOT call
    _fetch_customer_feedback or _fetch_customer_360."""
    print("\n[TEST 3] BC10 fast path skip DB fetches")
    from agents.bc10_coaching_delivery import BC10CoachingDelivery

    llm = MagicMock()
    llm.ready = True

    # Stub LLM response tool_use
    fake_tool_block = MagicMock()
    fake_tool_block.type = "tool_use"
    fake_tool_block.name = "submit_pre_call_brief"
    fake_tool_block.input = {
        "customer_summary": (
            "Coachee Nguyễn Test stage S2. Target 100tr/tháng. "
            "Đang chạy ads test ROAS. Concern về landing page. "
            "Buổi này tập trung tối ưu funnel."
        ),
        "top_wins": ["Setup store xong + chạy ads 3 ngày"],
        "top_challenges": ["ROAS chưa profitable"],
        "suggested_agenda": [
            {"minutes": 10, "block": "Check action items"},
            {"minutes": 30, "block": "Deep dive landing optimization"},
            {"minutes": 20, "block": "Commit tuần tới"},
        ],
        "questions_for_anna": [
            "Em thấy điểm nào landing yếu nhất?",
            "Tuần này em thử thay gì?",
            "Ngân sách ads em tính tiếp thế nào?",
        ],
        "watch_out": [],
    }
    fake_resp = MagicMock()
    fake_resp.content = [fake_tool_block]
    llm.client = MagicMock()
    llm.client.messages = MagicMock()
    llm.client.messages.create = AsyncMock(return_value=fake_resp)

    memory = MagicMock()
    memory.ready = False  # force fast path uses only injected
    memory.dsn = None

    bc10 = BC10CoachingDelivery(llm=llm, memory=memory)

    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        user_id="99999",
        venture_context="breakout",
        trigger_event="coaching.pre_call",
        payload={
            "customer_id": 99999,
            "session_id": "sess_fast_001",
            "session_type": "weekly",
        },
        injected_memories=[
            {
                "source": "profile",
                "content": (
                    "- [bc3_profile | breakout | 2026-06-01] coachee "
                    "Nguyễn Test S2 has product target 100tr/tháng"
                ),
                "count": 1,
            },
            {
                "source": "task",
                "content": (
                    "- [bc3_task | breakout | 2026-06-05] tuần này chạy "
                    "ads 200k/ngày test ROAS landing yếu"
                ),
                "count": 1,
            },
        ],
    )

    os.environ["BC10_DRY_RUN"] = "1"
    fetch_360_mock = AsyncMock(return_value=None)
    fetch_fb_mock = AsyncMock(return_value=[])
    fetch_mem_mock = AsyncMock(return_value=[])

    with patch.object(bc10, "_fetch_customer_360", new=fetch_360_mock), patch.object(
        bc10, "_fetch_customer_feedback", new=fetch_fb_mock
    ), patch.object(bc10, "_fetch_coaching_memories", new=fetch_mem_mock):
        result = await bc10.run(ctx)

    print(f"  success={result.success} path={result.output_payload.get('path')}")
    assert result.success is True, "fast path phải success"
    assert result.output_payload.get("path") == "fast", "không chạy fast path"
    assert fetch_360_mock.await_count == 0, (
        f"fast path KHÔNG được call _fetch_customer_360, "
        f"nhưng đã call {fetch_360_mock.await_count} lần"
    )
    assert fetch_fb_mock.await_count == 0, (
        "fast path KHÔNG được call _fetch_customer_feedback"
    )
    assert fetch_mem_mock.await_count == 0, (
        "fast path KHÔNG được call _fetch_coaching_memories"
    )
    print("  OK BC10 fast path skip 3 DB fetches")
    return True


async def test_bc10_slow_path_fallback() -> bool:
    """Không có Profile + Task injected → BC10 fallback re-analyze (slow path)."""
    print("\n[TEST 4] BC10 slow path fallback")
    from agents.bc10_coaching_delivery import BC10CoachingDelivery

    llm = MagicMock()
    llm.ready = True
    fake_tool_block = MagicMock()
    fake_tool_block.type = "tool_use"
    fake_tool_block.name = "submit_pre_call_brief"
    fake_tool_block.input = {
        "customer_summary": "A. B. C. D. E.",
        "top_wins": [],
        "top_challenges": [],
        "suggested_agenda": [
            {"minutes": 60, "block": "Default"},
            {"minutes": 0, "block": "x"},
            {"minutes": 0, "block": "y"},
        ],
        "questions_for_anna": ["a?", "b?", "c?"],
        "watch_out": [],
    }
    fake_resp = MagicMock()
    fake_resp.content = [fake_tool_block]
    llm.client = MagicMock()
    llm.client.messages = MagicMock()
    llm.client.messages.create = AsyncMock(return_value=fake_resp)

    memory = MagicMock()
    memory.ready = False
    memory.dsn = "postgres://fake"
    memory.retrieve = AsyncMock(return_value=[])

    bc10 = BC10CoachingDelivery(llm=llm, memory=memory)

    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        user_id="99999",
        venture_context="breakout",
        trigger_event="coaching.pre_call",
        payload={
            "customer_id": 99999,
            "session_id": "sess_slow_001",
            "session_type": "weekly",
        },
        injected_memories=[],  # KHÔNG có pre-processed Profile/Task
    )

    os.environ["BC10_DRY_RUN"] = "1"
    fetch_360_mock = AsyncMock(
        return_value={
            "id": 99999,
            "full_name": "Nguyễn Slow",
            "ltv_vnd": 50_000_000,
            "current_stage": "S2",
            "ventures_active": ["breakout_coaching"],
            "notes": "kickoff note",
        }
    )
    fetch_fb_mock = AsyncMock(return_value=[])
    fetch_mem_mock = AsyncMock(return_value=[])

    with patch.object(bc10, "_fetch_customer_360", new=fetch_360_mock), patch.object(
        bc10, "_fetch_customer_feedback", new=fetch_fb_mock
    ), patch.object(bc10, "_fetch_coaching_memories", new=fetch_mem_mock):
        result = await bc10.run(ctx)

    print(f"  success={result.success}")
    assert result.success is True, "slow path phải success"
    assert result.output_payload.get("path") != "fast", (
        "slow path không được dán flag path=fast"
    )
    assert fetch_360_mock.await_count >= 1, (
        "slow path PHẢI call _fetch_customer_360"
    )
    print(
        f"  OK BC10 slow path called _fetch_customer_360 "
        f"{fetch_360_mock.await_count}x + customer_feedback "
        f"{fetch_fb_mock.await_count}x"
    )
    return True


# ============================================================
# Test 5: BC6 fast vs slow path
# ============================================================
async def test_bc6_fast_vs_slow_path() -> bool:
    """BC6 fast path: pre-injected Profile/Task → skip _retrieve_context.
    Slow path: empty injected → call _retrieve_context."""
    print("\n[TEST 5] BC6 fast vs slow path")
    from agents.bc6_cskh_faq_haiku import BC6CSKHFAQHaiku

    llm = MagicMock()
    llm.ready = True
    fake_tool_block = MagicMock()
    fake_tool_block.type = "tool_use"
    fake_tool_block.name = "submit_faq_reply"
    fake_tool_block.input = {
        "verdict": "AUTO_REPLY",
        "confidence": 85,
        "reply_text": "Khoá Breakout Coaching 50tr 6 tháng nhé bạn.",
        "reason": "FAQ pricing trực tiếp từ pre-injected canonical",
        "topic": "pricing",
    }
    fake_resp = MagicMock()
    fake_resp.content = [fake_tool_block]
    llm.client = MagicMock()
    llm.client.messages = MagicMock()
    llm.client.messages.create = AsyncMock(return_value=fake_resp)

    memory = MagicMock()
    memory.ready = True
    memory.dsn = "postgres://fake"
    memory.retrieve = AsyncMock(return_value=[])
    memory.to_natural_language = AsyncMock(return_value="")

    bc6 = BC6CSKHFAQHaiku(llm=llm, memory=memory)

    # FAST: pre-injected
    ctx_fast = ExecutionContext(
        run_id=str(uuid.uuid4()),
        user_id="12345",
        venture_context="breakout",
        trigger_event="cskh.message.in",
        payload={
            "message_text": "Khoá Breakout giá bao nhiêu?",
            "customer_id": 12345,
            "channel": "ghl_chat",
        },
        injected_memories=[
            {
                "source": "profile",
                "content": "- [bc3_profile | breakout | 2026-06-01] khách quan tâm coaching",
                "count": 1,
            },
            {
                "source": "canonical",
                "content": "- [bc3 | breakout | 2026-06-01] Coaching 50tr 6 tháng",
                "count": 1,
            },
        ],
    )
    os.environ["BC6_DRY_RUN"] = "1"
    with patch.object(
        bc6, "_retrieve_context", new=AsyncMock(return_value="")
    ) as retrieve_mock:
        res_fast = await bc6.run(ctx_fast)
    print(f"  fast: success={res_fast.success} retrieve_called={retrieve_mock.await_count}")
    assert res_fast.success is True
    assert retrieve_mock.await_count == 0, (
        "BC6 fast path KHÔNG được call _retrieve_context"
    )

    # SLOW: empty injected
    ctx_slow = ExecutionContext(
        run_id=str(uuid.uuid4()),
        user_id="12345",
        venture_context="breakout",
        trigger_event="cskh.message.in",
        payload={
            "message_text": "Khoá Breakout giá bao nhiêu?",
            "customer_id": 12345,
            "channel": "ghl_chat",
        },
        injected_memories=[],
    )
    with patch.object(
        bc6, "_retrieve_context", new=AsyncMock(return_value="")
    ) as retrieve_mock_slow:
        res_slow = await bc6.run(ctx_slow)
    print(
        f"  slow: success={res_slow.success} "
        f"retrieve_called={retrieve_mock_slow.await_count}"
    )
    assert res_slow.success is True
    assert retrieve_mock_slow.await_count == 1, (
        "BC6 slow path PHẢI call _retrieve_context"
    )
    print("  OK BC6 fast skip retrieve, slow call retrieve")
    return True


# ============================================================
# Main runner
# ============================================================
async def main() -> int:
    tests = [
        ("retrieve_category_filter", test_retrieve_category_filter),
        ("scheduler_auto_inject_tiers", test_scheduler_auto_inject_tiers),
        ("bc10_fast_path", test_bc10_fast_path),
        ("bc10_slow_path_fallback", test_bc10_slow_path_fallback),
        ("bc6_fast_vs_slow_path", test_bc6_fast_vs_slow_path),
    ]
    results: list[tuple[str, bool, str]] = []
    for name, fn in tests:
        try:
            ok = await fn()
            results.append((name, ok, ""))
        except AssertionError as exc:
            results.append((name, False, f"AssertionError: {exc}"))
        except Exception as exc:  # noqa: BLE001
            results.append((name, False, f"{type(exc).__name__}: {exc}"))

    print("\n=== RESULTS ===")
    all_ok = True
    for name, ok, err in results:
        status = "OK" if ok else "FAIL"
        print(f"  {name}: {status}{(' ' + err) if err else ''}")
        all_ok = all_ok and ok

    if all_ok:
        print(f"\nOK Sprint 5 personalization test passed ({len(tests)}/{len(tests)})")
        return 0
    print("\nFAIL Sprint 5 personalization test")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
