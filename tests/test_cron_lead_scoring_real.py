"""Cron Lead Scoring real GHL wiring smoke test.

Chạy:
    cd cohangai/services/camas-kernel
    /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python \\
        tests/test_cron_lead_scoring_real.py

Tests:
    1. LeadScorer formula sanity (mock contact)
    2. GHLClient instantiation
    3. list_custom_fields() returns count
    4. get_or_create_lead_score_field() returns field id (idempotent)
    5. list_contacts(max=10) returns sample
    6. CronLeadScoring.run() with dry_run=True (no PATCH, no Telegram)

KHÔNG test batch_update_scores trực tiếp ngoài dry_run (writes data!).
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

from agents.cron_lead_scoring import (  # noqa: E402
    CronLeadScoring,
    GHLClient,
    LeadScorer,
)
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer, VoyageEmbedder  # noqa: E402


def test_lead_scorer_formula() -> bool:
    """Mock contact: tags=[email-opened-2025-12, wk_attended_d1], revenue=2M.

    Expected:
        behavior = email-opened-* (10) + wk_attended_d1 (10) = 20
        purchase = revenue>0 (10) + revenue>1M (5) = 15
        total = 35, tier = warm
    """
    print("\n=== Test 1: LeadScorer formula ===")
    contact = {
        "tags": ["email-opened-2025-12-broadcast", "wk_attended_d1"],
        "total_revenue_vnd": 2_000_000,
    }
    s = LeadScorer.score_contact(contact)
    print(f"  Input tags: {contact['tags']}")
    print(f"  Input revenue: {contact['total_revenue_vnd']:,}")
    print(f"  Output: total={s['total']} behavior={s['behavior']} "
          f"purchase={s['purchase']} tier={s['tier']}")
    print(f"  Breakdown: {s['breakdown']}")

    assert s["behavior"] == 20, f"behavior expected 20, got {s['behavior']}"
    assert s["purchase"] == 15, f"purchase expected 15, got {s['purchase']}"
    assert s["total"] == 35, f"total expected 35, got {s['total']}"
    assert s["tier"] == "warm", f"tier expected warm, got {s['tier']}"
    print("  PASS: formula đúng")

    # Edge: hot
    contact_hot = {
        "tags": [
            "wk_attended_d3", "wk_attended_d2", "wk_attended_d1",
            "breakout-customer-k1", "email-opened-x", "email-clicked-y",
        ],
        "total_revenue_vnd": 60_000_000,
    }
    s2 = LeadScorer.score_contact(contact_hot)
    print(f"  Hot mock: total={s2['total']} tier={s2['tier']} "
          f"(behavior cap60, purchase 30)")
    assert s2["behavior"] == 60, f"behavior cap expected 60, got {s2['behavior']}"
    assert s2["purchase"] == 30, f"purchase cap expected 30, got {s2['purchase']}"
    assert s2["total"] == 90, f"total expected 90, got {s2['total']}"
    assert s2["tier"] == "hot", f"tier expected hot, got {s2['tier']}"
    print("  PASS: cap + tier hot ok")

    # Edge: cold (empty)
    s3 = LeadScorer.score_contact({"tags": [], "total_revenue_vnd": 0})
    assert s3["total"] == 0 and s3["tier"] == "cold"
    print("  PASS: cold empty ok")
    return True


async def test_ghl_client_basic() -> bool:
    """GHLClient list_custom_fields + get_or_create_lead_score_field."""
    print("\n=== Test 2-4: GHLClient real API ===")
    token = os.getenv("GHL_API_KEY", "").strip()
    location_id = os.getenv("GHL_LOCATION_ID", "").strip()

    if not token or not location_id:
        print("  SKIP: GHL_API_KEY or GHL_LOCATION_ID chưa set")
        return True

    client = GHLClient(api_token=token, location_id=location_id)
    print(f"  Client: location={location_id[:8]}...")

    # 2. list_custom_fields
    try:
        fields = await client.list_custom_fields()
        print(f"  list_custom_fields: count={len(fields)}")
        for f in fields[:3]:
            print(
                f"    sample: name={f.get('name')!r} "
                f"key={f.get('fieldKey')!r} id={f.get('id')!r}"
            )
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL list_custom_fields: {exc!r}")
        return False

    # 3. get_or_create_lead_score_field (idempotent)
    try:
        cf_id_1 = await client.get_or_create_lead_score_field()
        print(f"  get_or_create round1: id={cf_id_1}")
        cf_id_2 = await client.get_or_create_lead_score_field()
        print(f"  get_or_create round2: id={cf_id_2}")
        assert cf_id_1 == cf_id_2, "idempotency fail: id thay đổi"
        print("  PASS: custom field id idempotent")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL get_or_create_lead_score_field: {exc!r}")
        return False

    # 4. list_contacts(max=10)
    try:
        contacts = await client.list_contacts(max_contacts=10, page_limit=10)
        print(f"  list_contacts(max=10): fetched={len(contacts)}")
        for c in contacts[:3]:
            first = (c.get("firstName") or "")[:20]
            tag_count = len(c.get("tags") or [])
            print(
                f"    sample: first={first!r} "
                f"tags={tag_count} id={c.get('id')!r}"
            )
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL list_contacts: {exc!r}")
        return False

    return True


async def test_agent_dry_run() -> bool:
    """CronLeadScoring.run() with dry_run=True. NO writes."""
    print("\n=== Test 5: CronLeadScoring.run() dry_run ===")
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    llm = LLMLayer(api_key=api_key) if api_key else LLMLayer(api_key="dummy")

    voyage_key = os.getenv("VOYAGE_API_KEY", "")
    embedder = VoyageEmbedder(api_key=voyage_key) if voyage_key else None
    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
    memory = MemoryLayer(dsn=dsn, embedder=embedder)

    agent = CronLeadScoring(llm=llm, memory=memory)
    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="cron.lead_scoring.tick",
        payload={"max_contacts": 20, "dry_run": True},
    )
    res = await agent.run(ctx)
    print(f"  success: {res.success}")
    print(f"  output: {(res.output_text or '')[:140]}")
    stats = res.output_payload.get("stats", {})
    print(
        f"  stats: processed={stats.get('processed')} "
        f"hot={stats.get('hot')} warm={stats.get('warm')} "
        f"cold={stats.get('cold')} patched={stats.get('patched')}"
    )
    print(f"  custom_field_id: {stats.get('custom_field_id')}")
    print(f"  telegram_sent: {stats.get('telegram_sent')}")
    print(f"  warnings: {stats.get('warnings')}")
    top_hot = stats.get("top_hot") or []
    print(f"  top_hot count: {len(top_hot)}")
    for i, h in enumerate(top_hot[:5], 1):
        first = (h.get("first_name") or "").strip()
        print(f"    {i}. first={first!r} score={h.get('score')}")

    assert res.success is True
    # Dry run: patched MUST be 0
    assert stats.get("patched", 0) == 0, "dry_run nhưng patched > 0!"
    print("  PASS: dry_run ok, không PATCH GHL")

    try:
        await memory.close()
    except Exception:  # noqa: BLE001
        pass
    return True


async def main() -> int:
    passed = 0
    failed = 0

    try:
        if test_lead_scorer_formula():
            passed += 1
    except AssertionError as exc:
        print(f"FAIL test_lead_scorer_formula: {exc}")
        failed += 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR test_lead_scorer_formula: {exc!r}")
        failed += 1

    try:
        if await test_ghl_client_basic():
            passed += 1
    except AssertionError as exc:
        print(f"FAIL test_ghl_client_basic: {exc}")
        failed += 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR test_ghl_client_basic: {exc!r}")
        failed += 1

    try:
        if await test_agent_dry_run():
            passed += 1
    except AssertionError as exc:
        print(f"FAIL test_agent_dry_run: {exc}")
        failed += 1
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR test_agent_dry_run: {exc!r}")
        failed += 1

    print("\n" + "=" * 50)
    print(f"Cron Lead Scoring real tests: passed={passed} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
