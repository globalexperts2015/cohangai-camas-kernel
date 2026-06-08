"""Offer Engineer agent.

Apply Hormozi $100M Offers formula để optimize offer của Anna. Calculate
Offer Value = (Dream Outcome × Perceived Likelihood) ÷ (Time Delay × Effort).
Recommend Stack value + Bonus + Guarantee + lever optimization.

P0.1 Sprint 13 per `cohangai/aios/aios-build-instructions-sprint-13.md`.
Framework v2 Stage 9 per `wiki/concepts/solo-business-growth-system-v2.md`.
"""
from .agent import OfferEngineer

__all__ = ["OfferEngineer"]
