"""Content Distributor agent.

Apply Stage 11 Content Pyramid: long-form video transcript → 65 derived assets.
- 10 Short hooks (60s extract suggestions với timestamp)
- 20 Reel angles (15s remix với hook variation)
- 5 Blog post outlines
- 10 Email drip (chunked nurture sequence)
- 20 Facebook posts (snippet + CTA)

Trigger event: content.distribute_pyramid

Output: 65 records canonical (per-derived-asset) + 1 summary record.

KHÔNG auto-publish. Anna review trước qua BC2 voice gate downstream.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

log = logging.getLogger("camas.content_distributor")

EXPECTED_EVENTS = {"content.distribute_pyramid"}

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 8000
DEFAULT_TIMEOUT = 240.0


SUBMIT_PYRAMID_TOOL = {
    "name": "submit_content_pyramid",
    "description": "Submit content pyramid 65 derived assets từ 1 long-form video",
    "input_schema": {
        "type": "object",
        "properties": {
            "source_video_id": {"type": "string"},
            "source_platform": {"type": "string"},
            "source_topic": {"type": "string"},
            "venture": {"type": "string"},
            "short_hooks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "hook_text": {"type": "string"},
                        "timestamp_start_seconds": {"type": "integer"},
                        "timestamp_end_seconds": {"type": "integer"},
                        "format": {"type": "string", "description": "60s shorts YouTube/TikTok"},
                    },
                },
                "description": "10 Shorts 60s",
            },
            "reel_angles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "hook_first_5_sec": {"type": "string"},
                        "body": {"type": "string"},
                        "cta": {"type": "string"},
                    },
                },
                "description": "20 Reels 15s remix với hook variation",
            },
            "blog_outlines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "h2_headers": {"type": "array", "items": {"type": "string"}},
                        "key_takeaway": {"type": "string"},
                        "target_keywords": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "description": "5 blog post outlines",
            },
            "email_drip": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "day": {"type": "integer"},
                        "subject": {"type": "string"},
                        "body_summary": {"type": "string"},
                        "cta": {"type": "string"},
                    },
                },
                "description": "10 email nurture sequence",
            },
            "fb_posts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "hook": {"type": "string"},
                        "body": {"type": "string"},
                        "cta": {"type": "string"},
                    },
                },
                "description": "20 FB post snippets",
            },
            "pyramid_summary": {"type": "string"},
        },
        "required": [
            "source_video_id",
            "source_platform",
            "venture",
            "short_hooks",
            "reel_angles",
            "blog_outlines",
            "email_drip",
            "fb_posts",
            "pyramid_summary",
        ],
    },
}


def build_pyramid_prompt(
    transcript: str, source_video_id: str, source_platform: str, source_topic: str, venture: str
) -> str:
    return f"""Bạn là chuyên gia Content Pyramid theo Stage 11 framework Solo Business Growth System v2.

# Source video
- ID: {source_video_id}
- Platform: {source_platform}
- Topic: {source_topic}
- Venture: {venture}

# Transcript (first 4000 chars)
{transcript[:4000]}

# Task

Distribute long-form video thành 65 derived assets:

## 10 Short hooks (60s YouTube/TikTok Shorts)
Mỗi short có: hook_text (5s đầu critical) + timestamp_start + timestamp_end (extract 60s từ transcript) + format.

## 20 Reel angles (15s remix)
Mỗi reel: title (white box red text) + hook_first_5_sec + body + cta. Apply Anna voice DNA (Hằng/bạn, mộc mạc, concrete).

## 5 Blog post outlines
Mỗi blog: title (SEO keyword) + 5-8 H2 headers + key_takeaway + 3-5 target_keywords.

## 10 Email drip nurture sequence
Day 1-30 spacing. Mỗi email: day + subject (5-9 từ) + body_summary (150-300 từ) + cta.

## 20 FB posts
Mỗi post: hook (2 dòng đầu) + body (300-500 từ) + cta. Mix story-driven + insight + CTA discussion.

# Quality requirements
- KHÔNG bịa quote không có trong transcript
- Apply Dan Lok 8 Tactical Secrets (call out + big promise + enemies + stories + specificity + pain + demonstrate + USP)
- Apply Brunson Soap Opera cho email sequence
- Apply Hormozi Hook-Retain-Reward cho mọi piece
- Anna voice DNA: Hằng/bạn, mộc mạc, concrete number, ẩn dụ dân dã
- KHÔNG em-dash, no "mẹ đơn thân", no Perth/Adelaide

Output qua tool submit_content_pyramid.
"""


class ContentDistributor(BaseBC):
    """BC Content Distributor, Stage 11 Pyramid."""

    name = "content_distributor"
    scope = "Distribute 1 long-form video → 65 derived assets (Stage 11 Content Pyramid)"
    autonomy_level = AutonomyLevel.L2_APPROVE  # Anna review trước publish
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = True
    requires_compliance_gate = True

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        model: str = DEFAULT_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(
                success=False,
                output_text=f"{self.name} không xử lý event này",
                output_payload={
                    "trigger_event": event,
                    "supported": list(EXPECTED_EVENTS),
                },
            )

        payload = ctx.payload or {}
        transcript = payload.get("transcript", "")
        source_video_id = payload.get("source_video_id", "unknown")
        source_platform = payload.get("source_platform", "youtube")
        source_topic = payload.get("source_topic", "")
        venture = ctx.venture_context or "all"

        if not transcript or len(transcript) < 200:
            return AgentResult(
                success=False,
                output_text="Missing transcript",
                output_payload={"error": "payload.transcript < 200 chars"},
            )

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "ANTHROPIC_API_KEY chưa set"},
            )

        prompt = build_pyramid_prompt(
            transcript, source_video_id, source_platform, source_topic, venture
        )

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_PYRAMID_TOOL],
                tool_choice={"type": "tool", "name": "submit_content_pyramid"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("content_distributor LLM fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        pyramid = self._parse_response(response)
        if "error" in pyramid:
            return AgentResult(success=False, output_text=pyramid["error"], output_payload=pyramid)

        shorts = len(pyramid.get("short_hooks", []))
        reels = len(pyramid.get("reel_angles", []))
        blogs = len(pyramid.get("blog_outlines", []))
        emails = len(pyramid.get("email_drip", []))
        posts = len(pyramid.get("fb_posts", []))
        total = shorts + reels + blogs + emails + posts

        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = (
            f"pyramid source={source_video_id} venture={venture} "
            f"shorts={shorts} reels={reels} blogs={blogs} "
            f"emails={emails} posts={posts} total={total}"
        )

        memory_entry = {
            "agent_name": self.name,
            "content_summary": (
                f"Content pyramid {date_str} source={source_video_id}: "
                f"{shorts} shorts + {reels} reels + {blogs} blogs + "
                f"{emails} emails + {posts} posts = {total} assets"
            ),
            "keywords": ["content_distributor", venture, source_video_id, source_topic[:50]],
            "tags": [
                "content_distributor",
                "stage_11",
                "pyramid",
                venture,
                source_platform,
                date_str,
            ],
            "venture": venture,
            "category": "venture_state",
            "context": f"content.distribute_pyramid {date_str} source={source_video_id}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=pyramid,
            emitted_memories=[memory_entry],
        )

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_content_pyramid"
            ):
                return block.input or {}
        return {"error": "No tool_use block"}
