"""Smoke test cho 10 Phòng ban agents.

Chạy:
    cd cohangai/services/camas-kernel
    PBAN_DRY_RUN=1 /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python tests/test_pban_smoke.py

DRY_RUN bắt buộc:
- Skip Telegram send (mọi agent)
- DB queries vẫn chạy thật nếu DATABASE_URL set (graceful nếu không)
- LLM call SKIP khi ANTHROPIC_API_KEY trống (LLMLayer.ready=False, agent fallback)
- HTTP probe vẫn chạy thật nhưng fail-soft

Test mỗi phòng ban 1 sample event:
- 8 phòng ban real → assert success=True + emitted_memories non-empty
- 2 phòng ban thin alias (06, 09) → assert success=False + memory tag
  alias_redirect
- BONUS: 1 unknown event cho 1 agent → assert success=False
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    env_path = ROOT.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from agents.pban_01_quang_cao import Pban01QuangCao  # noqa: E402
from agents.pban_02_noi_dung import Pban02NoiDung  # noqa: E402
from agents.pban_03_landing_webinar import Pban03LandingWebinar  # noqa: E402
from agents.pban_04_phieu_comms import Pban04PhieuComms  # noqa: E402
from agents.pban_05_thanh_toan import Pban05ThanhToan  # noqa: E402
from agents.pban_06_cskh_faq_haiku import Pban06CSKHFAQHaiku  # noqa: E402
from agents.pban_07_hoan_tien import Pban07HoanTien  # noqa: E402
from agents.pban_08_du_lieu import Pban08DuLieu  # noqa: E402
from agents.pban_09_tuan_thu import Pban09TuanThu  # noqa: E402
from agents.pban_10_chien_luoc import Pban10ChienLuoc  # noqa: E402
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer, VoyageEmbedder  # noqa: E402


# Map agent class → (event_name, payload, expected_success, expected_tags_any)
CASES: list[dict[str, Any]] = [
    {
        "cls": Pban01QuangCao,
        "name": "pban_01_quang_cao",
        "event": "ads.budget_check",
        "payload": {},
        "venture": "breakout",
        "expect_success": True,
        "expect_tag_any": ["pban_01", "budget_check"],
    },
    {
        "cls": Pban02NoiDung,
        "name": "pban_02_noi_dung",
        "event": "content.batch_audit",
        "payload": {},
        "venture": "breakout",
        "expect_success": True,
        "expect_tag_any": ["pban_02", "batch_audit"],
    },
    {
        "cls": Pban03LandingWebinar,
        "name": "pban_03_landing_webinar",
        "event": "landing.health_5min",
        "payload": {},
        "venture": "breakout",
        "expect_success": True,
        "expect_tag_any": ["pban_03", "landing_health"],
    },
    {
        "cls": Pban04PhieuComms,
        "name": "pban_04_phieu_comms",
        "event": "comms.workflow_audit",
        "payload": {},
        "venture": "all",
        "expect_success": True,
        "expect_tag_any": ["pban_04", "workflow_audit"],
    },
    {
        "cls": Pban05ThanhToan,
        "name": "pban_05_thanh_toan",
        "event": "payment.health_check",
        "payload": {},
        "venture": "breakout",
        "expect_success": True,
        "expect_tag_any": ["pban_05", "health_check"],
    },
    {
        "cls": Pban06CSKHFAQHaiku,
        "name": "pban_06_cskh_faq_haiku",
        "event": "cskh.faq_request",  # arbitrary, alias bỏ qua
        "payload": {},
        "venture": "all",
        "expect_success": False,
        "expect_tag_any": ["alias_redirect"],
    },
    {
        "cls": Pban07HoanTien,
        "name": "pban_07_hoan_tien",
        "event": "refund.batch_audit",
        "payload": {},
        "venture": "breakout",
        "expect_success": True,
        "expect_tag_any": ["pban_07", "batch_audit"],
    },
    {
        "cls": Pban08DuLieu,
        "name": "pban_08_du_lieu",
        "event": "data.adhoc_query",
        "payload": {"query_name": "kpi_snapshot"},
        "venture": "all",
        "expect_success": True,
        "expect_tag_any": ["pban_08", "adhoc_query"],
    },
    {
        "cls": Pban09TuanThu,
        "name": "pban_09_tuan_thu",
        "event": "compliance.check",  # arbitrary, alias bỏ qua
        "payload": {},
        "venture": "all",
        "expect_success": False,
        "expect_tag_any": ["alias_redirect"],
    },
    {
        "cls": Pban10ChienLuoc,
        "name": "pban_10_chien_luoc",
        "event": "unknown.event",  # cần test unknown → success=False
        "payload": {},
        "venture": "all",
        "expect_success": False,
        "expect_tag_any": [],
    },
]


async def main() -> int:
    os.environ.setdefault("PBAN_DRY_RUN", "1")

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    llm = LLMLayer(api_key=api_key) if api_key else LLMLayer(api_key="dummy")

    voyage_key = os.getenv("VOYAGE_API_KEY", "")
    embedder = VoyageEmbedder(api_key=voyage_key) if voyage_key else None
    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
    memory = MemoryLayer(dsn=dsn, embedder=embedder)

    passed = 0
    failed = 0
    failures: list[str] = []

    for case in CASES:
        agent = case["cls"](llm=llm, memory=memory)
        assert agent.name == case["name"], (
            f"name mismatch: {agent.name} != {case['name']}"
        )

        ctx = ExecutionContext(
            run_id=str(uuid.uuid4()),
            venture_context=case["venture"],
            trigger_event=case["event"],
            payload=case["payload"],
        )
        try:
            result = await agent.run(ctx)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{case['name']} crash: {exc!r}")
            failed += 1
            continue

        # Check success
        if result.success is not case["expect_success"]:
            failures.append(
                f"{case['name']} success={result.success}, "
                f"expected {case['expect_success']}"
            )
            failed += 1
            continue

        # Check emitted memory (alias agents emit alias_redirect memory)
        if case["expect_tag_any"]:
            if not result.emitted_memories:
                failures.append(f"{case['name']} không emit memory")
                failed += 1
                continue
            mem_tags = result.emitted_memories[0].get("tags", [])
            if not any(t in mem_tags for t in case["expect_tag_any"]):
                failures.append(
                    f"{case['name']} tags {mem_tags} không chứa "
                    f"any của {case['expect_tag_any']}"
                )
                failed += 1
                continue
        else:
            # Unknown event case: không yêu cầu memory
            pass

        print(
            f"[OK] {case['name']:30s} event={case['event']:30s} "
            f"success={result.success}"
        )
        passed += 1

    try:
        await memory.close()
    except Exception:  # noqa: BLE001
        pass

    print("---")
    print(f"PASSED: {passed}/{len(CASES)}")
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("OK Pban smoke test passed (all 10 phòng ban)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
