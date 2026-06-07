"""BC7 FB Autoreply smoke test.

Chạy:
    cd cohangai/services/camas-kernel
    BC7_DRY_RUN=1 /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python tests/test_bc7_smoke.py

DRY_RUN bắt buộc cho local test:
- Không gửi FB Send API (kernel post-hook skip publish_target)
- Vẫn gọi LLM thật (cần ANTHROPIC_API_KEY)

Test 4 trigger event:
1. FB DM hỏi giá khoá Breakout → AUTO_REPLY, confidence ≥ 70
2. FB comment spam "Bán hàng giá rẻ tại nhà.com" → IGNORE, is_spam=True
3. FB DM troll "Bạn lừa đảo" → IGNORE, is_troll=True
4. unknown event → success=False
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

from agents.bc7_fb_autoreply import BC7FBAutoreply  # noqa: E402
from kernel.base_agent import ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer, VoyageEmbedder  # noqa: E402


async def main() -> int:
    os.environ.setdefault("BC7_DRY_RUN", "1")

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

    bc7 = BC7FBAutoreply(llm=llm, memory=memory)
    assert bc7.name == "bc7_fb_autoreply"
    assert bc7.autonomy_level.value == "L1"
    assert bc7.requires_voice_gate is True
    assert bc7.requires_compliance_gate is True

    page_id = "112307003450690"  # Đào Thị Hằng page

    # Test 1: FB DM hỏi giá khoá Breakout → AUTO_REPLY
    ctx_dm_pricing = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="fb.message.in",
        payload={
            "message_text": (
                "Chị ơi cho em hỏi khoá Breakout giá bao nhiêu vậy ạ? "
                "Em mới biết tới chị qua reel."
            ),
            "sender_id": "test_sender_001",
            "page_id": page_id,
        },
    )
    print("Test 1: FB DM pricing question...")
    res1 = await bc7.run(ctx_dm_pricing)
    print(f"  success={res1.success}")
    print(f"  verdict={res1.output_payload.get('verdict')}")
    print(f"  confidence={res1.output_payload.get('confidence')}")
    print(f"  reply_text={res1.output_payload.get('reply_text')!r}")
    print(f"  reply_len={len(res1.output_payload.get('reply_text') or '')}")
    print(f"  topic={res1.output_payload.get('topic')}")
    print(f"  publish_target={res1.publish_target}")
    assert res1.success is True
    assert res1.output_payload.get("verdict") == "AUTO_REPLY", (
        f"Expected AUTO_REPLY, got {res1.output_payload.get('verdict')}"
    )
    assert res1.output_payload.get("confidence", 0) >= 70, (
        f"Confidence too low: {res1.output_payload.get('confidence')}"
    )
    assert res1.publish_target == "fb_dm"
    assert len(res1.output_payload.get("reply_text") or "") <= 120, (
        "DM reply must be ≤120 chars"
    )

    # Test 2: FB comment spam → IGNORE
    ctx_comment_spam = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="personal",
        trigger_event="fb.comment.in",
        payload={
            "message_text": (
                "Bán hàng giá rẻ tại nhà.com - kiếm 50tr/tháng inbox em "
                "ngay! Link: http://spam-promo-site.tk/abc"
            ),
            "sender_id": "test_spammer_001",
            "page_id": page_id,
        },
    )
    print("\nTest 2: FB comment spam...")
    res2 = await bc7.run(ctx_comment_spam)
    print(f"  success={res2.success}")
    print(f"  verdict={res2.output_payload.get('verdict')}")
    print(f"  is_spam={res2.output_payload.get('is_spam')}")
    print(f"  reply_text={res2.output_payload.get('reply_text')!r}")
    print(f"  publish_target={res2.publish_target}")
    assert res2.success is True
    assert res2.output_payload.get("verdict") == "IGNORE", (
        f"Expected IGNORE, got {res2.output_payload.get('verdict')}"
    )
    assert res2.output_payload.get("is_spam") is True, "Must detect spam"
    assert res2.publish_target is None, "IGNORE should not publish"
    assert (res2.output_payload.get("reply_text") or "") == "", (
        "Spam reply must be empty"
    )

    # Test 3: FB DM troll → IGNORE
    ctx_dm_troll = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="personal",
        trigger_event="fb.message.in",
        payload={
            "message_text": "Bạn lừa đảo, mấy khoá học của bạn vô dụng!",
            "sender_id": "test_troll_001",
            "page_id": page_id,
        },
    )
    print("\nTest 3: FB DM troll...")
    res3 = await bc7.run(ctx_dm_troll)
    print(f"  success={res3.success}")
    print(f"  verdict={res3.output_payload.get('verdict')}")
    print(f"  is_troll={res3.output_payload.get('is_troll')}")
    print(f"  reply_text={res3.output_payload.get('reply_text')!r}")
    print(f"  publish_target={res3.publish_target}")
    assert res3.success is True
    assert res3.output_payload.get("verdict") == "IGNORE", (
        f"Expected IGNORE, got {res3.output_payload.get('verdict')}"
    )
    assert res3.output_payload.get("is_troll") is True, "Must detect troll"
    assert res3.publish_target is None, "IGNORE should not publish"

    # Test 4: unknown event → success=False
    ctx_unknown = ExecutionContext(
        run_id=str(uuid.uuid4()),
        venture_context="breakout",
        trigger_event="fb.random.unknown",
        payload={},
    )
    print("\nTest 4: unknown event...")
    res4 = await bc7.run(ctx_unknown)
    print(f"  success={res4.success}")
    print(f"  output_text={res4.output_text}")
    assert res4.success is False
    assert "không xử lý" in (res4.output_text or "")

    try:
        await memory.close()
    except Exception:  # noqa: BLE001
        pass

    print("\n---")
    print("OK BC7 smoke test passed (4/4)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
