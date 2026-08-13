#!/usr/bin/env python3
"""Bao cao chi phi va luu luong goi LLM cho Breakout/Starter OS.

Chay:
    DATABASE_URL=... python3 tools/llm_cost_report.py            # 7 ngay
    DATABASE_URL=... python3 tools/llm_cost_report.py --days 30

Nguon du lieu, theo thu tu uu tien:
  1. breakoutos.llm_usage_log            (day du: model, token vao/ra, ai goi)
  2. breakout_challenge.sessions
     -> metadata_json->'api_spend_log'   (chi lop Starter OS, chi co cost_usd)

KHONG bia so. Thieu du lieu thi noi ro la thieu.
KHONG in secret, KHONG in noi dung hoc vien.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

try:
    import asyncpg
except ImportError:
    print("Thieu asyncpg. Cai: pip install asyncpg")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent


def _fmt_usd(v) -> str:
    if v is None:
        return "     n/a"
    return f"${float(v):>9.4f}"


async def _table_exists(conn, schema: str, table: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT 1 FROM information_schema.tables WHERE table_schema=$1 AND table_name=$2",
        schema, table,
    ))


def _agents_in_code() -> set[str]:
    d = ROOT / "agents"
    if not d.is_dir():
        return set()
    return {
        p.name for p in d.iterdir()
        if p.is_dir() and not p.name.startswith(("__", ".", "Icon"))
    }


async def main(days: int) -> None:
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("CDP_DATABASE_URL")
    if not dsn:
        print("Thieu DATABASE_URL")
        sys.exit(1)
    conn = await asyncpg.connect(dsn)
    try:
        print("=" * 74)
        print(f"BAO CAO CHI PHI LLM  |  {days} ngay gan nhat")
        print("=" * 74)

        has_usage = await _table_exists(conn, "breakoutos", "llm_usage_log")
        if not has_usage:
            print("\n[!] Bang breakoutos.llm_usage_log CHUA TON TAI.")
            print("    Chay migration 019_llm_usage_log.sql truoc.")
        else:
            total = await conn.fetchval(
                "SELECT count(*) FROM breakoutos.llm_usage_log "
                "WHERE occurred_at > now() - ($1||' days')::interval", str(days))
            oldest = await conn.fetchval(
                "SELECT min(occurred_at) FROM breakoutos.llm_usage_log")
            print(f"\nSo lan goi ghi nhan: {total}")
            if oldest:
                span = await conn.fetchval("SELECT now() - $1::timestamptz", oldest)
                print(f"Du lieu bat dau tu : {oldest:%Y-%m-%d %H:%M} (dai {span.days} ngay)")
                if span.days < days:
                    print(f"[!] CHUA DU DU LIEU LICH SU {days} NGAY. "
                          f"Moi co {span.days} ngay. Con so duoi day chi phan anh khoang do.")
            else:
                print("[!] CHUA CO DU LIEU. He thong ghi nhan da san sang, "
                      "so lieu se day len khi co lenh goi that.")

        if has_usage and total:
            await _section_by_source(conn, days)
            await _section_by_day_model(conn, days)
            await _section_by_group(conn, days)
            await _section_top_callers(conn, days)
            await _section_anomalies(conn, days)
            await _section_agents(conn, days)
        elif has_usage:
            print("\n(Bo qua cac muc thong ke vi chua co ban ghi nao.)")

        await _section_legacy_k3(conn, days)
    finally:
        await conn.close()


async def _section_by_source(conn, days: int) -> None:
    """Tach ro dich vu nao ton tien. camas-kernel sinh ho so hoc vien,
    breakout-app chay chat lop va Gap Report."""
    print("\n" + "-" * 74)
    print("0. TACH THEO DICH VU")
    print("-" * 74)
    rows = await conn.fetch("""
        SELECT source, count(*) AS so_lan, sum(input_tokens) AS tok_vao,
               sum(output_tokens) AS tok_ra, sum(estimated_cost_usd) AS tien
        FROM breakoutos.llm_usage_log
        WHERE occurred_at > now() - ($1||' days')::interval
        GROUP BY 1 ORDER BY tien DESC NULLS LAST
    """, str(days))
    print(f"  {'Dich vu':<18}{'Lan':>7}{'Tok vao':>12}{'Tok ra':>11}{'Tien':>11}")
    for r in rows:
        print(f"  {(r['source'] or '?')[:17]:<18}{r['so_lan']:>7}"
              f"{r['tok_vao']:>12,}{r['tok_ra']:>11,}{_fmt_usd(r['tien']):>11}")
    thieu = [r["source"] for r in rows]
    for s in ("camas-kernel", "breakout-app"):
        if s not in thieu:
            print(f"  [!] Chua thay ban ghi nao tu {s} trong khoang nay.")


async def _section_by_day_model(conn, days: int) -> None:
    print("\n" + "-" * 74)
    print("1. CHI PHI MOI NGAY THEO MODEL")
    print("-" * 74)
    rows = await conn.fetch("""
        SELECT date_trunc('day', occurred_at)::date AS ngay, model,
               count(*) AS so_lan, sum(input_tokens) AS tok_vao,
               sum(output_tokens) AS tok_ra, sum(estimated_cost_usd) AS tien
        FROM breakoutos.llm_usage_log
        WHERE occurred_at > now() - ($1||' days')::interval
        GROUP BY 1,2 ORDER BY 1 DESC, tien DESC NULLS LAST
    """, str(days))
    if not rows:
        print("  (chua co)")
        return
    print(f"  {'Ngay':<11}{'Model':<22}{'Lan':>6}{'Tok vao':>11}{'Tok ra':>10}{'Tien':>11}")
    for r in rows:
        print(f"  {str(r['ngay']):<11}{r['model'][:21]:<22}{r['so_lan']:>6}"
              f"{r['tok_vao']:>11,}{r['tok_ra']:>10,}{_fmt_usd(r['tien']):>11}")
    tot = await conn.fetchval("""
        SELECT sum(estimated_cost_usd) FROM breakoutos.llm_usage_log
        WHERE occurred_at > now() - ($1||' days')::interval""", str(days))
    print(f"  {'TONG':<39}{'':>21}{_fmt_usd(tot):>11}")


async def _section_by_group(conn, days: int) -> None:
    print("\n" + "-" * 74)
    print("2. LENH GOI DEN TU NHOM NAO")
    print("-" * 74)
    rows = await conn.fetch("""
        SELECT call_group, count(*) AS so_lan,
               sum(input_tokens) AS tok_vao, sum(output_tokens) AS tok_ra,
               sum(estimated_cost_usd) AS tien
        FROM breakoutos.llm_usage_log
        WHERE occurred_at > now() - ($1||' days')::interval
        GROUP BY 1 ORDER BY tien DESC NULLS LAST
    """, str(days))
    nhan = {
        "hoc_vien_lam_bai": "Hoc vien lam bai",
        "chat_lop": "Chat lop",
        "cron": "Cron chay nen",
        "agent_noi_bo": "Agent noi bo",
        "test_manual": "Test / chay tay",
        "route_khac": "Route khac",
        "khong_ro": "Khong ro",
    }
    print(f"  {'Nhom':<22}{'Lan':>7}{'Tok vao':>12}{'Tok ra':>11}{'Tien':>11}")
    for r in rows:
        print(f"  {nhan.get(r['call_group'], r['call_group'] or '?')[:21]:<22}"
              f"{r['so_lan']:>7}{r['tok_vao']:>12,}{r['tok_ra']:>11,}{_fmt_usd(r['tien']):>11}")


async def _section_top_callers(conn, days: int) -> None:
    print("\n" + "-" * 74)
    print("3. TOP 10 NOI TON TIEN NHAT")
    print("-" * 74)
    rows = await conn.fetch("""
        SELECT source, caller, model, count(*) AS so_lan,
               sum(estimated_cost_usd) AS tien,
               avg(duration_ms)::int AS ms_tb
        FROM breakoutos.llm_usage_log
        WHERE occurred_at > now() - ($1||' days')::interval
        GROUP BY 1,2,3 ORDER BY tien DESC NULLS LAST LIMIT 10
    """, str(days))
    print(f"  {'Dich vu':<14}{'Noi goi':<34}{'Model':<18}{'Lan':>5}{'Tien':>11}")
    for r in rows:
        print(f"  {(r['source'] or '?')[:13]:<14}{(r['caller'] or '?')[:33]:<34}"
              f"{(r['model'] or '?')[:17]:<18}{r['so_lan']:>5}{_fmt_usd(r['tien']):>11}")


async def _section_anomalies(conn, days: int) -> None:
    print("\n" + "-" * 74)
    print("4. DAU HIEU BAT THUONG")
    print("-" * 74)
    found = False

    # a) Dung model dat cho viec co the Haiku lam duoc (output ngan)
    rows = await conn.fetch("""
        SELECT caller, model, count(*) AS so_lan, avg(output_tokens)::int AS ra_tb,
               sum(estimated_cost_usd) AS tien
        FROM breakoutos.llm_usage_log
        WHERE occurred_at > now() - ($1||' days')::interval
          AND model NOT LIKE '%haiku%' AND success
        GROUP BY 1,2 HAVING avg(output_tokens) < 400 AND count(*) >= 5
        ORDER BY tien DESC NULLS LAST LIMIT 5
    """, str(days))
    for r in rows:
        found = True
        print(f"  [model qua manh] {r['caller']} dung {r['model']}, "
              f"{r['so_lan']} lan, trung binh chi ra {r['ra_tb']} token. Haiku co the du.")

    # b) Goi lap: cung noi goi, cung hoc vien, nhieu lan trong 1 gio
    rows = await conn.fetch("""
        SELECT caller, student_id, date_trunc('hour', occurred_at) AS gio, count(*) AS so_lan
        FROM breakoutos.llm_usage_log
        WHERE occurred_at > now() - ($1||' days')::interval AND student_id IS NOT NULL
        GROUP BY 1,2,3 HAVING count(*) >= 5 ORDER BY so_lan DESC LIMIT 5
    """, str(days))
    for r in rows:
        found = True
        print(f"  [goi lap] {r['caller']} goi {r['so_lan']} lan cho cung 1 hoc vien "
              f"trong 1 gio ({r['gio']:%Y-%m-%d %H:00}). Kiem xem co phai mo lai trang la goi lai.")

    # c) Cron chay qua day
    rows = await conn.fetch("""
        SELECT caller, count(*) AS so_lan,
               count(*)::float / GREATEST($2::int,1) AS lan_moi_ngay
        FROM breakoutos.llm_usage_log
        WHERE occurred_at > now() - ($1||' days')::interval AND call_group='cron'
        GROUP BY 1 HAVING count(*)::float / GREATEST($2::int,1) > 24
        ORDER BY so_lan DESC LIMIT 5
    """, str(days), days)
    for r in rows:
        found = True
        print(f"  [cron day] {r['caller']} chay {r['lan_moi_ngay']:.0f} lan/ngay. "
              f"Nhieu hon 1 lan/gio, kiem lai lich.")

    # d) Ty le loi cao
    rows = await conn.fetch("""
        SELECT caller, count(*) FILTER (WHERE NOT success) AS loi, count(*) AS tong
        FROM breakoutos.llm_usage_log
        WHERE occurred_at > now() - ($1||' days')::interval
        GROUP BY 1 HAVING count(*) FILTER (WHERE NOT success) > 0
        ORDER BY loi DESC LIMIT 5
    """, str(days))
    for r in rows:
        found = True
        print(f"  [loi] {r['caller']}: {r['loi']}/{r['tong']} lan that bai. "
              f"Token da tra tien nhung khong ra ket qua.")

    if not found:
        print("  Khong thay dau hieu bat thuong nao trong khoang nay.")


async def _section_agents(conn, days: int) -> None:
    print("\n" + "-" * 74)
    print("5. AGENT NAO THAT SU CHAY")
    print("-" * 74)
    rows = await conn.fetch("""
        SELECT caller, count(*) AS so_lan FROM breakoutos.llm_usage_log
        WHERE occurred_at > now() - ($1||' days')::interval AND caller LIKE 'agents/%'
        GROUP BY 1
    """, str(days))
    da_chay = set()
    for r in rows:
        part = (r["caller"] or "").split("/")
        if len(part) >= 2:
            da_chay.add(part[1].split(":")[0])
    trong_code = _agents_in_code()
    chua_chay = sorted(trong_code - da_chay)
    print(f"  Agent co trong code : {len(trong_code)}")
    print(f"  Agent da chay {days} ngay: {len(da_chay)}")
    if da_chay:
        print("    " + ", ".join(sorted(da_chay)[:20]))
    print(f"  Agent CHUA thay chay: {len(chua_chay)}")
    if chua_chay:
        print("    " + ", ".join(chua_chay[:25]) + (" ..." if len(chua_chay) > 25 else ""))
        print("  Luu y: 'chua thay chay' chi dung trong khoang do duoc. Agent chay theo")
        print("  lich thang/quy co the chua toi luot, dung voi ket luan la code chet.")


async def _section_legacy_k3(conn, days: int) -> None:
    print("\n" + "-" * 74)
    print("6. DU LIEU CU CUA LOP STARTER OS (nguon duy nhat co truoc hom nay)")
    print("-" * 74)
    if not await _table_exists(conn, "breakout_challenge", "sessions"):
        print("  (khong tim thay bang breakout_challenge.sessions)")
        return
    row = await conn.fetchrow("""
        WITH e AS (
          SELECT s.access_tier, (entry->>'kind') AS kind,
                 ((entry->>'cost_usd')::numeric) AS cost
          FROM breakout_challenge.sessions s,
               jsonb_array_elements(COALESCE(s.metadata_json->'api_spend_log','[]'::jsonb)) entry
        )
        SELECT count(*) AS so_ban_ghi,
               COALESCE(sum(cost),0)::float AS tong,
               COALESCE(sum(cost) FILTER (WHERE kind LIKE 'llm_%'),0)::float AS llm,
               COALESCE(sum(cost) FILTER (WHERE access_tier='free'),0)::float AS mien_phi,
               COALESCE(sum(cost) FILTER (WHERE access_tier='vip'),0)::float AS tra_phi
        FROM e
    """)
    print(f"  So ban ghi chi tieu : {row['so_ban_ghi']}")
    print(f"  Tong tu truoc den nay: ${row['tong']:.4f}  (LLM ${row['llm']:.4f})")
    print(f"  Hoc vien mien phi   : ${row['mien_phi']:.4f}")
    print(f"  Hoc vien tra phi    : ${row['tra_phi']:.4f}")
    print("  Han che: nguon nay khong ghi model, khong tach token vao/ra,")
    print("  va chi phu song lop Starter OS. Khong dung de suy ra toan he thong.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()
    asyncio.run(main(a.days))
