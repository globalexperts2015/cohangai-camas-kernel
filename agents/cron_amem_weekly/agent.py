"""Cron A-mem Weekly auto-evolve, Sunday weekly Zettelkasten-inspired pass.

Pattern: cron-job.org -> POST /kernel/execute, event=cron.amem_weekly.tick.

A-mem (Agentic Memory) Zettelkasten pattern từ paper arxiv 2502.12110:
- MemoryNote auto-evolves theo thời gian
- Mỗi memory auto-extract keywords + auto-discover links tới related memories
- Track evolution_history append-only
- Pain theme cluster = group BC3 customer feedback theo semantic similarity

Pipeline run():
    Phase 1: SQL scan past 7 ngày memory thiếu keywords (cardinality < 3)
    Phase 2: Haiku batch extract keywords (10 memory/call) cho cost efficiency
    Phase 3: pgvector cosine auto-discover top 3 links/memory (threshold 0.4)
    Phase 4: Append evolution_history JSONB
    Phase 5: BC3 feedback pain theme cluster qua 1 Haiku batch call
    Phase 6: Emit digest memory + Telegram BC1 group Breakout Ops

Env vars:
    ANTHROPIC_API_KEY: cho Haiku 4.5 batch call
    DATABASE_URL: Postgres pgvector cho agent_memory
    TELEGRAM_BOT_TOKEN: bot token send digest
    TELEGRAM_OPS_GROUP_ID: chat id (default -1003813280155)
    CRON_AMEM_WEEKLY_DRY_RUN=1: skip Telegram + skip Postgres write
    CRON_DRY_RUN=1: alias dry run cho cron pipeline

Payload (optional):
    max_memories: int (default 200)
    batch_size: int (default 10, Haiku batch)
    cosine_threshold: float (default 0.4)
    dry_run: bool (override env)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

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

log = logging.getLogger("camas.cron_amem_weekly")

EXPECTED_EVENT = "cron.amem_weekly.tick"

DEFAULT_LLM_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_MEMORIES = 200
DEFAULT_BATCH_SIZE = 10
DEFAULT_COSINE_THRESHOLD = 0.4
DEFAULT_LLM_MAX_TOKENS = 2000
DEFAULT_LLM_TIMEOUT = 60.0
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"  # Breakout Ops

BC3_AGENTS = ("bc3_feedback_loop", "bc3_profile_extractor")
PAIN_THEME_SAMPLE_LIMIT = 50


class CronAmemWeekly(BaseBC):
    """Cron weekly A-mem auto-evolve.

    Zettelkasten dynamic linking + LLM keyword extraction + pain theme cluster.
    Output digest memory cho BC1 rollup + Telegram alert Breakout Ops.
    """

    name = "cron_amem_weekly"
    scope = (
        "A-mem auto-evolve: weekly extract keywords, auto-link related memories, "
        "cluster pain themes, emit BC1 digest"
    )
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

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

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event != EXPECTED_EVENT:
            return AgentResult(
                success=False,
                output_text=f"{self.name} không xử lý event này",
                output_payload={
                    "trigger_event": event,
                    "supported": [EXPECTED_EVENT],
                },
            )

        date_vn = self._date_vn_str()
        payload = ctx.payload or {}
        max_memories = int(payload.get("max_memories") or DEFAULT_MAX_MEMORIES)
        batch_size = int(payload.get("batch_size") or DEFAULT_BATCH_SIZE)
        cosine_threshold = float(
            payload.get("cosine_threshold") or DEFAULT_COSINE_THRESHOLD
        )
        dry_run = bool(payload.get("dry_run")) or (
            os.getenv("CRON_AMEM_WEEKLY_DRY_RUN", "") == "1"
        ) or (
            os.getenv("CRON_DRY_RUN", "") == "1"
        )

        stats = await self._run_pipeline(
            date_vn=date_vn,
            max_memories=max_memories,
            batch_size=batch_size,
            cosine_threshold=cosine_threshold,
            dry_run=dry_run,
        )
        status_tag = "ok" if stats.get("error") is None else "fail"

        top_theme = "không có"
        pain_themes = stats.get("pain_themes") or []
        if pain_themes:
            first = pain_themes[0]
            top_theme = f"{first.get('theme', '?')} ({first.get('count', 0)})"

        content_summary = (
            f"A-mem weekly evolve: {stats.get('processed', 0)} memories updated, "
            f"{stats.get('keywords_total', 0)} keywords added, "
            f"{stats.get('links_total', 0)} links discovered, "
            f"top theme: {top_theme}"
        )

        emitted_memories = [
            {
                "agent_name": self.name,
                "content_summary": content_summary,
                "content": json.dumps(stats, ensure_ascii=False)[:4000],
                "keywords": ["amem", "auto_evolve", "pain_themes"],
                "tags": ["cron", "amem", "weekly", "evolve", status_tag],
                "category": "venture_state",
                "venture": "all",
                "context": f"{EXPECTED_EVENT} {date_vn}",
            }
        ]

        return AgentResult(
            success=True,
            output_text=(
                f"A-mem weekly {date_vn}: {stats.get('processed', 0)} memories updated, "
                f"{stats.get('keywords_total', 0)} keywords added, "
                f"{stats.get('links_total', 0)} links, "
                f"pain themes top {len(pain_themes)}, dry_run={dry_run}"
            ),
            output_payload={
                "event": EXPECTED_EVENT,
                "date_vn": date_vn,
                "status_tag": status_tag,
                "stats": stats,
                "dry_run": dry_run,
            },
            emitted_memories=emitted_memories,
        )

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self,
        *,
        date_vn: str,
        max_memories: int,
        batch_size: int,
        cosine_threshold: float,
        dry_run: bool,
    ) -> dict[str, Any]:
        """Pipeline 6 phase A-mem auto-evolve.

        Fail-soft: SQL fail / LLM fail / Telegram fail = log + continue, không crash.
        """
        stats: dict[str, Any] = {
            "scanned": 0,
            "processed": 0,
            "keywords_total": 0,
            "links_total": 0,
            "pain_themes": [],
            "telegram_sent": False,
            "dry_run": dry_run,
            "error": None,
            "warnings": [],
        }

        if not self.memory.dsn:
            stats["error"] = "DATABASE_URL chưa set"
            return stats

        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            log.warning("cron_amem_weekly pool fail: %r", exc)
            stats["error"] = f"pool init fail: {exc!r}"
            return stats

        # Phase 1: Scan
        try:
            scan_rows = await self._phase1_scan(pool, max_memories=max_memories)
        except Exception as exc:  # noqa: BLE001
            log.warning("phase1 scan fail: %r", exc)
            stats["error"] = f"phase1 scan fail: {exc!r}"
            return stats
        stats["scanned"] = len(scan_rows)
        log.info("phase1 scanned=%d memories cần evolve", len(scan_rows))

        # Phase 2: Haiku batch extract keywords
        keywords_by_id: dict[int, list[str]] = {}
        if scan_rows and self.llm.ready:
            try:
                keywords_by_id = await self._phase2_extract_keywords(
                    scan_rows, batch_size=batch_size
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("phase2 keywords fail: %r", exc)
                stats["warnings"].append(f"phase2 keywords fail: {exc!r}")
        elif not self.llm.ready:
            stats["warnings"].append("LLM chưa ready, skip phase2 keywords")

        # Phase 3: Auto-discover links via pgvector cosine
        # Phase 4: Append evolution_history entry
        # Combine 3+4 trong 1 transaction per memory tránh roundtrip
        processed = 0
        kw_total = 0
        lk_total = 0
        for row in scan_rows:
            mid = row["id"]
            new_keywords = keywords_by_id.get(mid, [])
            try:
                new_links = await self._phase3_discover_links(
                    pool,
                    memory_db_id=mid,
                    cosine_threshold=cosine_threshold,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "phase3 link fail memory_id=%s: %r", row.get("memory_id"), exc
                )
                stats["warnings"].append(
                    f"phase3 link fail id={mid}: {exc!r}"
                )
                new_links = []

            # Skip nothing-to-update
            if not new_keywords and not new_links:
                continue

            if dry_run:
                processed += 1
                kw_total += len(new_keywords)
                lk_total += len(new_links)
                continue

            try:
                await self._phase4_apply_update(
                    pool,
                    memory_db_id=mid,
                    new_keywords=new_keywords,
                    new_links=new_links,
                )
                processed += 1
                kw_total += len(new_keywords)
                lk_total += len(new_links)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "phase4 update fail memory_id=%s: %r",
                    row.get("memory_id"),
                    exc,
                )
                stats["warnings"].append(
                    f"phase4 update fail id={mid}: {exc!r}"
                )

        stats["processed"] = processed
        stats["keywords_total"] = kw_total
        stats["links_total"] = lk_total

        # Phase 5: Pain theme cluster
        try:
            pain_themes = await self._phase5_pain_themes(pool)
            stats["pain_themes"] = pain_themes
        except Exception as exc:  # noqa: BLE001
            log.warning("phase5 pain themes fail: %r", exc)
            stats["warnings"].append(f"phase5 pain themes fail: {exc!r}")

        # Phase 6: Telegram digest
        if dry_run:
            log.info("cron_amem_weekly DRY_RUN, skip Telegram send")
        else:
            try:
                msg = self._build_telegram_message(
                    date_vn=date_vn,
                    stats=stats,
                )
                sent_ok = await send_telegram(msg)
                stats["telegram_sent"] = sent_ok
            except Exception as exc:  # noqa: BLE001
                log.warning("cron_amem_weekly Telegram fail: %r", exc)
                stats["warnings"].append(f"telegram fail: {exc!r}")

        return stats

    # ------------------------------------------------------------------
    # Phase 1: Scan
    # ------------------------------------------------------------------

    async def _phase1_scan(
        self,
        pool: Any,
        *,
        max_memories: int,
    ) -> list[dict[str, Any]]:
        """SQL scan past 7d memory thiếu keywords."""
        sql = """
        SELECT id, memory_id, agent_name, content, keywords, links, tags,
               category, customer_id, venture
        FROM public.agent_memory
        WHERE created_at > now() - interval '7 days'
          AND (keywords = '{}' OR cardinality(keywords) < 3)
          AND content IS NOT NULL
          AND length(content) > 20
        ORDER BY created_at DESC
        LIMIT $1
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, max_memories)
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append({
                "id": r["id"],
                "memory_id": r["memory_id"],
                "agent_name": r["agent_name"],
                "content": r["content"],
                "keywords": list(r["keywords"] or []),
                "links": list(r["links"] or []),
                "tags": list(r["tags"] or []),
                "category": r["category"],
                "customer_id": r["customer_id"],
                "venture": r["venture"],
            })
        return out

    # ------------------------------------------------------------------
    # Phase 2: Keyword extraction via Haiku batch
    # ------------------------------------------------------------------

    async def _phase2_extract_keywords(
        self,
        rows: list[dict[str, Any]],
        *,
        batch_size: int,
    ) -> dict[int, list[str]]:
        """Batch Haiku call extract 3-5 keyword phrase tiếng Việt per memory.

        Return {memory_db_id: [keyword phrases]}. Fail batch = skip batch, không crash.
        """
        result: dict[int, list[str]] = {}
        for i in range(0, len(rows), batch_size):
            chunk = rows[i : i + batch_size]
            try:
                kws_list = await self._haiku_extract_batch(chunk)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "phase2 batch idx=%d fail: %r, skip batch", i, exc
                )
                continue
            for row, kws in zip(chunk, kws_list):
                if kws:
                    result[row["id"]] = kws
        return result

    async def _haiku_extract_batch(
        self,
        chunk: list[dict[str, Any]],
    ) -> list[list[str]]:
        """1 Haiku call return list[list[str]] cùng order với chunk."""
        # Build prompt
        lines: list[str] = []
        for idx, row in enumerate(chunk, 1):
            content = (row.get("content") or "").replace("\n", " ").strip()
            if len(content) > 300:
                content = content[:297] + "..."
            lines.append(f"Memory {idx}: {content}")
        memory_block = "\n".join(lines)

        prompt = (
            "You are extracting search keywords from Vietnamese memory records "
            "for an agentic memory system (A-mem pattern).\n\n"
            f"For each of the {len(chunk)} memories below, extract 3-5 keyword "
            "phrases (Vietnamese, 2-4 words each) that capture the SEMANTIC "
            "essence. NOT generic keywords. Output as JSON array of arrays, "
            f"exactly {len(chunk)} inner arrays in order.\n\n"
            f"{memory_block}\n\n"
            "Output ONLY valid JSON, no preamble, no markdown fence:\n"
            "[[\"keyword 1\", \"keyword 2\", \"keyword 3\"], ...]"
        )

        resp = await self.llm.client.messages.create(
            model=self.model,
            max_tokens=DEFAULT_LLM_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            timeout=DEFAULT_LLM_TIMEOUT,
        )
        text_parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        raw = "".join(text_parts).strip()
        parsed = self._safe_parse_json_array(raw)
        if not isinstance(parsed, list):
            return [[] for _ in chunk]

        out: list[list[str]] = []
        for i in range(len(chunk)):
            if i < len(parsed) and isinstance(parsed[i], list):
                kws = [
                    str(k).strip()
                    for k in parsed[i]
                    if isinstance(k, (str, int, float)) and str(k).strip()
                ]
                # Cap 5 keywords
                out.append(kws[:5])
            else:
                out.append([])
        return out

    @staticmethod
    def _safe_parse_json_array(raw: str) -> Any:
        """Parse JSON tolerant với code fence + leading/trailing noise."""
        if not raw:
            return None
        text = raw.strip()
        # Strip markdown fence
        if text.startswith("```"):
            lines = text.split("\n")
            # remove first fence + last fence
            if lines:
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        # Find first [ and last ]
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return None
        snippet = text[start : end + 1]
        try:
            return json.loads(snippet)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Phase 3: Auto-discover links via pgvector cosine
    # ------------------------------------------------------------------

    async def _phase3_discover_links(
        self,
        pool: Any,
        *,
        memory_db_id: int,
        cosine_threshold: float,
    ) -> list[UUID]:
        """Top 3 semantically related memory_id UUID within same scope."""
        sql = """
        SELECT m2.memory_id
        FROM public.agent_memory am
        JOIN public.agent_memory m2
            ON m2.id != am.id
           AND m2.embedding IS NOT NULL
           AND (m2.customer_id IS NOT DISTINCT FROM am.customer_id
                OR m2.venture = am.venture
                OR m2.agent_name = am.agent_name)
        WHERE am.id = $1
          AND am.embedding IS NOT NULL
          AND (m2.embedding <=> am.embedding) < $2
        ORDER BY (m2.embedding <=> am.embedding)
        LIMIT 3
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, memory_db_id, cosine_threshold)
        return [r["memory_id"] for r in rows if r["memory_id"] is not None]

    # ------------------------------------------------------------------
    # Phase 4: Apply update keywords + links + evolution_history
    # ------------------------------------------------------------------

    async def _phase4_apply_update(
        self,
        pool: Any,
        *,
        memory_db_id: int,
        new_keywords: list[str],
        new_links: list[UUID],
    ) -> None:
        """1 SQL UPDATE merge keywords + links + append evolution_history."""
        evolved_at = datetime.now(tz=timezone.utc).isoformat()
        evolution_entry = {
            "evolved_at": evolved_at,
            "evolved_by": self.name,
            "keywords_added": new_keywords,
            "links_added": [str(u) for u in new_links],
        }
        sql = """
        UPDATE public.agent_memory
        SET keywords = (
                SELECT ARRAY(
                    SELECT DISTINCT unnest(COALESCE(keywords, '{}') || $2::text[])
                )
            ),
            links = (
                SELECT ARRAY(
                    SELECT DISTINCT unnest(COALESCE(links, '{}') || $3::uuid[])
                )
            ),
            evolution_history = COALESCE(evolution_history, '[]'::jsonb)
                                || $4::jsonb,
            updated_at = now()
        WHERE id = $1
        """
        async with pool.acquire() as conn:
            await conn.execute(
                sql,
                memory_db_id,
                new_keywords,
                new_links,
                json.dumps([evolution_entry]),
            )

    # ------------------------------------------------------------------
    # Phase 5: Pain theme cluster
    # ------------------------------------------------------------------

    async def _phase5_pain_themes(
        self,
        pool: Any,
    ) -> list[dict[str, Any]]:
        """1 Haiku batch call extract top 5 pain themes BC3 feedback last 7d."""
        sql = """
        SELECT id, content, keywords, customer_id, venture
        FROM public.agent_memory
        WHERE agent_name = ANY($1::text[])
          AND created_at > now() - interval '7 days'
          AND content IS NOT NULL
          AND length(content) > 20
        LIMIT $2
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, list(BC3_AGENTS), PAIN_THEME_SAMPLE_LIMIT)

        if not rows:
            log.info("phase5 không có BC3 feedback memory trong 7d")
            return []
        if not self.llm.ready:
            log.warning("phase5 LLM chưa ready, skip pain theme cluster")
            return []

        # Build prompt
        lines: list[str] = []
        for i, r in enumerate(rows, 1):
            content = (r["content"] or "").replace("\n", " ").strip()
            if len(content) > 300:
                content = content[:297] + "..."
            lines.append(f"Feedback {i}: {content}")
        feedback_block = "\n".join(lines)

        prompt = (
            f"Read these {len(rows)} Vietnamese customer feedback memories. "
            "Identify top 5 PAIN THEMES (clusters of complaints / concerns / pain "
            "points). Output JSON array of exactly 5 objects.\n\n"
            f"{feedback_block}\n\n"
            "Output ONLY valid JSON, no preamble, no markdown fence:\n"
            "[{\"theme\": \"<short Vietnamese label, 2-5 words>\", "
            "\"count\": <int approximate>, "
            "\"sample_quotes\": [\"<quote 1>\", \"<quote 2>\"]}, ...]"
        )

        try:
            resp = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_LLM_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("phase5 LLM call fail: %r", exc)
            return []

        text_parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        raw = "".join(text_parts).strip()
        parsed = self._safe_parse_json_array(raw)
        if not isinstance(parsed, list):
            return []

        out: list[dict[str, Any]] = []
        for item in parsed[:5]:
            if not isinstance(item, dict):
                continue
            theme = str(item.get("theme") or "").strip()
            if not theme:
                continue
            try:
                count = int(item.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            quotes_raw = item.get("sample_quotes") or []
            quotes = [
                str(q).strip()
                for q in quotes_raw
                if isinstance(q, (str, int, float)) and str(q).strip()
            ][:3]
            out.append({"theme": theme, "count": count, "sample_quotes": quotes})
        return out

    # ------------------------------------------------------------------
    # Phase 6: Telegram digest
    # ------------------------------------------------------------------

    def _build_telegram_message(
        self,
        *,
        date_vn: str,
        stats: dict[str, Any],
    ) -> str:
        processed = stats.get("processed", 0)
        scanned = stats.get("scanned", 0)
        kw_total = stats.get("keywords_total", 0)
        lk_total = stats.get("links_total", 0)
        pain_themes = stats.get("pain_themes") or []

        avg_kw = round(kw_total / processed, 1) if processed else 0.0

        lines = [
            f"🧠 *A-mem Weekly Evolve {date_vn}*",
            "",
            f"_Quét 7 ngày qua:_ {scanned} memory cần evolve",
            f"- Processed: {processed} memory updated",
            f"- Keywords added: {kw_total} (avg {avg_kw}/memory)",
            f"- Links discovered: {lk_total}",
            "",
            "*Pain themes top 5 (BC3 feedback):*",
        ]
        if not pain_themes:
            lines.append("- Chưa có theme nào")
        else:
            for i, t in enumerate(pain_themes[:5], 1):
                theme = t.get("theme", "?")
                count = t.get("count", 0)
                lines.append(f"{i}. {theme} ({count})")

        warnings = stats.get("warnings") or []
        if warnings:
            lines.append("")
            lines.append(f"_Warnings: {len(warnings)}_")
            for w in warnings[:3]:
                w_short = str(w)
                if len(w_short) > 120:
                    w_short = w_short[:117] + "..."
                lines.append(f"- {w_short}")
        return "\n".join(lines)

    @staticmethod
    def _date_vn_str() -> str:
        now_vn = datetime.now(tz=timezone.utc) + timedelta(hours=7)
        return now_vn.strftime("%Y-%m-%d")


async def send_telegram(text: str) -> bool:
    """Gửi message tới Telegram group Breakout Ops."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_OPS_GROUP_ID", DEFAULT_TELEGRAM_GROUP_ID)
    if not token:
        log.warning("cron_amem_weekly TELEGRAM_BOT_TOKEN chưa set, skip send")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=DEFAULT_TELEGRAM_TIMEOUT) as client:
        resp = await client.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
        )
        if resp.status_code != 200:
            log.warning(
                "cron_amem_weekly Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
