"""BC5 CDP Monitor smoke test.

Chạy:
    cd cohangai/services/camas-kernel
    BC5_DRY_RUN=1 /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python tests/test_bc5_smoke.py

DRY_RUN bắt buộc:
- Skip Telegram send (CRITICAL/WARNING streak)
- DB queries vẫn chạy thật (Postgres reuse pool)
- HTTP probe CDP webhook chạy thật

Test 3 event:
1. monitor.health_5min → success=True, status ∈ {ok, warning, critical}
2. monitor.daily_audit → success=True, output contains stats
3. Unknown event → success=False
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

from agents.bc5_cdp_monitor import BC5CDPMonitor  # noqa: E402
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer, VoyageEmbedder  # noqa: E402


async def main() -> int:
    os.environ.setdefault("BC5_DRY_RUN", "1")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    # BC5 không gọi LLM nhưng vẫn giữ LLMLayer để symmetry với BC1/BC3
    llm = LLMLayer(api_key=api_key) if api_key else LLMLayer(api_key="dummy")

    voyage_key = os.getenv("VOYAGE_API_KEY", "")
    embedder = VoyageEmbedder(api_key=voyage_key) if voyage_key else None
    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
    memory = MemoryLayer(dsn=dsn, embedder=embedder)

    bc5 = BC5CDPMonitor(llm=llm, memory=memory)
    assert bc5.name == "bc5_cdp_monitor"
    assert bc5.autonomy_level.value == "L1"
    assert bc5.escalate_to.value == "telegram_breakout_ops"

    # Test 1: unknown event → success=False
    ctx_unknown = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="some.random.event",
        payload={},
    )
    res_unknown = await bc5.run(ctx_unknown)
    print(
        f"[unknown event] success={res_unknown.success} "
        f"output={res_unknown.output_text}"
    )
    assert res_unknown.success is False
    assert "không xử lý" in (res_unknown.output_text or "")

    # Test 2: monitor.health_5min
    ctx_health = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="monitor.health_5min",
        payload={},
    )
    print("Calling BC5 monitor.health_5min (DRY_RUN)...")
    res_health = await bc5.run(ctx_health)
    print("---")
    print(f"success={res_health.success}")
    print(f"status={res_health.output_payload.get('status')}")
    print(f"send_required={res_health.output_payload.get('send_required')}")
    print(f"sent_ok={res_health.output_payload.get('sent_ok')}")
    print(f"checks={res_health.output_payload.get('checks')}")
    print("--- output_text ---")
    print(res_health.output_text)
    print("--- END ---")
    assert res_health.success is True
    assert res_health.output_payload.get("status") in {"ok", "warning", "critical"}
    assert res_health.emitted_memories, "health_5min phải emit memory"
    mem = res_health.emitted_memories[0]
    assert mem["agent_name"] == "bc5_cdp_monitor"
    assert "health_check" in mem["tags"]
    assert mem.get("venture") == "all"

    # Test 3: monitor.daily_audit
    ctx_audit = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="monitor.daily_audit",
        payload={},
    )
    print("Calling BC5 monitor.daily_audit (DRY_RUN)...")
    res_audit = await bc5.run(ctx_audit)
    print("---")
    print(f"success={res_audit.success}")
    print(f"status={res_audit.output_payload.get('status')}")
    print(f"stats={res_audit.output_payload.get('stats')}")
    print("--- DIGEST ---")
    print(res_audit.output_text)
    print("--- END DIGEST ---")
    assert res_audit.success is True
    assert "CDP Daily Audit" in (res_audit.output_text or "")
    assert "stats" in res_audit.output_payload
    assert res_audit.emitted_memories, "daily_audit phải emit memory"

    # Test 4 (bonus): monitor.on_demand
    ctx_on_demand = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="monitor.on_demand",
        payload={},
    )
    print("Calling BC5 monitor.on_demand (DRY_RUN)...")
    res_on_demand = await bc5.run(ctx_on_demand)
    print(f"on_demand success={res_on_demand.success} "
          f"status={res_on_demand.output_payload.get('status')}")
    assert res_on_demand.success is True
    assert res_on_demand.output_payload.get("event") == "monitor.on_demand"

    try:
        await memory.close()
    except Exception:  # noqa: BLE001
        pass

    print("---")
    print("OK BC5 smoke test passed (4/4)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
