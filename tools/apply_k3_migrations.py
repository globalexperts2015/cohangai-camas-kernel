"""Apply Fan Hub internal API and Breakout Challenge K3 migrations."""
from __future__ import annotations

import asyncio
import argparse
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parents[2]
MIGRATIONS = {
    "fanhub": WORKSPACE / "cohangai/services/fan-hub/migrations/017_breakout_internal_api.sql",
    "challenge": ROOT / "migrations/014_breakout_challenge.sql",
}


async def main(target: str) -> int:
    load_dotenv(WORKSPACE / "cohangai/.env", override=False)
    if target == "fanhub":
        dsn = os.getenv("FAN_HUB_DATABASE_URL") or os.getenv("DATABASE_URL")
    else:
        dsn = os.getenv("CDP_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        print("Database URL is required")
        return 1
    conn = await asyncpg.connect(dsn)
    try:
        migration = MIGRATIONS[target]
        await conn.execute(migration.read_text())
        print(f"applied {migration.name}")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=sorted(MIGRATIONS), required=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.target)))
