"""BC3 Feedback Loop smoke test.

Chạy:
    cd cohangai/services/camas-kernel
    BC3_DRY_RUN=1 /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python tests/test_bc3_smoke.py

DRY_RUN bắt buộc cho local test:
- Skip Telegram send
- Skip DB INSERT vào customer_feedback
- Vẫn gọi LLM thật (cần ANTHROPIC_API_KEY)

Test 3 trigger event:
1. unknown event → success=False
2. feedback.tally.submitted (sample onboarding form data) → classify + memory emit
3. feedback.weekly_digest → query (sẽ rỗng nếu DB không có data 7 ngày), check output
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

from agents.bc3_feedback_loop import BC3FeedbackLoop  # noqa: E402
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer, VoyageEmbedder  # noqa: E402


async def main() -> int:
    os.environ.setdefault("BC3_DRY_RUN", "1")

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

    bc3 = BC3FeedbackLoop(llm=llm, memory=memory)
    assert bc3.name == "bc3_feedback_loop"
    assert bc3.autonomy_level.value == "L2"

    # Test 1: unknown event
    ctx_unknown = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="some.random.event",
        payload={},
    )
    res_unknown = await bc3.run(ctx_unknown)
    print(f"[unknown event] success={res_unknown.success} text={res_unknown.output_text}")
    assert res_unknown.success is False
    assert "không xử lý" in (res_unknown.output_text or "")

    # Test 2: feedback.tally.submitted (sample onboarding form)
    sample_tally = {
        "form_name": "onboarding",
        "customer_id": None,
        "event_id": None,
        "fields": [
            {"label": "Tên", "value": "Lan Anh"},
            {"label": "Email", "value": "lananh@example.com"},
            {
                "label": "Lý do tham gia Breakout?",
                "value": (
                    "Em đang bán hàng trên Shopee mà phí ngày càng cao, "
                    "muốn build store riêng nhưng không biết bắt đầu từ đâu. "
                    "Thấy chị Hằng chia sẻ thực tế nên đăng ký."
                ),
            },
            {
                "label": "Bạn lo lắng gì nhất khi build store?",
                "value": (
                    "Em sợ làm xong không có khách, đầu tư thời gian + tiền "
                    "mà không ra đơn. Anh chồng em cũng nói thử nhưng em "
                    "không tự tin."
                ),
            },
            {
                "label": "Bạn mong đạt được gì sau 90 ngày?",
                "value": "Có ít nhất 30 đơn/tháng, biết chạy ads cơ bản.",
            },
        ],
    }
    ctx_tally = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="feedback.tally.submitted",
        payload=sample_tally,
    )
    print("Calling BC3 feedback.tally.submitted (DRY_RUN, no DB insert)...")
    res_tally = await bc3.run(ctx_tally)
    print("---")
    print(f"success={res_tally.success}")
    print(f"output_text={res_tally.output_text}")
    classification = res_tally.output_payload.get("classification", {})
    print(f"feedback_type={classification.get('feedback_type')}")
    print(f"sentiment={classification.get('sentiment')}")
    print(f"theme_tags={classification.get('theme_tags')}")
    print(f"content_summary={classification.get('content_summary')}")
    print(f"emitted_memories_count={len(res_tally.emitted_memories)}")
    assert res_tally.success is True, f"Tally classify fail: {res_tally.output_text}"
    assert classification.get("feedback_type") in (
        "pain", "gain", "win", "objection", "feature_request", "complaint", "praise"
    ), f"Invalid feedback_type: {classification}"
    assert classification.get("sentiment") is not None
    assert classification.get("theme_tags"), "theme_tags must be non-empty"
    assert res_tally.emitted_memories, "Tally must emit memory"

    # Test 3: feedback.weekly_digest
    ctx_digest = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="feedback.weekly_digest",
        payload={},
    )
    print("\nCalling BC3 feedback.weekly_digest (DRY_RUN, no Telegram)...")
    res_digest = await bc3.run(ctx_digest)
    print("---")
    print(f"success={res_digest.success}")
    print(f"events_count={res_digest.output_payload.get('events_count')}")
    print(f"dry_run={res_digest.output_payload.get('dry_run')}")
    if res_digest.output_payload.get("events_count", 0) > 0:
        print("--- DIGEST OUTPUT ---")
        print(res_digest.output_text)
        print("--- END DIGEST ---")
        print(
            f"emitted_memories_count={len(res_digest.emitted_memories)} "
            "(1 digest + N auto_fed records)"
        )
    else:
        print(f"output_text={res_digest.output_text}")
        print("(no feedback rows in window, expected on fresh DB)")
    assert res_digest.success is True

    try:
        await memory.close()
    except Exception:  # noqa: BLE001
        pass

    print("---")
    print("OK BC3 smoke test passed (3/3)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
