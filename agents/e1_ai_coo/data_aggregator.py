"""Data Aggregator cho E1 AI COO Dashboard.

Pull số liệu 24h/7d/30d từ Fan Hub (person), order (Sepay), trust_score_log,
content_engine_output, brevo_email_event, ga4 fact table.

Fail-soft: query exception → return -1 với "error" key, KHÔNG raise. Mục đích
là báo cáo có thể partial, agent vẫn run được khi 1 table chưa tồn tại.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("camas.e1_ai_coo.data_aggregator")


class DataAggregator:
    """Aggregator pull data từ Postgres pool của MemoryLayer."""

    def __init__(self, memory_layer: Any) -> None:
        self.memory = memory_layer

    async def _acquire(self) -> Optional[Any]:
        if not getattr(self.memory, "dsn", None):
            log.warning("E1 DataAggregator: DATABASE_URL chưa set, skip queries")
            return None
        try:
            return await self.memory._get_pool()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            log.warning("E1 DataAggregator pool init fail: %r", exc)
            return None

    # ----------------------------------------------------------------
    # Public API: 3 collectors
    # ----------------------------------------------------------------
    async def collect_24h(self, student_id: str, tenant_id: str) -> dict[str, Any]:
        """Pull 24h data points cho daily report."""
        return await self._collect(student_id, tenant_id, hours=24, label="daily")

    async def collect_7d(self, student_id: str, tenant_id: str) -> dict[str, Any]:
        """Pull 7d data points cho weekly report."""
        return await self._collect(student_id, tenant_id, hours=24 * 7, label="weekly")

    async def collect_30d(self, student_id: str, tenant_id: str) -> dict[str, Any]:
        """Pull 30d data points cho monthly memo."""
        return await self._collect(student_id, tenant_id, hours=24 * 30, label="monthly")

    # ----------------------------------------------------------------
    # Internal: master collector
    # ----------------------------------------------------------------
    async def _collect(
        self,
        student_id: str,
        tenant_id: str,
        hours: int,
        label: str,
    ) -> dict[str, Any]:
        pool = await self._acquire()
        if pool is None:
            return {
                "label": label,
                "hours": hours,
                "leads_new": {"total": 0, "by_source": {}},
                "revenue_vnd": 0,
                "revenue_avg_7d_vnd": 0,
                "hot_leads_top3": [],
                "content_planned_vs_done": {"planned_today": 0, "done_today": 0},
                "last_email_stats": {},
                "pipeline": {},
                "error": "no_pool",
            }

        out: dict[str, Any] = {
            "label": label,
            "hours": hours,
            "student_id": student_id,
            "tenant_id": tenant_id,
        }
        async with pool.acquire() as conn:
            out["leads_new"] = await self._fetch_leads(conn, tenant_id, hours)
            out["revenue_vnd"] = await self._fetch_revenue(conn, tenant_id, hours)
            if hours <= 24:
                out["revenue_avg_7d_vnd"] = await self._fetch_revenue_avg(
                    conn, tenant_id, days=7
                )
            else:
                out["revenue_avg_7d_vnd"] = 0
            out["hot_leads_top3"] = await self._fetch_hot_leads(conn, tenant_id)
            out["content_planned_vs_done"] = await self._fetch_content_stats(
                conn, student_id, hours
            )
            out["last_email_stats"] = await self._fetch_last_email_stats(
                conn, student_id, hours
            )
            out["pipeline"] = await self._fetch_pipeline_snapshot(conn, tenant_id)
            out["ga4_traffic"] = await self._fetch_ga4_traffic(
                conn, tenant_id, hours
            )
        return out

    # ----------------------------------------------------------------
    # Per-source fetchers, all fail-soft
    # ----------------------------------------------------------------
    async def _fetch_leads(
        self, conn: Any, tenant_id: str, hours: int
    ) -> dict[str, Any]:
        """Lead mới theo source. Schema fan_hub.person hoặc public.person."""
        try:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*)::int AS total,
                    COALESCE(
                        jsonb_object_agg(source, cnt)
                            FILTER (WHERE source IS NOT NULL),
                        '{}'::jsonb
                    ) AS by_source
                FROM (
                    SELECT
                        COALESCE(NULLIF(source_tag, ''), 'unknown') AS source,
                        COUNT(*)::int AS cnt
                    FROM public.person
                    WHERE ($1::text = '' OR tenant_id = $1)
                      AND created_at > now() - make_interval(hours => $2)
                    GROUP BY source_tag
                ) sub
                """,
                tenant_id or "",
                hours,
            )
            if not row:
                return {"total": 0, "by_source": {}}
            by_source = row["by_source"] or {}
            if isinstance(by_source, str):
                import json as _json

                by_source = _json.loads(by_source)
            return {"total": int(row["total"] or 0), "by_source": dict(by_source)}
        except Exception as exc:  # noqa: BLE001
            log.warning("E1 fetch_leads fail (%s): %r", hours, exc)
            return {"total": -1, "by_source": {}, "error": str(exc)[:120]}

    async def _fetch_revenue(
        self, conn: Any, tenant_id: str, hours: int
    ) -> int:
        """Sum amount_vnd từ public.events payment.completed N giờ gần đây."""
        try:
            row = await conn.fetchrow(
                """
                SELECT COALESCE(
                    SUM(
                        CASE
                            WHEN payload ? 'amount_vnd'
                            THEN (payload->>'amount_vnd')::bigint
                            WHEN payload ? 'amount'
                            THEN (payload->>'amount')::bigint
                            ELSE 0
                        END
                    ),
                    0
                )::bigint AS revenue_vnd
                FROM public.events
                WHERE event_type IN (
                    'payment.completed',
                    'sepay.payment.success',
                    'sepay.match.success'
                )
                  AND ($1::text = '' OR venture = $1 OR (payload->>'tenant_id') = $1)
                  AND received_at > now() - make_interval(hours => $2)
                """,
                tenant_id or "",
                hours,
            )
            return int(row["revenue_vnd"] or 0) if row else 0
        except Exception as exc:  # noqa: BLE001
            log.warning("E1 fetch_revenue fail: %r", exc)
            return -1

    async def _fetch_revenue_avg(
        self, conn: Any, tenant_id: str, days: int
    ) -> int:
        """Average daily revenue trong N ngày gần đây, dùng để so sánh trend."""
        try:
            row = await conn.fetchrow(
                """
                SELECT COALESCE(
                    SUM(
                        CASE
                            WHEN payload ? 'amount_vnd'
                            THEN (payload->>'amount_vnd')::bigint
                            ELSE 0
                        END
                    ) / GREATEST($2, 1),
                    0
                )::bigint AS avg_daily
                FROM public.events
                WHERE event_type IN (
                    'payment.completed',
                    'sepay.payment.success'
                )
                  AND ($1::text = '' OR venture = $1)
                  AND received_at > now() - make_interval(days => $2)
                """,
                tenant_id or "",
                days,
            )
            return int(row["avg_daily"] or 0) if row else 0
        except Exception as exc:  # noqa: BLE001
            log.warning("E1 fetch_revenue_avg fail: %r", exc)
            return 0

    async def _fetch_hot_leads(
        self, conn: Any, tenant_id: str
    ) -> list[dict[str, Any]]:
        """Top 3 hot leads theo trust_score ≥ 50 hoặc breakout_lead_score ≥ 50."""
        try:
            rows = await conn.fetch(
                """
                SELECT
                    COALESCE(p.display_name, p.full_name, p.email, 'unknown')::text AS name,
                    COALESCE(p.phone, '') AS phone,
                    COALESCE(t.trust_score, 0)::int AS trust_score,
                    p.email
                FROM public.person p
                LEFT JOIN LATERAL (
                    SELECT trust_score
                    FROM public.trust_score_log
                    WHERE person_id = p.id
                    ORDER BY scored_at DESC
                    LIMIT 1
                ) t ON true
                WHERE ($1::text = '' OR p.tenant_id = $1)
                  AND COALESCE(t.trust_score, 0) >= 50
                ORDER BY t.trust_score DESC NULLS LAST
                LIMIT 3
                """,
                tenant_id or "",
            )
            return [
                {
                    "name": r["name"],
                    "phone": r["phone"],
                    "email": r["email"],
                    "trust_score": int(r["trust_score"] or 0),
                }
                for r in rows
            ]
        except Exception as exc:  # noqa: BLE001
            log.warning("E1 fetch_hot_leads fail: %r", exc)
            return []

    async def _fetch_content_stats(
        self, conn: Any, student_id: str, hours: int
    ) -> dict[str, Any]:
        """Content planned vs done từ content_engine_output table."""
        try:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status IN ('planned', 'draft'))::int AS planned_today,
                    COUNT(*) FILTER (WHERE status = 'published')::int AS done_today,
                    COUNT(*)::int AS total
                FROM public.content_engine_output
                WHERE ($1::text = '' OR student_id = $1)
                  AND created_at > now() - make_interval(hours => $2)
                """,
                student_id or "",
                hours,
            )
            if not row:
                return {"planned_today": 0, "done_today": 0, "total": 0}
            return {
                "planned_today": int(row["planned_today"] or 0),
                "done_today": int(row["done_today"] or 0),
                "total": int(row["total"] or 0),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("E1 fetch_content_stats fail: %r", exc)
            return {"planned_today": 0, "done_today": 0, "error": str(exc)[:120]}

    async def _fetch_last_email_stats(
        self, conn: Any, student_id: str, hours: int
    ) -> dict[str, Any]:
        """Last email campaign open/click rate. Source: brevo_email_event table."""
        try:
            row = await conn.fetchrow(
                """
                SELECT
                    campaign_id,
                    subject,
                    sent_count,
                    open_count,
                    click_count,
                    CASE
                        WHEN sent_count > 0
                        THEN open_count::float / sent_count
                        ELSE 0
                    END AS open_rate,
                    CASE
                        WHEN sent_count > 0
                        THEN click_count::float / sent_count
                        ELSE 0
                    END AS click_rate,
                    sent_at
                FROM public.brevo_email_event
                WHERE ($1::text = '' OR student_id = $1)
                  AND sent_at > now() - make_interval(hours => $2)
                ORDER BY sent_at DESC
                LIMIT 1
                """,
                student_id or "",
                hours,
            )
            if not row:
                return {}
            return {
                "campaign_id": row["campaign_id"],
                "subject": row["subject"],
                "sent": int(row["sent_count"] or 0),
                "opens": int(row["open_count"] or 0),
                "clicks": int(row["click_count"] or 0),
                "open_rate": float(row["open_rate"] or 0),
                "click_rate": float(row["click_rate"] or 0),
                "sent_at": (
                    row["sent_at"].isoformat() if row["sent_at"] else None
                ),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("E1 fetch_last_email_stats fail: %r", exc)
            return {"error": str(exc)[:120]}

    async def _fetch_pipeline_snapshot(
        self, conn: Any, tenant_id: str
    ) -> dict[str, int]:
        """Pipeline count per stage. Fan Hub person có lifecycle_stage column."""
        try:
            rows = await conn.fetch(
                """
                SELECT
                    COALESCE(NULLIF(lifecycle_stage, ''), 'visitor') AS stage,
                    COUNT(*)::int AS cnt
                FROM public.person
                WHERE ($1::text = '' OR tenant_id = $1)
                GROUP BY lifecycle_stage
                """,
                tenant_id or "",
            )
            out = {
                "visitor": 0,
                "lead": 0,
                "considering": 0,
                "decision": 0,
                "buyer": 0,
            }
            for r in rows:
                stage = str(r["stage"]).lower()
                if stage in out:
                    out[stage] = int(r["cnt"] or 0)
                else:
                    out.setdefault(stage, int(r["cnt"] or 0))
            return out
        except Exception as exc:  # noqa: BLE001
            log.warning("E1 fetch_pipeline fail: %r", exc)
            return {}

    async def _fetch_ga4_traffic(
        self, conn: Any, tenant_id: str, hours: int
    ) -> dict[str, Any]:
        """GA4 sessions + users từ ga4_fact table (server-side MP synced)."""
        try:
            row = await conn.fetchrow(
                """
                SELECT
                    COALESCE(SUM(sessions), 0)::int AS sessions,
                    COALESCE(SUM(users), 0)::int AS users,
                    COALESCE(SUM(conversions), 0)::int AS conversions
                FROM public.ga4_fact
                WHERE ($1::text = '' OR tenant_id = $1)
                  AND event_date > (CURRENT_DATE - make_interval(days => $2))
                """,
                tenant_id or "",
                max(1, hours // 24),
            )
            if not row:
                return {"sessions": 0, "users": 0, "conversions": 0}
            return {
                "sessions": int(row["sessions"] or 0),
                "users": int(row["users"] or 0),
                "conversions": int(row["conversions"] or 0),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("E1 fetch_ga4 fail: %r", exc)
            return {"sessions": 0, "users": 0, "error": str(exc)[:120]}
