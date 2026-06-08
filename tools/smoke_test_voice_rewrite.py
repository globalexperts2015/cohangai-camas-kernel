"""Smoke test apply_voice_rewrite() Sprint 14 P0.3.

Run:
    cd cohangai/services/camas-kernel
    python3 tools/smoke_test_voice_rewrite.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Load env
env_path = Path(__file__).parent.parent.parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

sys.path.insert(0, str(Path(__file__).parent.parent))

from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.voice_gate import apply_voice_rewrite  # noqa: E402


SAMPLE_AI_TONE = """# Vision 5 Năm Cho Nguyen Van A

## Tóm Tắt
Dựa trên thông tin về Nguyen Van A, một nhân viên ngân hàng 38 tuổi đang tìm kiếm cơ hội xây dựng AI Solo Empire, tôi đã phân tích và đưa ra vision 5 năm chi tiết.

## Life Goal Categories

### 1. Tài chính
- Hơn nữa, mục tiêu tài chính của bạn cần được xác định rõ ràng. Tuy nhiên, không nên đặt mục tiêu quá cao ngay từ đầu.
- Do đó, tôi tin rằng bạn nên bắt đầu với mục tiêu thêm 15-20 triệu/tháng.

### 2. Sức khỏe
- Bên cạnh đó, sức khỏe là yếu tố quan trọng. Theo tôi, bạn nên duy trì lịch tập gym 3 lần/tuần.

### 3. Gia đình
- Như chúng ta đã biết, gia đình là nền tảng. Có thể nói, việc cân bằng công việc và gia đình là rất quan trọng.

## Hành Động Tiếp Theo
Tôi tin rằng bạn nên bắt đầu ngay với việc xây dựng nền tảng. Hơn nữa, cần phải có kế hoạch rõ ràng.
"""


async def main() -> int:
    llm = LLMLayer()
    if not llm.ready:
        print("ERROR: LLM not ready, check ANTHROPIC_API_KEY")
        return 1

    print("=" * 60)
    print("INPUT (AI tone):")
    print("=" * 60)
    print(SAMPLE_AI_TONE)
    print()

    print("=" * 60)
    print("REWRITING via apply_voice_rewrite() Haiku 4.5...")
    print("=" * 60)
    rewritten = await apply_voice_rewrite(llm, SAMPLE_AI_TONE, venture_context="breakout")

    print()
    print("=" * 60)
    print("OUTPUT (Anna voice):")
    print("=" * 60)
    print(rewritten)
    print()

    # Verification checks
    print("=" * 60)
    print("VERIFICATION:")
    print("=" * 60)
    checks = {
        "Output != input": rewritten != SAMPLE_AI_TONE,
        "Has signature": "voice-rewritten-anna" in rewritten,
        "No em-dash": "—" not in rewritten,
        "No 'Tôi tin rằng'": "Tôi tin rằng" not in rewritten,
        "No 'Hơn nữa'": "Hơn nữa" not in rewritten,
        "No 'Bên cạnh đó'": "Bên cạnh đó" not in rewritten,
        "No 'Như chúng ta đã biết'": "Như chúng ta đã biết" not in rewritten,
        "Headers preserved": "##" in rewritten,
    }
    all_ok = True
    for check, ok in checks.items():
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {check}")
        if not ok:
            all_ok = False

    print()
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
