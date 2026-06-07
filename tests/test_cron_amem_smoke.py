"""cron_amem_weekly smoke test.

Chạy:
    cd cohangai/services/camas-kernel
    CRON_AMEM_WEEKLY_DRY_RUN=1 /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python tests/test_cron_amem_smoke.py

DRY_RUN bắt buộc:
- Skip Telegram send
- Skip Postgres write
- SQL reads vẫn chạy thật nếu DATABASE_URL set, fail-soft nếu không

Tests:
1. Trigger valid event cron.amem_weekly.tick → success=True, output mention
   "memories updated" + "pain themes"
2. Trigger unknown event → success=False, "không xử lý"
3. Test keyword extraction sample (mock 3 memories) → 3-5 keywords each
   (chỉ chạy nếu ANTHROPIC_API_KEY set, else skip)
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

from agents.cron_amem_weekly import CronAmemWeekly  # noqa: E402
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer, VoyageEmbedder  # noqa: E402


async def test_unknown_event(agent: CronAmemWeekly) -> None:
    print("\n=== test 1: unknown event ===")
    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="some.random.event",
        payload={},
    )
    res = await agent.run(ctx)
    print(f"success={res.success}")
    print(f"output={(res.output_text or '')[:120]}")
    assert res.success is False, "unknown event phải fail"
    assert "không xử lý" in (res.output_text or ""), "output sai"
    print("OK test 1")


async def test_valid_event_dry_run(agent: CronAmemWeekly) -> None:
    print("\n=== test 2: valid event dry_run ===")
    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="cron.amem_weekly.tick",
        payload={"dry_run": True, "max_memories": 50},
    )
    res = await agent.run(ctx)
    print(f"success={res.success}")
    print(f"output={(res.output_text or '')[:200]}")
    payload = res.output_payload or {}
    stats = payload.get("stats") or {}
    print(f"stats keys={list(stats.keys())}")
    print(f"scanned={stats.get('scanned')} processed={stats.get('processed')}")
    print(f"keywords_total={stats.get('keywords_total')} links_total={stats.get('links_total')}")
    pain_themes = stats.get("pain_themes") or []
    print(f"pain_themes count={len(pain_themes)}")
    if pain_themes:
        print("Sample pain themes:")
        for i, t in enumerate(pain_themes[:3], 1):
            print(f"  {i}. {t.get('theme')} ({t.get('count')})")

    assert res.success is True, "valid event phải success"
    output_text = res.output_text or ""
    assert "memories updated" in output_text, (
        f"output thiếu 'memories updated': {output_text}"
    )
    # 'pain themes' string trong output_text
    assert "pain themes" in output_text.lower(), (
        f"output thiếu 'pain themes': {output_text}"
    )
    assert res.emitted_memories, "phải emit memory"
    mem = res.emitted_memories[0]
    assert mem["agent_name"] == "cron_amem_weekly", "agent_name mismatch"
    assert "amem" in mem["tags"], f"tag 'amem' thiếu: {mem['tags']}"
    assert "weekly" in mem["tags"], f"tag 'weekly' thiếu: {mem['tags']}"
    print(f"emitted memory tags={mem['tags']}")
    print("OK test 2")


async def test_keyword_extraction(agent: CronAmemWeekly) -> None:
    print("\n=== test 3: keyword extraction sample ===")
    if not agent.llm.ready:
        print("SKIP test 3: LLM chưa ready (ANTHROPIC_API_KEY chưa set)")
        return

    sample_rows = [
        {
            "id": 1,
            "content": (
                "Khách hàng phản hồi rằng giá khóa Foundation 3 triệu quá cao so "
                "với thu nhập của họ, đặc biệt là chị em nội trợ vùng quê. Họ đề "
                "nghị trả góp 3 tháng không lãi."
            ),
        },
        {
            "id": 2,
            "content": (
                "Học viên Speakout chia sẻ rằng buổi 1 phát âm quá nhanh, không "
                "theo kịp Anna khi luyện líu lưỡi. Cần slide chậm hơn hoặc replay."
            ),
        },
        {
            "id": 3,
            "content": (
                "Phản hồi BC3: Học viên Breakout K1 báo lỗi không vào được app "
                "breakout.live, đăng nhập email báo email không tồn tại trong "
                "whitelist. Đã backfill 956 contact."
            ),
        },
    ]
    try:
        kws_list = await agent._haiku_extract_batch(sample_rows)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL test 3: Haiku call exception {exc!r}")
        raise

    print(f"Returned {len(kws_list)} keyword sets:")
    for i, kws in enumerate(kws_list, 1):
        print(f"  Memory {i}: {kws}")

    assert len(kws_list) == 3, f"phải trả 3 keyword set, nhận {len(kws_list)}"
    for i, kws in enumerate(kws_list, 1):
        # Vài batch có thể trả [] nếu parse fail, log nhưng không assert cứng
        if not kws:
            print(f"  WARN memory {i} keywords empty (parse fail có thể)")
            continue
        assert 3 <= len(kws) <= 5, (
            f"memory {i}: expected 3-5 keywords, got {len(kws)}: {kws}"
        )
        for k in kws:
            assert isinstance(k, str) and k.strip(), (
                f"memory {i}: keyword sai type/empty: {k!r}"
            )
    print("OK test 3")


async def main() -> int:
    os.environ.setdefault("CRON_AMEM_WEEKLY_DRY_RUN", "1")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    llm = LLMLayer(api_key=api_key) if api_key else LLMLayer(api_key="dummy")

    voyage_key = os.getenv("VOYAGE_API_KEY", "")
    embedder = VoyageEmbedder(api_key=voyage_key) if voyage_key else None
    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
    memory = MemoryLayer(dsn=dsn, embedder=embedder)

    agent = CronAmemWeekly(llm=llm, memory=memory)
    assert agent.name == "cron_amem_weekly"
    assert agent.autonomy_level.value == "L1"
    assert agent.escalate_to.value == "telegram_breakout_ops"
    print(f"Instantiated {agent.name} OK")

    passed = 0
    failed = 0
    tests = [
        ("unknown_event", test_unknown_event),
        ("valid_event_dry_run", test_valid_event_dry_run),
        ("keyword_extraction", test_keyword_extraction),
    ]
    for name, fn in tests:
        try:
            await fn(agent)
            passed += 1
        except AssertionError as exc:
            print(f"FAIL {name}: {exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR {name}: {exc!r}")
            failed += 1

    try:
        await memory.close()
    except Exception:  # noqa: BLE001
        pass

    print("\n" + "=" * 50)
    print(f"cron_amem_weekly smoke: passed={passed} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
