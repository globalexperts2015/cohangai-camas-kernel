"""Decision Engine cho E1 AI COO.

Rule-based phân tích metric → top 3 actions + red flags. Hybrid: rule engine
xử lý case deterministic, LLM (gọi từ agent.py) bổ sung narrative cho
weekly/monthly ambiguous case.

Mọi rule trả về action có priority 1-5 (1 = highest). Top 3 = sort + cắt 3.
Red flag chia 2 severity: critical (action ngay) vs warning (theo dõi).
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("camas.e1_ai_coo.decision_engine")


# Threshold canonical, tunable qua env nếu cần
THRESHOLD_HOT_TRUST = 50
THRESHOLD_EMAIL_OPEN_LOW = 0.15
THRESHOLD_EMAIL_OPEN_TARGET = 0.25
THRESHOLD_REVENUE_DROP_RATIO = 0.5
THRESHOLD_LEADS_MIN_DAILY = 3
THRESHOLD_PIPELINE_STUCK_RATIO = 0.8  # >80% stuck ở visitor → broken funnel


class DecisionEngine:
    """Rule-based engine. analyze_daily/weekly/monthly trả dict structure."""

    # ----------------------------------------------------------------
    # Daily
    # ----------------------------------------------------------------
    def analyze_daily(self, data: dict[str, Any]) -> dict[str, Any]:
        actions: list[dict[str, Any]] = []
        red_flags: list[dict[str, Any]] = []

        # Rule 1: Hot leads top 3 → action #1
        hot = data.get("hot_leads_top3") or []
        if hot:
            detail = ", ".join(
                [
                    f"{h.get('name', '?')} (T{h.get('trust_score', 0)})"
                    for h in hot[:3]
                ]
            )
            actions.append(
                {
                    "priority": 1,
                    "action": f"Follow up {len(hot)} khách Nóng (Trust ≥{THRESHOLD_HOT_TRUST})",
                    "detail": detail,
                    "estimated_time_min": 30,
                }
            )

        # Rule 2: Content planned vs done
        cs = data.get("content_planned_vs_done") or {}
        planned = int(cs.get("planned_today", 0) or 0)
        done = int(cs.get("done_today", 0) or 0)
        if planned > done:
            backlog = planned - done
            actions.append(
                {
                    "priority": 2,
                    "action": f"Đăng {backlog} content còn pending hôm nay",
                    "detail": f"{done}/{planned} đã xong",
                    "estimated_time_min": 15 * backlog,
                }
            )

        # Rule 3: No new leads 24h → critical
        leads_data = data.get("leads_new") or {}
        leads_total = int(leads_data.get("total", 0) or 0)
        if leads_total == 0:
            red_flags.append(
                {
                    "severity": "critical",
                    "metric": "no_new_leads",
                    "current": "0 lead 24h",
                    "target": f"≥{THRESHOLD_LEADS_MIN_DAILY} lead/ngày",
                    "recommendation": (
                        "Check Content Engine output, lead magnet form alive, "
                        "ads đang chạy. Nếu ads pause -> bật lại."
                    ),
                }
            )
            actions.append(
                {
                    "priority": 1,
                    "action": "Debug funnel zero-lead: check ads + form + landing",
                    "estimated_time_min": 30,
                }
            )

        # Rule 4: Email open rate low
        last_email = data.get("last_email_stats") or {}
        open_rate = float(last_email.get("open_rate", 0) or 0)
        sent = int(last_email.get("sent", 0) or 0)
        if sent > 0 and open_rate < THRESHOLD_EMAIL_OPEN_LOW:
            red_flags.append(
                {
                    "severity": "warning",
                    "metric": "email_open_rate",
                    "current": f"{open_rate * 100:.0f}%",
                    "target": f"≥{int(THRESHOLD_EMAIL_OPEN_TARGET * 100)}%",
                    "recommendation": (
                        "Đổi subject. Test 3 angle: story personal, "
                        "specific number, contrarian statement."
                    ),
                }
            )

        # Rule 5: Revenue trend drop
        rev = int(data.get("revenue_vnd", 0) or 0)
        rev_avg = int(data.get("revenue_avg_7d_vnd", 0) or 0)
        if rev_avg > 0 and rev >= 0 and rev < rev_avg * THRESHOLD_REVENUE_DROP_RATIO:
            red_flags.append(
                {
                    "severity": "warning",
                    "metric": "revenue_drop",
                    "current": f"{rev:,} VND",
                    "target": f"avg 7d {rev_avg:,} VND",
                    "recommendation": (
                        "Push 1 reactivation email cho khách Ấm + chạy 1 "
                        "reel about offer trong ngày."
                    ),
                }
            )

        # Rule 6: Pipeline stuck visitor
        pipe = data.get("pipeline") or {}
        total_pipe = sum(pipe.values()) if pipe else 0
        visitor_cnt = int(pipe.get("visitor", 0) or 0)
        if total_pipe > 50 and visitor_cnt / total_pipe > THRESHOLD_PIPELINE_STUCK_RATIO:
            red_flags.append(
                {
                    "severity": "warning",
                    "metric": "pipeline_stuck",
                    "current": f"{visitor_cnt}/{total_pipe} visitor",
                    "target": "≤80% visitor",
                    "recommendation": (
                        "Lead magnet conversion thấp. Test offer lead magnet "
                        "mới + thêm CTA khác mạnh hơn ở landing."
                    ),
                }
            )

        # Sort, top 3
        actions = sorted(actions, key=lambda x: x.get("priority", 99))[:3]
        # If no rule fired, add baseline action
        if not actions:
            actions.append(
                {
                    "priority": 1,
                    "action": "Hệ thống xanh. Review pipeline + chuẩn bị content tuần sau",
                    "estimated_time_min": 30,
                }
            )

        return {
            "top_3_actions": actions,
            "red_flags": red_flags,
            "summary": self._summarize(data, actions, red_flags, "daily"),
        }

    # ----------------------------------------------------------------
    # Weekly: aggregate trend
    # ----------------------------------------------------------------
    def analyze_weekly(self, data: dict[str, Any]) -> dict[str, Any]:
        actions: list[dict[str, Any]] = []
        red_flags: list[dict[str, Any]] = []

        leads_total = int((data.get("leads_new") or {}).get("total", 0) or 0)
        revenue = int(data.get("revenue_vnd", 0) or 0)
        content = data.get("content_planned_vs_done") or {}
        content_done = int(content.get("done_today", 0) or 0)

        # Rule W1: Weekly leads target = 21 (3/day)
        target_weekly_leads = THRESHOLD_LEADS_MIN_DAILY * 7
        if leads_total < target_weekly_leads:
            red_flags.append(
                {
                    "severity": "warning" if leads_total > 0 else "critical",
                    "metric": "weekly_leads_below_target",
                    "current": f"{leads_total} leads/tuần",
                    "target": f"≥{target_weekly_leads} leads/tuần",
                    "recommendation": (
                        "Tăng frequency Reel + bật lại Google Ads campaign + "
                        "deploy 1 lead magnet mới."
                    ),
                }
            )
            actions.append(
                {
                    "priority": 1,
                    "action": f"Boost lead gen: {target_weekly_leads - leads_total} leads cần fill",
                    "estimated_time_min": 120,
                }
            )

        # Rule W2: Content velocity
        if content_done < 7:
            actions.append(
                {
                    "priority": 2,
                    "action": (
                        f"Tăng tốc content: chỉ {content_done} bài tuần qua, "
                        f"target 7 bài/tuần"
                    ),
                    "estimated_time_min": 90,
                }
            )

        # Rule W3: Revenue baseline
        if revenue == 0:
            red_flags.append(
                {
                    "severity": "critical",
                    "metric": "zero_revenue_week",
                    "current": "0 VND tuần qua",
                    "target": "≥1 đơn/tuần",
                    "recommendation": (
                        "Chạy 1 offer flash sale + đặt outbound 5 hot leads "
                        "ưu tiên cao + reactivation email."
                    ),
                }
            )

        # Hot leads action vẫn priority 1
        hot = data.get("hot_leads_top3") or []
        if hot:
            actions.append(
                {
                    "priority": 1,
                    "action": f"Đóng deal {len(hot)} khách Nóng trong tuần này",
                    "detail": ", ".join([h.get("name", "?") for h in hot[:3]]),
                    "estimated_time_min": 90,
                }
            )

        actions = sorted(actions, key=lambda x: x.get("priority", 99))[:3]
        if not actions:
            actions.append(
                {
                    "priority": 1,
                    "action": "Tuần xanh. Plan 7 ngày tới + 1 experiment mới",
                    "estimated_time_min": 60,
                }
            )

        return {
            "top_3_actions": actions,
            "red_flags": red_flags,
            "summary": self._summarize(data, actions, red_flags, "weekly"),
        }

    # ----------------------------------------------------------------
    # Monthly: zoom out, strategic
    # ----------------------------------------------------------------
    def analyze_monthly(self, data: dict[str, Any]) -> dict[str, Any]:
        actions: list[dict[str, Any]] = []
        red_flags: list[dict[str, Any]] = []

        leads_total = int((data.get("leads_new") or {}).get("total", 0) or 0)
        revenue = int(data.get("revenue_vnd", 0) or 0)
        pipe = data.get("pipeline") or {}
        buyer_cnt = int(pipe.get("buyer", 0) or 0)
        visitor_cnt = int(pipe.get("visitor", 0) or 0)

        # Rule M1: Monthly leads target
        target_monthly_leads = THRESHOLD_LEADS_MIN_DAILY * 30
        if leads_total < target_monthly_leads:
            actions.append(
                {
                    "priority": 1,
                    "action": (
                        f"Strategic review lead gen: chỉ {leads_total}/"
                        f"{target_monthly_leads} target"
                    ),
                    "estimated_time_min": 180,
                }
            )

        # Rule M2: Conversion visitor → buyer
        if visitor_cnt > 100 and buyer_cnt / max(visitor_cnt, 1) < 0.02:
            red_flags.append(
                {
                    "severity": "warning",
                    "metric": "low_conversion_visitor_to_buyer",
                    "current": (
                        f"{buyer_cnt}/{visitor_cnt} ="
                        f" {buyer_cnt / max(visitor_cnt, 1) * 100:.1f}%"
                    ),
                    "target": "≥2%",
                    "recommendation": (
                        "Rebuild offer + value ladder. Audit toàn bộ funnel "
                        "step + chuyển landing copy theo Eagle Camp."
                    ),
                }
            )

        # Rule M3: Revenue zero month
        if revenue == 0:
            red_flags.append(
                {
                    "severity": "critical",
                    "metric": "zero_revenue_month",
                    "current": "0 VND tháng qua",
                    "target": "≥1 sale/tháng baseline",
                    "recommendation": (
                        "Pause non-revenue activities. Focus 100% week 1 "
                        "của tháng sau vào outbound 50 hot leads + 1 webinar."
                    ),
                }
            )

        actions = sorted(actions, key=lambda x: x.get("priority", 99))[:3]
        if not actions:
            actions.append(
                {
                    "priority": 1,
                    "action": "Tháng xanh. Plan tháng tới 1 mục tiêu chính + 3 OKR",
                    "estimated_time_min": 120,
                }
            )

        return {
            "top_3_actions": actions,
            "red_flags": red_flags,
            "summary": self._summarize(data, actions, red_flags, "monthly"),
        }

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------
    def _summarize(
        self,
        data: dict[str, Any],
        actions: list[dict[str, Any]],
        red_flags: list[dict[str, Any]],
        period: str,
    ) -> str:
        leads = int((data.get("leads_new") or {}).get("total", 0) or 0)
        rev = int(data.get("revenue_vnd", 0) or 0)
        crit = sum(1 for r in red_flags if r.get("severity") == "critical")
        warn = sum(1 for r in red_flags if r.get("severity") == "warning")
        return (
            f"e1_ai_coo period={period} leads={leads} revenue_vnd={rev} "
            f"actions={len(actions)} red_flags=crit{crit}/warn{warn}"
        )
