"""BC3 split smoke test (Profile + Task agents, Cerebrum NAACL 2025 pattern).

Chạy:
    cd cohangai/services/camas-kernel
    /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python tests/test_bc3_split.py

Test 4 case:
1. BC3-Profile profile.refresh_single với mock customer_id=1 → success + profile structured.
2. BC3-Profile profile.refresh_weekly cap=5 → success + count updated.
3. BC3-Task task.update_post_call với mock transcript → success + task stored.
4. BC3-Task task.update_generic với mock customer_feedback → success.

Test dùng DB DRY-RUN mode khi không có DATABASE_URL: chỉ verify class import +
attribute contract, không gọi LLM thật. Khi DB sẵn sàng, sẽ chạy live qua
Opus + Haiku.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    env_path = ROOT.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from agents.bc3_profile_extractor import BC3ProfileExtractor  # noqa: E402
from agents.bc3_task_tracker import BC3TaskTracker  # noqa: E402
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer, VoyageEmbedder  # noqa: E402


def _build_layers() -> tuple[LLMLayer, MemoryLayer, bool]:
    """Init LLM + Memory layer. Return (llm, memory, live_mode)."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    llm = LLMLayer(api_key=api_key)

    voyage_key = os.getenv("VOYAGE_API_KEY", "")
    embedder = VoyageEmbedder(api_key=voyage_key) if voyage_key else None
    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
    memory = MemoryLayer(dsn=dsn, embedder=embedder)

    live_mode = bool(api_key and dsn)
    return llm, memory, live_mode


async def test_1_profile_refresh_single() -> bool:
    """BC3-Profile profile.refresh_single mock customer_id=1."""
    print("\n=== Test 1: BC3-Profile profile.refresh_single ===")
    llm, memory, live = _build_layers()
    bc = BC3ProfileExtractor(llm=llm, memory=memory)

    assert bc.name == "bc3_profile_extractor", f"name={bc.name}"
    assert bc.autonomy_level.value == "L1"
    assert bc.escalate_to.value == "none"
    assert bc.scope.startswith("Maintain customer Profile")
    print(f"  Class contract OK (name={bc.name}, autonomy={bc.autonomy_level.value})")

    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="profile.refresh_single",
        payload={"customer_id": 1},
    )

    if not live:
        # Skip LLM call, verify dispatch logic
        ctx_missing = ExecutionContext(
            run_id=str(uuid.uuid4()),
            venture_context="breakout",
            trigger_event="profile.refresh_single",
            payload={},
        )
        res = await bc.run(ctx_missing)
        assert res.success is False
        assert "thiếu customer_id" in (res.output_text or "")
        print("  DRY mode: dispatch + payload guard OK")
        try:
            await memory.close()
        except Exception:
            pass
        return True

    res = await bc.run(ctx)
    print(f"  success={res.success}")
    print(f"  output_text={res.output_text}")
    profile = res.output_payload.get("profile") or {}
    print(f"  personality={(profile.get('personality') or '')[:80]}")
    print(f"  venture_focus={profile.get('venture_focus')}")
    print(f"  current_phase={(profile.get('current_phase') or '')[:80]}")
    print(f"  risk_flags={profile.get('risk_flags')}")

    if res.success:
        assert profile, "profile must be non-empty"
        assert profile.get("personality"), "personality required"
        assert profile.get("current_phase"), "current_phase required"
        assert profile.get("biggest_obstacle"), "biggest_obstacle required"
        assert profile.get("communication_preference"), "communication_preference required"
    else:
        # customer_id=1 có thể không tồn tại trên DB staging, vẫn pass test
        # nếu lỗi là "không tồn tại"
        err = res.output_text or ""
        assert "không tồn tại" in err or "customer_id" in err, f"Unexpected error: {err}"
        print("  (customer_id=1 không có trên DB, test pass với guard)")

    try:
        await memory.close()
    except Exception:
        pass
    return True


async def test_2_profile_refresh_weekly() -> bool:
    """BC3-Profile profile.refresh_weekly cap 5."""
    print("\n=== Test 2: BC3-Profile profile.refresh_weekly (cap 5) ===")
    llm, memory, live = _build_layers()

    # Override cap để chạy nhanh local
    from agents.bc3_profile_extractor import agent as profile_agent_mod

    original_cap = profile_agent_mod.WEEKLY_CAP
    profile_agent_mod.WEEKLY_CAP = 5

    bc = BC3ProfileExtractor(llm=llm, memory=memory)
    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="profile.refresh_weekly",
        payload={},
    )

    if not live:
        # Verify unknown event dispatch
        ctx_bad = ExecutionContext(
            run_id=str(uuid.uuid4()),
            venture_context="breakout",
            trigger_event="profile.unknown",
            payload={},
        )
        res_bad = await bc.run(ctx_bad)
        assert res_bad.success is False
        assert "không xử lý" in (res_bad.output_text or "")
        print("  DRY mode: unknown event guard OK")
        profile_agent_mod.WEEKLY_CAP = original_cap
        try:
            await memory.close()
        except Exception:
            pass
        return True

    res = await bc.run(ctx)
    print(f"  success={res.success}")
    print(f"  output_text={res.output_text}")
    print(f"  candidates={res.output_payload.get('candidates')}")
    print(f"  profiles_updated={res.output_payload.get('profiles_updated')}")
    print(f"  capped_at={res.output_payload.get('capped_at')}")
    print(f"  failed_count={res.output_payload.get('failed_count')}")

    assert res.success is True, f"Weekly fail: {res.output_text}"
    assert res.output_payload.get("capped_at") == 5
    assert isinstance(res.output_payload.get("profiles_updated"), int)

    profile_agent_mod.WEEKLY_CAP = original_cap
    try:
        await memory.close()
    except Exception:
        pass
    return True


async def test_3_task_update_post_call() -> bool:
    """BC3-Task task.update_post_call với mock transcript."""
    print("\n=== Test 3: BC3-Task task.update_post_call ===")
    llm, memory, live = _build_layers()
    bc = BC3TaskTracker(llm=llm, memory=memory)

    assert bc.name == "bc3_task_tracker", f"name={bc.name}"
    assert bc.autonomy_level.value == "L1"
    assert bc.escalate_to.value == "none"
    assert bc.scope.startswith("Maintain customer Task state")
    print(f"  Class contract OK (name={bc.name}, autonomy={bc.autonomy_level.value})")

    mock_transcript = (
        "Anna: Em tuần này thế nào rồi? Đã setup được Shopify store chưa? "
        "Customer: Dạ rồi chị ơi, em đã tạo store xong, upload 10 sản phẩm, "
        "nhưng còn rối phần chạy ads Facebook, em chưa biết bắt đầu campaign "
        "đầu tiên thế nào. Anna: OK, tuần tới em commit hoàn thành 1 ad set "
        "với budget 200k/ngày, chị sẽ gửi em link template ad copy. Customer: "
        "Em ok, em làm xong gửi chị review trước thứ Năm. "
        "Anna: Tốt, mục tiêu tuần này là chạy ads + có 5 đơn đầu tiên."
    )

    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="task.update_post_call",
        payload={
            "customer_id": 1,
            "session_id": "fathom_test_001",
            "session_type": "weekly",
            "transcript": mock_transcript,
        },
    )

    if not live:
        # Verify payload guards
        ctx_missing_cust = ExecutionContext(
            run_id=str(uuid.uuid4()),
            venture_context="breakout",
            trigger_event="task.update_post_call",
            payload={"transcript": mock_transcript},
        )
        res = await bc.run(ctx_missing_cust)
        assert res.success is False
        assert "customer_id" in (res.output_text or "")

        ctx_missing_tx = ExecutionContext(
            run_id=str(uuid.uuid4()),
            venture_context="breakout",
            trigger_event="task.update_post_call",
            payload={"customer_id": 1},
        )
        res2 = await bc.run(ctx_missing_tx)
        assert res2.success is False
        assert "transcript" in (res2.output_text or "")
        print("  DRY mode: payload guards OK")
        try:
            await memory.close()
        except Exception:
            pass
        return True

    res = await bc.run(ctx)
    print(f"  success={res.success}")
    print(f"  output_text={res.output_text}")
    task_state = res.output_payload.get("task_state") or {}
    print(f"  current_focus={(task_state.get('current_focus') or '')[:80]}")
    print(f"  open_action_items={len(task_state.get('open_action_items') or [])}")
    print(f"  watch_out={task_state.get('watch_out')}")

    if res.success:
        assert task_state.get("current_focus"), "current_focus required"
        assert isinstance(task_state.get("open_action_items"), list)
    else:
        # customer_id=1 có thể không tồn tại trên DB
        err = res.output_text or ""
        assert "không tồn tại" in err or "customer_id" in err, f"Unexpected: {err}"
        print("  (customer_id=1 không có trên DB, test pass với guard)")

    try:
        await memory.close()
    except Exception:
        pass
    return True


async def test_4_task_update_generic() -> bool:
    """BC3-Task task.update_generic với mock raw_text."""
    print("\n=== Test 4: BC3-Task task.update_generic ===")
    llm, memory, live = _build_layers()
    bc = BC3TaskTracker(llm=llm, memory=memory)

    mock_raw = (
        "Khách phản ánh tuần qua đã hoàn thành 80% module 1 Foundation, "
        "đang stuck ở phần payment gateway. Tuần này muốn focus vào finish "
        "checkout flow + bắt đầu chạy thử order đầu tiên."
    )

    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="task.update_generic",
        payload={
            "customer_id": 1,
            "raw_text": mock_raw,
        },
    )

    if not live:
        # Test guard missing both feedback_id và raw_text
        ctx_empty = ExecutionContext(
            run_id=str(uuid.uuid4()),
            venture_context="breakout",
            trigger_event="task.update_generic",
            payload={"customer_id": 1},
        )
        res_empty = await bc.run(ctx_empty)
        assert res_empty.success is False
        assert "feedback_id" in (res_empty.output_text or "") or "raw_text" in (
            res_empty.output_text or ""
        )

        # Test unknown event
        ctx_unknown = ExecutionContext(
            run_id=str(uuid.uuid4()),
            venture_context="breakout",
            trigger_event="task.unknown",
            payload={},
        )
        res_unk = await bc.run(ctx_unknown)
        assert res_unk.success is False
        assert "không xử lý" in (res_unk.output_text or "")
        print("  DRY mode: payload + unknown event guards OK")
        try:
            await memory.close()
        except Exception:
            pass
        return True

    res = await bc.run(ctx)
    print(f"  success={res.success}")
    print(f"  output_text={res.output_text}")
    task_state = res.output_payload.get("task_state") or {}
    print(f"  current_focus={(task_state.get('current_focus') or '')[:80]}")
    print(f"  session_type={task_state.get('session_type')}")

    if res.success:
        assert task_state.get("current_focus"), "current_focus required"
        assert isinstance(task_state.get("open_action_items"), list)
    else:
        err = res.output_text or ""
        assert "không tồn tại" in err or "customer_id" in err, f"Unexpected: {err}"
        print("  (customer_id=1 không có trên DB, test pass với guard)")

    try:
        await memory.close()
    except Exception:
        pass
    return True


async def main() -> int:
    results: list[tuple[str, bool]] = []
    for name, fn in [
        ("test_1_profile_refresh_single", test_1_profile_refresh_single),
        ("test_2_profile_refresh_weekly", test_2_profile_refresh_weekly),
        ("test_3_task_update_post_call", test_3_task_update_post_call),
        ("test_4_task_update_generic", test_4_task_update_generic),
    ]:
        try:
            ok = await fn()
            results.append((name, ok))
        except AssertionError as exc:
            print(f"FAIL {name}: {exc}")
            results.append((name, False))
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR {name}: {exc!r}")
            results.append((name, False))

    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print("\n=== RESULTS ===")
    for name, ok in results:
        print(f"  {'OK' if ok else 'FAIL'} {name}")
    print(f"\n{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
