"""BC1 Team Leader smoke test.

Chạy:
    cd cohangai/services/camas-kernel
    BC1_DRY_RUN=1 /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python tests/test_bc1_smoke.py

DRY_RUN bắt buộc cho local test để tránh spam Telegram group thật.
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

from agents.bc1_team_leader import BC1TeamLeader  # noqa: E402
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer, VoyageEmbedder  # noqa: E402


async def main() -> int:
    # Force DRY_RUN để khỏi spam Telegram group thật
    os.environ.setdefault("BC1_DRY_RUN", "1")

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

    bc1 = BC1TeamLeader(llm=llm, memory=memory)
    assert bc1.name == "bc1_team_leader"
    assert bc1.autonomy_level.value == "L1"

    # Test 1: unknown event → success=False
    ctx_unknown = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="some.random.event",
        payload={},
    )
    res_unknown = await bc1.run(ctx_unknown)
    print(f"[unknown event] success={res_unknown.success} output={res_unknown.output_text}")
    assert res_unknown.success is False
    assert "không xử lý" in (res_unknown.output_text or "")

    # Test 2: rollup.morning
    ctx_morning = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="rollup.morning",
        payload={},
    )
    print("Calling BC1 rollup.morning (DRY_RUN)...")
    res_morning = await bc1.run(ctx_morning)
    print("---")
    print(f"success={res_morning.success}")
    print(f"dry_run={res_morning.output_payload.get('dry_run')}")
    print(f"sent_ok={res_morning.output_payload.get('sent_ok')}")
    print(f"window_hours={res_morning.output_payload.get('window_hours')}")
    print("--- DIGEST (morning) ---")
    print(res_morning.output_text)
    print("--- END DIGEST ---")
    assert res_morning.success is True
    assert res_morning.output_payload.get("kind") == "morning"
    assert res_morning.output_payload.get("dry_run") is True
    assert res_morning.emitted_memories, "morning phải emit memory"

    # Test 3: rollup.evening
    ctx_evening = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="rollup.evening",
        payload={},
    )
    print("Calling BC1 rollup.evening (DRY_RUN)...")
    res_evening = await bc1.run(ctx_evening)
    print("---")
    print(f"success={res_evening.success}")
    print(f"window_hours={res_evening.output_payload.get('window_hours')}")
    print("--- DIGEST (evening) ---")
    print(res_evening.output_text)
    print("--- END DIGEST ---")
    assert res_evening.success is True
    assert res_evening.output_payload.get("kind") == "evening"
    assert res_evening.output_payload.get("window_hours") == 12

    try:
        await memory.close()
    except Exception:  # noqa: BLE001
        pass

    print("---")
    print("OK BC1 smoke test passed (3/3)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
