"""MemoryLayer smoke test, gọi pgvector thật + Voyage AI thật.

Chạy:
    cd cohangai/services/camas-kernel
    /Users/mac/Documents/ANNA SECOND BRAIN/cohangai/.venv/bin/python tests/test_memory_layer.py

Yêu cầu VOYAGE_API_KEY + DATABASE_URL (hoặc CDP_DATABASE_URL) trong env hoặc cohangai/.env.

3 test:
  1. embed_and_store: store 1 record về câu chuyện mắm Quảng Trị, assert UUID + DB row + embedding 1024
  2. retrieve_semantic: store 3 record khác chủ đề, retrieve "câu chuyện Hằng làm mắm" → top result là mắm
  3. cleanup: xóa 3 record test khỏi DB để giữ data sạch
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

import asyncpg  # noqa: E402

from kernel.memory_layer import (  # noqa: E402
    MemoryLayer,
    MemoryRecord,
    VoyageEmbedder,
)


TEST_AGENT = "test_memory_layer_smoke"


async def test_embed_and_store(memory: MemoryLayer, dsn: str) -> uuid.UUID:
    """Test 1: embed + store + assert DB row có embedding length 1024."""
    print("\n[TEST 1] test_embed_and_store")
    record = MemoryRecord(
        agent_name=TEST_AGENT,
        content="Hằng làm mắm ở quê Quảng Trị, mắm Thuyền Nan ra đời năm 2014.",
        keywords=["mam", "quang_tri", "thuyen_nan"],
        tags=["story", "personal"],
        venture="personal",
        context="test_memory_layer_smoke",
    )
    memory_id = await memory.store(record)
    assert isinstance(memory_id, uuid.UUID), f"memory_id phải là UUID: {memory_id}"
    print(f"  memory_id = {memory_id}")

    # Verify DB row + embedding length
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT memory_id, content, embedding_model, "
            "array_length(embedding::real[], 1) AS emb_dim "
            "FROM public.agent_memory WHERE memory_id = $1",
            memory_id,
        )
    finally:
        await conn.close()
    assert row is not None, "Row không tồn tại trong DB"
    assert row["emb_dim"] == 1024, f"Embedding length sai: {row['emb_dim']}"
    assert row["embedding_model"] == "voyage-3", f"Model sai: {row['embedding_model']}"
    print(f"  OK row exists, embedding dim = {row['emb_dim']}, model = {row['embedding_model']}")
    return memory_id


async def test_retrieve_semantic(memory: MemoryLayer) -> list[uuid.UUID]:
    """Test 2: store 3 record khác chủ đề + retrieve assert top hit = mắm."""
    print("\n[TEST 2] test_retrieve_semantic")
    records = [
        MemoryRecord(
            agent_name=TEST_AGENT,
            content="Câu chuyện Hằng làm mắm Thuyền Nan tại Hải Lăng Quảng Trị từ 2014.",
            keywords=["mam", "thuyen_nan"],
            tags=["story", "founder"],
            venture="personal",
            context="test_memory_layer_smoke",
        ),
        MemoryRecord(
            agent_name=TEST_AGENT,
            content="Speakout 2026 portfolio gồm Nói là Hiểu, Luca System, Speak Pro.",
            keywords=["speakout", "portfolio"],
            tags=["product"],
            venture="speakout",
            context="test_memory_layer_smoke",
        ),
        MemoryRecord(
            agent_name=TEST_AGENT,
            content="Breakout coaching 6 tháng giá 50 triệu VND, dành cho founder Shopify.",
            keywords=["breakout", "coaching"],
            tags=["product", "pricing"],
            venture="breakout",
            context="test_memory_layer_smoke",
        ),
    ]
    memory_ids = await memory.store_many(records)
    assert len(memory_ids) == 3, f"Phải store 3 record, được {len(memory_ids)}"
    print(f"  Stored 3 records: {memory_ids}")

    results = await memory.retrieve(
        query="câu chuyện Hằng làm mắm ở Quảng Trị",
        k=5,
        agent_name=TEST_AGENT,
    )
    assert len(results) > 0, "Retrieve trả 0 result"
    print(f"  Retrieved {len(results)} records")
    for i, r in enumerate(results):
        print(f"    [{i}] venture={r.venture} content={r.content[:80]}")

    top = results[0]
    assert "mắm" in top.content.lower() or "mam" in (top.keywords or []), (
        f"Top result không phải về mắm: {top.content}"
    )
    print(f"  OK top result = mắm Thuyền Nan")
    return memory_ids


async def test_cleanup(dsn: str, memory_ids: list[uuid.UUID]) -> None:
    """Test 3: xóa 3 test record + record test 1."""
    print("\n[TEST 3] test_cleanup")
    conn = await asyncpg.connect(dsn)
    try:
        result = await conn.execute(
            "DELETE FROM public.agent_memory WHERE agent_name = $1",
            TEST_AGENT,
        )
    finally:
        await conn.close()
    print(f"  DELETE result: {result}")
    print("  OK cleanup done")


async def main() -> int:
    voyage_key = os.getenv("VOYAGE_API_KEY", "")
    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL", "")
    if not voyage_key:
        print("FAIL: VOYAGE_API_KEY chưa set")
        return 1
    if not dsn:
        print("FAIL: DATABASE_URL/CDP_DATABASE_URL chưa set")
        return 1

    embedder = VoyageEmbedder(api_key=voyage_key, model="voyage-3")
    memory = MemoryLayer(dsn=dsn, embedder=embedder)
    assert memory.ready, "MemoryLayer chưa ready"

    test_memory_ids: list[uuid.UUID] = []
    try:
        mid1 = await test_embed_and_store(memory, dsn)
        test_memory_ids.append(mid1)

        mids2 = await test_retrieve_semantic(memory)
        test_memory_ids.extend(mids2)
    finally:
        await test_cleanup(dsn, test_memory_ids)
        await memory.close()

    print("\n---")
    print("OK all 3 MemoryLayer smoke tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
