"""BC8 Night Audit agent.

Audit toàn diện 24h cuối, 6 ventures + AIOS infra, chạy 11pm Perth daily.
Gửi email tổng hợp tới Anna `hang.dao.bbb@gmail.com` (sáng sau Anna đọc với
cà phê) + Telegram Breakout Ops fallback.

Single trigger event:
- `audit.nightly` (cron 11pm AWST Perth = 15:00 UTC)

Per venture (Breakout, Speakout, BMCorner, DAHAFA, Migration, Đất Gia Nghĩa):
- Revenue 24h từ events.payment.completed (sum amount_vnd) per venture tag
- New leads/customers count từ agent_memory + transactions
- Refund requests count
- Compliance violations (BC9 BLOCK count 24h)
- Voice rejects (BC2 REJECT count 24h)
- Customer complaints (BC3 feedback_type='complaint' count)

Cross venture:
- Total agent_memory growth 24h
- Top 3 most-triggered agents 24h
- L3 escalation pending
- Service health (BC5 critical alert)

LLM: Claude Opus 4.7 cho recommendation (chạy 1 lần/ngày, depth > tốc độ).

Email send qua SMTP (Gmail App Password trong cohangai/.env) hoặc Resend
fallback. Nếu cả 2 thiếu, log skip + vẫn gửi Telegram.

BC8_DRY_RUN=1: skip email + Telegram, chỉ print report.

Style: tiếng Việt cho report + email + docstring. ZERO em-dash `—`.
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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

log = logging.getLogger("camas.bc8_night_audit")

DEFAULT_LLM_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 800
DEFAULT_LLM_TIMEOUT = 120.0
DEFAULT_HTTP_TIMEOUT = 30.0
DEFAULT_TELEGRAM_GROUP_ID = "-1003813280155"  # Breakout Ops
DEFAULT_ANNA_EMAIL = "hang.dao.bbb@gmail.com"

# 6 ventures Anna đang vận hành (memory project-aios-build-2026 + vault CLAUDE.md)
VENTURES: list[str] = [
    "breakout",
    "speakout",
    "bmcorner",
    "dahafa",
    "migration",
    "dat_gia_nghia",
]

# Tỷ giá VND -> AUD xấp xỉ (1 AUD ≈ 16,500 VND tháng 6/2026, chỉ dùng hiển thị
# tham khảo, không claim chính xác financial)
VND_PER_AUD = 16500


class BC8NightAudit(BaseBC):
    """BC8 Night Audit, comprehensive overnight audit 6 ventures.

    Pipeline run() (event=audit.nightly):
        1. Query Postgres aggregate 24h: revenue per venture, leads, alerts
        2. Cross-venture metric: memory growth, top agents, escalation
        3. LLM Opus 4.7 sinh 2-3 đề xuất tomorrow tiếng Việt
        4. Build report markdown (1500+ chars OK vì email channel)
        5. Send email Anna + Telegram backup (skip nếu DRY_RUN)
        6. Emit memory entry audit.nightly.sent
    """

    name = "bc8_night_audit"
    scope = "Comprehensive overnight audit 6 ventures, email Anna 11pm Perth"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.EMAIL_ANNA
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

        if event == "audit.nightly":
            return await self._handle_audit(ctx)

        return AgentResult(
            success=False,
            output_text="BC8 không xử lý event này",
            output_payload={
                "trigger_event": event,
                "supported": ["audit.nightly"],
            },
        )

    async def _handle_audit(self, ctx: ExecutionContext) -> AgentResult:
        """Run 1 audit cycle, build report, gửi email + Telegram."""
        # Date label giờ Perth AWST (UTC+8) vì cron chạy 11pm Perth
        now_perth = datetime.now(tz=timezone.utc) + timedelta(hours=8)
        date_perth = now_perth.strftime("%Y-%m-%d")

        # 1. Stats
        stats = await self._collect_stats()

        # 2. LLM recommendation
        recommendation = await self._llm_recommendation(stats, date_perth)

        # 3. Build report
        report = self._build_report(
            date_str=date_perth,
            stats=stats,
            recommendation=recommendation,
        )

        # 4. Send email + Telegram
        dry_run = os.getenv("BC8_DRY_RUN", "") == "1"
        email_sent = False
        telegram_sent = False
        if dry_run:
            log.info("BC8 DRY_RUN, skip email + Telegram, in-memory report only")
            email_sent = True
            telegram_sent = True
        else:
            email_to = os.getenv("ALERT_EMAIL", DEFAULT_ANNA_EMAIL)
            subject = self._build_subject(stats=stats, date_str=date_perth)
            try:
                email_sent = await send_email(
                    to_address=email_to,
                    subject=subject,
                    body_text=report,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("BC8 email send fail: %r", exc)
                email_sent = False

            # Telegram DISABLED 2026-06-11 (Anna chốt im lặng cho daily audit, chỉ giữ email)
            # Anna receive nightly report via email Brevo, KHÔNG cần spam Telegram.
            telegram_sent = False
            # Original code preserved nếu cần re-enable:
            # telegram_body = report[:3700] + "...(xem email)" if len(report) > 3800 else report
            # telegram_sent = await send_telegram(telegram_body)

        # 5. Emit memory
        alert_count = stats.get("alerts_count", 0)
        revenue_total = stats.get("revenue_total_vnd", 0)
        memory_entry = {
            "agent_name": self.name,
            "content_summary": (
                f"audit {date_perth} revenue={revenue_total} alerts={alert_count}"
            ),
            "keywords": ["audit", "nightly", date_perth],
            "tags": ["audit", "nightly", date_perth],
            "venture": "all",
            "context": (
                f"audit.nightly {date_perth} "
                f"email_sent={email_sent} telegram_sent={telegram_sent}"
            ),
        }

        return AgentResult(
            success=True,
            output_text=report,
            output_payload={
                "date": date_perth,
                "stats": stats,
                "email_sent": email_sent,
                "telegram_sent": telegram_sent,
                "dry_run": dry_run,
                "recommendation": recommendation,
            },
            emitted_memories=[memory_entry],
        )

    async def _collect_stats(self) -> dict[str, Any]:
        """Query Postgres aggregate 24h.

        Reuse MemoryLayer pool, fail-soft graceful nếu pool/asyncpg lỗi.
        Mọi metric default 0 nếu query fail (không bịa số, không silent skip).
        """
        stats: dict[str, Any] = {
            "per_venture": {v: self._empty_venture_stats() for v in VENTURES},
            "revenue_total_vnd": 0,
            "new_customers_total": 0,
            "memory_created_24h": 0,
            "top_agents": [],
            "l3_escalation_pending": 0,
            "bc5_last_critical": None,
            "alerts_count": 0,
            "error": None,
        }

        if not self.memory.dsn:
            stats["error"] = "DATABASE_URL chưa set"
            return stats

        try:
            pool = await self.memory._get_pool()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            log.warning("BC8 get_pool fail: %r", exc)
            stats["error"] = f"pool init fail: {exc}"
            return stats

        try:
            async with pool.acquire() as conn:
                # Query 1: Revenue per venture từ events.payment.completed 24h
                # Schema events: payload JSONB chứa amount_vnd, venture column
                rows = await conn.fetch(
                    """
                    SELECT venture,
                           COUNT(*)::int AS payment_count,
                           COALESCE(
                               SUM(
                                   CASE
                                       WHEN payload ? 'amount_vnd'
                                       THEN (payload->>'amount_vnd')::bigint
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
                      AND received_at > now() - interval '24 hours'
                    GROUP BY venture
                    """
                )
                for r in rows:
                    venture = (r["venture"] or "other").lower()
                    if venture in stats["per_venture"]:
                        stats["per_venture"][venture]["revenue_vnd"] = int(
                            r["revenue_vnd"] or 0
                        )
                        stats["per_venture"][venture]["payment_count"] = int(
                            r["payment_count"] or 0
                        )
                    stats["revenue_total_vnd"] += int(r["revenue_vnd"] or 0)

                # Query 2: New leads/customers per venture (BC5 + GHL contact events)
                rows = await conn.fetch(
                    """
                    SELECT venture, COUNT(*)::int AS cnt
                    FROM public.events
                    WHERE event_type IN (
                        'ghl.contact.created',
                        'lead.registered',
                        'wk.register'
                    )
                      AND received_at > now() - interval '24 hours'
                    GROUP BY venture
                    """
                )
                for r in rows:
                    venture = (r["venture"] or "other").lower()
                    cnt = int(r["cnt"] or 0)
                    if venture in stats["per_venture"]:
                        stats["per_venture"][venture]["new_leads"] = cnt
                    stats["new_customers_total"] += cnt

                # Query 3: Refund requests per venture
                rows = await conn.fetch(
                    """
                    SELECT venture, COUNT(*)::int AS cnt
                    FROM public.events
                    WHERE event_type IN (
                        'refund.requested',
                        'sepay.refund',
                        'payment.refunded'
                    )
                      AND received_at > now() - interval '24 hours'
                    GROUP BY venture
                    """
                )
                for r in rows:
                    venture = (r["venture"] or "other").lower()
                    if venture in stats["per_venture"]:
                        stats["per_venture"][venture]["refund_count"] = int(
                            r["cnt"] or 0
                        )

                # Query 4: BC9 BLOCK count per venture 24h
                rows = await conn.fetch(
                    """
                    SELECT venture, COUNT(*)::int AS cnt
                    FROM public.agent_memory
                    WHERE agent_name = 'bc9_compliance_officer'
                      AND 'BLOCK' = ANY(tags)
                      AND created_at > now() - interval '24 hours'
                    GROUP BY venture
                    """
                )
                for r in rows:
                    venture = (r["venture"] or "other").lower()
                    if venture in stats["per_venture"]:
                        stats["per_venture"][venture]["compliance_blocks"] = int(
                            r["cnt"] or 0
                        )

                # Query 5: BC2 REJECT count per venture 24h
                rows = await conn.fetch(
                    """
                    SELECT venture, COUNT(*)::int AS cnt
                    FROM public.agent_memory
                    WHERE agent_name = 'bc2_voice_guardian'
                      AND 'REJECT' = ANY(tags)
                      AND created_at > now() - interval '24 hours'
                    GROUP BY venture
                    """
                )
                for r in rows:
                    venture = (r["venture"] or "other").lower()
                    if venture in stats["per_venture"]:
                        stats["per_venture"][venture]["voice_rejects"] = int(
                            r["cnt"] or 0
                        )

                # Query 6: BC3 complaint count 24h (gắn về Breakout default vì
                # customer_feedback chưa có column venture trong migration 003)
                try:
                    row = await conn.fetchrow(
                        """
                        SELECT COUNT(*)::int AS cnt
                        FROM public.customer_feedback
                        WHERE feedback_type = 'complaint'
                          AND created_at > now() - interval '24 hours'
                        """
                    )
                    if row:
                        cnt = int(row["cnt"] or 0)
                        # Default route về Breakout vì BC3 chủ yếu serve Breakout
                        stats["per_venture"]["breakout"]["complaints"] = cnt
                except Exception as exc:  # noqa: BLE001
                    log.debug("BC8 complaint count fail-soft: %r", exc)

                # Query 7: Total memory created 24h
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(*)::int AS cnt
                    FROM public.agent_memory
                    WHERE created_at > now() - interval '24 hours'
                    """
                )
                stats["memory_created_24h"] = int(row["cnt"] or 0) if row else 0

                # Query 8: Top 3 most-triggered agents 24h
                rows = await conn.fetch(
                    """
                    SELECT agent_name, COUNT(*)::int AS cnt
                    FROM public.agent_memory
                    WHERE created_at > now() - interval '24 hours'
                    GROUP BY agent_name
                    ORDER BY cnt DESC
                    LIMIT 3
                    """
                )
                stats["top_agents"] = [
                    {"agent": r["agent_name"], "count": int(r["cnt"])}
                    for r in rows
                ]

                # Query 9: L3 escalation pending (any memory tagged L3 chưa resolve)
                # Heuristic: agent_memory với tag 'L3' hoặc 'escalation' last 7 days
                row = await conn.fetchrow(
                    """
                    SELECT COUNT(*)::int AS cnt
                    FROM public.agent_memory
                    WHERE ('L3' = ANY(tags) OR 'escalation' = ANY(tags))
                      AND created_at > now() - interval '7 days'
                    """
                )
                stats["l3_escalation_pending"] = (
                    int(row["cnt"] or 0) if row else 0
                )

                # Query 10: BC5 last critical alert
                row = await conn.fetchrow(
                    """
                    SELECT content, created_at
                    FROM public.agent_memory
                    WHERE agent_name = 'bc5_cdp_monitor'
                      AND ('CRITICAL' = ANY(tags) OR 'critical' = ANY(tags))
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                if row:
                    stats["bc5_last_critical"] = {
                        "content": (row["content"] or "")[:200],
                        "at": (
                            row["created_at"].isoformat()
                            if row["created_at"]
                            else None
                        ),
                    }
        except Exception as exc:  # noqa: BLE001
            log.warning("BC8 stats SQL fail: %r", exc)
            stats["error"] = f"SQL fail: {exc}"

        # Compute alerts_count = tổng compliance + voice rejects + complaints +
        # refund + L3 pending
        alerts = stats["l3_escalation_pending"]
        for v_stats in stats["per_venture"].values():
            alerts += v_stats["compliance_blocks"]
            alerts += v_stats["voice_rejects"]
            alerts += v_stats["complaints"]
            alerts += v_stats["refund_count"]
        stats["alerts_count"] = alerts

        return stats

    @staticmethod
    def _empty_venture_stats() -> dict[str, int]:
        return {
            "revenue_vnd": 0,
            "payment_count": 0,
            "new_leads": 0,
            "refund_count": 0,
            "compliance_blocks": 0,
            "voice_rejects": 0,
            "complaints": 0,
        }

    async def _llm_recommendation(
        self,
        stats: dict[str, Any],
        date_str: str,
    ) -> str:
        """Call Opus 4.7 sinh 2-3 đề xuất tomorrow tiếng Việt."""
        if not self.llm.ready:
            return "LLM chưa init, không có đề xuất."

        compact = {
            "date": date_str,
            "revenue_total_vnd": stats.get("revenue_total_vnd", 0),
            "new_customers_total": stats.get("new_customers_total", 0),
            "memory_created_24h": stats.get("memory_created_24h", 0),
            "top_agents": stats.get("top_agents", []),
            "l3_escalation_pending": stats.get("l3_escalation_pending", 0),
            "alerts_count": stats.get("alerts_count", 0),
            "per_venture": stats.get("per_venture", {}),
        }
        prompt = (
            "You are Anna's strategic operations advisor reading her nightly "
            "audit. Suggest 2-3 specific, actionable recommendations for "
            "tomorrow based on these stats. Output in Vietnamese, 1-2 lines "
            "per recommendation. No preamble. No em-dash.\n\n"
            f"Stats: {json.dumps(compact, ensure_ascii=False)}"
        )

        try:
            resp = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                timeout=DEFAULT_LLM_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC8 LLM call fail: %r", exc)
            return "LLM call fail, không có đề xuất."

        text_parts: list[str] = []
        for block in resp.content or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", ""))
        text = "".join(text_parts).strip()
        return text or "Không có đề xuất."

    def _build_subject(self, *, stats: dict[str, Any], date_str: str) -> str:
        """Email subject: [Night Audit YYYY-MM-DD] Revenue ₫X.X | Y action items."""
        revenue_vnd = stats.get("revenue_total_vnd", 0)
        revenue_label = self._fmt_vnd_short(revenue_vnd)
        alerts = stats.get("alerts_count", 0)
        return (
            f"[Night Audit {date_str}] Revenue {revenue_label} | "
            f"{alerts} alerts"
        )

    def _build_report(
        self,
        *,
        date_str: str,
        stats: dict[str, Any],
        recommendation: str,
    ) -> str:
        """Render report tiếng Việt cho email + Telegram.

        Format dài 1500+ chars OK vì email channel chính.
        """
        revenue_vnd = stats.get("revenue_total_vnd", 0)
        revenue_aud = revenue_vnd / VND_PER_AUD if revenue_vnd else 0
        new_customers = stats.get("new_customers_total", 0)
        memory_created = stats.get("memory_created_24h", 0)
        alerts_count = stats.get("alerts_count", 0)

        lines: list[str] = [
            f"🌙 Night Audit Report {date_str}",
            "",
            "📊 Tổng quan 24h:",
            f"- Revenue total: {self._fmt_vnd(revenue_vnd)} VND "
            f"(~{revenue_aud:,.0f} AUD)",
            f"- New customers: {new_customers}",
            f"- Memory created: {memory_created}",
            f"- L3 escalation pending: {stats.get('l3_escalation_pending', 0)}",
            "",
            "📈 Per venture:",
        ]

        for venture in VENTURES:
            v = stats["per_venture"].get(venture, self._empty_venture_stats())
            label = self._venture_label(venture)
            rev_label = self._fmt_vnd(v["revenue_vnd"])
            lines.append(
                f"[{label}] Revenue: {rev_label} VND ({v['payment_count']} payments) | "
                f"Leads: {v['new_leads']} | Refund: {v['refund_count']} | "
                f"Compliance flags: {v['compliance_blocks']} | "
                f"Voice rejects: {v['voice_rejects']} | "
                f"Complaints: {v['complaints']}"
            )

        # Cross-venture stats
        lines += ["", "🤖 Top 3 agents 24h:"]
        top_agents = stats.get("top_agents", [])
        if top_agents:
            for i, a in enumerate(top_agents, 1):
                lines.append(f"{i}. {a['agent']}: {a['count']} actions")
        else:
            lines.append("- Không có activity")

        # Alerts cần Anna xem sáng
        lines += ["", "⚠️ Alerts cần Anna xem sáng:"]
        alert_lines: list[str] = []
        for venture in VENTURES:
            v = stats["per_venture"].get(venture, {})
            v_label = self._venture_label(venture)
            if v.get("compliance_blocks", 0) > 0:
                alert_lines.append(
                    f"- [{v_label}] {v['compliance_blocks']} compliance BLOCK, "
                    "rà BC9 queue"
                )
            if v.get("voice_rejects", 0) > 0:
                alert_lines.append(
                    f"- [{v_label}] {v['voice_rejects']} voice REJECT, "
                    "kiểm tra root cause BC2"
                )
            if v.get("complaints", 0) > 0:
                alert_lines.append(
                    f"- [{v_label}] {v['complaints']} complaint, xem BC3 dashboard"
                )
            if v.get("refund_count", 0) > 0:
                alert_lines.append(
                    f"- [{v_label}] {v['refund_count']} refund request, xử lý K2 hoàn tiền"
                )
        if stats.get("l3_escalation_pending", 0) > 0:
            alert_lines.append(
                f"- {stats['l3_escalation_pending']} L3 escalation pending 7 ngày qua"
            )
        if stats.get("bc5_last_critical"):
            crit = stats["bc5_last_critical"]
            alert_lines.append(
                f"- BC5 CDP last CRITICAL @ {crit.get('at', 'unknown')}: "
                f"{crit.get('content', '')[:120]}"
            )
        if stats.get("error"):
            alert_lines.append(f"- DB error: {stats['error']}")
        if not alert_lines:
            alert_lines.append("- Không có, tất cả ổn")
        lines.extend(alert_lines)

        # Hệ thống healthy
        lines += ["", "✅ Hệ thống healthy:"]
        healthy_lines: list[str] = []
        if memory_created > 0:
            healthy_lines.append(
                f"- Memory layer hoạt động ({memory_created} record 24h)"
            )
        if top_agents:
            healthy_lines.append(
                f"- {len(top_agents)} agent có activity gần nhất"
            )
        if revenue_vnd > 0:
            healthy_lines.append(
                f"- Payment pipeline thông ({self._fmt_vnd(revenue_vnd)} VND 24h)"
            )
        if not stats.get("error"):
            healthy_lines.append("- DB pool + asyncpg ổn định")
        if not healthy_lines:
            healthy_lines.append("- (chưa có dữ liệu healthy signal)")
        lines.extend(healthy_lines)

        # Recommended tomorrow
        lines += [
            "",
            "🎯 Đề xuất tomorrow (Opus 4.7):",
            recommendation or "Không có đề xuất.",
            "",
            f"_Generated by BC8 Night Audit, alerts_count={alerts_count}_",
        ]

        return "\n".join(lines)

    @staticmethod
    def _venture_label(venture: str) -> str:
        """Map slug -> tên hiển thị tiếng Việt."""
        labels = {
            "breakout": "Breakout",
            "speakout": "Speakout",
            "bmcorner": "BMCorner",
            "dahafa": "DAHAFA",
            "migration": "Migration",
            "dat_gia_nghia": "Đất Gia Nghĩa",
        }
        return labels.get(venture, venture)

    @staticmethod
    def _fmt_vnd(amount: int) -> str:
        """Format VND có dấu phẩy ngăn cách hàng nghìn."""
        try:
            return f"{int(amount):,}"
        except (TypeError, ValueError):
            return "0"

    @staticmethod
    def _fmt_vnd_short(amount: int) -> str:
        """Format ngắn cho subject line, vd ₫1.5M / ₫120K."""
        try:
            n = int(amount)
        except (TypeError, ValueError):
            return "₫0"
        if n >= 1_000_000_000:
            return f"₫{n / 1_000_000_000:.1f}B"
        if n >= 1_000_000:
            return f"₫{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"₫{n / 1_000:.0f}K"
        return f"₫{n}"


# ============================================================
# Email send helper
# ============================================================
async def send_email(
    *,
    to_address: str,
    subject: str,
    body_text: str,
) -> bool:
    """Gửi email Anna qua SMTP (Gmail App Password) hoặc Resend.

    Env vars (try theo thứ tự):
        1. SMTP_HOST + SMTP_USER + SMTP_PASS (generic SMTP)
        2. GMAIL_USER + GMAIL_APP_PASSWORD (Gmail SMTP qua smtp.gmail.com:587)
        3. RESEND_API_KEY (HTTPS POST tới Resend API)

    Return True nếu gửi OK, False nếu thiếu config hoặc fail.
    """
    # Generic SMTP
    smtp_host = os.getenv("SMTP_HOST")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    if smtp_host and smtp_user and smtp_pass:
        return _send_smtp(
            host=smtp_host,
            port=int(os.getenv("SMTP_PORT", "587")),
            user=smtp_user,
            password=smtp_pass,
            from_address=os.getenv("SMTP_FROM", smtp_user),
            to_address=to_address,
            subject=subject,
            body_text=body_text,
        )

    # Gmail App Password
    gmail_user = os.getenv("GMAIL_USER")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD")
    if gmail_user and gmail_pass:
        return _send_smtp(
            host="smtp.gmail.com",
            port=587,
            user=gmail_user,
            password=gmail_pass,
            from_address=gmail_user,
            to_address=to_address,
            subject=subject,
            body_text=body_text,
        )

    # Resend HTTPS
    resend_key = os.getenv("RESEND_API_KEY")
    if resend_key:
        return await _send_resend(
            api_key=resend_key,
            from_address=os.getenv("RESEND_FROM", "audit@daothihang.com"),
            to_address=to_address,
            subject=subject,
            body_text=body_text,
        )

    log.warning(
        "BC8 email skip, thiếu SMTP/Gmail/Resend config trong env"
    )
    return False


def _send_smtp(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    from_address: str,
    to_address: str,
    subject: str,
    body_text: str,
) -> bool:
    """SMTP send qua smtplib (sync nhưng nhanh, chấp nhận trong async)."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.sendmail(from_address, [to_address], msg.as_string())
        log.info("BC8 email sent qua SMTP %s tới %s", host, to_address)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("BC8 SMTP send fail: %r", exc)
        return False


async def _send_resend(
    *,
    api_key: str,
    from_address: str,
    to_address: str,
    subject: str,
    body_text: str,
) -> bool:
    """Resend HTTPS API send."""
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "from": from_address,
        "to": [to_address],
        "subject": subject,
        "text": body_text,
    }
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code in (200, 202):
                log.info("BC8 email sent qua Resend tới %s", to_address)
                return True
            log.warning(
                "BC8 Resend non-2xx: %s %s", resp.status_code, resp.text[:200]
            )
            return False
    except Exception as exc:  # noqa: BLE001
        log.warning("BC8 Resend send fail: %r", exc)
        return False


# ============================================================
# Telegram backup channel
# ============================================================
async def send_telegram(text: str) -> bool:
    """Gửi message tới Telegram group Breakout Ops làm backup channel.

    Env vars:
        TELEGRAM_BOT_TOKEN: bot token
        TELEGRAM_OPS_GROUP_ID: chat id (default -1003813280155)

    Return True nếu HTTP 200, False nếu thiếu token hoặc non-200.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_OPS_GROUP_ID", DEFAULT_TELEGRAM_GROUP_ID)
    if not token:
        log.warning("BC8 TELEGRAM_BOT_TOKEN chưa set, skip backup")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT) as client:
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
                "BC8 Telegram non-200: %s %s",
                resp.status_code,
                resp.text[:200],
            )
        return resp.status_code == 200
