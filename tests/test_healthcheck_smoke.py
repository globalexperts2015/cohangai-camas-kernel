"""StandaloneHealthcheck smoke test.

Chạy:
    cd cohangai/services/camas-kernel
    HEALTHCHECK_DRY_RUN=1 /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python tests/test_healthcheck_smoke.py

DRY_RUN bắt buộc:
- Skip Telegram send (CRITICAL/WARNING streak)
- HTTP probe service THẬT (8 URL public)
- DB queries chạy thật nếu có DATABASE_URL

Test 3 event:
1. healthcheck.system_5min → success=True, status ∈ {ok, warning, critical}, probes ≥ 5
2. healthcheck.on_demand → success=True, returns JSON payload
3. Unknown event → success=False
"""
from __future__ import annotations

import asyncio
import json
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

from agents.standalone_healthcheck import StandaloneHealthcheck  # noqa: E402
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer, VoyageEmbedder  # noqa: E402


async def main() -> int:
    os.environ.setdefault("HEALTHCHECK_DRY_RUN", "1")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    llm = LLMLayer(api_key=api_key) if api_key else LLMLayer(api_key="dummy")

    voyage_key = os.getenv("VOYAGE_API_KEY", "")
    embedder = VoyageEmbedder(api_key=voyage_key) if voyage_key else None
    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
    memory = MemoryLayer(dsn=dsn, embedder=embedder)

    agent = StandaloneHealthcheck(llm=llm, memory=memory)
    assert agent.name == "standalone_healthcheck"
    assert agent.autonomy_level.value == "L1"
    assert agent.escalate_to.value == "telegram_breakout_ops"
    assert len(agent.services) >= 5, "Phải có ≥5 service config"

    # Test 1: unknown event
    ctx_unknown = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="some.random.event",
        payload={},
    )
    res_unknown = await agent.run(ctx_unknown)
    print(
        f"[unknown event] success={res_unknown.success} "
        f"output={res_unknown.output_text}"
    )
    assert res_unknown.success is False
    assert "không xử lý" in (res_unknown.output_text or "")

    # Test 2: healthcheck.system_5min (real HTTP probes)
    ctx_system = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="healthcheck.system_5min",
        payload={},
    )
    print("Calling StandaloneHealthcheck system_5min (real probes, DRY_RUN)...")
    res_system = await agent.run(ctx_system)
    print("---")
    print(f"success={res_system.success}")
    print(f"status={res_system.output_payload.get('status')}")
    print(f"send_required={res_system.output_payload.get('send_required')}")
    print(f"sent_ok={res_system.output_payload.get('sent_ok')}")
    print("--- probes ---")
    for p in res_system.output_payload.get("probes", []):
        print(f"  {p}")
    print("--- postgres ---")
    print(res_system.output_payload.get("postgres"))
    print("--- output_text ---")
    print(res_system.output_text)
    print("--- END ---")
    assert res_system.success is True
    assert res_system.output_payload.get("status") in {
        "ok",
        "warning",
        "critical",
    }
    probes = res_system.output_payload.get("probes", [])
    assert len(probes) >= 5, f"Phải probe ≥5 service, got {len(probes)}"
    assert res_system.emitted_memories, "system_5min phải emit memory"
    mem = res_system.emitted_memories[0]
    assert mem["agent_name"] == "standalone_healthcheck"
    assert "healthcheck" in mem["tags"]
    assert mem.get("venture") == "all"

    # Test 3: healthcheck.on_demand
    ctx_on_demand = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="healthcheck.on_demand",
        payload={},
    )
    print("Calling StandaloneHealthcheck on_demand (real probes)...")
    res_on_demand = await agent.run(ctx_on_demand)
    print(
        f"on_demand success={res_on_demand.success} "
        f"status={res_on_demand.output_payload.get('status')}"
    )
    assert res_on_demand.success is True
    assert res_on_demand.output_payload.get("event") == "healthcheck.on_demand"
    # output_text phải parse được như JSON
    try:
        json.loads(res_on_demand.output_text or "")
    except Exception as exc:  # noqa: BLE001
        print(f"on_demand output_text không parse được JSON: {exc}")
        return 1

    try:
        await memory.close()
    except Exception:  # noqa: BLE001
        pass

    print("---")
    print("OK StandaloneHealthcheck smoke test passed (3/3)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
