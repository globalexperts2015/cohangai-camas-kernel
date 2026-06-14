"""Apply migration 006 SDL BreakoutOS schema to Railway Postgres.

Run: railway run --service camas-kernel python tools/apply_migration_006_sdl.py
"""
import asyncio
import os
import sys
from pathlib import Path

import asyncpg


MIGRATION = Path(__file__).parent.parent / "migrations" / "006_sdl_breakoutos_schema.sql"


async def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 1

    sql = MIGRATION.read_text(encoding="utf-8")
    print(f"Applying {MIGRATION.name} ({len(sql)} chars)...")

    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute(sql)

        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='breakoutos' ORDER BY tablename"
        )
        print(f"\n✓ Migration 006 applied. {len(rows)} tables in breakoutos schema:")
        for r in rows:
            print(f"  - breakoutos.{r['tablename']}")

        views = await conn.fetch(
            "SELECT viewname FROM pg_views WHERE schemaname='breakoutos'"
        )
        for v in views:
            print(f"  - breakoutos.{v['viewname']} (view)")

        return 0
    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
