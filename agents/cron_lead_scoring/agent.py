"""Cron Lead Scoring, 5am VN daily, score contacts + classify hot/warm/cold.

Pattern: cron-job.org → POST /kernel/execute, event=cron.lead_scoring.tick.

Sprint 6: REAL GHL wiring.
1. Lấy contacts từ GHL Marketing API (paginated, max_contacts cap)
2. Lookup revenue từ Postgres customers.total_revenue_vnd join by email
3. Compute score qua LeadScorer (weighted formula, Anna chốt memory
   `reference-lead-scoring`)
4. PATCH custom field `breakout_lead_score` per contact (auto-create field nếu
   chưa có, idempotent)
5. Build Telegram top 20 hot list + send group Breakout Ops
6. Emit memory stats cho BC1 Team Leader rollup

Env vars:
    GHL_API_KEY: pit-* Personal Integration Token
    GHL_LOCATION_ID: GHL location uuid
    TELEGRAM_BOT_TOKEN: bot token
    TELEGRAM_OPS_GROUP_ID: chat id (default -1003813280155)
    CRON_LEAD_SCORING_DRY_RUN=1: skip GHL PATCH + Telegram send
    CRON_DRY_RUN=1: alias dry run cho cron pipeline

Payload (optional):
    max_contacts: int (default 2000)
    dry_run: bool (override env)
    max_concurrent: int (default 5, batch update concurrency)

Tier (memory reference-lead-scoring):
    Hot ≥ 50, Warm 30-49, Cold < 30
"""
from __future__ import annotations

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

from .ghl_client import GHLClient

log = logging.getLogger("camas.cron_lead_scoring")

EXPECTED_EVENT = "cron.lead_scoring.tick"

# Thresholds memory reference-lead-scoring
HOT_THRESHOLD = 50
WARM_THRESHOLD = 30

DEFAULT_MAX_CONTACTS = 2000
DEFAULT_MAX_CONCURRENT = 5
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"  # Breakout Ops


class LeadScorer:
    """Compute weighted score per memory `reference-lead-scoring`.

    Behavior cap 60, Purchase cap 30, Total cap 100.
    Để dành 10 room cho signals tương lai (refund tag, course completion, etc.).

    Rule trong BEHAVIOR_RULES:
    - Key kết thúc bằng `-` = prefix match (vd `email-opened-` match
      `email-opened-2025-12-broadcast-newyear`)
    - Key khác = exact match (lowercase)
    """

    BEHAVIOR_RULES: dict[str, int] = {
        # WK attendance (exact)
        "wk_attended_d3": 20,
        "wk_attended_d2": 15,
        "wk_attended_d1": 10,
        # Webinar signup tags
        "dangky_webinar_phuonganb": 5,
        "breakout.live_dangky": 5,
        # Engagement (prefix match)
        "email-opened-": 10,
        "email-clicked-": 10,
        "fb-commented-": 5,
        # Customer tier tags
        "breakout-foundation-k1": 10,
        "breakout-customer-k1": 10,
        "breakout-growth-k1": 10,
        # Cross-venture signals
        "shopify": 5,
        "trolyao": 5,
    }
    BEHAVIOR_MAX = 60
    PURCHASE_MAX = 30
    TOTAL_MAX = 100

    @classmethod
    def score_contact(cls, contact: dict[str, Any]) -> dict[str, Any]:
        """Compute score breakdown cho 1 contact.

        Args:
            contact: dict với keys `tags` (list[str]) + `total_revenue_vnd` (int)

        Return:
            {
                "total": int 0-100,
                "behavior": int 0-60,
                "purchase": int 0-30,
                "tier": "hot" | "warm" | "cold",
                "breakdown": [(rule_pattern, points)],
                "revenue": int,
            }
        """
        raw_tags = contact.get("tags") or []
        tags = {(t or "").strip().lower() for t in raw_tags if t}

        behavior = 0
        breakdown_b: list[tuple[str, int]] = []
        for pattern, pts in cls.BEHAVIOR_RULES.items():
            if pattern.endswith("-"):
                # Prefix match
                if any(t.startswith(pattern) for t in tags):
                    behavior += pts
                    breakdown_b.append((pattern, pts))
            else:
                if pattern in tags:
                    behavior += pts
                    breakdown_b.append((pattern, pts))
        behavior = min(behavior, cls.BEHAVIOR_MAX)

        # Purchase score (cumulative threshold)
        revenue = int(contact.get("total_revenue_vnd") or 0)
        purchase = 0
        if revenue > 0:
            purchase += 10
        if revenue > 1_000_000:
            purchase += 5
        if revenue > 10_000_000:
            purchase += 5
        if revenue > 50_000_000:
            purchase += 10
        purchase = min(purchase, cls.PURCHASE_MAX)

        total = min(behavior + purchase, cls.TOTAL_MAX)
        if total >= HOT_THRESHOLD:
            tier = "hot"
        elif total >= WARM_THRESHOLD:
            tier = "warm"
        else:
            tier = "cold"

        return {
            "total": total,
            "behavior": behavior,
            "purchase": purchase,
            "tier": tier,
            "breakdown": breakdown_b,
            "revenue": revenue,
        }


class CronLeadScoring(BaseBC):
    """Cron 5am VN daily, score contacts + PATCH GHL + Telegram top 20 hot."""

    name = "cron_lead_scoring"
    scope = "Cron 5am VN daily, score contacts + classify Hot/Warm/Cold + PATCH GHL"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(self, llm: LLMLayer, memory: MemoryLayer) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory

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
        max_contacts = int(payload.get("max_contacts") or DEFAULT_MAX_CONTACTS)
        max_concurrent = int(
            payload.get("max_concurrent") or DEFAULT_MAX_CONCURRENT
        )
        dry_run = bool(payload.get("dry_run")) or (
            os.getenv("CRON_LEAD_SCORING_DRY_RUN", "") == "1"
        ) or (
            os.getenv("CRON_DRY_RUN", "") == "1"
        )

        result = await self._run_pipeline(
            date_vn=date_vn,
            max_contacts=max_contacts,
            max_concurrent=max_concurrent,
            dry_run=dry_run,
        )
        status_tag = "ok" if result.get("error") is None else "fail"

        emitted_memories = [
            {
                "agent_name": self.name,
                "content_summary": (
                    f"Lead scoring 5am VN executed processed={result.get('processed', 0)} "
                    f"hot={result.get('hot', 0)} warm={result.get('warm', 0)} "
                    f"cold={result.get('cold', 0)} "
                    f"patched={result.get('patched', 0)} "
                    f"failed={result.get('patch_failed', 0)} "
                    f"dry_run={dry_run}"
                ),
                "keywords": ["lead_scoring", date_vn, status_tag],
                "tags": ["cron", "lead_scoring", "daily", status_tag],
                "venture": "all",
                "context": f"{EXPECTED_EVENT} {date_vn}",
            }
        ]

        return AgentResult(
            success=True,
            output_text=(
                f"Lead scoring {date_vn} processed={result.get('processed', 0)} "
                f"hot={result.get('hot', 0)} warm={result.get('warm', 0)} "
                f"cold={result.get('cold', 0)} "
                f"patched={result.get('patched', 0)} dry_run={dry_run}"
            ),
            output_payload={
                "event": EXPECTED_EVENT,
                "date_vn": date_vn,
                "status_tag": status_tag,
                "stats": result,
                "dry_run": dry_run,
                "max_contacts": max_contacts,
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
        max_contacts: int,
        max_concurrent: int,
        dry_run: bool,
    ) -> dict[str, Any]:
        """Pipeline: GHL fetch → revenue lookup → score → PATCH → Telegram.

        Fail-soft: token miss → memory-only stats. SQL fail → score qua tags
        only (revenue=0). GHL fail → memory-only stats.
        """
        result: dict[str, Any] = {
            "processed": 0,
            "hot": 0,
            "warm": 0,
            "cold": 0,
            "patched": 0,
            "patch_failed": 0,
            "top_hot": [],
            "custom_field_id": None,
            "telegram_sent": False,
            "error": None,
            "warnings": [],
        }

        token = os.getenv("GHL_API_KEY", "").strip()
        location_id = os.getenv("GHL_LOCATION_ID", "").strip()

        if not token or not location_id:
            result["error"] = "GHL_API_KEY / GHL_LOCATION_ID chưa set"
            result["warnings"].append("fallback memory-only, no GHL update")
            return result

        # 1. Revenue lookup từ Postgres (best-effort, fail-soft)
        revenue_by_email = await self._load_revenue_by_email()
        if revenue_by_email is None:
            result["warnings"].append("revenue lookup fail, score tags-only")
            revenue_by_email = {}

        # 2. Init GHL client + ensure custom field
        ghl = GHLClient(api_token=token, location_id=location_id)
        try:
            cf_id = await ghl.get_or_create_lead_score_field()
        except Exception as exc:  # noqa: BLE001
            log.warning("GHL get_or_create_lead_score_field fail: %r", exc)
            result["error"] = f"GHL custom field fail: {exc!r}"
            return result
        result["custom_field_id"] = cf_id

        # 3. Fetch contacts
        try:
            contacts = await ghl.list_contacts(max_contacts=max_contacts)
        except Exception as exc:  # noqa: BLE001
            log.warning("GHL list_contacts fail: %r", exc)
            result["error"] = f"GHL list_contacts fail: {exc!r}"
            return result

        result["processed"] = len(contacts)

        # 4. Score per contact
        scored: list[dict[str, Any]] = []
        scores_map: dict[str, int] = {}
        for c in contacts:
            email = (c.get("email") or "").strip().lower()
            revenue = revenue_by_email.get(email, 0) if email else 0
            scoring_input = {
                "tags": c.get("tags") or [],
                "total_revenue_vnd": revenue,
            }
            s = LeadScorer.score_contact(scoring_input)
            cid = c.get("id")
            if not cid:
                continue
            scores_map[cid] = s["total"]
            scored.append({
                "contact_id": cid,
                "first_name": c.get("firstName") or "",
                "last_name": c.get("lastName") or "",
                "email": email,
                "score": s["total"],
                "behavior": s["behavior"],
                "purchase": s["purchase"],
                "tier": s["tier"],
                "revenue": s["revenue"],
            })
            if s["tier"] == "hot":
                result["hot"] += 1
            elif s["tier"] == "warm":
                result["warm"] += 1
            else:
                result["cold"] += 1

        # 5. PATCH GHL (skip nếu dry_run)
        if dry_run:
            log.info("cron_lead_scoring DRY_RUN, skip GHL PATCH")
        else:
            try:
                batch_res = await ghl.batch_update_scores(
                    scores=scores_map,
                    custom_field_id=cf_id,
                    max_concurrent=max_concurrent,
                )
                result["patched"] = batch_res.get("success", 0)
                result["patch_failed"] = batch_res.get("failed", 0)
                if batch_res.get("errors"):
                    result["warnings"].append(
                        f"patch errors sample={batch_res['errors'][:5]}"
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("GHL batch_update_scores fail: %r", exc)
                result["warnings"].append(f"batch update fail: {exc!r}")

        # 6. Top 20 hot
        top_hot = sorted(
            (s for s in scored if s["tier"] == "hot"),
            key=lambda s: s["score"],
            reverse=True,
        )[:20]
        result["top_hot"] = [
            {
                "first_name": h["first_name"],
                "last_name": h["last_name"],
                "score": h["score"],
                "tier": h["tier"],
            }
            for h in top_hot
        ]

        # 7. Telegram top 20 hot
        if dry_run:
            log.info("cron_lead_scoring DRY_RUN, skip Telegram send")
        else:
            try:
                msg = self._build_telegram_message(
                    date_vn=date_vn,
                    processed=result["processed"],
                    hot=result["hot"],
                    warm=result["warm"],
                    cold=result["cold"],
                    patched=result["patched"],
                    patch_failed=result["patch_failed"],
                    top_hot=top_hot,
                )
                sent_ok = await send_telegram(msg)
                result["telegram_sent"] = sent_ok
            except Exception as exc:  # noqa: BLE001
                log.warning("cron_lead_scoring Telegram fail: %r", exc)
                result["warnings"].append(f"telegram fail: {exc!r}")

        return result

    async def _load_revenue_by_email(self) -> Optional[dict[str, int]]:
        """Best-effort load revenue map từ Postgres customers table.

        Return:
            dict[email_lowercase, revenue_vnd] hoặc None nếu fail.
        """
        if not self.memory.dsn:
            log.info("DATABASE_URL chưa set, skip revenue lookup")
            return {}

        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            log.warning("cron_lead_scoring pool fail: %r", exc)
            return None

        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT primary_email, total_revenue_vnd
                    FROM public.customers
                    WHERE primary_email IS NOT NULL
                      AND total_revenue_vnd IS NOT NULL
                      AND total_revenue_vnd > 0
                    """
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("cron_lead_scoring revenue SQL fail: %r", exc)
            return None

        out: dict[str, int] = {}
        for r in rows:
            email = (r["primary_email"] or "").strip().lower()
            if not email:
                continue
            try:
                out[email] = int(r["total_revenue_vnd"] or 0)
            except (TypeError, ValueError):
                continue
        log.info("revenue lookup loaded=%d", len(out))
        return out

    def _build_telegram_message(
        self,
        *,
        date_vn: str,
        processed: int,
        hot: int,
        warm: int,
        cold: int,
        patched: int,
        patch_failed: int,
        top_hot: list[dict[str, Any]],
    ) -> str:
        lines = [
            f"🔥 *Lead Scoring {date_vn}*",
            "",
            f"_Tổng quét:_ {processed} contacts",
            f"- Hot (≥{HOT_THRESHOLD}): {hot}",
            f"- Warm ({WARM_THRESHOLD}-{HOT_THRESHOLD - 1}): {warm}",
            f"- Cold (<{WARM_THRESHOLD}): {cold}",
            f"- PATCH GHL: {patched} ok / {patch_failed} fail",
            "",
            f"*Top {min(20, len(top_hot))} Hot Leads:*",
        ]
        if not top_hot:
            lines.append("- Chưa có hot lead nào")
        else:
            for i, h in enumerate(top_hot, 1):
                first = (h.get("first_name") or "").strip()
                last = (h.get("last_name") or "").strip()
                display = f"{first} {last}".strip() or "(không tên)"
                lines.append(f"{i}. {display}, score={h['score']}")
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
        log.warning("cron_lead_scoring TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "cron_lead_scoring Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
