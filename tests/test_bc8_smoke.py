"""BC8 Night Audit smoke test.

Chạy:
    cd cohangai/services/camas-kernel
    BC8_DRY_RUN=1 /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python tests/test_bc8_smoke.py

DRY_RUN bắt buộc cho local test để tránh spam email + Telegram thật.
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

from agents.bc8_night_audit import BC8NightAudit  # noqa: E402
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer, VoyageEmbedder  # noqa: E402


async def main() -> int:
    # Force DRY_RUN để khỏi spam email + Telegram thật
    os.environ.setdefault("BC8_DRY_RUN", "1")

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

    bc8 = BC8NightAudit(llm=llm, memory=memory)
    assert bc8.name == "bc8_night_audit"
    assert bc8.autonomy_level.value == "L1"
    assert bc8.escalate_to.value == "email_anna"

    # Test 1: unknown event → success=False
    ctx_unknown = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="some.random.event",
        payload={},
    )
    res_unknown = await bc8.run(ctx_unknown)
    print(
        f"[unknown event] success={res_unknown.success} "
        f"output={res_unknown.output_text}"
    )
    assert res_unknown.success is False
    assert "không xử lý" in (res_unknown.output_text or "")

    # Test 2: audit.nightly (DRY_RUN)
    ctx_audit = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="all",
        trigger_event="audit.nightly",
        payload={},
    )
    print("Calling BC8 audit.nightly (DRY_RUN)...")
    res_audit = await bc8.run(ctx_audit)
    print("---")
    print(f"success={res_audit.success}")
    print(f"dry_run={res_audit.output_payload.get('dry_run')}")
    print(f"email_sent={res_audit.output_payload.get('email_sent')}")
    print(f"telegram_sent={res_audit.output_payload.get('telegram_sent')}")
    print(f"date={res_audit.output_payload.get('date')}")
    print("--- REPORT ---")
    print(res_audit.output_text)
    print("--- END REPORT ---")

    assert res_audit.success is True
    assert res_audit.output_payload.get("dry_run") is True
    assert res_audit.emitted_memories, "audit.nightly phải emit memory"

    report_text = res_audit.output_text or ""
    # Verify 6 ventures đều có trong report
    expected_labels = [
        "Breakout",
        "Speakout",
        "BMCorner",
        "DAHAFA",
        "Migration",
        "Đất Gia Nghĩa",
    ]
    for label in expected_labels:
        assert f"[{label}]" in report_text, f"Report thiếu venture {label}"

    # Verify section headers
    assert "📊 Tổng quan 24h" in report_text
    assert "📈 Per venture" in report_text
    assert "⚠️ Alerts cần Anna xem sáng" in report_text
    assert "✅ Hệ thống healthy" in report_text
    assert "🎯 Đề xuất tomorrow" in report_text

    try:
        await memory.close()
    except Exception:  # noqa: BLE001
        pass

    print("---")
    print("OK BC8 smoke test passed (2/2)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
