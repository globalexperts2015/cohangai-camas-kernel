"""Financial Modeler agent.

Apply CAC/LTV/Payback/Cashflow math cho Anna. Daily 6am Perth (sau BC1 Morning
Brief) emit canonical fact category=venture_state cho Pban10 Chiến lược RAG
retrieve khi propose budget.

Framework reference: solo-business-growth-system-v2 Overlay B Financial Model
(per sprint-13 section 6).

Trigger events:
- financial.daily_calc, run all venture
- financial.venture_audit, on-demand single venture

Autonomy L1. Escalate Telegram Breakout Ops if CRITICAL alert.
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

log = logging.getLogger("camas.financial_modeler")

EXPECTED_EVENTS = {"financial.daily_calc", "financial.venture_audit"}

DEFAULT_VENTURES = ["breakout", "speakout", "cohangai", "migration", "bmcorner", "dahafa"]

OPS_COST_MONTHLY_VND = {
    "breakout": 4_500_000,
    "speakout": 3_500_000,
    "cohangai": 2_500_000,
    "migration": 2_000_000,
    "bmcorner": 1_500_000,
    "dahafa": 1_500_000,
    "default": 2_000_000,
}

TELEGRAM_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP = "-1003813280155"


class FinancialModeler(BaseBC):
    """BC Financial Modeler, daily CAC/LTV/Payback/Runway audit 6 venture."""

    name = "financial_modeler"
    scope = "CAC/LTV/Payback/Cashflow per venture (Overlay B Financial Model)"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        self.telegram_chat_id = os.environ.get(
            "BREAKOUT_TELEGRAM_CHAT_ID", DEFAULT_TELEGRAM_GROUP
        ).strip()

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

        if event == "financial.daily_calc":
            return await self._handle_daily_calc(ctx)
        return await self._handle_venture_audit(ctx)

    async def _handle_daily_calc(self, ctx: ExecutionContext) -> AgentResult:
        """Daily 6am Perth, run all 6 venture."""
        ventures = ctx.payload.get("ventures", DEFAULT_VENTURES) if ctx.payload else DEFAULT_VENTURES
        results: list[dict] = []
        alerts: list[str] = []

        for venture in ventures:
            try:
                metrics = await self._calculate_per_venture(venture)
                results.append(metrics)

                alert = self._check_alert(metrics)
                if alert:
                    alerts.append(alert)
            except Exception as exc:  # noqa: BLE001
                log.warning("financial_modeler %s fail: %r", venture, exc)
                results.append({"venture": venture, "error": str(exc)})

        timestamp_iso = datetime.now(tz=timezone.utc).isoformat()
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        emitted_memories = []
        for r in results:
            if "error" in r:
                continue
            cac = r.get("cac_vnd", 0)
            ltv = r.get("ltv_vnd", 0)
            ratio = r.get("ltv_cac_ratio", 0)
            payback = r.get("payback_months", 0)
            runway = r.get("runway_months", 0)
            score = r.get("health_score", 0)
            venture = r["venture"]

            emitted_memories.append({
                "agent_name": self.name,
                "content_summary": (
                    f"Financial {venture} {date_str}: "
                    f"CAC {cac:,.0f}VND, LTV {ltv:,.0f}VND, "
                    f"LTV/CAC {ratio:.2f}x, Payback {payback:.1f}mo, "
                    f"Runway {runway:.1f}mo, Health {score}/10"
                ),
                "keywords": ["financial", "cac_ltv", venture, f"health-{score}"],
                "tags": [
                    "financial_model",
                    "stage_overlay_b",
                    "cac_ltv",
                    venture,
                    f"health-{score}",
                    date_str,
                ],
                "venture": venture,
                "category": "venture_state",
                "context": f"financial.daily_calc {date_str} venture={venture}",
            })

        # Telegram digest if any alert OR if any health_score < 6
        digest_needed = bool(alerts) or any(
            r.get("health_score", 10) < 6 for r in results if "error" not in r
        )
        telegram_sent = False
        if digest_needed and self.telegram_bot_token:
            try:
                await self._send_telegram_digest(results, alerts, date_str)
                telegram_sent = True
            except Exception as exc:  # noqa: BLE001
                log.warning("Telegram digest fail: %r", exc)

        critical_alert = any("CRITICAL" in a for a in alerts)
        summary = (
            f"financial daily {date_str}: {len(results)} venture, "
            f"{len(alerts)} alert, telegram={telegram_sent}"
        )

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload={
                "event": "financial.daily_calc",
                "date": date_str,
                "ventures": results,
                "alerts": alerts,
                "telegram_sent": telegram_sent,
            },
            emitted_memories=emitted_memories,
            escalation_required=critical_alert,
            escalation_reason=(
                f"Financial CRITICAL alerts: {'; '.join(alerts)[:200]}"
                if critical_alert
                else None
            ),
        )

    async def _handle_venture_audit(self, ctx: ExecutionContext) -> AgentResult:
        """On-demand single venture audit."""
        venture = (ctx.payload or {}).get("venture") or ctx.venture_context or "breakout"
        try:
            metrics = await self._calculate_per_venture(venture)
        except Exception as exc:  # noqa: BLE001
            return AgentResult(
                success=False,
                output_text=f"financial audit {venture} fail: {exc}",
                output_payload={"error": str(exc), "venture": venture},
            )

        alert = self._check_alert(metrics)
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

        emitted_memories = [{
            "agent_name": self.name,
            "content_summary": (
                f"Financial audit {venture} {date_str}: "
                f"CAC {metrics.get('cac_vnd', 0):,.0f}VND, "
                f"LTV {metrics.get('ltv_vnd', 0):,.0f}VND, "
                f"ratio {metrics.get('ltv_cac_ratio', 0):.2f}x, "
                f"health {metrics.get('health_score', 0)}/10"
            ),
            "keywords": ["financial", "audit", venture],
            "tags": ["financial_model", "audit", venture, date_str],
            "venture": venture,
            "category": "venture_state",
            "context": f"financial.venture_audit {date_str}",
        }]

        return AgentResult(
            success=True,
            output_text=f"audit {venture} health={metrics.get('health_score')}/10",
            output_payload={"event": "financial.venture_audit", "metrics": metrics, "alert": alert},
            emitted_memories=emitted_memories,
            escalation_required=bool(alert and "CRITICAL" in alert),
            escalation_reason=alert if alert and "CRITICAL" in alert else None,
        )

    async def _calculate_per_venture(self, venture: str) -> dict:
        """Calculate financial metrics for 1 venture."""
        ads_spend = await self._sum_ads_spend(venture, days=30)
        ops_cost = OPS_COST_MONTHLY_VND.get(venture, OPS_COST_MONTHLY_VND["default"])
        new_customers = await self._count_new_customers(venture, days=30)

        cac = (ads_spend + ops_cost) / max(new_customers, 1)

        avg_revenue = await self._avg_revenue_per_customer(venture, period_months=12)
        retention_months = await self._retention_months(venture)
        ltv = avg_revenue * retention_months

        ratio = ltv / cac if cac > 0 else 0
        payback_months = cac / (avg_revenue / 12) if avg_revenue > 0 else 0

        current_cash = await self._get_current_cash(venture)
        monthly_burn = ads_spend + ops_cost
        runway_months = current_cash / monthly_burn if monthly_burn > 0 else 0

        health_score = self._calc_health(ratio, payback_months, runway_months)

        return {
            "venture": venture,
            "cac_vnd": cac,
            "ltv_vnd": ltv,
            "ltv_cac_ratio": ratio,
            "payback_months": payback_months,
            "runway_months": runway_months,
            "ads_spend_30d_vnd": ads_spend,
            "ops_cost_monthly_vnd": ops_cost,
            "new_customers_30d": new_customers,
            "avg_revenue_per_customer_vnd": avg_revenue,
            "retention_months": retention_months,
            "current_cash_vnd": current_cash,
            "health_score": health_score,
        }

    async def _sum_ads_spend(self, venture: str, days: int = 30) -> float:
        """RAG retrieve Pban01 canonical for ads spend last N days."""
        if not self.memory.ready:
            return 0.0
        try:
            records = await self.memory.retrieve(
                query=f"ads spend {venture} last {days} days",
                categories=["venture_state"],
                venture=venture if venture != "all" else None,
                k=10,
                max_age_days=days,
            )
            total = 0.0
            for r in records:
                tags = r.tags or []
                if not any(t in tags for t in ["ads_pull", "fb_ads", "google_ads"]):
                    continue
                content = r.content or ""
                amount = self._extract_vnd_amount(content)
                if amount > 0:
                    total += amount
            return total
        except Exception as exc:  # noqa: BLE001
            log.warning("ads_spend %s fail: %r", venture, exc)
            return 0.0

    async def _count_new_customers(self, venture: str, days: int = 30) -> int:
        """RAG retrieve Pban08 / BC3 canonical for new customer count."""
        if not self.memory.ready:
            return 1
        try:
            records = await self.memory.retrieve(
                query=f"new customer {venture} last {days} days payment",
                categories=["venture_state"],
                venture=venture if venture != "all" else None,
                k=10,
                max_age_days=days,
            )
            count = 0
            for r in records:
                content = (r.content or "").lower()
                if "new customer" in content or "purchase" in content or "đăng ký" in content:
                    extracted = self._extract_count(content)
                    if extracted > count:
                        count = extracted
            return max(count, 1)
        except Exception as exc:  # noqa: BLE001
            log.warning("count_customers %s fail: %r", venture, exc)
            return 1

    async def _avg_revenue_per_customer(self, venture: str, period_months: int = 12) -> float:
        """RAG retrieve pricing canonical fact + estimate average."""
        if not self.memory.ready:
            return self._default_avg_revenue(venture)
        try:
            records = await self.memory.retrieve(
                query=f"pricing tier {venture} customer avg",
                categories=["pricing"],
                venture=venture if venture != "all" else None,
                k=10,
            )
            prices: list[float] = []
            for r in records:
                amount = self._extract_vnd_amount(r.content or "")
                if 100_000 < amount < 100_000_000:
                    prices.append(amount)
            if not prices:
                return self._default_avg_revenue(venture)
            prices.sort()
            mid = len(prices) // 2
            if len(prices) % 2 == 1:
                return float(prices[mid])
            return (prices[mid - 1] + prices[mid]) / 2
        except Exception as exc:  # noqa: BLE001
            log.warning("avg_revenue %s fail: %r", venture, exc)
            return self._default_avg_revenue(venture)

    def _default_avg_revenue(self, venture: str) -> float:
        defaults = {
            "breakout": 5_000_000,
            "speakout": 6_000_000,
            "cohangai": 1_500_000,
            "migration": 8_000_000,
            "bmcorner": 200_000,
            "dahafa": 1_000_000,
        }
        return defaults.get(venture, 3_000_000)

    async def _retention_months(self, venture: str) -> float:
        """Retention estimate per venture (cohort analysis simplified)."""
        defaults = {
            "breakout": 18.0,
            "speakout": 24.0,
            "cohangai": 12.0,
            "migration": 6.0,
            "bmcorner": 24.0,
            "dahafa": 12.0,
        }
        return defaults.get(venture, 12.0)

    async def _get_current_cash(self, venture: str) -> float:
        """Current cash estimate (placeholder, real impl query bank API)."""
        defaults = {
            "breakout": 100_000_000,
            "speakout": 200_000_000,
            "cohangai": 50_000_000,
            "migration": 80_000_000,
            "bmcorner": 60_000_000,
            "dahafa": 40_000_000,
        }
        return defaults.get(venture, 50_000_000)

    @staticmethod
    def _calc_health(ratio: float, payback: float, runway: float) -> int:
        score = 0
        if ratio >= 3:
            score += 4
        elif ratio >= 2:
            score += 3
        elif ratio >= 1.5:
            score += 2
        elif ratio >= 1:
            score += 1

        if payback <= 12:
            score += 3
        elif payback <= 18:
            score += 2
        elif payback <= 24:
            score += 1

        if runway >= 6:
            score += 3
        elif runway >= 3:
            score += 2
        elif runway >= 1:
            score += 1

        return min(score, 10)

    @staticmethod
    def _check_alert(metrics: dict) -> Optional[str]:
        ratio = metrics.get("ltv_cac_ratio", 0)
        payback = metrics.get("payback_months", 0)
        runway = metrics.get("runway_months", 0)
        venture = metrics.get("venture", "?")

        alerts: list[str] = []
        if ratio < 1.5:
            alerts.append(
                f"CRITICAL {venture}: LTV/CAC {ratio:.2f}x unprofitable acquisition"
            )
        if payback > 18:
            alerts.append(
                f"WARNING {venture}: payback {payback:.1f}mo too slow recoup"
            )
        if 0 < runway < 3:
            alerts.append(
                f"CRITICAL {venture}: cash runway {runway:.1f}mo emergency"
            )
        if not alerts:
            return None
        return " | ".join(alerts)

    @staticmethod
    def _extract_vnd_amount(content: str) -> float:
        """Extract VND amount from natural language fact."""
        import re

        cleaned = content.replace(",", "")
        patterns = [
            r"([\d.]+)\s*tr(?:iệu)?\s*VND",
            r"([\d.]+)\s*tr(?:iệu)?\s*/?\s*tháng",
            r"([\d]+)\s*[,.]?[\d]*\s*VND",
            r"([\d]+)[,.]?\d*\s*đồng",
        ]
        for pattern in patterns:
            matches = re.findall(pattern, cleaned, flags=re.IGNORECASE)
            if matches:
                try:
                    val = float(matches[0])
                    if "tr" in pattern or "triệu" in pattern.lower():
                        return val * 1_000_000
                    return val
                except ValueError:
                    continue
        return 0.0

    @staticmethod
    def _extract_count(content: str) -> int:
        """Extract integer count from natural language."""
        import re

        matches = re.findall(r"\b(\d{1,5})\b", content)
        for m in matches:
            try:
                val = int(m)
                if 1 <= val <= 10000:
                    return val
            except ValueError:
                continue
        return 0

    async def _send_telegram_digest(
        self, results: list[dict], alerts: list[str], date_str: str
    ) -> None:
        lines = [f"💰 Financial Audit {date_str}"]
        for r in results:
            if "error" in r:
                lines.append(f"{r['venture']}: ERROR {r['error'][:60]}")
                continue
            venture = r["venture"]
            cac = r.get("cac_vnd", 0)
            ltv = r.get("ltv_vnd", 0)
            ratio = r.get("ltv_cac_ratio", 0)
            score = r.get("health_score", 0)
            status = "✅" if score >= 7 else "⚠️" if score >= 4 else "🚨"
            lines.append(
                f"{venture}: CAC {cac/1e6:.1f}M LTV {ltv/1e6:.1f}M "
                f"ratio {ratio:.1f}x health {score}/10 {status}"
            )

        if alerts:
            lines.append("")
            for a in alerts:
                lines.append(f"🚨 {a}")

        text = "\n".join(lines)[:4000]

        async with httpx.AsyncClient(timeout=TELEGRAM_TIMEOUT) as client:
            await client.post(
                f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage",
                data={"chat_id": self.telegram_chat_id, "text": text},
            )
