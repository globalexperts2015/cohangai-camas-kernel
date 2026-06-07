"""BC9 Compliance Officer smoke test, gọi LLM thật + run deterministic regex.

Chạy:
    cd cohangai/services/camas-kernel
    /Users/mac/Documents/ANNA SECOND BRAIN/cohangai/.venv/bin/python tests/test_bc9_smoke.py

Yêu cầu ANTHROPIC_API_KEY trong env hoặc trong cohangai/.env.

3 test case:
1. Clean content                → APPROVE
2. MARA hard violation          → BLOCK with mara flagged
3. Brand hard violation         → BLOCK with brand flagged
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

# Add camas-kernel root to sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Load env từ cohangai/.env nếu có
try:
    from dotenv import load_dotenv

    env_path = ROOT.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from agents.bc9_compliance_officer import BC9ComplianceOfficer  # noqa: E402
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402


def make_ctx(content: str, venture: str = "personal") -> ExecutionContext:
    return ExecutionContext(
        run_id=str(uuid.uuid4()),
        user_id=None,
        venture_context=venture,
        trigger_event="bc9.smoke_test",
        payload={
            "content": content,
            "meta": {
                "channel": "facebook",
                "venture": venture,
                "language": "vi",
            },
        },
    )


async def run_case(
    bc9: BC9ComplianceOfficer,
    label: str,
    content: str,
    expect_verdict: str,
    expect_layer: str | None = None,
) -> bool:
    print(f"\n=== {label} ===")
    print(f"Content: {content[:120]}...")
    ctx = make_ctx(content)
    result = await bc9.run(ctx)

    verdict = (result.output_payload or {}).get("verdict")
    layers = (result.output_payload or {}).get("layers", {})
    violations = (result.output_payload or {}).get("violations", [])
    fixes = (result.output_payload or {}).get("suggested_fixes", [])

    print(f"success={result.success}")
    print(f"verdict={verdict}")
    print(f"layers={layers}")
    print(f"violations={violations[:3]}")
    if fixes:
        sample_fix = fixes[0]
        print(
            f"sample_fix: original={sample_fix.get('original', '')[:50]!r} "
            f"-> suggested={sample_fix.get('suggested', '')[:50]!r}"
        )

    ok = True
    if verdict != expect_verdict:
        print(f"FAIL: expected verdict={expect_verdict}, got {verdict}")
        ok = False
    if expect_layer and layers.get(expect_layer) != "hard":
        print(
            f"FAIL: expected layer={expect_layer} = hard, "
            f"got {layers.get(expect_layer)}"
        )
        ok = False
    if ok:
        print(f"PASS ({label})")
    return ok


async def main() -> int:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("FAIL: ANTHROPIC_API_KEY chưa set")
        return 1

    llm = LLMLayer(api_key=api_key)
    assert llm.ready, "LLMLayer chưa init AsyncAnthropic"

    bc9 = BC9ComplianceOfficer(llm=llm)
    assert bc9.name == "bc9_compliance_officer"
    assert bc9.rules, "Rules chưa load"
    assert len(bc9._compiled_rules) > 0, "Compiled rules empty"
    print(f"BC9 loaded {len(bc9.rules)} layer, {len(bc9._compiled_rules)} compiled rules")

    results = []

    # Case 1: clean
    results.append(
        await run_case(
            bc9,
            "Case 1: Clean content",
            "Hằng chia sẻ kinh nghiệm xây business solo bằng AI. "
            "Đây là hành trình từ con số 0 lên hệ thống tự vận hành.",
            expect_verdict="APPROVE",
        )
    )

    # Case 2: MARA violation
    results.append(
        await run_case(
            bc9,
            "Case 2: MARA hard violation",
            "Khoá học của Hằng đảm bảo visa cho bạn với 100% thành công. "
            "Tỷ lệ thành công của chúng tôi là 98% cho mọi hồ sơ visa 482.",
            expect_verdict="BLOCK",
            expect_layer="mara",
        )
    )

    # Case 3: Brand violation
    results.append(
        await run_case(
            bc9,
            "Case 3: Brand hard violation",
            "Là mẹ đơn thân ở Perth, Hằng đã xây Mắm Thuyền Nan từ con số 0. "
            "Cô là Việt kiều thành công ở Úc.",
            expect_verdict="BLOCK",
            expect_layer="brand",
        )
    )

    passed = sum(1 for r in results if r)
    print(f"\n=== SUMMARY: {passed}/{len(results)} passed ===")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
