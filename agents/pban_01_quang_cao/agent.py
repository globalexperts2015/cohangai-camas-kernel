"""Phòng 01 Quảng cáo agent.

FB Ads optimize daily + budget guard + creative rotation + audience refresh cho
Breakout K3 + Speakout 33k nurture funnel. Wrap FB Marketing API + FB CAPI
(Sprint 6 wire), hiện tại stub HTTP call và emit propose memory.

Trigger events:
- `ads.budget_check`: hourly budget guard, pause nếu spend > 120% plan
- `ads.performance_review`: daily 6am VN, CPM/CTR/CPL/ROAS digest + Telegram
- `ads.campaign_propose`: weekly Sunday, propose campaign mới + budget ask

Autonomy L2: budget change > 20%/ngày require Anna approve qua Telegram.

Style: tiếng Việt docstring + Telegram. ZERO em-dash. Type hints + async/await.
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

from .fb_marketing_client import FBMarketingClient
from .google_ads_client import GoogleAdsClient

log = logging.getLogger("camas.pban_01_quang_cao")

DEFAULT_LLM_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TOKENS = 500
DEFAULT_LLM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"

BUDGET_CHANGE_L2_THRESHOLD = 20  # percent
BUDGET_OVERSPEND_AUTO_PAUSE = 120  # percent of plan


class Pban01QuangCao(BaseBC):
    """Phòng 01 Quảng cáo, FB Ads optimize + budget guard cho Breakout/Speakout.

    Wrap FB Marketing API + FB Conversion API (CAPI). Sprint 6 wire thật, hiện
    tại stub data + emit propose memory + Telegram approve queue.
    """

    name = "pban_01_quang_cao"
    scope = "FB Ads optimize daily + budget guard 20%/ngày + CAPI matchback"
    autonomy_level = AutonomyLevel.L2_APPROVE
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = ["fb_marketing_api", "fb_capi"]
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
        self._fb_client: Optional[FBMarketingClient] = None
        self._gads_client: Optional[GoogleAdsClient] = None

    def _get_fb_client(self) -> Optional[FBMarketingClient]:
        """Lazy init FB Marketing client. None nếu thiếu credentials."""
        if self._fb_client is None:
            token = os.getenv("FB_MARKETING_API_TOKEN")
            ad_acct = os.getenv("FB_AD_ACCOUNT_ID")
            if not token or not ad_acct:
                log.warning(
                    "FB Marketing API credentials thiếu (token=%s acct=%s), dùng stub",
                    bool(token),
                    bool(ad_acct),
                )
                return None
            self._fb_client = FBMarketingClient(
                access_token=token,
                ad_account_id=ad_acct,
            )
        return self._fb_client

    def _get_gads_client(self) -> Optional[GoogleAdsClient]:
        """Lazy init Google Ads client. None nếu thiếu credentials.

        Google Ads cần 5 credential: developer_token + OAuth client_id +
        client_secret + refresh_token + customer_id. Anna apply developer token
        riêng (https://ads.google.com/aw/apicenter), 2-5 ngày Google duyệt.
        """
        if self._gads_client is None:
            dev_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
            client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
            client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
            refresh_token = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "")
            customer_id = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "")
            login_customer_id = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "")
            if not all([dev_token, client_id, client_secret, refresh_token, customer_id]):
                log.info(
                    "Google Ads credentials chưa đủ "
                    "(dev_token=%s client_id=%s refresh_token=%s customer_id=%s), skip",
                    bool(dev_token),
                    bool(client_id),
                    bool(refresh_token),
                    bool(customer_id),
                )
                return None
            self._gads_client = GoogleAdsClient(
                developer_token=dev_token,
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
                customer_id=customer_id,
                login_customer_id=login_customer_id or None,
            )
        return self._gads_client

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""

        if event == "ads.budget_check":
            return await self._handle_budget_check(ctx)
        if event == "ads.performance_review":
            return await self._handle_performance_review(ctx)
        if event == "ads.campaign_propose":
            return await self._handle_campaign_propose(ctx)

        return AgentResult(
            success=False,
            output_text="Phòng 01 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": [
                    "ads.budget_check",
                    "ads.performance_review",
                    "ads.campaign_propose",
                ],
            },
        )

    # ============================================================
    # Event 1: budget check (hourly)
    # ============================================================
    async def _handle_budget_check(self, ctx: ExecutionContext) -> AgentResult:
        """Hourly budget guard. Pause ad set nếu spend > 120% daily plan."""
        client = self._get_fb_client()
        spend_snapshot = await self._fetch_spend_snapshot(ctx)
        anomalies = self._detect_budget_anomalies(spend_snapshot)
        timestamp = self._now_perth_str()

        auto_paused: list[str] = []
        propose_queue: list[dict[str, Any]] = []
        for anomaly in anomalies:
            if anomaly["spend_pct"] >= BUDGET_OVERSPEND_AUTO_PAUSE:
                if client:
                    try:
                        await client.pause_ad_set(anomaly["ad_set_id"])
                        auto_paused.append(anomaly["ad_set_id"])
                        log.info(
                            "FB Marketing paused ad_set %s spend_pct=%s",
                            anomaly["ad_set_id"],
                            anomaly["spend_pct"],
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "FB Marketing pause fail %s: %r",
                            anomaly["ad_set_id"],
                            exc,
                        )
                        propose_queue.append({**anomaly, "pause_failed": True})
                else:
                    propose_queue.append({**anomaly, "pause_proposal": True})
            elif anomaly["spend_pct"] >= BUDGET_CHANGE_L2_THRESHOLD + 80:
                propose_queue.append(anomaly)

        telegram_text: Optional[str] = None
        sent_ok = False
        if auto_paused or propose_queue:
            telegram_text = self._format_budget_alert(
                timestamp=timestamp,
                auto_paused=auto_paused,
                propose_queue=propose_queue,
            )
            sent_ok = await self._maybe_send_telegram(telegram_text)

        memory_tags = ["pban_01", "budget_check"]
        if auto_paused:
            memory_tags.append("auto_paused")
        if propose_queue:
            memory_tags.append("l2_propose")
        status = "alert" if (auto_paused or propose_queue) else "ok"

        return AgentResult(
            success=True,
            output_text=telegram_text or f"Phòng 01 budget_check status={status}",
            output_payload={
                "event": "ads.budget_check",
                "status": status,
                "anomalies_count": len(anomalies),
                "auto_paused": auto_paused,
                "propose_queue": propose_queue,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"ads.budget_check status={status} "
                        f"paused={len(auto_paused)} propose={len(propose_queue)}"
                    ),
                    "keywords": ["fb_ads", "budget_guard", timestamp[:10]],
                    "tags": memory_tags + [status],
                    "venture": ctx.venture_context,
                    "context": (
                        f"ads.budget_check anomalies={len(anomalies)} status={status}"
                    ),
                }
            ],
        )

    # ============================================================
    # Event 2: performance review (daily 6am VN)
    # ============================================================
    async def _handle_performance_review(
        self, ctx: ExecutionContext
    ) -> AgentResult:
        """Daily 6am VN, pull CPM/CTR/CPL/ROAS + Telegram digest.

        Emit memory 2 layer cho RAG retrieve:
        - 1 record summary aggregate (BC1 morning brief query "ads spend hôm qua")
        - N record per-campaign (Pban10 strategy query "campaign nào perf tốt")
        """
        metrics = await self._fetch_performance_metrics(ctx)
        per_campaign = await self._fetch_per_campaign_facts(ctx)
        timestamp = self._now_perth_str()
        date_tag = timestamp[:10]

        recommendation = await self._llm_recommendation(metrics)
        digest = self._format_performance_digest(
            timestamp=timestamp,
            metrics=metrics,
            recommendation=recommendation,
        )

        sent_ok = await self._maybe_send_telegram(digest)

        emitted_memories: list[dict[str, Any]] = [
            {
                "agent_name": self.name,
                "content_summary": (
                    f"FB Ads tổng quan {date_tag} spend={metrics.get('spend_7d')} "
                    f"cpl={metrics.get('cpl_avg')} cpm={metrics.get('cpm_avg')} "
                    f"ctr={metrics.get('ctr_avg')} roas={metrics.get('roas_avg')} "
                    f"leads={metrics.get('leads_7d')}"
                ),
                "keywords": ["fb_ads", "performance", "summary", date_tag],
                "tags": [
                    "pban_01",
                    "perf_review",
                    "ads_insights",
                    "sent" if sent_ok else "send_failed",
                ],
                "venture": ctx.venture_context,
                "context": "ads.performance_review daily digest summary",
                "category": "ads_insights",
            }
        ]

        for camp in per_campaign:
            emitted_memories.append(
                {
                    "agent_name": self.name,
                    "content_summary": camp["content"],
                    "keywords": camp["keywords"],
                    "tags": camp["tags"],
                    "venture": ctx.venture_context,
                    "context": f"ads.performance_review campaign={camp['campaign_id']}",
                    "category": "ads_insights",
                }
            )

        return AgentResult(
            success=True,
            output_text=digest,
            output_payload={
                "event": "ads.performance_review",
                "metrics": metrics,
                "per_campaign_count": len(per_campaign),
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            emitted_memories=emitted_memories,
        )

    async def _fetch_per_campaign_facts(
        self, ctx: ExecutionContext
    ) -> list[dict[str, Any]]:
        """Pull per-campaign insights last 7d từ FB + Google Ads, return list dict.

        Mỗi dict: {platform, campaign_id, content, keywords, tags}. Content là
        natural language fact dễ embed + RAG retrieve.

        Fallback: skip platform nào client không sẵn sàng. Failure không break
        parent _handle_performance_review.
        """
        date_tag = self._now_perth_str()[:10]
        out: list[dict[str, Any]] = []

        out.extend(await self._fetch_fb_campaign_facts(date_tag))
        out.extend(await self._fetch_gads_campaign_facts(date_tag))

        return out

    async def _fetch_fb_campaign_facts(
        self, date_tag: str
    ) -> list[dict[str, Any]]:
        """FB Ads per-campaign last 7d → list canonical fact dict."""
        client = self._get_fb_client()
        if not client:
            return []
        try:
            rows = await client.fetch_insights(
                level="campaign",
                date_preset="last_7d",
                fields=[
                    "campaign_id",
                    "campaign_name",
                    "spend",
                    "impressions",
                    "clicks",
                    "ctr",
                    "cpc",
                    "cpm",
                    "reach",
                    "actions",
                ],
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "FB per-campaign insights fail, return empty: %r", exc
            )
            return []

        out: list[dict[str, Any]] = []
        for row in rows:
            campaign_id = str(row.get("campaign_id") or "")
            if not campaign_id:
                continue
            name = row.get("campaign_name") or campaign_id
            spend = float(row.get("spend") or 0)
            impressions = int(row.get("impressions") or 0)
            clicks = int(row.get("clicks") or 0)
            ctr = float(row.get("ctr") or 0)
            cpc = float(row.get("cpc") or 0)
            cpm = float(row.get("cpm") or 0)
            reach = int(row.get("reach") or 0)
            leads = 0
            for action in row.get("actions") or []:
                if action.get("action_type") == "lead":
                    leads = int(float(action.get("value") or 0))
                    break

            tag_perf = "high_ctr" if ctr >= 2.0 else "low_ctr"
            tag_spend = "active_spend" if spend > 0 else "no_spend"

            content = (
                f"FB Ads campaign '{name[:60]}' (id {campaign_id}) "
                f"7 ngày tính đến {date_tag}: spend {spend:.2f} AUD, "
                f"impressions {impressions}, reach {reach}, clicks {clicks}, "
                f"ctr {ctr:.2f}%, cpc {cpc:.3f} AUD, cpm {cpm:.2f} AUD, "
                f"leads {leads}."
            )
            out.append(
                {
                    "campaign_id": campaign_id,
                    "content": content,
                    "keywords": [
                        "fb_ads",
                        "campaign",
                        campaign_id,
                        date_tag,
                    ],
                    "tags": [
                        "pban_01",
                        "ads_insights",
                        "campaign_level",
                        "platform_fb",
                        tag_perf,
                        tag_spend,
                    ],
                }
            )
        return out

    async def _fetch_gads_campaign_facts(
        self, date_tag: str
    ) -> list[dict[str, Any]]:
        """Google Ads per-campaign last 7d → list canonical fact dict.

        Return [] khi credential chưa wire (graceful, không raise). Anna apply
        developer token + OAuth refresh thì auto-enable mà không cần redeploy.
        """
        client = self._get_gads_client()
        if not client:
            return []
        try:
            rows = await client.fetch_campaign_insights()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Google Ads per-campaign insights fail, return empty: %r", exc
            )
            return []

        out: list[dict[str, Any]] = []
        for row in rows:
            campaign_id = str(row.get("campaign_id") or "")
            if not campaign_id:
                continue
            name = row.get("campaign_name") or campaign_id
            status = row.get("campaign_status") or "UNKNOWN"
            spend = float(row.get("spend") or 0)
            impressions = int(row.get("impressions") or 0)
            clicks = int(row.get("clicks") or 0)
            ctr = float(row.get("ctr") or 0)
            cpc = float(row.get("cpc") or 0)
            cpm = float(row.get("cpm") or 0)
            conversions = float(row.get("conversions") or 0)
            cpa = float(row.get("cost_per_conversion") or 0)

            tag_perf = "high_ctr" if ctr >= 2.0 else "low_ctr"
            tag_spend = "active_spend" if spend > 0 else "no_spend"
            tag_status = f"status_{status.lower()}"

            content = (
                f"Google Ads campaign '{name[:60]}' (id {campaign_id}, status {status}) "
                f"7 ngày tính đến {date_tag}: spend {spend:.2f} AUD, "
                f"impressions {impressions}, clicks {clicks}, "
                f"ctr {ctr:.2f}%, cpc {cpc:.3f} AUD, cpm {cpm:.2f} AUD, "
                f"conversions {conversions:.2f}, cpa {cpa:.2f} AUD."
            )
            out.append(
                {
                    "campaign_id": campaign_id,
                    "content": content,
                    "keywords": [
                        "google_ads",
                        "campaign",
                        campaign_id,
                        date_tag,
                    ],
                    "tags": [
                        "pban_01",
                        "ads_insights",
                        "campaign_level",
                        "platform_gads",
                        tag_perf,
                        tag_spend,
                        tag_status,
                    ],
                }
            )
        return out

    # ============================================================
    # Event 3: campaign propose (weekly Sunday)
    # ============================================================
    async def _handle_campaign_propose(
        self, ctx: ExecutionContext
    ) -> AgentResult:
        """Weekly Sunday, propose campaign mới + budget ask qua Telegram L2."""
        proposal = await self._build_campaign_proposal(ctx)
        timestamp = self._now_perth_str()

        text = self._format_campaign_proposal(
            timestamp=timestamp, proposal=proposal
        )
        sent_ok = await self._maybe_send_telegram(text)

        return AgentResult(
            success=True,
            output_text=text,
            output_payload={
                "event": "ads.campaign_propose",
                "proposal": proposal,
                "sent_ok": sent_ok,
                "timestamp_perth": timestamp,
            },
            emitted_memories=[
                {
                    "agent_name": self.name,
                    "content_summary": (
                        f"ads.campaign_propose budget={proposal.get('budget_vnd')}"
                    ),
                    "keywords": ["fb_ads", "campaign_propose", timestamp[:10]],
                    "tags": ["pban_01", "campaign_propose", "l2_propose"],
                    "venture": ctx.venture_context,
                    "context": "ads.campaign_propose weekly Anna approve",
                }
            ],
        )

    # ============================================================
    # Real FB Marketing API fetchers (fallback stub nếu thiếu credentials)
    # ============================================================
    async def _fetch_spend_snapshot(
        self, ctx: ExecutionContext
    ) -> dict[str, Any]:
        """Real spend snapshot từ FB Marketing API today. Fallback stub khi fail."""
        client = self._get_fb_client()
        if not client:
            return await self._stub_fetch_spend_snapshot(ctx)
        try:
            today_insights = await client.fetch_insights(
                level="adset",
                date_preset="today",
                fields=["spend", "impressions", "cpm", "ctr"],
            )
            ad_sets_meta = await client.list_active_ad_sets()
            # Map ad_set_id → daily_budget
            budget_map: dict[str, float] = {}
            name_map: dict[str, str] = {}
            for adset in ad_sets_meta:
                aid = str(adset.get("id") or "")
                if not aid:
                    continue
                # FB budget is in cents (minor units), convert
                daily_budget_raw = adset.get("daily_budget")
                if daily_budget_raw:
                    try:
                        budget_map[aid] = float(daily_budget_raw)
                    except (TypeError, ValueError):
                        pass
                name_map[aid] = adset.get("name") or aid

            ad_sets_out: list[dict[str, Any]] = []
            total_spend = 0.0
            for row in today_insights:
                aid = str(row.get("adset_id") or "")
                if not aid:
                    continue
                spend = float(row.get("spend") or 0)
                total_spend += spend
                daily_budget = budget_map.get(aid, 0)
                spend_pct = (
                    (spend / daily_budget * 100) if daily_budget else 0
                )
                ad_sets_out.append(
                    {
                        "id": aid,
                        "ad_set_id": aid,
                        "ad_set_name": row.get("adset_name") or name_map.get(aid, aid),
                        "spend_today": spend,
                        "daily_budget": daily_budget,
                        "spend_pct": round(spend_pct, 2),
                        "cpm": float(row.get("cpm") or 0),
                        "ctr": float(row.get("ctr") or 0),
                        "cpl": None,
                    }
                )

            total_plan = sum(budget_map.values()) or 0
            return {
                "ad_sets": ad_sets_out,
                "plan_daily_vnd": total_plan,
                "actual_today_vnd": total_spend,
                "total_spend_today": total_spend,
                "currency": "VND",
                "fetched_at": self._now_perth_str(),
                "source": "fb_marketing_api",
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("FB Marketing fetch_spend fail, fallback stub: %r", exc)
            return await self._stub_fetch_spend_snapshot(ctx)

    async def _fetch_performance_metrics(
        self, ctx: ExecutionContext
    ) -> dict[str, Any]:
        """Real performance 7d. Fallback stub khi fail."""
        client = self._get_fb_client()
        if not client:
            return await self._stub_fetch_performance_metrics(ctx)
        try:
            summary = await client.get_campaign_performance_summary(days=7)
            return {
                "cpl_avg": summary.get("cost_per_lead") or summary.get("cpa") or 0,
                "cpm_avg": summary.get("cpm") or 0,
                "ctr_avg": summary.get("ctr") or 0,
                "cpc_avg": summary.get("cpc") or 0,
                "roas_avg": summary.get("roas") or 0,
                "spend_24h_vnd": summary.get("spend_total") or 0,
                "spend_7d": summary.get("spend_total") or 0,
                "leads_24h": summary.get("leads_count") or 0,
                "leads_7d": summary.get("leads_count") or 0,
                "purchases_7d": summary.get("purchases_count") or 0,
                "currency": "VND",
                "fetched_at": self._now_perth_str(),
                "source": "fb_marketing_api",
            }
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "FB Marketing performance fetch fail, fallback stub: %r", exc
            )
            return await self._stub_fetch_performance_metrics(ctx)

    async def _build_campaign_proposal(
        self, ctx: ExecutionContext
    ) -> dict[str, Any]:
        """Build proposal dựa trên lookalike + recent perf. Fallback stub."""
        client = self._get_fb_client()
        if not client:
            return await self._stub_build_campaign_proposal(ctx)
        try:
            audiences = await client.get_lookalike_audiences()
            perf = await client.get_campaign_performance_summary(days=7)
            top_audiences = sorted(
                audiences,
                key=lambda a: a.get("approximate_count") or 0,
                reverse=True,
            )[:2]

            llm_brief = await self._llm_campaign_brief(
                ctx, perf, top_audiences
            )

            picked_audience = (
                top_audiences[0]["name"]
                if top_audiences
                else "Lookalike 1% K2 customers"
            )
            audience_count = (
                top_audiences[0].get("approximate_count")
                if top_audiences
                else None
            )

            return {
                "name": llm_brief.get("name")
                or f"BR-K3-{ctx.venture_context}-Lookalike",
                "campaign_name": llm_brief.get("name")
                or f"BR-K3-{ctx.venture_context}-Lookalike",
                "objective": "LEAD",
                "audience": picked_audience,
                "budget_vnd": llm_brief.get("budget_vnd", 8_000_000),
                "creative_request": llm_brief.get(
                    "creative_angle", "Phòng 02 ship 5 angle variant"
                ),
                "creative_angle": llm_brief.get("creative_angle", ""),
                "test_hypothesis": llm_brief.get("test_hypothesis", ""),
                "expected_cpl": int(perf.get("cost_per_lead") or 55000),
                "based_on_performance": perf,
                "audience_count": audience_count,
                "source": "fb_marketing_api + llm_propose",
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("FB Marketing propose fail, fallback stub: %r", exc)
            return await self._stub_build_campaign_proposal(ctx)

    async def _llm_campaign_brief(
        self,
        ctx: ExecutionContext,
        perf: dict[str, Any],
        top_audiences: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Haiku 4.5 sinh brief campaign (name/budget/creative angle)."""
        if not self.llm.ready:
            return {}
        audiences_brief = [
            {
                "name": a.get("name"),
                "count": a.get("approximate_count"),
            }
            for a in top_audiences
        ]
        prompt = (
            f"Đề xuất 1 campaign FB Ads cho venture {ctx.venture_context}.\n\n"
            f"Performance 7 ngày gần:\n"
            f"- CPL avg: {perf.get('cost_per_lead')} VND\n"
            f"- ROAS: {perf.get('roas')}\n"
            f"- Spend: {perf.get('spend_total')} VND\n\n"
            f"Lookalike audiences sẵn có:\n"
            f"{json.dumps(audiences_brief, ensure_ascii=False)}\n\n"
            f"Trả về JSON object với key: name, audience, budget_vnd (số int), "
            f"creative_angle (1 câu), test_hypothesis (1 câu). "
            f"Tiếng Việt, không có preamble, không markdown fence."
        )
        try:
            resp = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban01 LLM campaign brief fail: %r", exc)
            return {}
        text = ""
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                text += getattr(block, "text", "")
        text = text.strip()
        # Strip markdown fence if any
        if text.startswith("```"):
            text = text.split("```", 2)[1] if text.count("```") >= 2 else text
            text = text.lstrip("json").strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:  # noqa: BLE001
            log.info("Pban01 LLM brief không parse JSON, raw=%s", text[:200])
        return {}

    # ============================================================
    # Stubs (fallback khi thiếu credentials hoặc API fail)
    # ============================================================
    async def _stub_fetch_spend_snapshot(
        self, ctx: ExecutionContext
    ) -> dict[str, Any]:
        """STUB. Sprint 6 wire fb_marketing_api Insights."""
        # TODO Sprint 6 wire fb_marketing_api
        return {
            "ad_sets": [
                {"id": "stub_ad_set_1", "spend_pct": 85, "cpl": 45000},
                {"id": "stub_ad_set_2", "spend_pct": 115, "cpl": 90000},
            ],
            "plan_daily_vnd": 5_000_000,
            "actual_today_vnd": 4_300_000,
        }

    async def _stub_fetch_performance_metrics(
        self, ctx: ExecutionContext
    ) -> dict[str, Any]:
        """STUB. Sprint 6 wire fb_marketing_api Insights + Postgres ad_performance."""
        # TODO Sprint 6 wire fb_marketing_api
        return {
            "cpl_avg": 62000,
            "cpm_avg": 130000,
            "ctr_avg": 2.4,
            "roas_avg": 2.1,
            "spend_24h_vnd": 4_800_000,
            "leads_24h": 78,
            "top_creative_id": "stub_creative_42",
        }

    async def _stub_build_campaign_proposal(
        self, ctx: ExecutionContext
    ) -> dict[str, Any]:
        """STUB. Sprint 6 wire Phòng 02 creative + audience builder."""
        # TODO Sprint 6 wire fb_marketing_api campaign create
        return {
            "name": "BR-K3-VIP-Lookalike-1pct",
            "objective": "LEAD",
            "audience": "LAL 1% K2 customers",
            "budget_vnd": 8_000_000,
            "creative_request": "Phòng 02 ship 5 angle variant",
            "expected_cpl": 55000,
        }

    # ============================================================
    # Decision helpers
    # ============================================================
    def _detect_budget_anomalies(
        self, snapshot: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Return list ad_set vượt 100% spend plan."""
        anomalies: list[dict[str, Any]] = []
        for ad_set in snapshot.get("ad_sets", []):
            pct = ad_set.get("spend_pct", 0)
            if pct >= 100:
                anomalies.append(
                    {
                        "ad_set_id": ad_set.get("id"),
                        "spend_pct": pct,
                        "cpl": ad_set.get("cpl"),
                    }
                )
        return anomalies

    async def _llm_recommendation(self, metrics: dict[str, Any]) -> str:
        """Haiku 4.5 sinh 1-2 action item tiếng Việt."""
        if not self.llm.ready:
            return "LLM chưa init, không có khuyến nghị"
        compact = json.dumps(metrics, ensure_ascii=False)
        prompt = (
            "You are Anna's FB Ads strategist. Given today's metrics, "
            "suggest 1-2 short concrete actions tiếng Việt. No preamble.\n\n"
            f"Metrics: {compact}"
        )
        try:
            resp = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban01 LLM call fail: %r", exc)
            return "LLM call fail, không có khuyến nghị"
        parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))
        return ("".join(parts).strip()) or "Không có khuyến nghị"

    # ============================================================
    # Format helpers
    # ============================================================
    def _format_budget_alert(
        self,
        *,
        timestamp: str,
        auto_paused: list[str],
        propose_queue: list[dict[str, Any]],
    ) -> str:
        lines = [
            f"FB Ads Budget Alert {timestamp}",
            "",
        ]
        if auto_paused:
            lines.append(
                f"Auto-paused (spend >= {BUDGET_OVERSPEND_AUTO_PAUSE}% plan):"
            )
            for ad_id in auto_paused:
                lines.append(f"- {ad_id}")
            lines.append("")
        if propose_queue:
            lines.append(f"L2 approve queue (Anna 1-click):")
            for item in propose_queue:
                lines.append(
                    f"- {item['ad_set_id']} spend={item['spend_pct']}% "
                    f"CPL={item['cpl']}"
                )
        return "\n".join(lines)

    def _format_performance_digest(
        self,
        *,
        timestamp: str,
        metrics: dict[str, Any],
        recommendation: str,
    ) -> str:
        return (
            f"FB Ads Performance {timestamp}\n\n"
            f"Spend 24h: {metrics.get('spend_24h_vnd'):,} VND\n"
            f"Leads 24h: {metrics.get('leads_24h')}\n"
            f"CPL avg: {metrics.get('cpl_avg'):,} VND\n"
            f"CTR avg: {metrics.get('ctr_avg')}%\n"
            f"ROAS avg: {metrics.get('roas_avg')}x\n\n"
            f"Khuyến nghị:\n{recommendation}"
        )

    def _format_campaign_proposal(
        self, *, timestamp: str, proposal: dict[str, Any]
    ) -> str:
        return (
            f"FB Ads Campaign Propose {timestamp}\n\n"
            f"Name: {proposal.get('name')}\n"
            f"Audience: {proposal.get('audience')}\n"
            f"Budget: {proposal.get('budget_vnd'):,} VND\n"
            f"Expected CPL: {proposal.get('expected_cpl'):,} VND\n"
            f"Creative request: {proposal.get('creative_request')}\n\n"
            f"Cần Anna L2 approve (budget > 20%/ngày threshold)"
        )

    # ============================================================
    # Telegram + utility
    # ============================================================
    async def _maybe_send_telegram(self, text: str) -> bool:
        dry_run = os.getenv("PBAN_DRY_RUN", "") == "1"
        if dry_run:
            log.info("Pban01 DRY_RUN, skip Telegram send")
            return True
        try:
            return await send_telegram(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("Pban01 Telegram send fail: %r", exc)
            return False

    @staticmethod
    def _now_perth_str() -> str:
        now_perth = datetime.now(tz=timezone.utc) + timedelta(hours=8)
        return now_perth.strftime("%Y-%m-%d %H:%M")


async def send_telegram(text: str) -> bool:
    """Gửi Telegram Breakout Ops, fallback nếu thiếu token."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_OPS_GROUP_ID", DEFAULT_TELEGRAM_GROUP_ID)
    if not token:
        log.warning("Pban01 TELEGRAM_BOT_TOKEN chưa set, skip send")
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
                "Pban01 Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
