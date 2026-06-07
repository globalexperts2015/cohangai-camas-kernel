"""BC2 Voice Guardian smoke test, gọi LLM thật.

Chạy:
    cd cohangai/services/camas-kernel
    /Users/mac/Documents/ANNA SECOND BRAIN/cohangai/.venv/bin/python tests/test_bc2_smoke.py

Yêu cầu ANTHROPIC_API_KEY trong env hoặc trong cohangai/.env.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

# Add camas-kernel root to sys.path để import như khi chạy từ project root
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

from agents.bc2_voice_guardian import BC2VoiceGuardian  # noqa: E402
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402


async def main() -> int:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("FAIL: ANTHROPIC_API_KEY chưa set")
        return 1

    llm = LLMLayer(api_key=api_key)
    assert llm.ready, "LLMLayer chưa init AsyncAnthropic"

    bc2 = BC2VoiceGuardian(llm=llm)
    assert bc2.name == "bc2_voice_guardian"
    assert bc2.knowledge_base, "knowledge_base.md không load được"
    assert bc2.style_rules, "style_rules.md không load được"
    assert bc2.story_pool.get("stories"), "story_pool.json thiếu stories"

    sample_content = (
        "Hồi 2004, Hằng từ Hải Lăng Quảng Trị bay qua Adelaide học master, "
        "không biết tiếng Anh, đem theo 3 chai mắm. "
        "Chính từ 3 chai mắm đó, Mắm Thuyền Nan ra đời 2014."
    )

    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        user_id=None,
        venture_context="personal",
        trigger_event="bc2.smoke_test",
        payload={
            "content": sample_content,
            "meta": {
                "channel": "facebook",
                "venture": "personal",
                "persona": "phụ nữ 30-45",
                "language": "vi",
            },
        },
    )

    print("Calling BC2 Voice Guardian...")
    result = await bc2.run(ctx)

    print("---")
    print(f"success={result.success}")
    print(f"output_text={result.output_text}")
    if result.output_payload:
        verdict = result.output_payload.get("verdict")
        total = result.output_payload.get("total")
        scores = result.output_payload.get("scores")
        red_flags = result.output_payload.get("red_flags")
        notes = result.output_payload.get("notes")
        print(f"verdict={verdict}")
        print(f"total={total}")
        print(f"scores={scores}")
        print(f"red_flags={red_flags}")
        print(f"notes={notes}")
    if result.emitted_memories:
        print(f"emitted_memories={result.emitted_memories}")

    assert result.success is True, f"BC2 phải success, output={result.output_text}"
    verdict = (result.output_payload or {}).get("verdict")
    assert verdict in {"APPROVE", "FLAG", "REJECT"}, f"Verdict không hợp lệ: {verdict}"

    print("---")
    print("OK BC2 smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
