"""Smoke test FB Marketing API thật cho Pban01.

Chạy:
    cd cohangai/services/camas-kernel
    PBAN_DRY_RUN=1 /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python tests/test_pban_01_fb_real.py

Tests:
1. FBMarketingClient instantiate với token từ env
2. list_active_ad_sets() - print count + first 3 names
3. fetch_insights(adset, last_7d) - print top 3 by spend
4. get_campaign_performance_summary(days=7) - print summary
5. get_lookalike_audiences() - print count + names
6. SKIP pause_ad_set (sẽ pause ads Anna thật!)
7. Full agent flow ads.performance_review (DRY_RUN=1 skip Telegram)
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

from agents.pban_01_quang_cao import Pban01QuangCao  # noqa: E402
from agents.pban_01_quang_cao.fb_marketing_client import (  # noqa: E402
    FBMarketingAPIError,
    FBMarketingClient,
)
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer  # noqa: E402


def header(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


async def main() -> int:
    os.environ.setdefault("PBAN_DRY_RUN", "1")

    token = os.getenv("FB_MARKETING_API_TOKEN", "")
    ad_acct = os.getenv("FB_AD_ACCOUNT_ID", "")
    if not token or not ad_acct:
        print("MISSING FB_MARKETING_API_TOKEN hoặc FB_AD_ACCOUNT_ID trong env")
        return 1

    print(
        f"Token len={len(token)} acct={ad_acct} (token KHÔNG log full vì security)"
    )

    client = FBMarketingClient(
        access_token=token,
        ad_account_id=ad_acct,
    )

    failures: list[str] = []
    sample_data: dict[str, object] = {}

    # ============================================================
    # Test 1: list_active_ad_sets
    # ============================================================
    header("Test 1: list_active_ad_sets()")
    try:
        ad_sets = await client.list_active_ad_sets()
        print(f"  count={len(ad_sets)}")
        for ad in ad_sets[:3]:
            print(
                f"    - id={ad.get('id')} name={ad.get('name')} "
                f"daily_budget={ad.get('daily_budget')} status={ad.get('effective_status')}"
            )
        sample_data["ad_sets_count"] = len(ad_sets)
        sample_data["ad_sets_first3_names"] = [
            a.get("name") for a in ad_sets[:3]
        ]
    except FBMarketingAPIError as exc:
        msg = f"Test 1 FAIL: {exc} code={exc.code} subcode={exc.subcode}"
        print(f"  {msg}")
        failures.append(msg)
    except Exception as exc:  # noqa: BLE001
        msg = f"Test 1 CRASH: {exc!r}"
        print(f"  {msg}")
        failures.append(msg)

    # ============================================================
    # Test 2: fetch_insights last_7d
    # ============================================================
    header("Test 2: fetch_insights(adset, last_7d)")
    try:
        insights = await client.fetch_insights(
            level="adset",
            date_preset="last_7d",
        )
        print(f"  rows={len(insights)}")
        sorted_by_spend = sorted(
            insights,
            key=lambda r: float(r.get("spend") or 0),
            reverse=True,
        )
        for row in sorted_by_spend[:3]:
            print(
                f"    - adset={row.get('adset_name')} spend={row.get('spend')} "
                f"cpm={row.get('cpm')} ctr={row.get('ctr')}"
            )
        sample_data["insights_rows"] = len(insights)
        sample_data["top3_spend"] = [
            {
                "name": r.get("adset_name"),
                "spend": r.get("spend"),
            }
            for r in sorted_by_spend[:3]
        ]
    except FBMarketingAPIError as exc:
        msg = f"Test 2 FAIL: {exc} code={exc.code} subcode={exc.subcode}"
        print(f"  {msg}")
        failures.append(msg)
    except Exception as exc:  # noqa: BLE001
        msg = f"Test 2 CRASH: {exc!r}"
        print(f"  {msg}")
        failures.append(msg)

    # ============================================================
    # Test 3: get_campaign_performance_summary(days=7)
    # ============================================================
    header("Test 3: get_campaign_performance_summary(days=7)")
    try:
        summary = await client.get_campaign_performance_summary(days=7)
        for k, v in summary.items():
            print(f"    {k}: {v}")
        sample_data["perf_summary"] = summary
    except FBMarketingAPIError as exc:
        msg = f"Test 3 FAIL: {exc} code={exc.code} subcode={exc.subcode}"
        print(f"  {msg}")
        failures.append(msg)
    except Exception as exc:  # noqa: BLE001
        msg = f"Test 3 CRASH: {exc!r}"
        print(f"  {msg}")
        failures.append(msg)

    # ============================================================
    # Test 4: get_lookalike_audiences
    # ============================================================
    header("Test 4: get_lookalike_audiences()")
    try:
        audiences = await client.get_lookalike_audiences()
        print(f"  count={len(audiences)}")
        for a in audiences[:5]:
            print(
                f"    - name={a.get('name')} subtype={a.get('subtype')} "
                f"count={a.get('approximate_count')}"
            )
        sample_data["audiences_count"] = len(audiences)
        sample_data["audiences_first5_names"] = [
            a.get("name") for a in audiences[:5]
        ]
    except FBMarketingAPIError as exc:
        msg = f"Test 4 FAIL: {exc} code={exc.code} subcode={exc.subcode}"
        print(f"  {msg}")
        failures.append(msg)
    except Exception as exc:  # noqa: BLE001
        msg = f"Test 4 CRASH: {exc!r}"
        print(f"  {msg}")
        failures.append(msg)

    # ============================================================
    # Test 5: SKIP pause_ad_set (would pause real ads)
    # ============================================================
    header("Test 5: pause_ad_set() - SKIP (would actually pause Anna ads)")
    print("  skipped intentionally")

    # ============================================================
    # Test 6: agent flow ads.performance_review (DRY_RUN)
    # ============================================================
    header("Test 6: agent ads.performance_review (DRY_RUN)")
    try:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        llm = LLMLayer(api_key=api_key) if api_key else LLMLayer(api_key="dummy")
        memory = MemoryLayer(dsn=None, embedder=None)
        agent = Pban01QuangCao(llm=llm, memory=memory)
        ctx = ExecutionContext(
            run_id=str(uuid.uuid4()),
            venture_context="breakout",
            trigger_event="ads.performance_review",
            payload={"dry_run": True},
        )
        result = await agent.run(ctx)
        print(f"  success={result.success}")
        print(f"  payload.metrics.source={result.output_payload.get('metrics', {}).get('source')}")
        print(f"  payload.metrics.cpm_avg={result.output_payload.get('metrics', {}).get('cpm_avg')}")
        print(f"  payload.metrics.cpl_avg={result.output_payload.get('metrics', {}).get('cpl_avg')}")
        print(f"  payload.metrics.roas_avg={result.output_payload.get('metrics', {}).get('roas_avg')}")
        sample_data["agent_perf_source"] = result.output_payload.get(
            "metrics", {}
        ).get("source")
        try:
            await memory.close()
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        msg = f"Test 6 CRASH: {exc!r}"
        print(f"  {msg}")
        failures.append(msg)

    # ============================================================
    # Summary
    # ============================================================
    header("SUMMARY")
    print(f"Failures: {len(failures)}")
    for f in failures:
        print(f"  - {f}")
    print("\nSample data captured:")
    for k, v in sample_data.items():
        print(f"  {k}: {v}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
