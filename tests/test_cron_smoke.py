"""6 cron agents smoke test, parametrized.

Chạy:
    cd cohangai/services/camas-kernel
    CRON_DRY_RUN=1 /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python tests/test_cron_smoke.py

DRY_RUN bắt buộc:
- Skip HTTP call thật (cdp-webhook + Telegram)
- DB queries vẫn chạy thật nếu DATABASE_URL set, fail-soft nếu không

Mỗi cron:
1. Trigger valid event → success=True
2. Trigger wrong event → success=False
3. Memory emitted với tag "cron"
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

from agents.cron_ads_pull import CronAdsPull  # noqa: E402
from agents.cron_dedupe_contact import CronDedupeContact  # noqa: E402
from agents.cron_lead_scoring import CronLeadScoring  # noqa: E402
from agents.cron_morning_brief import CronMorningBrief  # noqa: E402
from agents.cron_social_posts import CronSocialPosts  # noqa: E402
from agents.cron_stale_alert import CronStaleAlert  # noqa: E402
from agents.cron_wk_sync import CronWkSync  # noqa: E402
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer, VoyageEmbedder  # noqa: E402


CRON_SPECS = [
    {
        "cls": CronMorningBrief,
        "name": "cron_morning_brief",
        "valid_event": "cron.morning_brief.tick",
        "expected_tag": "morning_brief",
    },
    {
        "cls": CronWkSync,
        "name": "cron_wk_sync",
        "valid_event": "cron.wk_sync.tick",
        "expected_tag": "wk_sync",
    },
    {
        "cls": CronLeadScoring,
        "name": "cron_lead_scoring",
        "valid_event": "cron.lead_scoring.tick",
        "expected_tag": "lead_scoring",
    },
    {
        "cls": CronStaleAlert,
        "name": "cron_stale_alert",
        "valid_event": "cron.stale_alert.tick",
        "expected_tag": "stale_alert",
    },
    {
        "cls": CronSocialPosts,
        "name": "cron_social_posts",
        "valid_event": "cron.social_posts.tick",
        "expected_tag": "social_post",
    },
    {
        "cls": CronDedupeContact,
        "name": "cron_dedupe_contact",
        "valid_event": "cron.dedupe_contact.tick",
        "expected_tag": "dedupe_contact",
    },
    {
        "cls": CronAdsPull,
        "name": "cron_ads_pull",
        "valid_event": "cron.ads_pull.tick",
        "expected_tag": "ads_pull",
    },
]


async def run_one(spec: dict, llm: LLMLayer, memory: MemoryLayer) -> int:
    cls = spec["cls"]
    name = spec["name"]
    valid_event = spec["valid_event"]
    expected_tag = spec["expected_tag"]

    print(f"\n=== {name} ===")
    agent = cls(llm=llm, memory=memory)
    assert agent.name == name
    assert agent.autonomy_level.value == "L1"
    assert agent.escalate_to.value == "telegram_breakout_ops"

    # Test 1: unknown event → success=False
    ctx_unknown = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="some.random.event",
        payload={},
    )
    res_unknown = await agent.run(ctx_unknown)
    print(f"[unknown] success={res_unknown.success}")
    assert res_unknown.success is False, f"{name}: unknown event phải fail"
    assert "không xử lý" in (res_unknown.output_text or ""), (
        f"{name}: unknown event output sai"
    )

    # Test 2: valid event → success=True
    ctx_valid = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event=valid_event,
        payload={},
    )
    print(f"[valid={valid_event}] calling run() ...")
    res_valid = await agent.run(ctx_valid)
    print(f"[valid] success={res_valid.success}")
    print(f"[valid] output={(res_valid.output_text or '')[:120]}")
    print(f"[valid] payload_keys={list((res_valid.output_payload or {}).keys())}")
    assert res_valid.success is True, f"{name}: valid event phải success"

    # Test 3: memory emitted với tag cron
    assert res_valid.emitted_memories, f"{name}: phải emit memory"
    mem = res_valid.emitted_memories[0]
    assert mem["agent_name"] == name, f"{name}: agent_name mismatch"
    assert "cron" in mem["tags"], f"{name}: tag 'cron' thiếu"
    assert expected_tag in mem["tags"], (
        f"{name}: expected tag '{expected_tag}' thiếu, tags={mem['tags']}"
    )
    assert mem.get("venture") in {"all", "breakout"}, (
        f"{name}: venture phải all hoặc breakout"
    )
    print(f"[memory] tags={mem['tags']}")
    print(f"OK {name} (3/3)")
    return 0


async def main() -> int:
    os.environ.setdefault("CRON_DRY_RUN", "1")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    llm = LLMLayer(api_key=api_key) if api_key else LLMLayer(api_key="dummy")

    voyage_key = os.getenv("VOYAGE_API_KEY", "")
    embedder = VoyageEmbedder(api_key=voyage_key) if voyage_key else None
    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
    memory = MemoryLayer(dsn=dsn, embedder=embedder)

    passed = 0
    failed = 0
    for spec in CRON_SPECS:
        try:
            await run_one(spec, llm, memory)
            passed += 1
        except AssertionError as exc:
            print(f"FAIL {spec['name']}: {exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR {spec['name']}: {exc!r}")
            failed += 1

    try:
        await memory.close()
    except Exception:  # noqa: BLE001
        pass

    print("\n" + "=" * 50)
    print(f"Cron smoke tests: passed={passed}/{len(CRON_SPECS)} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
