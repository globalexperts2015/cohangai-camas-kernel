"""CAMAS Kernel FastAPI entry point.

Bootstraps the kernel singleton, mounts routers, and exposes a root probe.
The kernel exposes two routers:
    - /kernel/*   internal control plane (execute, status, agents)
    - /webhook/*  external event ingestion (Sepay, Zalo, GHL, Tally, Fathom)
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from agents.bc1_team_leader import BC1TeamLeader
from agents.bc2_voice_guardian import BC2VoiceGuardian
from agents.bc3_feedback_loop import BC3FeedbackLoop
from agents.bc3_profile_extractor import BC3ProfileExtractor
from agents.bc3_task_tracker import BC3TaskTracker
from agents.bc4_k2_launch import BC4K2Launch
from agents.bc5_cdp_monitor import BC5CDPMonitor
from agents.bc6_cskh_faq_haiku import BC6CSKHFAQHaiku
from agents.bc7_fb_autoreply import BC7FBAutoreply
from agents.bc8_night_audit import BC8NightAudit
from agents.bc9_compliance_officer import BC9ComplianceOfficer
from agents.bc10_coaching_delivery import BC10CoachingDelivery

# Sprint 12 Tier 2: WHO Intelligence (BC11-BC15)
from agents.bc11_vpc_builder import BC11VPCBuilder
from agents.bc12_consciousness_tracker import BC12ConsciousnessTracker
from agents.bc13_pain_scorer import BC13PainScorer
from agents.bc14_joy_mapper import BC14JoyMapper
from agents.bc15_character_builder import BC15CharacterBuilder

# Sprint 12 Tier 2: WHAT Intelligence (BC16-BC20)
from agents.bc16_value_ladder import BC16ValueLadder
from agents.bc17_grand_slam_offer import BC17GrandSlamOffer
from agents.bc18_value_equation import BC18ValueEquation
from agents.bc19_funnel_architect import BC19FunnelArchitect
from agents.bc20_copy_stack import BC20CopyStack

# Sprint 13 P0.3: Financial Modeler (CAC/LTV/Payback/Runway daily)
from agents.financial_modeler import FinancialModeler

# Sprint 13 P1: Framework v2 partial → strong L1
from agents.niche_validator import NicheValidator
from agents.demand_research import DemandResearch
from agents.content_distributor import ContentDistributor
from agents.trust_capital_tracker import TrustCapitalTracker
from agents.overlay_a_cohort_comparison import OverlayACohortComparison
from agents.overlay_a_antifragility import OverlayAAntifragility

# Sprint 5 Tier 3: 10 Phòng ban
from agents.pban_01_quang_cao import Pban01QuangCao
from agents.pban_02_noi_dung import Pban02NoiDung
from agents.pban_03_landing_webinar import Pban03LandingWebinar
from agents.pban_04_phieu_comms import Pban04PhieuComms
from agents.pban_05_thanh_toan import Pban05ThanhToan
from agents.pban_06_cskh_faq_haiku import Pban06CSKHFAQHaiku
from agents.pban_07_hoan_tien import Pban07HoanTien
from agents.pban_08_du_lieu import Pban08DuLieu
from agents.pban_09_tuan_thu import Pban09TuanThu
from agents.pban_10_chien_luoc import Pban10ChienLuoc

# Sprint 5 Tier 3: 6 Cron jobs
from agents.cron_ads_pull import CronAdsPull
from agents.cron_morning_brief import CronMorningBrief
from agents.cron_wk_sync import CronWkSync
from agents.cron_lead_scoring import CronLeadScoring
from agents.cron_stale_alert import CronStaleAlert
from agents.cron_social_posts import CronSocialPosts
from agents.cron_dedupe_contact import CronDedupeContact
from agents.cron_amem_weekly import CronAmemWeekly

# Sprint 5 Tier 3: 1 standalone
from agents.standalone_healthcheck import StandaloneHealthcheck
from kernel.memory_layer import MemoryLayer, VoyageEmbedder
from kernel.scheduler import Scheduler
from routes.kernel_routes import router as kernel_router
from routes.webhook_routes import router as webhook_router

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("camas.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Boot Scheduler at startup, drain queues at shutdown."""
    log.info("CAMAS Kernel khởi động, scheduler ready")

    # Wire MemoryLayer pgvector + Voyage embedder (Sprint 4)
    voyage_key = os.getenv("VOYAGE_API_KEY", "")
    embedder = VoyageEmbedder(
        api_key=voyage_key,
        model=os.getenv("VOYAGE_MODEL", "voyage-3"),
    )
    dsn = os.getenv("DATABASE_URL") or os.getenv("CDP_DATABASE_URL")
    memory = MemoryLayer(dsn=dsn, embedder=embedder)
    if memory.ready:
        log.info("MemoryLayer wired: pgvector + voyage-3 ready")
    else:
        log.warning(
            "MemoryLayer NOT ready: voyage_key=%s dsn=%s",
            bool(voyage_key),
            bool(dsn),
        )

    scheduler = Scheduler(memory=memory)
    await scheduler.start()

    # BC2 Voice Guardian, register vào scheduler + wire vào VoiceGate
    bc2 = BC2VoiceGuardian(llm=scheduler.llm)
    scheduler.register(bc2)
    scheduler.voice_gate.bc2_agent = bc2
    log.info("BC2 Voice Guardian registered + wired to VoiceGate")

    # BC1 Team Leader, orchestrator rollup 2x/ngày Telegram
    bc1 = BC1TeamLeader(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc1)
    log.info("BC1 Team Leader registered (rollup.morning + rollup.evening)")

    # BC3 Feedback Loop, Customer Voice digest weekly + Tally/Fathom ingest (legacy monolith)
    bc3 = BC3FeedbackLoop(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc3)
    log.info(
        "BC3 Feedback Loop registered (feedback.weekly_digest + "
        "feedback.tally.submitted + feedback.fathom.transcript)"
    )

    # Sprint 7: BC3 split System-Wide Personalization (Cerebrum pattern)
    bc3_profile = BC3ProfileExtractor(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc3_profile)
    log.info("BC3 Profile Extractor registered (profile.refresh_weekly + profile.refresh_single)")

    bc3_task = BC3TaskTracker(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc3_task)
    log.info("BC3 Task Tracker registered (task.update_post_call + task.update_generic)")

    # BC9 Compliance Officer, register + wire vào ComplianceGate
    bc9 = BC9ComplianceOfficer(llm=scheduler.llm)
    scheduler.register(bc9)
    scheduler.compliance_gate.bc9_agent = bc9
    log.info("BC9 Compliance Officer registered + wired to ComplianceGate")

    # Sprint 5 Tier 2: 6 BC agents

    # BC4 K2 Launch, pre-launch + launch week tactical 72h critical
    bc4 = BC4K2Launch(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc4)
    log.info("BC4 K2 Launch registered (launch.t_minus_3/1, launch.live_day, launch.post_24h)")

    # BC5 CDP Monitor, health 5min + daily audit
    bc5 = BC5CDPMonitor(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc5)
    log.info("BC5 CDP Monitor registered (monitor.health_5min, monitor.daily_audit, monitor.on_demand)")

    # BC6 CSKH FAQ Haiku, customer support tier 1
    bc6 = BC6CSKHFAQHaiku(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc6)
    log.info("BC6 CSKH FAQ Haiku registered (cskh.message.in, cskh.batch_audit)")

    # BC7 FB Autoreply, FB DM + comment auto-reply
    bc7 = BC7FBAutoreply(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc7)
    log.info("BC7 FB Autoreply registered (fb.message.in, fb.comment.in, fb.batch_audit)")

    # BC8 Night Audit, overnight comprehensive 6 ventures
    bc8 = BC8NightAudit(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc8)
    log.info("BC8 Night Audit registered (audit.nightly)")

    # BC10 Coaching Delivery, 1on1 50M tier pre/post call + weekly check-in
    bc10 = BC10CoachingDelivery(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc10)
    log.info("BC10 Coaching Delivery registered (coaching.pre_call/post_call/weekly_checkin)")

    # Sprint 12 Tier 2: WHO Intelligence (BC11-BC15, framework encoders)
    bc11 = BC11VPCBuilder(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc11)
    log.info("BC11 VPC Builder registered (vpc.build_canvas, Eagle Camp Tròn Vuông + CIS M2)")

    bc12 = BC12ConsciousnessTracker(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc12)
    log.info("BC12 Consciousness Tracker registered (consciousness.classify, Eagle Camp 8 cấp)")

    bc13 = BC13PainScorer(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc13)
    log.info("BC13 Pain Scorer registered (pain.score_severity, CIS M3 + Hormozi VE + Dan Lok)")

    bc14 = BC14JoyMapper(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc14)
    log.info("BC14 Joy Mapper registered (joy.map_to_pain, CIS M4 + Tròn Vuông Gains + Hormozi)")

    bc15 = BC15CharacterBuilder(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc15)
    log.info("BC15 Character Builder registered (character.build_profile, Brunson + Dan Lok + Anna story pool)")

    # Sprint 12 Tier 2: WHAT Intelligence (BC16-BC20, framework encoders)
    bc16 = BC16ValueLadder(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc16)
    log.info("BC16 Value Ladder registered (ladder.design, Brunson Value Ladder + Anna Empire Stack + Eagle CL5)")

    bc17 = BC17GrandSlamOffer(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc17)
    log.info("BC17 Grand Slam Offer registered (offer.build_grand_slam, Hormozi + Brunson Stack + Dan Lok USP)")

    bc18 = BC18ValueEquation(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc18)
    log.info("BC18 Value Equation registered (offer.audit_value_equation, Hormozi 4 lever + Brunson Epiphany)")

    bc19 = BC19FunnelArchitect(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc19)
    log.info("BC19 Funnel Architect registered (funnel.architect_7_phases, Brunson 7 Phases + Eagle IPS + CIS M6)")

    bc20 = BC20CopyStack(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(bc20)
    log.info("BC20 Copy Stack registered (copy.generate_stack, Dan Lok 8 secrets + Brunson Soap Opera + Hormozi)")

    # Sprint 13 P0.3: Financial Modeler daily CAC/LTV/Payback/Runway
    financial_modeler = FinancialModeler(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(financial_modeler)
    log.info("Financial Modeler registered (financial.daily_calc + financial.venture_audit, Overlay B)")

    # Sprint 13 P1: Framework v2 partial → strong L1
    niche_validator = NicheValidator(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(niche_validator)
    log.info("Niche Validator registered (niche.validate, Stage 3 framework v2)")

    demand_research = DemandResearch(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(demand_research)
    log.info("Demand Research registered (demand.research, Stage 5 framework v2)")

    content_distributor = ContentDistributor(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(content_distributor)
    log.info("Content Distributor registered (content.distribute_pyramid, Stage 11 Content Pyramid)")

    trust_capital_tracker = TrustCapitalTracker(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(trust_capital_tracker)
    log.info("Trust Capital Tracker registered (trust.quarterly_audit, Stage 13)")

    # Sprint 13 P1.5: Overlay A enhance (BC3 + BC8 antifragility)
    overlay_a_cohort = OverlayACohortComparison(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(overlay_a_cohort)
    log.info("Overlay A Cohort Comparison registered (overlay_a.cohort_compare, BC3 enhance)")

    overlay_a_antifragility = OverlayAAntifragility(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(overlay_a_antifragility)
    log.info("Overlay A Antifragility registered (overlay_a.antifragility_score, BC8 enhance)")

    # Sprint 5 Tier 3: 10 Phòng ban Breakout Funnel OS
    pban_classes = [
        ("Pban01 Quảng cáo", Pban01QuangCao),
        ("Pban02 Nội dung", Pban02NoiDung),
        ("Pban03 Landing Webinar", Pban03LandingWebinar),
        ("Pban04 Phiếu Comms", Pban04PhieuComms),
        ("Pban05 Thanh toán", Pban05ThanhToan),
        ("Pban06 CSKH FAQ (alias BC6)", Pban06CSKHFAQHaiku),
        ("Pban07 Hoàn tiền", Pban07HoanTien),
        ("Pban08 Dữ liệu", Pban08DuLieu),
        ("Pban09 Tuân thủ (alias BC9)", Pban09TuanThu),
        ("Pban10 Chiến lược", Pban10ChienLuoc),
    ]
    for label, klass in pban_classes:
        agent = klass(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(agent)
        log.info(f"{label} registered")

    # Sprint 5 Tier 3: 7 Cron jobs (+ Cron Ads Pull Sprint 11)
    # Cron Morning Brief + Cron Social Posts + Cron Ads Pull cần scheduler để delegate
    cron_classes_scheduler_aware = {
        "Cron Morning Brief",
        "Cron Social Posts",
        "Cron Ads Pull",
    }
    cron_classes = [
        ("Cron Morning Brief", CronMorningBrief),
        ("Cron Ads Pull", CronAdsPull),
        ("Cron WK Sync", CronWkSync),
        ("Cron Lead Scoring", CronLeadScoring),
        ("Cron Stale Alert", CronStaleAlert),
        ("Cron Social Posts", CronSocialPosts),
        ("Cron Dedupe Contact", CronDedupeContact),
        ("Cron A-mem Weekly Evolve", CronAmemWeekly),
    ]
    for label, klass in cron_classes:
        if label in cron_classes_scheduler_aware:
            agent = klass(
                llm=scheduler.llm,
                memory=scheduler.memory,
                scheduler=scheduler,
            )
        else:
            agent = klass(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(agent)
        log.info(f"{label} registered")

    # Sprint 5 Tier 3: 1 standalone
    healthcheck = StandaloneHealthcheck(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(healthcheck)
    log.info("Standalone Healthcheck registered (system-wide probe)")

    app.state.scheduler = scheduler
    try:
        yield
    finally:
        log.info("CAMAS Kernel shutdown, drain queues")
        await scheduler.stop()
        try:
            await memory.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("MemoryLayer close fail: %r", exc)


app = FastAPI(
    title="CAMAS Kernel",
    description="Cohangai AIOS Multi-Agent System Kernel, điều phối 25 agent qua shared memory + auto inject/extract.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(kernel_router, prefix="/kernel", tags=["kernel"])
app.include_router(webhook_router, prefix="/webhook", tags=["webhook"])


@app.get("/")
async def root() -> JSONResponse:
    """Public probe, không trả secret."""
    return JSONResponse(
        {
            "service": "camas-kernel",
            "version": "0.1.0",
            "status": "running",
            "docs": "/docs",
        }
    )
