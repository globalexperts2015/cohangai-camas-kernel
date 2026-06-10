"""Telegram formatter cho E1 AI COO.

Format MD message cho Telegram bot push. Plain text style (Telegram bot
sendMessage không cần parse_mode=Markdown vì ký tự đặc biệt phải escape).

Output:
- format_daily_report:    báo cáo sáng 6am
- format_weekly_report:   báo cáo Chủ Nhật 8pm
- format_monthly_memo:    memo đầu tháng
- format_pipeline_bar:    ASCII bar cho pipeline stage

Style: tiếng Việt, câu sự kiện, KHÔNG em-dash `—`. Em hỏi prefix theo Anna
Voice DNA register `hang_webinar` (xưng "Hằng", thân thiện founder-to-founder).
"""
from __future__ import annotations

from typing import Any


SEPARATOR = "━" * 25


def _fmt_int(n: int | float) -> str:
    """Format số có dấu phẩy ngăn nghìn, fallback '?' nếu -1 (error)."""
    if n is None:
        return "?"
    try:
        ni = int(n)
        if ni < 0:
            return "?"
        return f"{ni:,}"
    except Exception:  # noqa: BLE001
        return str(n)


def _fmt_trend(current: int, baseline: int) -> str:
    """Tính delta % vs baseline, return ' (↑20% vs avg)' style."""
    if baseline <= 0:
        return ""
    if current < 0:
        return ""
    delta = (current - baseline) / baseline * 100
    arrow = "↑" if delta >= 0 else "↓"
    return f" ({arrow}{abs(delta):.0f}% vs avg 7d)"


def format_pipeline_bar(pipeline: dict[str, int]) -> str:
    """ASCII bar cho 5 stage canonical. 1 ô = 50 người."""
    stages = ["visitor", "lead", "considering", "decision", "buyer"]
    if not pipeline:
        return "(chưa có data pipeline)"
    lines: list[str] = []
    for stage in stages:
        cnt = int(pipeline.get(stage, 0) or 0)
        filled = min(10, cnt // 50)
        empty = max(0, 10 - filled)
        bar = "█" * filled + "░" * empty
        lines.append(f"{stage.title():13}{bar} {cnt}")
    return "\n".join(lines)


def _format_actions(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return "(chưa có action ưu tiên)"
    lines: list[str] = []
    for action in actions:
        priority = action.get("priority", "?")
        text = action.get("action", "?")
        lines.append(f"{priority}. {text}")
        detail = action.get("detail")
        if detail:
            lines.append(f"   {detail}")
        est = action.get("estimated_time_min")
        if est:
            lines.append(f"   ~{est} phút")
        lines.append("")
    return "\n".join(lines).rstrip()


def _format_red_flags(red_flags: list[dict[str, Any]]) -> str:
    if not red_flags:
        return ""
    lines: list[str] = [SEPARATOR, "CẢNH BÁO", SEPARATOR]
    for rf in red_flags:
        sev = rf.get("severity", "warning")
        emoji = "🚨" if sev == "critical" else "⚠️"
        metric = rf.get("metric", "?")
        current = rf.get("current", "?")
        target = rf.get("target", "?")
        rec = rf.get("recommendation", "")
        lines.append(f"{emoji} {metric}: {current} (target {target})")
        if rec:
            lines.append(f"   -> {rec}")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_daily_report(
    student_name: str,
    date_str: str,
    analysis: dict[str, Any],
    data: dict[str, Any],
) -> str:
    """Format MD-style message cho Telegram daily 6am push."""
    leads = data.get("leads_new") or {}
    leads_total = int(leads.get("total", 0) or 0)
    by_source = leads.get("by_source") or {}
    source_str = ""
    if by_source:
        source_str = " (" + ", ".join(
            [f"{k} {v}" for k, v in by_source.items()]
        ) + ")"

    rev = int(data.get("revenue_vnd", 0) or 0)
    rev_avg = int(data.get("revenue_avg_7d_vnd", 0) or 0)
    trend = _fmt_trend(rev, rev_avg)

    cs = data.get("content_planned_vs_done") or {}
    done = int(cs.get("done_today", 0) or 0)
    planned = int(cs.get("planned_today", 0) or 0)

    last_email = data.get("last_email_stats") or {}
    email_line = ""
    if last_email.get("sent"):
        opens = int(last_email.get("opens", 0) or 0)
        sent = int(last_email.get("sent", 0) or 0)
        rate = float(last_email.get("open_rate", 0) or 0) * 100
        email_line = (
            f"Email cuối:    {opens}/{sent} open ({rate:.0f}%)\n"
        )

    msg = (
        f"Sáng {date_str}. Báo cáo BreakoutOS của {student_name}.\n\n"
        f"{SEPARATOR}\n"
        f"SỨC KHỎE HỆ THỐNG\n"
        f"{SEPARATOR}\n"
        f"Lead mới 24h:   +{leads_total}{source_str}\n"
        f"Doanh thu 24h:  {_fmt_int(rev)} VND{trend}\n"
        f"Content:        {done}/{planned} đăng\n"
        f"{email_line}"
        f"\n{SEPARATOR}\n"
        f"3 VIỆC CẦN LÀM HÔM NAY\n"
        f"{SEPARATOR}\n"
        f"{_format_actions(analysis.get('top_3_actions', []))}\n"
    )

    red_flag_block = _format_red_flags(analysis.get("red_flags", []))
    if red_flag_block:
        msg += "\n" + red_flag_block + "\n"

    msg += (
        f"\n{SEPARATOR}\n"
        f"PIPELINE\n"
        f"{SEPARATOR}\n"
        f"{format_pipeline_bar(data.get('pipeline') or {})}\n"
    )

    return msg


def format_weekly_report(
    student_name: str,
    date_str: str,
    analysis: dict[str, Any],
    data: dict[str, Any],
    narrative: dict[str, Any] | None = None,
) -> str:
    """Báo cáo tuần Chủ Nhật 8pm. Có narrative LLM-synthesized."""
    leads_total = int((data.get("leads_new") or {}).get("total", 0) or 0)
    rev = int(data.get("revenue_vnd", 0) or 0)
    cs = data.get("content_planned_vs_done") or {}
    content_done = int(cs.get("done_today", 0) or 0)

    msg = (
        f"Tuần kết thúc {date_str}. Báo cáo BreakoutOS của {student_name}.\n\n"
        f"{SEPARATOR}\n"
        f"TỔNG QUAN 7 NGÀY\n"
        f"{SEPARATOR}\n"
        f"Leads:        +{leads_total}\n"
        f"Doanh thu:    {_fmt_int(rev)} VND\n"
        f"Content:      {content_done} bài đăng\n"
    )

    if narrative:
        headline = narrative.get("headline", "")
        if headline:
            msg += f"\nTrạng thái: {headline}\n"

        wins = narrative.get("wins") or []
        if wins:
            msg += f"\n{SEPARATOR}\nWINS\n{SEPARATOR}\n"
            for w in wins:
                msg += f"+ {w}\n"

        losses = narrative.get("losses") or []
        if losses:
            msg += f"\n{SEPARATOR}\nCẦN FIX\n{SEPARATOR}\n"
            for L in losses:
                msg += f"- {L}\n"

        root = narrative.get("root_cause")
        if root:
            msg += f"\nNguyên nhân gốc: {root}\n"

        focus = narrative.get("next_week_focus")
        if focus:
            msg += f"\nƯU TIÊN TUẦN SAU: {focus}\n"

    msg += (
        f"\n{SEPARATOR}\n"
        f"3 VIỆC TUẦN NÀY\n"
        f"{SEPARATOR}\n"
        f"{_format_actions(analysis.get('top_3_actions', []))}\n"
    )

    red_flag_block = _format_red_flags(analysis.get("red_flags", []))
    if red_flag_block:
        msg += "\n" + red_flag_block + "\n"

    msg += (
        f"\n{SEPARATOR}\n"
        f"PIPELINE\n"
        f"{SEPARATOR}\n"
        f"{format_pipeline_bar(data.get('pipeline') or {})}\n"
    )

    return msg


def format_monthly_memo(
    student_name: str,
    date_str: str,
    analysis: dict[str, Any],
    data: dict[str, Any],
    narrative: dict[str, Any] | None = None,
) -> str:
    """Memo tháng đầu tháng. Format narrative-heavy, ít number-heavy."""
    leads_total = int((data.get("leads_new") or {}).get("total", 0) or 0)
    rev = int(data.get("revenue_vnd", 0) or 0)
    pipe = data.get("pipeline") or {}
    buyer = int(pipe.get("buyer", 0) or 0)

    msg = (
        f"Memo tháng {date_str}. BreakoutOS của {student_name}.\n\n"
        f"{SEPARATOR}\n"
        f"TỔNG QUAN 30 NGÀY\n"
        f"{SEPARATOR}\n"
        f"Leads mới:    +{leads_total}\n"
        f"Doanh thu:    {_fmt_int(rev)} VND\n"
        f"Buyer total:  {buyer}\n"
    )

    if narrative:
        headline = narrative.get("headline", "")
        if headline:
            msg += f"\nTrạng thái tháng: {headline}\n"

        wins = narrative.get("wins") or []
        if wins:
            msg += f"\n{SEPARATOR}\n3 WINS THÁNG\n{SEPARATOR}\n"
            for w in wins:
                msg += f"+ {w}\n"

        losses = narrative.get("losses") or []
        if losses:
            msg += f"\n{SEPARATOR}\nCẦN FIX\n{SEPARATOR}\n"
            for L in losses:
                msg += f"- {L}\n"

        root = narrative.get("root_cause")
        if root:
            msg += f"\nPattern gốc: {root}\n"

        focus = narrative.get("next_week_focus")
        if focus:
            msg += f"\nƯU TIÊN THÁNG SAU: {focus}\n"

    msg += (
        f"\n{SEPARATOR}\n"
        f"3 VIỆC ĐẦU THÁNG\n"
        f"{SEPARATOR}\n"
        f"{_format_actions(analysis.get('top_3_actions', []))}\n"
    )

    red_flag_block = _format_red_flags(analysis.get("red_flags", []))
    if red_flag_block:
        msg += "\n" + red_flag_block + "\n"

    msg += (
        f"\n{SEPARATOR}\n"
        f"PIPELINE\n"
        f"{SEPARATOR}\n"
        f"{format_pipeline_bar(pipe)}\n"
    )

    return msg
