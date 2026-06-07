"""BC4 K2 Launch smoke test.

Chạy:
    cd cohangai/services/camas-kernel
    BC4_DRY_RUN=1 /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python tests/test_bc4_smoke.py

DRY_RUN bắt buộc cho local test:
- Skip Telegram send
- Vẫn gọi LLM thật (cần ANTHROPIC_API_KEY)

Test 3 trigger event:
1. unknown event → success=False
2. launch.t_minus_3 → status report chứa checklist items
3. launch.post_24h với mock_stats → outcome report mention VND total
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

from agents.bc4_k2_launch import BC4K2Launch  # noqa: E402
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer, VoyageEmbedder  # noqa: E402


async def main() -> int:
    os.environ.setdefault("BC4_DRY_RUN", "1")

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

    bc4 = BC4K2Launch(llm=llm, memory=memory)
    assert bc4.name == "bc4_k2_launch"
    assert bc4.autonomy_level.value == "L3"

    # Test 1: unknown event
    ctx_unknown = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="some.random.event",
        payload={},
    )
    res_unknown = await bc4.run(ctx_unknown)
    print(f"[unknown event] success={res_unknown.success} text={res_unknown.output_text}")
    assert res_unknown.success is False
    assert "không xử lý" in (res_unknown.output_text or "")

    # Test 2: launch.t_minus_3 dry-run
    ctx_t3 = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="launch.t_minus_3",
        payload={"cohort": "K2"},
    )
    print("\nCalling BC4 launch.t_minus_3 (DRY_RUN)...")
    res_t3 = await bc4.run(ctx_t3)
    print("---")
    print(f"success={res_t3.success}")
    print(f"cohort={res_t3.output_payload.get('cohort')}")
    print(f"whitelist_count={res_t3.output_payload.get('whitelist_count')}")
    print(f"dry_run={res_t3.output_payload.get('dry_run')}")
    print("--- T-3 REPORT ---")
    print(res_t3.output_text)
    print("--- END REPORT ---")
    assert res_t3.success is True
    assert res_t3.output_payload.get("event") == "launch.t_minus_3"
    assert res_t3.output_payload.get("dry_run") is True
    assert res_t3.emitted_memories, "T-3 phải emit memory"
    # Verify checklist items có trong report
    t3_text = res_t3.output_text or ""
    assert "WK setup" in t3_text or "WebinarKit" in t3_text or "WK" in t3_text, (
        "T-3 report phải chứa WK item"
    )
    assert "GHL" in t3_text, "T-3 report phải chứa GHL item"
    assert "Whitelist" in t3_text or "whitelist" in t3_text, (
        "T-3 report phải chứa whitelist count"
    )

    # Test 3: launch.post_24h with mock stats → outcome mentions VND total
    mock_outcome = {
        "total_registered": 949,
        "total_paid": 73,
        "revenue_vnd": 67_950_000,  # vd: VIP 50 + Foundation 20 + Coaching 3
        "by_tier": {
            "vip": 50,
            "foundation": 20,
            "customer": 0,
            "growth": 0,
            "coaching": 3,
        },
        "error": None,
    }
    ctx_post = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="launch.post_24h",
        payload={"cohort": "K2", "mock_stats": mock_outcome},
    )
    print("\nCalling BC4 launch.post_24h (DRY_RUN, mock_stats)...")
    res_post = await bc4.run(ctx_post)
    print("---")
    print(f"success={res_post.success}")
    print(f"revenue_vnd={res_post.output_payload.get('revenue_vnd')}")
    print(f"revenue_aud={res_post.output_payload.get('revenue_aud')}")
    print(f"dry_run={res_post.output_payload.get('dry_run')}")
    print("--- OUTCOME REPORT ---")
    print(res_post.output_text)
    print("--- END REPORT ---")
    assert res_post.success is True
    assert res_post.output_payload.get("event") == "launch.post_24h"
    assert res_post.output_payload.get("revenue_vnd") == 67_950_000
    post_text = res_post.output_text or ""
    assert "VND" in post_text, "Outcome report phải mention VND"
    assert "67,950,000" in post_text or "67.950.000" in post_text, (
        "Outcome report phải show revenue total"
    )
    assert "K2" in post_text, "Outcome report phải mention cohort K2"
    assert res_post.emitted_memories, "post_24h phải emit memory"
    # Verify memory tag launch_outcome
    mem_tags = res_post.emitted_memories[0].get("tags", [])
    assert "launch_outcome" in mem_tags, (
        f"post_24h memory phải có tag launch_outcome, got: {mem_tags}"
    )

    try:
        await memory.close()
    except Exception:  # noqa: BLE001
        pass

    print("---")
    print("OK BC4 smoke test passed (3/3)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
