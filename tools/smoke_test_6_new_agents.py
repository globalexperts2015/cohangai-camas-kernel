"""Smoke test 6 new agents Sprint 14 sample build.

1. asset_bank_inventory (Stage 1.1)
2. market_signal_scraper (Stage 1.3)
3. competitor_intelligence (Stage 3)
4. value_creation_advisor (Stage 4)
5. perfect_webinar_designer (Stage 9)
6. onboarding_orchestrator (Stage 10)
"""
from __future__ import annotations

import json
import os
import sys

import httpx

KERNEL_URL = os.getenv("CAMAS_KERNEL_URL", "https://camas-kernel-production.up.railway.app")
CRON_SECRET = os.getenv("CAMAS_CRON_SECRET", "")
if not CRON_SECRET:
    print("ERROR: set env CAMAS_CRON_SECRET trước khi chạy smoke test")
    sys.exit(1)


def call(agent: str, event: str, payload: dict, venture: str = "breakout") -> dict:
    resp = httpx.post(
        f"{KERNEL_URL}/kernel/execute",
        headers={"Content-Type": "application/json", "X-CAMAS-Cron-Secret": CRON_SECRET},
        json={"agent_name": agent, "trigger_event": event, "venture_context": venture, "payload": payload},
        timeout=240,
    )
    resp.raise_for_status()
    return resp.json()


def step(num: int, name: str) -> None:
    print(f"\n{'=' * 60}\nSTEP {num}/6: {name}\n{'=' * 60}")


def main() -> int:
    results = {}

    # 1. asset_bank_inventory
    step(1, "asset_bank_inventory (Stage 1.1)")
    r = call("asset_bank_inventory", "asset.inventory_build", {
        "founder_id": "anna-001",
        "founder_data": {
            "name": "Dao Thi Hang",
            "ventures": ["Breakout", "Speakout", "Cohangai", "Migration", "BMCorner", "Dat Gia Nghia"],
            "achievements": ["Speakout 25 ty 33k HV", "build CAMAS 62 agent 1 ngay", "Master Adelaide 2010"],
            "skills": ["Shopify", "GHL", "AI", "Tieng Anh", "Di tru", "Funnel"],
            "experiences": ["startup Mam Thuyen Nan 2014", "scale Speakout 25 ty", "quan ly 70 NS"],
            "failures": ["Mam Thuyen Nan 4 thang khong luong 2014", "burnout 6 venture solo 2025"],
        },
    })
    p = r.get("output_payload", {})
    total = p.get("asset_count_total", 0)
    top5 = len(p.get("top_5_monetizable_assets", []))
    ok1 = r.get("success") and total > 0 and top5 >= 3
    print(f"  total_assets={total} top5={top5} VERDICT: {'✅ PASS' if ok1 else '❌ FAIL'}")
    results["asset_bank_inventory"] = ok1

    # 2. market_signal_scraper
    step(2, "market_signal_scraper (Stage 1.3)")
    r = call("market_signal_scraper", "market.signal_aggregate", {
        "window_days": 30,
        "signals": [
            {"channel": "fb", "source": "DM", "content": "Em oi co the kiem 15tr/thang tu Shopify khong?"},
            {"channel": "fb", "source": "comment", "content": "Hoc Shopify can von bao nhieu vay chi?"},
            {"channel": "ig", "source": "DM", "content": "Mua giao Hang Coaching 50tr co dam bao ket qua khong?"},
            {"channel": "zalo", "source": "DM", "content": "Khong co thoi gian hoc, mat 3 thang dau co duoc khong?"},
            {"channel": "email", "source": "feedback", "content": "Foundation 3M kha sinh dong nhung muon co them template"},
            {"channel": "fb", "source": "comment", "content": "Em la NV VP 38 tuoi luong 18tr, co the kiem them duoc khong?"},
            {"channel": "ig", "source": "comment", "content": "Hoc K2 xong em co ho tro setup store khong?"},
        ],
    })
    p = r.get("output_payload", {})
    questions = len(p.get("recurring_questions", []))
    opps = len(p.get("top_3_product_opportunities", []))
    ok2 = r.get("success") and questions > 0 and opps > 0
    print(f"  recurring_questions={questions} opportunities={opps} VERDICT: {'✅ PASS' if ok2 else '❌ FAIL'}")
    results["market_signal_scraper"] = ok2

    # 3. competitor_intelligence
    step(3, "competitor_intelligence (Stage 3)")
    r = call("competitor_intelligence", "competitor.intel_research", {
        "niche": "Shopify business coaching cho nguoi Viet 30-45",
        "market": "Vietnam",
        "known_competitors": ["Hieu.tv", "Pham Thanh Long", "Andy Luu"],
    })
    p = r.get("output_payload", {})
    comps = len(p.get("competitors", []))
    diffs = len(p.get("differentiation_opportunities", []))
    ok3 = r.get("success") and comps >= 3 and diffs >= 1
    print(f"  competitors={comps} differentiation_opps={diffs} VERDICT: {'✅ PASS' if ok3 else '❌ FAIL'}")
    results["competitor_intelligence"] = ok3

    # 4. value_creation_advisor
    step(4, "value_creation_advisor (Stage 4)")
    r = call("value_creation_advisor", "value.creation_advise", {
        "founder_id": "anna-001",
        "asset_bank": {
            "skills_top": ["Shopify", "AI agent build", "Funnel design"],
            "case_studies": ["33K HV Speakout", "5 venture solo"],
        },
        "persona": {
            "name": "Solo founder Viet 30-45",
            "pain": "scale 50-100tr/thang khong hire team",
            "income_range": "15-100tr/thang",
        },
        "market_signal": {
            "demand": "AI Solo Empire course + 1on1 coaching cao",
            "competitor_pricing": "1.5M-50M VND range",
        },
    })
    p = r.get("output_payload", {})
    primary = p.get("primary_product_type", "?")
    ideas = len(p.get("top_3_product_ideas", []))
    ok4 = r.get("success") and primary != "?" and ideas >= 1
    print(f"  primary_type={primary} ideas={ideas} VERDICT: {'✅ PASS' if ok4 else '❌ FAIL'}")
    results["value_creation_advisor"] = ok4

    # 5. perfect_webinar_designer
    step(5, "perfect_webinar_designer (Stage 9 Brunson)")
    r = call("perfect_webinar_designer", "webinar.design_perfect_90min", {
        "target_offer": {
            "name": "Foundation System 3M",
            "price_vnd": 3000000,
            "dream": "Build Shopify store + 15-20tr/thang trong 6 thang",
        },
        "persona": {"name": "NV VP 28-45 muon thoat 8-5"},
        "key_secrets": [
            "AI thay 1 VA Viet Nam 15tr/thang",
            "Build hệ thống tự động 1 lan dung mai",
            "Solo founder scale 800tr KHONG hire team",
        ],
    })
    p = r.get("output_payload", {})
    duration = p.get("total_duration_minutes", 0)
    has_domino = bool(p.get("s3_big_domino_belief"))
    has_stack = bool(p.get("s6_stack_items"))
    ok5 = r.get("success") and has_domino and has_stack and 60 <= duration <= 120
    print(f"  duration={duration}min big_domino={has_domino} stack={has_stack} VERDICT: {'✅ PASS' if ok5 else '❌ FAIL'}")
    results["perfect_webinar_designer"] = ok5

    # 6. onboarding_orchestrator
    step(6, "onboarding_orchestrator (Stage 10)")
    r = call("onboarding_orchestrator", "onboarding.welcome_sequence", {
        "customer_id": "test-buyer-001",
        "tier_purchased": "Foundation",
        "purchase": {"amount_vnd": 3000000, "product": "Foundation System", "paid_at": "2026-06-08"},
        "persona": {"name": "NV VP 38", "goal": "15tr/thang Shopify"},
    })
    p = r.get("output_payload", {})
    emails = len(p.get("email_sequence", []))
    metrics = len(p.get("progress_tracking_metrics", []))
    ok6 = r.get("success") and emails >= 5 and metrics >= 1
    print(f"  emails={emails} metrics={metrics} VERDICT: {'✅ PASS' if ok6 else '❌ FAIL'}")
    results["onboarding_orchestrator"] = ok6

    # Summary
    print(f"\n{'=' * 60}\nSMOKE TEST SUMMARY\n{'=' * 60}")
    for name, ok in results.items():
        print(f"  {'✅' if ok else '❌'} {name}")
    total = sum(bool(v) for v in results.values())
    print(f"\nTotal: {total}/6 agents pass")
    return 0 if total == 6 else 1


if __name__ == "__main__":
    sys.exit(main())
