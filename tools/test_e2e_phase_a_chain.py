"""E2E chain test Phase A WHO Intelligence: BC15 → BC11 → BC13 → BC14.

Pass 1 founder + 1 persona + 1 customer pain text through the 4-agent chain.
Verify each agent succeeds + output feeds correctly to next stage.

Usage:
    cd cohangai/services/camas-kernel
    python3 tools/test_e2e_phase_a_chain.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

KERNEL_URL = "https://camas-kernel-production.up.railway.app"
CRON_SECRET = "xuGm0mxA_--UxKkkR-NBxsT_LIf0qizRaWfwwl9bvKA"


def call_kernel(agent_name: str, trigger_event: str, payload: dict, venture: str = "breakout") -> dict:
    resp = httpx.post(
        f"{KERNEL_URL}/kernel/execute",
        headers={
            "Content-Type": "application/json",
            "X-CAMAS-Cron-Secret": CRON_SECRET,
        },
        json={
            "agent_name": agent_name,
            "trigger_event": trigger_event,
            "venture_context": venture,
            "payload": payload,
        },
        timeout=240,
    )
    resp.raise_for_status()
    return resp.json()


def step(num: int, total: int, name: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"STEP {num}/{total}: {name}")
    print(f"{'=' * 60}")


def main() -> int:
    print("=" * 60)
    print("E2E CHAIN TEST: Phase A WHO Intelligence")
    print("BC15 → BC11 → BC13 → BC14")
    print("=" * 60)

    # STEP 1: BC15 Character Builder
    step(1, 4, "BC15 Attractive Character Builder")
    bc15_payload = {
        "founder_data": {
            "name": "Dao Thi Hang",
            "vietnamese_name": "Đào Thị Hằng",
            "title": "Founder Breakout, AI Solo Empire architect",
            "achievements": [
                "2010 Master Adelaide hoc bong",
                "2014 Mam Thuyen Nan startup Quang Tri",
                "2018+ Speakout 33000 hoc vien tieng Anh",
                "2026 build CAMAS Kernel 56 agent solo",
            ],
            "audience": "Solo founder Viet 30-45 muon scale 50tr-800tr/thang khong hire team",
            "ventures": ["Breakout", "Speakout", "Cohangai", "Migration", "BMCorner", "Dat Gia Nghia"],
        }
    }
    bc15_result = call_kernel("bc15_character_builder", "character.build_profile", bc15_payload)
    character = bc15_result.get("output_payload", {})
    bc15_ok = bc15_result.get("success") and character.get("founder_name")
    print(f"BC15 success={bc15_result.get('success')} identity={character.get('identity')}")
    print(f"  moments={len(character.get('backstory_key_moments', []))} parables={len(character.get('parables', []))}")
    print(f"  polarity={len(character.get('polarity', []))} flaws={len(character.get('character_flaws', []))}")
    print(f"  VERDICT: {'✅ PASS' if bc15_ok else '❌ FAIL'}")

    # STEP 2: BC11 VPC Builder (use character context)
    step(2, 4, "BC11 Tròn Vuông VPC Builder")
    persona_from_character = {
        "founder_identity": character.get("identity", "Reluctant Hero"),
        "founder_audience": "NV VP 28-45 HCM/HN",
    }
    bc11_payload = {
        "persona_name": "Nhân viên văn phòng VN 28-45",
        "customer_data": {
            "age_range": "28-45",
            "location": "HN/HCM",
            "income": "15-25tr/thang",
            "goal": "thu nhap them Shopify 15-20tr/thang trong 6 thang",
            "pain": "khong biet bat dau, so mat tien dau tu, gia dinh phan doi",
            "founder_character": persona_from_character,
        },
    }
    bc11_result = call_kernel("bc11_vpc_builder", "vpc.build_canvas", bc11_payload)
    vpc = bc11_result.get("output_payload", {})
    bc11_ok = bc11_result.get("success") and vpc.get("fit_score", 0) >= 60
    print(f"BC11 success={bc11_result.get('success')} fit_score={vpc.get('fit_score')} anna_match={vpc.get('anna_persona_match')}")
    print(f"  jobs_functional={len(vpc.get('jobs_functional', []))} pains_emotional={len(vpc.get('pains_emotional', []))}")
    print(f"  pain_relievers={len(vpc.get('pain_relievers', []))} gain_creators={len(vpc.get('gain_creators', []))}")
    print(f"  VERDICT: {'✅ PASS' if bc11_ok else '❌ FAIL'}")

    # STEP 3: BC13 Pain Scorer (real customer pain text, NV VP persona)
    step(3, 4, "BC13 Pain Severity Scorer")
    pain_text = (
        "Em la nhan vien ngan hang 38 tuoi, cong viec nham chan, luong 18 trieu khong "
        "du chi tieu cho 2 con dang hoc. Em mat ngu vi lo tuong lai, so 45 tuoi van "
        "khong thoat duoc kiep lam thue. Ban be thi cuoi nhao khi em dang ky Shopify, "
        "gia dinh thi bao bo viec on dinh di ban hang online la dai. Em khong co thoi "
        "gian nhieu, chi buoi toi sau khi con ngu, va so hoc xong khong kiem duoc tien "
        "lai mat 20-30 trieu hoc phi. Em can kiem them gap trong 6 thang toi."
    )
    bc13_payload = {
        "pain_text": pain_text,
        "meta": {"customer_id": "e2e-test-001", "persona": "NV VP 38", "venture": "breakout"},
        "context": {"vpc_anna_match": vpc.get("anna_persona_match"), "vpc_fit_score": vpc.get("fit_score")},
    }
    bc13_result = call_kernel("bc13_pain_scorer", "pain.score_severity", bc13_payload)
    pain_matrix = bc13_result.get("output_payload", {})
    bc13_ok = bc13_result.get("success") and pain_matrix.get("max_severity", 0) >= 7
    print(f"BC13 success={bc13_result.get('success')} max_sev={pain_matrix.get('max_severity')} urgency={pain_matrix.get('urgency_rank')}")
    td = pain_matrix.get("type_distribution", {}) or {}
    print(f"  distribution F={td.get('functional_count', 0)} S={td.get('social_count', 0)} E={td.get('emotional_count', 0)} A={td.get('ancillary_count', 0)}")
    print(f"  top_3_critical={len(pain_matrix.get('top_3_critical', []))} deadline={pain_matrix.get('deadline_detected', 'none')[:50]}")
    print(f"  VERDICT: {'✅ PASS' if bc13_ok else '❌ FAIL'}")

    # STEP 4: BC14 Joy Mapper (chain pain_matrix from BC13)
    step(4, 4, "BC14 Joy/Gain Mapper")
    bc14_payload = {
        "pain_matrix": pain_matrix,
        "persona_context": {
            "name": "NV VP 38",
            "anna_match": vpc.get("anna_persona_match"),
            "fit_score": vpc.get("fit_score"),
        },
    }
    bc14_result = call_kernel("bc14_joy_mapper", "joy.map_to_pain", bc14_payload)
    joy_matrix = bc14_result.get("output_payload", {})
    bc14_ok = bool(bc14_result.get("success") and joy_matrix.get("primary_dream_outcome"))
    print(f"BC14 success={bc14_result.get('success')}")
    print(f"  dream: {joy_matrix.get('primary_dream_outcome', '')[:100]}")
    print(f"  wow: {joy_matrix.get('wow_factor', '')[:80]}")
    pairs = joy_matrix.get("pain_to_joy_pairs", [])
    print(f"  pain-joy pairs: {len(pairs)}")
    qc = joy_matrix.get("quality_check", {}) or {}
    print(f"  quality: passes={qc.get('passes_quality')} all_mapped={qc.get('all_pains_mapped')} wow={qc.get('wow_factor_identified')}")
    print(f"  VERDICT: {'✅ PASS' if bc14_ok else '❌ FAIL'}")

    # Summary
    print("\n" + "=" * 60)
    print("E2E CHAIN TEST SUMMARY")
    print("=" * 60)
    results = {
        "BC15 Character Builder": bc15_ok,
        "BC11 VPC Builder": bc11_ok,
        "BC13 Pain Scorer": bc13_ok,
        "BC14 Joy Mapper": bc14_ok,
    }
    for name, passed in results.items():
        print(f"  {'✅' if passed else '❌'} {name}")
    total_pass = sum(results.values())
    print(f"\nTotal: {total_pass}/4 agents pass")

    # Verify chain integration
    print("\n--- CHAIN INTEGRATION VERIFY ---")
    integration_checks = {
        "BC15 → BC11 (character context passed)": bool(character.get("identity")),
        "BC11 → BC13 (persona context for pain analysis)": bool(vpc.get("anna_persona_match")),
        "BC13 → BC14 (pain_matrix flows into joy mapping)": bool(pain_matrix.get("pains_by_type") and joy_matrix.get("pain_to_joy_pairs")),
        "BC14 quality_check passes": bool(qc.get("passes_quality")),
    }
    for name, ok in integration_checks.items():
        print(f"  {'✅' if ok else '❌'} {name}")
    total_int = sum(integration_checks.values())
    print(f"\nIntegration: {total_int}/4 checks pass")

    overall = total_pass == 4 and total_int >= 3
    print(f"\n{'🎯 E2E CHAIN TEST PASSED' if overall else '⚠️ E2E CHAIN TEST INCOMPLETE'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
