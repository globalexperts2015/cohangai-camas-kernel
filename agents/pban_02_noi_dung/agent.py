"""Phòng 02 Nội dung agent.

Content factory cho 3 ventures Breakout + Speakout + Cohangai. Pipeline: script
generation theo Pain→Gain (memory `feedback-reel-formula-pain-gain.md`) → Vbee
voiceover (phonetic VN) → Creatomate render → BC2 voice + BC9 compliance gate
→ multi-channel publish (FB + IG + TikTok + YouTube Shorts).

Trigger events:
- `content.reel_render_request`: single reel render từ topic + story id
- `content.batch_audit`: weekly batch performance audit + low performer flag

Autonomy L1 (sau BC2 voice + BC9 compliance). Escalate BC2 reject 3 lần → L3
Anna review script tay.

Stack: Vbee + Creatomate + Veed (memory `project-video-render-stack.md`).
ZERO em-dash. Stub APIs Sprint 6+.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

from .creatomate_client import CreatomateAPIError, CreatomateClient
from .vbee_client import VbeeAPIError, VbeeClient

log = logging.getLogger("camas.pban_02_noi_dung")

DEFAULT_LLM_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 800
DEFAULT_LLM_TIMEOUT = 60.0
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"


class Pban02NoiDung(BaseBC):
    """Phòng 02 Nội dung, content factory reel + script + multi-channel publish."""

    name = "pban_02_noi_dung"
    scope = "Reel script + Vbee + Creatomate + 4 channel publish 7-28 reel/tuần"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = [
        "vbee_tts",
        "creatomate_render",
        "fb_graph",
        "ig_reels",
        "tiktok_business",
        "youtube_data",
    ]
    requires_voice_gate = True
    requires_compliance_gate = True

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        model: str = DEFAULT_LLM_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model
        # Lazy clients, init khi cần để tránh crash startup nếu thiếu env
        self._vbee_client: Optional[VbeeClient] = None
        self._creatomate_client: Optional[CreatomateClient] = None

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""

        if event == "content.reel_render_request":
            return await self._handle_reel_render(ctx)
        if event == "content.batch_audit":
            return await self._handle_batch_audit(ctx)

        return AgentResult(
            success=False,
            output_text="Phòng 02 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "content.reel_render_request",
                    "content.batch_audit",
                ],
            },
        )

    # ============================================================
    # Event 1: reel render request
    # ============================================================
    async def _handle_reel_render(self, ctx: ExecutionContext) -> AgentResult:
        """Generate script Pain→Gain + Vbee + Creatomate render brief."""
        payload = ctx.payload or {}
        topic = payload.get("topic", "unknown_topic")
        story_id = payload.get("story_id", "H1")
        venture = ctx.venture_context or "breakout"
        timestamp = self._now_perth_str()

        script = await self._llm_generate_script(
            topic=topic, story_id=story_id, venture=venture
        )

        # Sprint 6 wired: Vbee + Creatomate real APIs với stub fallback
        voice_job = await self._vbee_submit(script, venture=venture)
        render_job = await self._creatomate_render(
            script, voice_job=voice_job, venture=venture
        )

        # BC2 + BC9 gate sẽ chạy ở kernel layer (requires_voice_gate +
        # requires_compliance_gate = True), Phòng 02 chỉ emit content.

        return AgentResult(
            success=True,
            output_text=script,
            output_payload={
                "event": "content.reel_render_request",
                "topic": topic,
                "story_id": story_id,
                "venture": venture,
                "voice_job_id": voice_job.get("job_id"),
                "voice_source": voice_job.get("source"),
                "voice_status": voice_job.get("status"),
                "render_job_id": render_job.get("job_id"),
                "render_source": render_job.get("source"),
                "render_status": render_job.get("status"),
                "audio_used": render_job.get("audio_used"),
                "timestamp_perth": timestamp,
            },
            publish_target="fb",  # downstream BC2/BC9 gate + publisher route
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"reel render topic={topic} story={story_id} venture={venture}"
                    ),
                    "keywords": ["reel", "render", topic, story_id, venture],
                    "tags": ["pban_02", "reel_render", venture],
                    "venture": venture,
                    "context": (
                        f"content.reel_render_request voice={voice_job.get('job_id')} "
                        f"render={render_job.get('job_id')}"
                    ),
                }
            ],
        )

    # ============================================================
    # Event 2: batch audit (weekly)
    # ============================================================
    async def _handle_batch_audit(self, ctx: ExecutionContext) -> AgentResult:
        """Weekly batch performance, flag low performer cho Phòng 10 review."""
        stats = await self._batch_stats(ctx)
        timestamp = self._now_perth_str()

        digest = self._format_batch_digest(timestamp=timestamp, stats=stats)
        sent_ok = await self._maybe_send_telegram(digest)

        return AgentResult(
            success=True,
            output_text=digest,
            output_payload={
                "event": "content.batch_audit",
                "stats": stats,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"batch_audit reels={stats.get('reels_count')} "
                        f"low_perf={stats.get('low_performer_count')}"
                    ),
                    "keywords": ["batch_audit", "performance", timestamp[:10]],
                    "tags": ["pban_02", "batch_audit", "weekly"],
                    "venture": "all",
                    "context": "content.batch_audit weekly digest",
                }
            ],
        )

    # ============================================================
    # LLM + Stubs
    # ============================================================
    async def _llm_generate_script(
        self, *, topic: str, story_id: str, venture: str
    ) -> str:
        """Sinh script Pain→Gain tiếng Việt, ~150 từ."""
        if not self.llm.ready:
            return (
                f"[STUB script] topic={topic} story={story_id} venture={venture} "
                "LLM chưa init"
            )
        prompt = (
            "You are Anna's content writer. Write a 28-60 second reel script in "
            "tiếng Việt theo công thức Pain→Gain (2 Pain + 2 Gain + 1 chiến lược "
            "+ story THẬT của Hằng + CTA Follow Kênh). KHÔNG dùng dấu em-dash. "
            "Câu ngắn 5-12 từ, talk-it-out. Không mention Perth/marital. "
            f"Topic: {topic}. Story id: {story_id}. Venture: {venture}.\n\n"
            "Output script raw, không kèm heading."
        )
        try:
            resp = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban02 LLM call fail: %r", exc)
            return f"[STUB script fallback] topic={topic} story={story_id}"
        parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))
        return ("".join(parts).strip()) or "[empty script]"

    # ============================================================
    # Vbee + Creatomate real wrappers (Sprint 6)
    # ============================================================
    def _get_vbee_client(self) -> Optional[VbeeClient]:
        """Lazy init Vbee client. Trả None nếu thiếu env."""
        if self._vbee_client is not None:
            return self._vbee_client
        api_key = os.getenv("VBEE_API_KEY", "")
        app_id = os.getenv("VBEE_APP_ID", "")
        if not api_key or not app_id:
            log.info("Vbee credentials chưa set, fallback stub")
            return None
        try:
            self._vbee_client = VbeeClient(api_key=api_key, app_id=app_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("Vbee client init fail: %r", exc)
            return None
        return self._vbee_client

    def _get_creatomate_client(self) -> Optional[CreatomateClient]:
        """Lazy init Creatomate client. Trả None nếu thiếu env."""
        if self._creatomate_client is not None:
            return self._creatomate_client
        api_key = os.getenv("CREATOMATE_API_KEY", "")
        if not api_key:
            log.info("Creatomate credentials chưa set, fallback stub")
            return None
        base_url = os.getenv("CREATOMATE_BASE_URL", "https://api.creatomate.com")
        try:
            self._creatomate_client = CreatomateClient(
                api_key=api_key, base_url=base_url
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Creatomate client init fail: %r", exc)
            return None
        return self._creatomate_client

    def _select_voice_code(self, venture: str) -> str:
        """Chọn voice code theo venture (memory `reference-vbee-voice`)."""
        if venture in ("migration", "ve_uc"):
            return os.getenv(
                "VBEE_VOICE_ID_NGOCHUYEN", "hn_female_ngochuyen_full_48k-fhg"
            )
        return os.getenv(
            "VBEE_VOICE_ID_ANNA_CLONE",
            "c_quangtri_female_daothihangmigration_education_vc",
        )

    @staticmethod
    def _extract_title(script: str) -> str:
        """Lấy title cho Creatomate Title.text. First line hoặc first 50 chars."""
        if not script:
            return ""
        first_line = script.strip().splitlines()[0] if script.strip() else ""
        if len(first_line) > 60:
            return first_line[:57] + "..."
        return first_line or script.strip()[:60]

    async def _vbee_submit(
        self, script: str, *, venture: str
    ) -> dict[str, Any]:
        """Real Vbee TTS submit. Fallback stub nếu thiếu creds hoặc lỗi."""
        client = self._get_vbee_client()
        if client is None:
            return await self._stub_vbee_submit(script)
        voice_code = self._select_voice_code(venture)
        try:
            result = await client.submit_tts(text=script, voice_code=voice_code)
        except (VbeeAPIError, ValueError) as exc:
            log.warning("Vbee submit fail, fallback stub: %r", exc)
            stub = await self._stub_vbee_submit(script)
            stub["error"] = repr(exc)
            return stub
        return {
            "job_id": result.get("request_id"),
            "voice": voice_code,
            "status": result.get("status"),
            "source": "vbee_api",
        }

    async def _creatomate_render(
        self,
        script: str,
        *,
        voice_job: dict[str, Any],
        venture: str,
    ) -> dict[str, Any]:
        """Real Creatomate render. Wait Vbee audio link best-effort, fallback stub."""
        client = self._get_creatomate_client()
        if client is None:
            return await self._stub_creatomate_render(script, voice_job)

        # Best-effort wait Vbee audio link (cap 60s, không block kernel)
        audio_url: Optional[str] = None
        vbee_job_id = voice_job.get("job_id")
        if (
            vbee_job_id
            and isinstance(vbee_job_id, str)
            and not vbee_job_id.startswith("vbee_stub_")
        ):
            vbee_client = self._get_vbee_client()
            if vbee_client is not None:
                try:
                    vbee_result = await vbee_client.wait_for_completion(
                        vbee_job_id, max_wait_seconds=60, poll_interval=3.0
                    )
                    if (vbee_result.get("status") or "").upper() == "SUCCESS":
                        audio_url = vbee_result.get("audio_link")
                    else:
                        log.warning(
                            "Vbee wait non-SUCCESS request_id=%s status=%s",
                            vbee_job_id,
                            vbee_result.get("status"),
                        )
                except Exception as exc:  # noqa: BLE001
                    log.warning("Vbee wait error: %r", exc)

        template_id = os.getenv(
            "CREATOMATE_TEMPLATE_ID_HIGHLIGHTED_SUBTITLES", ""
        )
        if not template_id:
            log.warning(
                "CREATOMATE_TEMPLATE_ID_HIGHLIGHTED_SUBTITLES thiếu, fallback stub"
            )
            return await self._stub_creatomate_render(script, voice_job)

        # Modification keys per Sprint 6 spec; verify một lần qua get_template
        # khi cần audit. Truncate subtitle ngăn payload bloat.
        title = self._extract_title(script)
        modifications: dict[str, Any] = {
            "Title.text": title,
            "Subtitle.text": script[:500],
        }
        if audio_url:
            modifications["Audio.source"] = audio_url

        try:
            result = await client.submit_render(
                template_id=template_id,
                modifications=modifications,
            )
        except (CreatomateAPIError, ValueError) as exc:
            log.warning("Creatomate render fail, fallback stub: %r", exc)
            stub = await self._stub_creatomate_render(script, voice_job)
            stub["error"] = repr(exc)
            return stub

        return {
            "job_id": result.get("id"),
            "template": template_id,
            "status": result.get("status"),
            "preview_url": result.get("snapshot_url") or result.get("url"),
            "audio_used": audio_url is not None,
            "voice_job_id": voice_job.get("job_id"),
            "source": "creatomate_api",
        }

    async def _batch_stats(self, ctx: ExecutionContext) -> dict[str, Any]:
        """Query agent_memory cho content performance 7 ngày. Fallback stub."""
        if not getattr(self.memory, "dsn", None):
            return await self._stub_batch_stats(ctx)
        try:
            pool = await self.memory._get_pool()
            async with pool.acquire() as conn:
                reels_count = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM public.agent_memory
                    WHERE agent_name = 'pban_02_noi_dung'
                      AND 'reel_render' = ANY(tags)
                      AND created_at > now() - interval '7 days'
                    """
                )
                rejected = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM public.agent_memory
                    WHERE agent_name = 'bc2_voice_guardian'
                      AND 'REJECT' = ANY(tags)
                      AND created_at > now() - interval '7 days'
                    """
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("batch_stats query fail, fallback stub: %r", exc)
            return await self._stub_batch_stats(ctx)

        return {
            "reels_count": int(reels_count or 0),
            "low_performer_count": int(rejected or 0),
            # Giữ schema dùng bởi _format_batch_digest, đặt 0.0 thay vì bịa
            "avg_stop_rate": 0.0,
            "avg_read_through": 0.0,
            "avg_action_rate": 0.0,
            "top_reel_id": "n/a",
            "period": "7d",
            "source": "agent_memory_query",
        }

    # ============================================================
    # STUB fallbacks (preserved cho test + missing creds)
    # ============================================================
    async def _stub_vbee_submit(self, script: str) -> dict[str, Any]:
        """STUB Vbee Special plan async API."""
        return {
            "job_id": f"vbee_stub_{abs(hash(script)) % 10**8}",
            "voice": "anna_clone_vn",
            "estimated_seconds": 45,
            "status": "STUB",
            "source": "stub",
        }

    async def _stub_creatomate_render(
        self, script: str, voice_job: dict[str, Any]
    ) -> dict[str, Any]:
        """STUB Creatomate render."""
        return {
            "job_id": f"crm_stub_{abs(hash(script)) % 10**8}",
            "template": "reel-white-red-box-v1",
            "voice_job_id": voice_job.get("job_id"),
            "status": "STUB",
            "audio_used": False,
            "source": "stub",
        }

    async def _stub_batch_stats(self, ctx: ExecutionContext) -> dict[str, Any]:
        """STUB Postgres content_log + FB Insights aggregate."""
        # TODO Sprint 6 wire Postgres content_log
        return {
            "reels_count": 18,
            "avg_stop_rate": 0.36,
            "avg_read_through": 0.42,
            "avg_action_rate": 0.05,
            "low_performer_count": 3,
            "top_reel_id": "stub_reel_42",
        }

    # ============================================================
    # Format helpers
    # ============================================================
    def _format_batch_digest(
        self, *, timestamp: str, stats: dict[str, Any]
    ) -> str:
        return (
            f"Phòng 02 Batch Audit {timestamp}\n\n"
            f"Reels published 7d: {stats.get('reels_count')}\n"
            f"Stop rate avg: {stats.get('avg_stop_rate'):.0%}\n"
            f"Read-through avg: {stats.get('avg_read_through'):.0%}\n"
            f"Action rate avg: {stats.get('avg_action_rate'):.0%}\n"
            f"Low performer: {stats.get('low_performer_count')} reels\n\n"
            f"Top reel: {stats.get('top_reel_id')}"
        )

    # ============================================================
    # Telegram + utility
    # ============================================================
    async def _maybe_send_telegram(self, text: str) -> bool:
        dry_run = os.getenv("PBAN_DRY_RUN", "") == "1"
        if dry_run:
            log.info("Pban02 DRY_RUN, skip Telegram send")
            return True
        try:
            return await send_telegram(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban02 Telegram send fail: %r", exc)
            return False

    @staticmethod
    def _now_perth_str() -> str:
        now_perth = datetime.now(tz=timezone.utc) + timedelta(hours=8)
        return now_perth.strftime("%Y-%m-%d %H:%M")


async def send_telegram(text: str) -> bool:
    """Gửi Telegram Breakout Ops."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_OPS_GROUP_ID", DEFAULT_TELEGRAM_GROUP_ID)
    if not token:
        log.warning("Pban02 TELEGRAM_BOT_TOKEN chưa set, skip send")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=DEFAULT_TELEGRAM_TIMEOUT) as client:
        resp = await client.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )
        if resp.status_code != 200:
            log.warning(
                "Pban02 Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
