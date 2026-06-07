"""Cron Ads Pull, 5am Perth daily wrapper delegate Pban01 ads.performance_review.

Pull FB Ads + Google Ads insights into canonical memory so BC1 morning brief,
BC8 night audit, and Pban10 chiến lược can RAG retrieve per-campaign performance.
"""
from .agent import CronAdsPull

__all__ = ["CronAdsPull"]
