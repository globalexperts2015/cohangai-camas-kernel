"""Deterministic Financial Feasibility Calculator.

Chain: profit target → AOV → orders → customers → leads → traffic → ad budget.
Pure Python, no LLM. Outputs structured numbers + viability flags.
"""
from __future__ import annotations

from typing import Any


def calculate_financial_feasibility(
    profit_target_vnd: int,
    aov_vnd: int,  # Average Order Value
    margin_pct: float,  # 0-100, gross margin %
    conversion_rate_pct: float = 2.0,  # lead → customer conversion
    optin_rate_pct: float = 20.0,  # traffic → lead opt-in
    repeat_purchase_ratio: float = 1.0,  # orders per customer
    cac_target_vnd: int = 0,  # Customer Acquisition Cost target, 0 = auto
    months: int = 12,
) -> dict[str, Any]:
    """Compute full financial feasibility chain.

    Returns dict with all intermediate numbers + viability flags.
    """
    if profit_target_vnd <= 0 or aov_vnd <= 0 or margin_pct <= 0:
        return {"error": "profit_target, aov, margin must all be positive"}

    margin_per_order_vnd = aov_vnd * (margin_pct / 100.0)
    orders_needed_year = profit_target_vnd / max(margin_per_order_vnd, 1)
    customers_needed_year = orders_needed_year / max(repeat_purchase_ratio, 0.1)
    leads_needed_year = customers_needed_year / max(conversion_rate_pct / 100.0, 0.001)
    traffic_needed_year = leads_needed_year / max(optin_rate_pct / 100.0, 0.001)

    # Per month
    orders_per_month = orders_needed_year / months
    customers_per_month = customers_needed_year / months
    leads_per_month = leads_needed_year / months
    traffic_per_month = traffic_needed_year / months

    # Ad budget: auto-compute CAC if not provided
    # Rule: CAC < margin_per_customer * 0.4 (40% of LTV-first-order margin)
    margin_per_customer = margin_per_order_vnd * repeat_purchase_ratio
    if cac_target_vnd <= 0:
        cac_target_vnd = int(margin_per_customer * 0.4)  # default 40% CAC ceiling

    ad_budget_year = customers_needed_year * cac_target_vnd
    ad_budget_per_month = ad_budget_year / months

    # Revenue + profit reconcile
    revenue_year = orders_needed_year * aov_vnd
    gross_profit_year = orders_needed_year * margin_per_order_vnd
    net_profit_year = gross_profit_year - ad_budget_year

    # Viability flags
    flags = []
    score = 100
    if customers_per_month > 1000:
        flags.append("HIGH_VOLUME_RISK: cần 1000+ khách mới/tháng, khó cho solo founder")
        score -= 25
    elif customers_per_month > 300:
        flags.append("MEDIUM_VOLUME_RISK: 300+ khách mới/tháng, cần team hoặc ad spend lớn")
        score -= 10
    if traffic_per_month > 100000:
        flags.append("HIGH_TRAFFIC_RISK: cần 100k+ visitor/tháng, đòi hỏi paid ads + SEO mạnh")
        score -= 15
    if cac_target_vnd > margin_per_customer * 0.6:
        flags.append("CAC_EXCEEDS_LTV_LIMIT: CAC > 60% margin/khách, unsustainable")
        score -= 25
    if ad_budget_per_month > profit_target_vnd / 12 * 0.5:
        flags.append("AD_BUDGET_HEAVY: ngân sách quảng cáo > 50% target lợi nhuận, rủi ro")
        score -= 15
    if net_profit_year < profit_target_vnd * 0.7:
        flags.append("PROFIT_GAP: net profit sau ad < 70% target, cần điều chỉnh giá hoặc margin")
        score -= 20
    if aov_vnd < 200000 and conversion_rate_pct < 3:
        flags.append("LOW_AOV_LOW_CONV: AOV thấp + conversion thấp = phải đẩy volume cao")
        score -= 15

    score = max(0, min(100, score))
    if score >= 80:
        verdict = "VIABLE_GO"
    elif score >= 60:
        verdict = "VIABLE_WITH_OPTIMIZATION"
    elif score >= 40:
        verdict = "RISKY"
    else:
        verdict = "NOT_VIABLE"

    return {
        "inputs": {
            "profit_target_vnd": profit_target_vnd,
            "aov_vnd": aov_vnd,
            "margin_pct": margin_pct,
            "conversion_rate_pct": conversion_rate_pct,
            "optin_rate_pct": optin_rate_pct,
            "repeat_purchase_ratio": repeat_purchase_ratio,
            "cac_target_vnd": cac_target_vnd,
            "months": months,
        },
        "chain": {
            "margin_per_order_vnd": int(margin_per_order_vnd),
            "margin_per_customer_vnd": int(margin_per_customer),
            "orders_needed_year": int(orders_needed_year),
            "orders_per_month": int(orders_per_month),
            "customers_needed_year": int(customers_needed_year),
            "customers_per_month": int(customers_per_month),
            "leads_needed_year": int(leads_needed_year),
            "leads_per_month": int(leads_per_month),
            "traffic_needed_year": int(traffic_needed_year),
            "traffic_per_month": int(traffic_per_month),
            "ad_budget_year_vnd": int(ad_budget_year),
            "ad_budget_per_month_vnd": int(ad_budget_per_month),
            "revenue_year_vnd": int(revenue_year),
            "gross_profit_year_vnd": int(gross_profit_year),
            "net_profit_year_vnd": int(net_profit_year),
        },
        "financial_viability_score": score,
        "verdict": verdict,
        "flags": flags,
    }
