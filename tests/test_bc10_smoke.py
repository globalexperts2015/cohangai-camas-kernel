"""BC10 Coaching Delivery smoke test.

Chạy:
    cd cohangai/services/camas-kernel
    BC10_DRY_RUN=1 /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python \\
        tests/test_bc10_smoke.py

DRY_RUN bắt buộc cho local test:
- Skip Telegram send
- Skip email send
- Skip customer_360.notes append
- Vẫn gọi LLM thật (cần ANTHROPIC_API_KEY)

Test 4 trigger event:
1. coaching.pre_call mock customer → success=True (graceful nếu DB rỗng)
2. coaching.post_call mock transcript → success=True, action_items extracted
3. coaching.weekly_checkin dry-run → success=True, check-in question generated
4. Unknown event → success=False
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    env_path = ROOT.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from agents.bc10_coaching_delivery import BC10CoachingDelivery  # noqa: E402
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer, VoyageEmbedder  # noqa: E402


MOCK_CUSTOMER = {
    "id": 99999,
    "full_name": "Nguyễn Test Coachee",
    "email": "test.coachee@example.com",
    "phone": "+84900000000",
    "ltv_vnd": 50_000_000,
    "current_stage": "S2_has_product",
    "ventures_active": ["breakout_coaching"],
    "notes": (
        "[2026-05-30] kickoff: coachee bán mỹ phẩm trên Shopee 2 năm, "
        "muốn build Shopify riêng, target 100tr/tháng sau 6 tháng coaching. "
        "Big concern: lo không có khách qua web own."
    ),
}

MOCK_FEEDBACK = [
    {
        "feedback_type": "pain",
        "content_summary": "Sợ đầu tư thời gian xây store mà không ra đơn.",
        "sentiment": -0.4,
        "theme_tags": ["niem-tin", "rui-ro"],
        "created_at": None,
    },
    {
        "feedback_type": "win",
        "content_summary": "Đã set up Shopify store thành công + import product.",
        "sentiment": 0.7,
        "theme_tags": ["tien-do", "store-setup"],
        "created_at": None,
    },
]

MOCK_MEMORIES = [
    {
        "content": "Pre-call brief weekly customer=Nguyễn Test, focus chạy ads.",
        "tags": ["coaching", "pre_call", "weekly"],
        "created_at": None,
        "retrieval_count": 1,
    },
]


async def main() -> int:
    os.environ.setdefault("BC10_DRY_RUN", "1")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("FAIL: ANTHROPIC_API_KEY chưa set")
        return 1

    llm = LLMLayer(api_key=api_key)
    assert llm.ready, "LLMLayer chưa init AsyncAnthropic"

    voyage_key = os.getenv("VOYAGE_API_KEY", "")
    embedder = VoyageEmbedder(api_key=voyage_key) if voyage_key else None
    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
    memory = MemoryLayer(dsn=dsn, embedder=embedder)

    bc10 = BC10CoachingDelivery(llm=llm, memory=memory)
    assert bc10.name == "bc10_coaching_delivery"
    assert bc10.autonomy_level.value == "L2"

    results: list[tuple[str, bool]] = []

    # =========================================================
    # Test 4 (chạy đầu cho fast): unknown event
    # =========================================================
    ctx_unknown = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="some.random.event",
        payload={},
    )
    res_unknown = await bc10.run(ctx_unknown)
    print(
        f"[unknown event] success={res_unknown.success} "
        f"text={res_unknown.output_text}"
    )
    ok4 = res_unknown.success is False and "không xử lý" in (
        res_unknown.output_text or ""
    )
    results.append(("unknown_event", ok4))

    # =========================================================
    # Test 1: coaching.pre_call (mock DB calls)
    # =========================================================
    print("\nCalling BC10 coaching.pre_call (mock DB, real LLM Opus)...")
    ctx_pre = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="coaching.pre_call",
        payload={
            "customer_id": MOCK_CUSTOMER["id"],
            "session_id": "sess_001",
            "session_type": "weekly",
        },
    )
    with patch.object(
        bc10,
        "_fetch_customer_360",
        new=AsyncMock(return_value=MOCK_CUSTOMER),
    ), patch.object(
        bc10,
        "_fetch_customer_feedback",
        new=AsyncMock(return_value=MOCK_FEEDBACK),
    ), patch.object(
        bc10,
        "_fetch_coaching_memories",
        new=AsyncMock(return_value=MOCK_MEMORIES),
    ), patch.object(
        bc10.memory,
        "retrieve",
        new=AsyncMock(return_value=[]),
    ):
        res_pre = await bc10.run(ctx_pre)

    print(f"success={res_pre.success}")
    if res_pre.output_text:
        print("--- PRE-CALL BRIEF OUTPUT ---")
        print(res_pre.output_text[:1500])
        print("--- END ---")
    brief = (res_pre.output_payload or {}).get("brief") or {}
    summary = brief.get("customer_summary", "")
    agenda = brief.get("suggested_agenda") or []
    questions = brief.get("questions_for_anna") or []
    print(
        f"summary_len={len(summary)} agenda_blocks={len(agenda)} "
        f"questions={len(questions)} memories_emitted="
        f"{len(res_pre.emitted_memories)}"
    )
    sentence_count = len([s for s in summary.split(".") if s.strip()])
    ok1 = (
        res_pre.success is True
        and 3 <= sentence_count <= 8  # 5 sentence target, tolerance
        and len(agenda) >= 3
        and len(questions) >= 3
        and len(res_pre.emitted_memories) >= 1
    )
    results.append(("pre_call", ok1))

    # =========================================================
    # Test 2: coaching.post_call (mock transcript)
    # =========================================================
    print("\nCalling BC10 coaching.post_call (mock transcript, real LLM)...")
    mock_transcript = (
        "Hằng: Chào em, tuần này thế nào? "
        "Coachee: Dạ chị, em đã setup xong store và chạy thử ads 200k/ngày 3 ngày. "
        "Hằng: Tốt vậy, có đơn nào chưa? "
        "Coachee: Em có 2 đơn nhỏ tổng 450k chị, nhưng ROAS chưa profitable. "
        "Hằng: OK, ta cần tối ưu landing trước khi tăng ngân sách. "
        "Em commit tuần này làm 3 việc: 1) viết lại headline + bullet point, "
        "2) thêm 5 review thật từ khách Shopee cũ, 3) test thumbnail mới. "
        "Coachee: Dạ em làm trước thứ 6 tuần này chị. "
        "Hằng: Anh chị review proposal pricing bundle xong gửi em thứ 5. "
        "Coachee: Cảm ơn chị, em hơi lo phần ad copy nhưng sẽ thử. "
        "Hằng: Buổi sau ta đi sâu vào funnel page + retarget setup."
    )
    ctx_post = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="coaching.post_call",
        payload={
            "customer_id": MOCK_CUSTOMER["id"],
            "recording_id": "rec_001",
            "session_type": "weekly",
            "transcript": mock_transcript,
            "participants": [
                {"email": MOCK_CUSTOMER["email"]},
            ],
        },
    )
    with patch.object(
        bc10,
        "_fetch_customer_360",
        new=AsyncMock(return_value=MOCK_CUSTOMER),
    ):
        res_post = await bc10.run(ctx_post)

    print(f"success={res_post.success}")
    if res_post.output_text:
        print("--- POST-CALL OUTPUT ---")
        print(res_post.output_text[:1500])
        print("--- END ---")
    analysis = (res_post.output_payload or {}).get("analysis") or {}
    cust_actions = analysis.get("customer_action_items") or []
    next_focus = analysis.get("next_session_focus") or ""
    print(
        f"customer_actions={len(cust_actions)} "
        f"anna_actions={len(analysis.get('anna_action_items') or [])} "
        f"next_focus_len={len(next_focus)}"
    )
    ok2 = (
        res_post.success is True
        and len(cust_actions) >= 1
        and len(next_focus) > 0
        and len(res_post.emitted_memories) >= 1
    )
    results.append(("post_call", ok2))

    # =========================================================
    # Test 3: coaching.weekly_checkin (mock 1 customer)
    # =========================================================
    print("\nCalling BC10 coaching.weekly_checkin (mock 1 customer, real Haiku)...")
    ctx_checkin = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="coaching.weekly_checkin",
        payload={},
    )
    with patch.object(
        bc10,
        "_fetch_active_coaching_customers",
        new=AsyncMock(return_value=[MOCK_CUSTOMER]),
    ), patch.object(
        bc10,
        "_fetch_last_post_call_actions",
        new=AsyncMock(return_value=[]),
    ):
        res_checkin = await bc10.run(ctx_checkin)

    print(f"success={res_checkin.success} text={res_checkin.output_text}")
    checkins = (res_checkin.output_payload or {}).get("checkins") or []
    print(f"checkins_count={len(checkins)}")
    for ck in checkins[:3]:
        print(f"  - cust={ck.get('name')} question={ck.get('question')[:120]}")
    ok3 = (
        res_checkin.success is True
        and len(checkins) >= 1
        and len(checkins[0].get("question") or "") > 0
        and len(res_checkin.emitted_memories) >= 1
    )
    results.append(("weekly_checkin", ok3))

    try:
        await memory.close()
    except Exception:  # noqa: BLE001
        pass

    print("\n=== RESULTS ===")
    all_ok = True
    for name, ok in results:
        print(f"  {name}: {'OK' if ok else 'FAIL'}")
        all_ok = all_ok and ok

    if all_ok:
        print("\nOK BC10 smoke test passed (4/4)")
        return 0
    print("\nFAIL BC10 smoke test")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
