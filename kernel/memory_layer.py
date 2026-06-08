"""Shared memory layer Cerebrum 4-field + Anna venture extension.

Storage backend = Postgres pgvector `public.agent_memory` (migration 003 + Sprint 4
embedding columns). Embedding = Voyage AI `voyage-3` (1024 dims).

Auto inject + auto extract hook gọi từ Scheduler quanh BaseBC.run().
Memory layer graceful degrade: nếu Voyage API hỏng hoặc Postgres unreachable thì
log warning + continue, KHÔNG crash kernel.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]

log = logging.getLogger("camas.memory_layer")


VOYAGE_DEFAULT_MODEL = "voyage-3"
VOYAGE_DIMS = 1024
VOYAGE_BATCH_LIMIT = 128
VOYAGE_TIMEOUT_S = 60.0
VOYAGE_MAX_RETRIES = 3


class MemoryRecord(BaseModel):
    """Mirror table `public.agent_memory` 1-1.

    Fields nullable theo schema thật (xem migration 003 + Sprint 4 embedding cols).
    Validator: embedding length = 1024 nếu present.
    """

    model_config = ConfigDict(extra="forbid")

    id: Optional[int] = None
    memory_id: Optional[UUID] = None
    agent_name: str
    content: str
    keywords: list[str] = Field(default_factory=list)
    links: list[UUID] = Field(default_factory=list)
    context: Optional[str] = None
    category: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    customer_id: Optional[int] = None
    venture: Optional[str] = None
    retrieval_count: int = 0
    last_accessed_at: Optional[datetime] = None
    evolution_history: list[dict[str, Any]] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    embedding: Optional[list[float]] = None
    embedding_model: Optional[str] = None
    embedded_at: Optional[datetime] = None

    @field_validator("embedding")
    @classmethod
    def _check_embedding_dim(cls, v: Optional[list[float]]) -> Optional[list[float]]:
        if v is not None and len(v) != VOYAGE_DIMS:
            raise ValueError(
                f"Embedding phải có {VOYAGE_DIMS} chiều, nhận {len(v)}"
            )
        return v


class VoyageEmbedder:
    """Voyage AI embedding client, dùng pure HTTP, không cần SDK."""

    def __init__(
        self,
        api_key: str,
        model: str = VOYAGE_DEFAULT_MODEL,
        base_url: str = "https://api.voyageai.com/v1",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    @property
    def ready(self) -> bool:
        return bool(self.api_key)

    async def embed(
        self,
        texts: list[str],
        input_type: Literal["query", "document"] = "document",
    ) -> list[list[float]]:
        """Embed list[str] thành list[vector 1024 chiều].

        Batch tối đa 128 text/call (Voyage limit), exponential backoff 3 retry
        cho 429 + 5xx.
        """
        if not texts:
            return []
        if not self.ready:
            raise RuntimeError("VoyageEmbedder thiếu api_key")

        results: list[list[float]] = []
        async with httpx.AsyncClient(timeout=VOYAGE_TIMEOUT_S) as client:
            for i in range(0, len(texts), VOYAGE_BATCH_LIMIT):
                batch = texts[i : i + VOYAGE_BATCH_LIMIT]
                vectors = await self._embed_batch(client, batch, input_type)
                results.extend(vectors)
        return results

    async def _embed_batch(
        self,
        client: httpx.AsyncClient,
        batch: list[str],
        input_type: str,
    ) -> list[list[float]]:
        url = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "input": batch,
            "model": self.model,
            "input_type": input_type,
        }

        for attempt in range(VOYAGE_MAX_RETRIES):
            try:
                resp = await client.post(url, headers=headers, json=body)
            except httpx.HTTPError as exc:
                if attempt == VOYAGE_MAX_RETRIES - 1:
                    raise RuntimeError(f"Voyage HTTP error: {exc}") from exc
                await self._backoff(attempt)
                continue

            if resp.status_code == 200:
                data = resp.json()
                vectors = [item["embedding"] for item in data.get("data", [])]
                if len(vectors) != len(batch):
                    raise RuntimeError(
                        f"Voyage trả {len(vectors)} vector cho {len(batch)} text"
                    )
                return vectors

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt == VOYAGE_MAX_RETRIES - 1:
                    raise RuntimeError(
                        f"Voyage {resp.status_code} sau {VOYAGE_MAX_RETRIES} retry: "
                        f"{resp.text[:200]}"
                    )
                await self._backoff(attempt)
                continue

            raise RuntimeError(
                f"Voyage {resp.status_code}: {resp.text[:200]}"
            )

        raise RuntimeError("Voyage embed: exhausted retries")

    @staticmethod
    async def _backoff(attempt: int) -> None:
        delay = (2 ** attempt) + random.uniform(0, 0.5)
        await asyncio.sleep(delay)


def _vector_literal(embedding: list[float]) -> str:
    """Cast list[float] sang pgvector text literal `[0.1,0.2,...]`."""
    return "[" + ",".join(f"{x:.7f}" for x in embedding) + "]"


class MemoryLayer:
    """Pgvector wrapper + Voyage embedding.

    Auto inject contract:
        retrieve(query, k, agent_name?, venture?, customer_id?, max_age_days?)
        → list[MemoryRecord] sorted theo relevance.

    Auto extract contract:
        store(MemoryRecord) hoặc store_many(list[MemoryRecord]) ghi vào
        `public.agent_memory` với ON CONFLICT (memory_id) DO UPDATE.
    """

    def __init__(
        self,
        dsn: Optional[str] = None,
        embedder: Optional[VoyageEmbedder] = None,
        max_injected_memories: int = 10,
        relevance_threshold: float = 0.5,
        max_memory_tokens: int = 2000,
    ) -> None:
        self.dsn = dsn or os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
        self.embedder = embedder
        self.max_injected_memories = max_injected_memories
        # Cosine distance: 0 = giống hệt, 1 = trực giao, 2 = đối lập.
        # Threshold 0.5 ≈ ngưỡng "có liên quan ngữ nghĩa".
        self.relevance_threshold = relevance_threshold
        self.max_memory_tokens = max_memory_tokens
        self._pool: Optional[Any] = None
        self._pool_lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        return bool(self.dsn) and self.embedder is not None and self.embedder.ready

    async def _get_pool(self) -> Any:
        """Lazy init asyncpg pool, thread-safe."""
        if self._pool is not None:
            return self._pool
        async with self._pool_lock:
            if self._pool is not None:
                return self._pool
            if asyncpg is None:
                raise RuntimeError("asyncpg chưa cài, không thể tạo pool")
            if not self.dsn:
                raise RuntimeError("MemoryLayer thiếu DATABASE_URL")
            self._pool = await asyncpg.create_pool(
                self.dsn,
                min_size=2,
                max_size=10,
                command_timeout=30.0,
            )
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def store(self, record: MemoryRecord) -> UUID:
        """Insert hoặc update 1 memory record. Return memory_id."""
        if record.embedding is None and self.embedder is not None and self.embedder.ready:
            try:
                vectors = await self.embedder.embed(
                    [record.content], input_type="document"
                )
                if vectors:
                    record.embedding = vectors[0]
                    record.embedding_model = self.embedder.model
                    record.embedded_at = datetime.now(tz=timezone.utc)
            except Exception as exc:  # noqa: BLE001
                log.warning("Voyage embed fail: %r, lưu memory không embedding", exc)

        pool = await self._get_pool()
        sql = """
        INSERT INTO public.agent_memory (
            memory_id, agent_name, content, keywords, links, context, category, tags,
            customer_id, venture, retrieval_count, evolution_history,
            embedding, embedding_model, embedded_at
        ) VALUES (
            COALESCE($1, gen_random_uuid()), $2, $3, $4, $5, $6, $7, $8,
            $9, $10, $11, $12::jsonb,
            CASE WHEN $13::text IS NULL THEN NULL ELSE $13::vector END,
            $14, $15
        )
        ON CONFLICT (memory_id) DO UPDATE SET
            content = EXCLUDED.content,
            keywords = EXCLUDED.keywords,
            tags = EXCLUDED.tags,
            context = EXCLUDED.context,
            category = EXCLUDED.category,
            venture = EXCLUDED.venture,
            embedding = EXCLUDED.embedding,
            embedding_model = EXCLUDED.embedding_model,
            embedded_at = EXCLUDED.embedded_at,
            updated_at = now(),
            evolution_history = agent_memory.evolution_history || EXCLUDED.evolution_history
        RETURNING memory_id;
        """
        embedding_literal = (
            _vector_literal(record.embedding) if record.embedding is not None else None
        )
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                sql,
                record.memory_id,
                record.agent_name,
                record.content,
                record.keywords,
                record.links,
                record.context,
                record.category,
                record.tags,
                record.customer_id,
                record.venture,
                record.retrieval_count,
                json.dumps(record.evolution_history),
                embedding_literal,
                record.embedding_model,
                record.embedded_at,
            )
        memory_id = row["memory_id"]
        record.memory_id = memory_id
        return memory_id

    async def store_many(self, records: list[MemoryRecord]) -> list[UUID]:
        """Batch embed + bulk insert. Return list[memory_id] cùng order."""
        if not records:
            return []

        # Batch embed records thiếu embedding
        if self.embedder is not None and self.embedder.ready:
            missing_idx = [
                i for i, r in enumerate(records) if r.embedding is None
            ]
            if missing_idx:
                texts = [records[i].content for i in missing_idx]
                try:
                    vectors = await self.embedder.embed(texts, input_type="document")
                    now = datetime.now(tz=timezone.utc)
                    for i, vec in zip(missing_idx, vectors):
                        records[i].embedding = vec
                        records[i].embedding_model = self.embedder.model
                        records[i].embedded_at = now
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "Voyage batch embed fail: %r, lưu memory không embedding", exc
                    )

        pool = await self._get_pool()
        sql = """
        INSERT INTO public.agent_memory (
            memory_id, agent_name, content, keywords, links, context, category, tags,
            customer_id, venture, retrieval_count, evolution_history,
            embedding, embedding_model, embedded_at
        ) VALUES (
            COALESCE($1, gen_random_uuid()), $2, $3, $4, $5, $6, $7, $8,
            $9, $10, $11, $12::jsonb,
            CASE WHEN $13::text IS NULL THEN NULL ELSE $13::vector END,
            $14, $15
        )
        ON CONFLICT (memory_id) DO UPDATE SET
            content = EXCLUDED.content,
            keywords = EXCLUDED.keywords,
            tags = EXCLUDED.tags,
            context = EXCLUDED.context,
            category = EXCLUDED.category,
            venture = EXCLUDED.venture,
            embedding = EXCLUDED.embedding,
            embedding_model = EXCLUDED.embedding_model,
            embedded_at = EXCLUDED.embedded_at,
            updated_at = now(),
            evolution_history = agent_memory.evolution_history || EXCLUDED.evolution_history
        RETURNING memory_id;
        """
        memory_ids: list[UUID] = []
        async with pool.acquire() as conn:
            async with conn.transaction():
                for record in records:
                    embedding_literal = (
                        _vector_literal(record.embedding)
                        if record.embedding is not None
                        else None
                    )
                    row = await conn.fetchrow(
                        sql,
                        record.memory_id,
                        record.agent_name,
                        record.content,
                        record.keywords,
                        record.links,
                        record.context,
                        record.category,
                        record.tags,
                        record.customer_id,
                        record.venture,
                        record.retrieval_count,
                        json.dumps(record.evolution_history),
                        embedding_literal,
                        record.embedding_model,
                        record.embedded_at,
                    )
                    mid = row["memory_id"]
                    record.memory_id = mid
                    memory_ids.append(mid)
        return memory_ids

    async def retrieve(
        self,
        query: str,
        *,
        k: int = 10,
        agent_name: Optional[str] = None,
        venture: Optional[str] = None,
        customer_id: Optional[int] = None,
        category: Optional[str] = None,
        categories: Optional[list[str]] = None,
        max_age_days: Optional[int] = None,
        relevance_threshold_override: Optional[float] = None,
    ) -> list[MemoryRecord]:
        """Semantic search bằng cosine distance trên embedding.

        Filter results distance > relevance_threshold (1.0 = không liên quan).
        Async update retrieval_count + last_accessed_at best-effort.

        Category filter (Sprint 5 priority retrieval):
            - `category` = single value (vd 'profile', 'task')
            - `categories` = IN clause (vd ['pricing', 'policy', 'brand'])
            - Nếu cả hai đều set, ưu tiên `category`.
        """
        if not query or not query.strip():
            return []
        if self.embedder is None or not self.embedder.ready:
            log.warning("MemoryLayer.retrieve: embedder chưa ready, trả []")
            return []

        try:
            vectors = await self.embedder.embed([query], input_type="query")
        except Exception as exc:  # noqa: BLE001
            log.warning("Voyage embed query fail: %r", exc)
            return []
        if not vectors:
            return []
        query_vec = _vector_literal(vectors[0])

        # Build WHERE clauses dynamically
        where: list[str] = ["embedding IS NOT NULL"]
        params: list[Any] = [query_vec]
        pi = 2

        if agent_name is not None:
            where.append(f"agent_name = ${pi}")
            params.append(agent_name)
            pi += 1
        if venture is not None:
            where.append(f"venture = ${pi}")
            params.append(venture)
            pi += 1
        if customer_id is not None:
            where.append(f"customer_id = ${pi}")
            params.append(customer_id)
            pi += 1
        if category is not None:
            where.append(f"category = ${pi}")
            params.append(category)
            pi += 1
        elif categories:
            where.append(f"category = ANY(${pi}::text[])")
            params.append(list(categories))
            pi += 1
        if max_age_days is not None:
            where.append(f"created_at > now() - (${pi}::int * interval '1 day')")
            params.append(max_age_days)
            pi += 1

        params.append(k)
        where_sql = " AND ".join(where)
        sql = f"""
        SELECT id, memory_id, agent_name, content, keywords, links, context, category,
               tags, customer_id, venture, retrieval_count, last_accessed_at,
               evolution_history, created_at, updated_at, embedding_model, embedded_at,
               (embedding <=> $1::vector) AS distance
        FROM public.agent_memory
        WHERE {where_sql}
        ORDER BY embedding <=> $1::vector
        LIMIT ${pi};
        """

        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
        except Exception as exc:  # noqa: BLE001
            log.warning("MemoryLayer.retrieve SQL fail: %r", exc)
            return []

        records: list[MemoryRecord] = []
        hit_ids: list[UUID] = []
        # Sprint 8: cho phép override threshold per call (Profile/Task tier bypass)
        threshold = relevance_threshold_override if relevance_threshold_override is not None else self.relevance_threshold
        for r in rows:
            distance = float(r["distance"])
            if distance > threshold:
                continue
            evol = r["evolution_history"]
            if isinstance(evol, str):
                try:
                    evol = json.loads(evol)
                except (TypeError, ValueError):
                    evol = []
            records.append(
                MemoryRecord(
                    id=r["id"],
                    memory_id=r["memory_id"],
                    agent_name=r["agent_name"],
                    content=r["content"],
                    keywords=list(r["keywords"] or []),
                    links=list(r["links"] or []),
                    context=r["context"],
                    category=r["category"],
                    tags=list(r["tags"] or []),
                    customer_id=r["customer_id"],
                    venture=r["venture"],
                    retrieval_count=r["retrieval_count"],
                    last_accessed_at=r["last_accessed_at"],
                    evolution_history=evol or [],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    embedding=None,  # không cần đẩy embedding lên kernel
                    embedding_model=r["embedding_model"],
                    embedded_at=r["embedded_at"],
                )
            )
            hit_ids.append(r["memory_id"])

        # Best-effort update retrieval_count + last_accessed_at
        if hit_ids:
            asyncio.create_task(self._touch_records(hit_ids))

        return records

    async def _touch_records(self, memory_ids: list[UUID]) -> None:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE public.agent_memory
                    SET retrieval_count = retrieval_count + 1,
                        last_accessed_at = now()
                    WHERE memory_id = ANY($1::uuid[])
                    """,
                    memory_ids,
                )
        except Exception as exc:  # noqa: BLE001
            log.debug("touch_records best-effort fail: %r", exc)

    async def retrieve_by_tags_recent(
        self,
        tags_must_contain: list[str],
        *,
        limit: int = 5,
        venture: Optional[str] = None,
    ) -> list[MemoryRecord]:
        """Direct SQL retrieve by tag containment, ordered by created_at DESC.

        Bypass embedding semantic search. Use cho chain context retrieval (cohort
        wizard chain) hoặc bất kỳ scenario nào cần exact-tag lookup recent.
        """
        if not tags_must_contain:
            return []

        where: list[str] = ["tags @> $1::text[]"]
        params: list[Any] = [list(tags_must_contain)]
        pi = 2

        if venture is not None:
            where.append(f"venture = ${pi}")
            params.append(venture)
            pi += 1

        params.append(limit)
        where_sql = " AND ".join(where)
        sql = f"""
        SELECT id, memory_id, agent_name, content, keywords, links, context, category,
               tags, customer_id, venture, retrieval_count, last_accessed_at,
               evolution_history, created_at, updated_at, embedding_model, embedded_at
        FROM public.agent_memory
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT ${pi};
        """

        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
        except Exception as exc:  # noqa: BLE001
            log.warning("MemoryLayer.retrieve_by_tags_recent SQL fail: %r", exc)
            return []

        records: list[MemoryRecord] = []
        for r in rows:
            evol = r["evolution_history"]
            if isinstance(evol, str):
                try:
                    evol = json.loads(evol)
                except (TypeError, ValueError):
                    evol = []
            records.append(
                MemoryRecord(
                    id=r["id"],
                    memory_id=r["memory_id"],
                    agent_name=r["agent_name"],
                    content=r["content"],
                    keywords=list(r["keywords"] or []),
                    links=list(r["links"] or []),
                    context=r["context"],
                    category=r["category"],
                    tags=list(r["tags"] or []),
                    customer_id=r["customer_id"],
                    venture=r["venture"],
                    retrieval_count=r["retrieval_count"],
                    last_accessed_at=r["last_accessed_at"],
                    evolution_history=evol or [],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    embedding=None,
                    embedding_model=r["embedding_model"],
                    embedded_at=r["embedded_at"],
                )
            )
        return records

    async def to_natural_language(self, records: list[MemoryRecord]) -> str:
        """Render bullet list NL cho inject vào prompt agent.

        Truncate mỗi memory 200 char, cap tổng char ≈ 3 * max_memory_tokens.
        """
        if not records:
            return ""
        char_cap = self.max_memory_tokens * 3
        lines: list[str] = []
        total = 0
        for r in records[: self.max_injected_memories]:
            venture = r.venture or "all"
            created = r.created_at.strftime("%Y-%m-%d") if r.created_at else "?"
            content = (r.content or "").replace("\n", " ").strip()
            if len(content) > 200:
                content = content[:197] + "..."
            kws = ", ".join((r.keywords or [])[:3])
            line = f"- [{r.agent_name} | {venture} | {created}] {content}"
            if kws:
                line += f" (keywords: {kws})"
            if total + len(line) + 1 > char_cap:
                break
            lines.append(line)
            total += len(line) + 1
        return "\n".join(lines)
