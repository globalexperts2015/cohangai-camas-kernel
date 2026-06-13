"""Pydantic schemas for BreakoutOS Student Data Layer (SDL).

Spec: wiki/concepts/breakoutos-student-data-layer-spec.md
Master: wiki/concepts/breakoutos-master-architecture.md

Anna amendments 2026-06-12:
1. Sprint dependency wording (no numbering inversion)
2. opportunity_maps fields: founder_fit + market_demand + monetization + ai_leverage + confidence
3. Gate policy: G1 Hard / G2 Soft @ T4 / G2 Hard @ T5+ (after L3 Offer Validation)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================
# 1. Students
# ============================================================
class StudentCreate(BaseModel):
    person_id: UUID | None = None
    fanhub_person_id: UUID | None = None
    program_id: str = Field(..., examples=["foundation", "customer", "growth", "coaching"])
    cohort_id: str = Field("cohort_1", examples=["cohort_1", "k2-2026-q3"])
    archetype: str | None = Field(None, examples=["corporate_escape", "expert", "store", "creator"])
    email: str | None = None
    full_name: str | None = None
    phone: str | None = None


class Student(StudentCreate):
    id: UUID
    status: str = "active"
    current_level: int = 1
    current_gate: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


# ============================================================
# 2. Founder Profile (L1 — 8 file canonical)
# ============================================================
class FounderAssets(BaseModel):
    """Anna L1 amendment V3.5.4: TÀI SẢN khác identity tư duy."""
    knowledge: list[str] = []         # Master, MBA, course completed
    experience: list[dict[str, Any]] = []  # [{years, field, role}]
    certifications: list[str] = []    # MARA, license, accreditation
    network: dict[str, Any] = {}      # {count, tier, niche}
    case_studies: list[dict[str, Any]] = []
    story_tags: list[str] = []        # link to founder-story
    media: dict[str, Any] = {}        # {fb_page, email_list, podcast}
    skills: list[str] = []


class FounderStory(BaseModel):
    """3-act narrative source cho mọi content founder-led."""
    act_1_origin: str
    act_2_crisis: str
    act_3_transformation: str
    concrete_details: list[str] = []  # 5-10 địa danh/năm/con số/nhân vật


class FounderProfileCreate(BaseModel):
    student_id: UUID
    mission: str | None = None        # 10-20 năm persistent
    vision: str | None = None         # 5 năm
    why_statement: str | None = None
    identity: str | None = None       # tư duy: values + skills + archetype
    principles_json: list[str] | None = None  # 5-7 decision principles
    anti_vision_json: list[str] | None = None # 5-10 "không muốn"
    founder_assets_json: FounderAssets | None = None
    founder_story_json: FounderStory | None = None


class FounderProfile(FounderProfileCreate):
    id: UUID
    structured_data_json: dict[str, Any] | None = None
    markdown_path: str | None = None
    status: str = "draft"
    version: int = 1
    created_at: datetime
    updated_at: datetime


# ============================================================
# 3. Customer Profile (L2 — Customer Fit Score + Full VPC)
# ============================================================
class CustomerJobs(BaseModel):
    functional: list[str] = []
    emotional: list[str] = []
    social: list[str] = []


class CustomerPains(BaseModel):
    obstacles: list[dict[str, Any]] = []   # [{pain, scale_1_10}]
    risks: list[dict[str, Any]] = []
    frustrations: list[dict[str, Any]] = []


class CustomerGains(BaseModel):
    required: list[str] = []
    expected: list[str] = []
    desired: list[str] = []
    unexpected: list[str] = []         # wow factor


class CustomerFitScore(BaseModel):
    """V3.5 6-component, Lived Experience 30% NOT pain-first."""
    lived_experience: int = Field(0, ge=0, le=30)
    empathy: int = Field(0, ge=0, le=20)
    credibility: int = Field(0, ge=0, le=15)
    pain: int = Field(0, ge=0, le=15)
    reach: int = Field(0, ge=0, le=10)
    wtp: int = Field(0, ge=0, le=10)

    @property
    def total(self) -> int:
        return (self.lived_experience + self.empathy + self.credibility
                + self.pain + self.reach + self.wtp)


class BuyingTrigger(BaseModel):
    trigger: str
    category: str = Field(..., examples=["life", "seasonal", "business", "crisis"])
    emotional_intensity: int = Field(..., ge=1, le=10)
    wtp_spike_pct: int | None = None
    channel: str | None = None


class CustomerProfileCreate(BaseModel):
    student_id: UUID
    target_customer: str | None = None
    jobs_json: CustomerJobs | None = None
    pains_json: CustomerPains | None = None
    gains_json: CustomerGains | None = None
    buying_triggers_json: list[BuyingTrigger] | None = None
    buying_journey_json: dict[str, Any] | None = None  # Schwartz 5-stage
    demand_evidence_json: dict[str, Any] | None = None  # Trends + ATP + YT
    conversation_evidence_json: dict[str, Any] | None = None  # Reddit + FB + TT + Amazon
    fit_score_json: CustomerFitScore | None = None


class CustomerProfile(CustomerProfileCreate):
    id: UUID
    structured_data_json: dict[str, Any] | None = None
    markdown_path: str | None = None
    status: str = "draft"
    version: int = 1
    created_at: datetime
    updated_at: datetime


# ============================================================
# 4. Opportunity Map (L2.5 — Anna amendment 5 score fields)
# ============================================================
class OpportunityScored(BaseModel):
    name: str
    founder_fit_score: int = Field(..., ge=0, le=10)
    market_demand_score: int = Field(..., ge=0, le=10)
    monetization_score: int = Field(..., ge=0, le=10)
    ai_leverage_score: int = Field(..., ge=0, le=10)
    confidence_score: int = Field(..., ge=0, le=10)
    evidence: dict[str, Any] = {}

    @property
    def total(self) -> int:
        return (self.founder_fit_score + self.market_demand_score
                + self.monetization_score + self.ai_leverage_score
                + self.confidence_score)


class OpportunityMapCreate(BaseModel):
    student_id: UUID
    opportunities_json: list[OpportunityScored]
    selected_opportunity: str | None = None
    founder_fit_score: int | None = None
    market_demand_score: int | None = None
    monetization_score: int | None = None
    ai_leverage_score: int | None = None
    confidence_score: int | None = None
    evidence_json: dict[str, Any] | None = None


class OpportunityMap(OpportunityMapCreate):
    id: UUID
    total_score: int  # GENERATED column from Postgres
    structured_data_json: dict[str, Any] | None = None
    markdown_path: str | None = None
    status: str = "draft"
    version: int = 1
    created_at: datetime
    updated_at: datetime


# ============================================================
# 5. Offers (L3 Value Proposition OS)
# ============================================================
class ValueEquation(BaseModel):
    """Hormozi 4 lever: Value = (Dream × Likelihood) / (Time × Effort)."""
    dream_outcome: int = Field(..., ge=1, le=10)
    perceived_likelihood: int = Field(..., ge=1, le=10)
    time_delay: int = Field(..., ge=1, le=10)
    effort_sacrifice: int = Field(..., ge=1, le=10)


class GuaranteeStrategy(BaseModel):
    """5 tier risk reversal."""
    tier: str = Field(..., examples=["conditional", "unconditional", "performance", "service", "lifetime"])
    description: str
    cost_to_deliver: str | None = None
    perceived_risk_reduction: int | None = None  # 1-10
    wtp_impact: str | None = None


class OfferCreate(BaseModel):
    student_id: UUID
    offer_name: str
    target_customer: str
    pain: str
    desired_identity: str          # V3.5.3: identity-shift not outcome-promise
    vehicle: str                   # V3.5.3: vehicle not mechanism
    transformation: str
    pricing_json: dict[str, Any] | None = None  # {tier, price, payment_plan}
    value_equation_json: ValueEquation | None = None
    guarantee_strategy_json: GuaranteeStrategy | None = None
    offer_stack_json: list[dict[str, Any]] | None = None  # 5 tier value ladder
    financial_model_json: dict[str, Any] | None = None    # margin + AOV + break-even


class Offer(OfferCreate):
    id: UUID
    structured_data_json: dict[str, Any] | None = None
    markdown_path: str | None = None
    status: str = "draft"
    version: int = 1
    created_at: datetime
    updated_at: datetime


# ============================================================
# 6. Positioning Profile (L3, tách khỏi offer)
# ============================================================
class PositioningProfileCreate(BaseModel):
    student_id: UUID
    category: str | None = None         # "Operating System for Solo Founder"
    enemy: str | None = None            # "agency 50 nhân sự / course platform"
    unique_angle: str | None = None     # USP one-liner
    positioning_statement: str | None = None
    statement_one_line: str | None = None  # 4-ý: WHO+CURRENT PAIN+DESIRED IDENTITY+VEHICLE
    differentiation_json: list[str] | None = None
    market_context_json: dict[str, Any] | None = None


class PositioningProfile(PositioningProfileCreate):
    id: UUID
    structured_data_json: dict[str, Any] | None = None
    markdown_path: str | None = None
    status: str = "draft"
    version: int = 1
    created_at: datetime
    updated_at: datetime


# ============================================================
# 7. Canonical File (universal registry)
# ============================================================
class CanonicalFileCreate(BaseModel):
    student_id: UUID
    level: int = Field(..., ge=1, le=6)
    file_key: str                       # 'life-mission' | 'customer-profile' | ...
    file_name: str                      # '{file_key}.md'
    file_type: str = "canonical"
    tier: str = Field(..., pattern="^[ABC]$")
    lock_type: str = Field("strategic", pattern="^(core|strategic|operational)$")
    markdown_content: str | None = None
    structured_data_json: dict[str, Any] | None = None
    generated_by: str | None = None     # 'student' | 'ai_haiku' | 'ai_opus' | 'gate_snapshot'


class CanonicalFile(CanonicalFileCreate):
    id: UUID
    version: int = 1
    status: str = "draft"
    reviewed_by: UUID | None = None
    ai_signature: str | None = None
    created_at: datetime
    updated_at: datetime


# ============================================================
# 8. Canonical Lock (gate state, Anna amendment)
# ============================================================
class CanonicalLockCreate(BaseModel):
    student_id: UUID
    gate_key: str                       # 'gate_1_founder' | 'gate_2_customer_soft' | ...
    level: int
    locked_files_json: list[UUID]
    lock_status: str = Field("soft", pattern="^(soft|hard|unlocked)$")
    locked_by: UUID
    signature: str
    snapshot_json: dict[str, Any]


class CanonicalLock(CanonicalLockCreate):
    id: int
    locked_at: datetime
    unlock_reason: str | None = None
    unlocked_at: datetime | None = None
    recert_required: bool = False
    created_at: datetime


# ============================================================
# 9. Student Event (ledger)
# ============================================================
class StudentEventCreate(BaseModel):
    student_id: UUID | None = None
    person_id: UUID | None = None
    event_type: str                     # 'form.submitted' | 'ai_chat.completed' | ...
    source: str                         # 'tally' | 'ai_chat' | 'fathom' | 'webinarkit' | 'manual'
    level: int | None = None
    payload_json: dict[str, Any]


class StudentEvent(StudentEventCreate):
    id: int
    extracted_data_json: dict[str, Any] | None = None
    extraction_status: str = "pending"
    created_at: datetime


# ============================================================
# Gate definitions (Anna amendment 2026-06-12)
# ============================================================
GATE_REQUIREMENTS = {
    "gate_1_founder": {
        "level": 1,
        "required_files": [
            "life-mission", "vision-statement", "why-statement",
            "founder-identity", "founder-assets",
            "decision-principles", "anti-vision", "founder-story",
        ],
        "lock_type": "hard",            # Anna amendment 3: G1 = HARD
        "snapshot_to": ["final-vision", "final-founder-identity"],
        "unlock_next": ["gate_2_customer_soft"],
    },
    "gate_2_customer_soft": {
        "level": 2,
        "required_files": [
            "who-i-serve", "customer-profile", "statement-mot-dong",
            "opportunity-map", "demand-evidence", "conversation-evidence",
            "buying-journey", "buying-triggers",
            "why-this-customer", "lived-experience", "customer-empathy-map",
        ],
        "lock_type": "soft",
        "min_total_opportunity_score": 30,
        "snapshot_to": ["final-customer-direction", "final-statement-mot-dong"],
        "unlock_next": ["l3_offer_module_chon"],
    },
    "gate_2_customer_hard": {
        "requires_passed": ["l3_offer_validation_completed"],
        "lock_type": "hard",
        "level": 2,
        "snapshot_to": ["final-customer-direction", "final-statement-mot-dong"],
        "unlock_next": ["gate_3_value_proposition"],
    },
    "gate_3_value_proposition": {
        "level": 3,
        "required_files": [
            "core-offer", "pricing-strategy", "transformation-promise",
            "positioning-statement", "offer-stack", "offer-financial-model",
            "value-equation", "guarantee-strategy",
        ],
        "lock_type": "hard",
        "snapshot_to": ["final-offer"],
        "unlock_next": ["gate_4_business_operating"],
    },
    "gate_4_business_operating": {
        "level": 4,
        "required_files": [
            "ai-coo", "business-vault", "automation-stack",
            "sop-library", "dashboard-stack", "decision-system",
        ],
        "lock_type": "hard",
        "evidence_required": True,      # MUST be running, not just doc
        "unlock_next": ["gate_5_revenue_growth"],
    },
    "gate_5_revenue_growth": {
        "level": 5,
        "required_files": [
            "traffic-engine", "lead-engine", "sales-process",
            "retention-engine", "ascension-engine",
        ],
        "lock_type": "hard",
        "min_revenue_vnd": 1_000_000,   # First Paid Customer threshold
        "min_repeat_or_referral": 1,
        "unlock_next": ["gate_6a_founder_freedom"],
    },
    "gate_6a_founder_freedom": {
        "level": 6,
        "required_files": [
            "freedom-score", "weekly-review", "ai-twin", "ceo-dashboard",
        ],
        "lock_type": "hard",
        "min_freedom_score": 70,
        "min_weeks_reviewed": 8,
        "unlock_next": [],              # graduation
    },
}


# ============================================================
# Validation result schema
# ============================================================
class GateValidation(BaseModel):
    gate_key: str
    passed: bool
    missing: list[str] = []
    warnings: list[str] = []
    metadata: dict[str, Any] = {}
