"""Smoke test Vbee + Creatomate real APIs cho Pban02 Nội dung.

Chạy:
    cd cohangai/services/camas-kernel
    PBAN_DRY_RUN=1 PBAN02_DRY_RUN=1 \\
      /Users/mac/Documents/ANNA\\ SECOND\\ BRAIN/cohangai/.venv/bin/python \\
      tests/test_pban_02_real.py

Tests:
1. VbeeClient instantiate + submit_tts với text ngắn ("xin chào")
   (1 submit, KHÔNG poll lâu để tiết kiệm Special plan budget)
2. CreatomateClient instantiate + get_template() (read-only, free)
3. Pban02 agent dry-run content.reel_render_request → source="vbee_api"
   và "creatomate_api"
4. Pban02 fallback stub khi xóa env credential
5. CronSocialPosts run với mock scheduler delegate (in-process)
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


from agents.cron_social_posts import CronSocialPosts  # noqa: E402
from agents.pban_02_noi_dung import Pban02NoiDung  # noqa: E402
from agents.pban_02_noi_dung.creatomate_client import (  # noqa: E402
    CreatomateAPIError,
    CreatomateClient,
)
from agents.pban_02_noi_dung.vbee_client import (  # noqa: E402
    VbeeAPIError,
    VbeeClient,
)
from kernel.base_agent import AgentResult, ExecutionContext  # noqa: E402
from kernel.llm_layer import LLMLayer  # noqa: E402
from kernel.memory_layer import MemoryLayer  # noqa: E402


def header(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


class FakeScheduler:
    """Mock scheduler để verify delegation chain Cron → Pban02 in-process."""

    def __init__(self, agents: dict[str, Any]) -> None:
        self._agents = agents
        self.calls: list[tuple[str, ExecutionContext]] = []

    async def execute(
        self, agent_name: str, ctx: ExecutionContext
    ) -> AgentResult:
        self.calls.append((agent_name, ctx))
        agent = self._agents.get(agent_name)
        if agent is None:
            return AgentResult(
                success=False, error=f"FakeScheduler thiếu agent {agent_name}"
            )
        return await agent.execute(ctx)


async def main() -> int:
    os.environ.setdefault("PBAN_DRY_RUN", "1")
    os.environ.setdefault("PBAN02_DRY_RUN", "1")

    vbee_key = os.getenv("VBEE_API_KEY", "")
    vbee_app = os.getenv("VBEE_APP_ID", "")
    crm_key = os.getenv("CREATOMATE_API_KEY", "")
    tmpl_id = os.getenv("CREATOMATE_TEMPLATE_ID_HIGHLIGHTED_SUBTITLES", "")

    print(
        f"vbee_key_len={len(vbee_key)} app_set={bool(vbee_app)} "
        f"crm_key_len={len(crm_key)} tmpl={tmpl_id[:8]}..."
    )

    failures: list[str] = []
    sample: dict[str, Any] = {}

    # ============================================================
    # Test 1: Vbee submit_tts text ngắn (KHÔNG poll lâu)
    # ============================================================
    header("Test 1: VbeeClient.submit_tts(text='xin chào')")
    if not vbee_key or not vbee_app:
        msg = "Test 1 SKIP: thiếu VBEE_API_KEY hoặc VBEE_APP_ID"
        print(f"  {msg}")
    else:
        try:
            client = VbeeClient(api_key=vbee_key, app_id=vbee_app)
            voice = os.getenv(
                "VBEE_VOICE_ID_ANNA_CLONE",
                "c_quangtri_female_daothihangmigration_education_vc",
            )
            result = await client.submit_tts(
                text="Xin chào, đây là test Vbee từ camas kernel.",
                voice_code=voice,
            )
            print(
                f"  request_id={result.get('request_id')} "
                f"status={result.get('status')}"
            )
            sample["vbee_request_id"] = result.get("request_id")
            sample["vbee_status"] = result.get("status")
        except VbeeAPIError as exc:
            msg = (
                f"Test 1 FAIL: VbeeAPIError {exc} status={exc.status_code} "
                f"body={(exc.body or '')[:200]}"
            )
            print(f"  {msg}")
            failures.append(msg)
        except Exception as exc:  # noqa: BLE001
            msg = f"Test 1 CRASH: {exc!r}"
            print(f"  {msg}")
            failures.append(msg)

    # ============================================================
    # Test 2: Creatomate get_template (read-only)
    # ============================================================
    header("Test 2: CreatomateClient.get_template(HighlightedSubtitles)")
    if not crm_key or not tmpl_id:
        msg = "Test 2 SKIP: thiếu CREATOMATE_API_KEY hoặc template id"
        print(f"  {msg}")
    else:
        try:
            cm = CreatomateClient(api_key=crm_key)
            tmpl = await cm.get_template(tmpl_id)
            print(f"  name={tmpl.get('name')} status={tmpl.get('status')}")
            keys = cm.extract_modification_keys(tmpl)
            print(f"  modification_keys (best-effort): {keys[:10]}")
            sample["template_name"] = tmpl.get("name")
            sample["template_mod_keys"] = keys[:10]
        except CreatomateAPIError as exc:
            msg = (
                f"Test 2 FAIL: CreatomateAPIError {exc} "
                f"status={exc.status_code} body={(exc.body or '')[:200]}"
            )
            print(f"  {msg}")
            failures.append(msg)
        except Exception as exc:  # noqa: BLE001
            msg = f"Test 2 CRASH: {exc!r}"
            print(f"  {msg}")
            failures.append(msg)

    # ============================================================
    # Test 3: Pban02 agent dry-run với real creds → source=*_api
    # ============================================================
    header("Test 3: Pban02 agent reel_render_request (real APIs)")
    try:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        llm = LLMLayer(api_key=api_key) if api_key else LLMLayer(api_key="dummy")
        memory = MemoryLayer(dsn=None, embedder=None)
        agent = Pban02NoiDung(llm=llm, memory=memory)
        ctx = ExecutionContext(
            run_id=str(uuid.uuid4()),
            venture_context="breakout",
            trigger_event="content.reel_render_request",
            payload={"topic": "ai_solo_business", "story_id": "H1"},
        )
        result = await agent.run(ctx)
        payload = result.output_payload or {}
        print(f"  success={result.success}")
        print(f"  voice_source={payload.get('voice_source')}")
        print(f"  voice_job_id={payload.get('voice_job_id')}")
        print(f"  voice_status={payload.get('voice_status')}")
        print(f"  render_source={payload.get('render_source')}")
        print(f"  render_job_id={payload.get('render_job_id')}")
        print(f"  audio_used={payload.get('audio_used')}")
        sample["agent_voice_source"] = payload.get("voice_source")
        sample["agent_render_source"] = payload.get("render_source")
        try:
            await memory.close()
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        msg = f"Test 3 CRASH: {exc!r}"
        print(f"  {msg}")
        failures.append(msg)

    # ============================================================
    # Test 4: Pban02 fallback stub khi creds rỗng
    # ============================================================
    header("Test 4: Pban02 fallback stub (creds missing)")
    saved_vbee = os.environ.pop("VBEE_API_KEY", None)
    saved_crm = os.environ.pop("CREATOMATE_API_KEY", None)
    try:
        llm = LLMLayer(api_key="dummy")
        memory = MemoryLayer(dsn=None, embedder=None)
        agent = Pban02NoiDung(llm=llm, memory=memory)
        ctx = ExecutionContext(
            run_id=str(uuid.uuid4()),
            venture_context="breakout",
            trigger_event="content.reel_render_request",
            payload={"topic": "fallback_test", "story_id": "H1"},
        )
        result = await agent.run(ctx)
        payload = result.output_payload or {}
        voice_src = payload.get("voice_source")
        render_src = payload.get("render_source")
        print(f"  voice_source={voice_src} render_source={render_src}")
        if voice_src != "stub" or render_src != "stub":
            failures.append(
                f"Test 4 FAIL: expected stub fallback, got "
                f"voice={voice_src} render={render_src}"
            )
        try:
            await memory.close()
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        msg = f"Test 4 CRASH: {exc!r}"
        print(f"  {msg}")
        failures.append(msg)
    finally:
        if saved_vbee:
            os.environ["VBEE_API_KEY"] = saved_vbee
        if saved_crm:
            os.environ["CREATOMATE_API_KEY"] = saved_crm

    # ============================================================
    # Test 5: CronSocialPosts → delegate Pban02 (mock scheduler)
    # ============================================================
    header("Test 5: CronSocialPosts → Pban02 delegation (3 topics)")
    try:
        llm = LLMLayer(api_key="dummy")
        memory = MemoryLayer(dsn=None, embedder=None)
        pban02 = Pban02NoiDung(llm=llm, memory=memory)
        fake_sched = FakeScheduler(agents={"pban_02_noi_dung": pban02})
        cron = CronSocialPosts(llm=llm, memory=memory, scheduler=fake_sched)
        ctx = ExecutionContext(
            run_id=str(uuid.uuid4()),
            venture_context="all",
            trigger_event="cron.social_posts.tick",
            payload={"dry_run": True},
        )
        result = await cron.run(ctx)
        payload = result.output_payload or {}
        print(f"  success={result.success}")
        print(f"  topic_count={payload.get('topic_count')}")
        print(f"  delegated_ok={payload.get('delegated_ok')}")
        print(f"  scheduler.calls={len(fake_sched.calls)}")
        for d in payload.get("delegations", []):
            print(
                f"    - {d.get('topic')} success={d.get('success')} "
                f"voice={d.get('voice_source')} render={d.get('render_source')}"
            )
        sample["cron_delegated_ok"] = payload.get("delegated_ok")
        sample["cron_topic_count"] = payload.get("topic_count")
        sample["cron_scheduler_calls"] = len(fake_sched.calls)
        if payload.get("topic_count") != 3:
            failures.append(
                f"Test 5 FAIL: expected 3 topic, got {payload.get('topic_count')}"
            )
        if len(fake_sched.calls) != 3:
            failures.append(
                f"Test 5 FAIL: expected 3 scheduler.execute calls, "
                f"got {len(fake_sched.calls)}"
            )
        try:
            await memory.close()
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        msg = f"Test 5 CRASH: {exc!r}"
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
    for k, v in sample.items():
        print(f"  {k}: {v}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
