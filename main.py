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

from fastapi import FastAPI, Request
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

# Sprint 13 P0.1: Offer Engineer (Hormozi $100M formula)
from agents.offer_engineer import OfferEngineer

# Sprint 13 P0.3: Financial Modeler (CAC/LTV/Payback/Runway daily)
from agents.financial_modeler import FinancialModeler

# Sprint 13 P1: Framework v2 partial → strong L1
from agents.niche_validator import NicheValidator
from agents.demand_research import DemandResearch
from agents.content_distributor import ContentDistributor
from agents.trust_capital_tracker import TrustCapitalTracker
from agents.overlay_a_cohort_comparison import OverlayACohortComparison
from agents.overlay_a_antifragility import OverlayAAntifragility

# Sprint 14 missing critical: Stage 1.1 + 1.3 + 3 + 4 agents
from agents.asset_bank_inventory import AssetBankInventory
from agents.market_signal_scraper import MarketSignalScraper
from agents.competitor_intelligence import CompetitorIntelligence
from agents.value_creation_advisor import ValueCreationAdvisor

# Sprint 14 enhance: Stage 9 Perfect Webinar + Stage 10 Onboarding proactive
from agents.perfect_webinar_designer import PerfectWebinarDesigner
from agents.onboarding_orchestrator import OnboardingOrchestrator

# Sprint 13 P2: 7 L2 Cohangai Cohort 1 wizards
from agents.l2_vision_clarity import L2VisionClarity
from agents.l2_niche_validator_student import L2NicheValidatorStudent
from agents.l2_transformation_mapper_7d import L2TransformationMapper7D
from agents.l2_vpc_fit_checker import L2VPCFitChecker
from agents.l2_mvo_cohort_launcher import L2MVOCohortLauncher
from agents.l2_offer_engineer_student import L2OfferEngineerStudent
from agents.l2_referral_engine_template import L2ReferralEngineTemplate

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
from routes.cohort_widget_routes import router as cohort_router, mount_static as mount_cohort_static
from routes.chon_module_routes import router as chon_module_router
from routes.sdl_routes import router as sdl_router
from routes.freedom_score_routes import router as freedom_score_router
from routes.l1_routes import router as l1_router
from routes.l2_routes import router as l2_router
from routes.l3_routes import router as l3_router
from routes.l4_routes import router as l4_router
from routes.l5_routes import router as l5_router
from routes.l6a_routes import router as l6a_router
from routes.dashboard_routes import router as dashboard_router
from routes.intake_forms import router as intake_forms_router
from routes.validation_routes import router as validation_router, log_system_error
from routes.discovery_routes import router as discovery_router
from routes.discovery_view import router as discovery_view_router
from routes.day3_challenge import router as day3_router
from routes.day3_view import router as day3_view_router

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

    # Sprint 13 P0.1: Offer Engineer (Hormozi $100M formula, Stage 9)
    offer_engineer = OfferEngineer(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(offer_engineer)
    log.info("Offer Engineer registered (offer.engineer + offer.audit, Hormozi $100M Offers)")

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

    # Sprint 14 missing critical agents (Stage 1.1 + 1.3 + 3 + 4)
    asset_bank = AssetBankInventory(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(asset_bank)
    log.info("Asset Bank Inventory registered (asset.inventory_build, Stage 1.1)")

    market_signal = MarketSignalScraper(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(market_signal)
    log.info("Market Signal Scraper registered (market.signal_aggregate, Stage 1.3)")

    competitor_intel = CompetitorIntelligence(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(competitor_intel)
    log.info("Competitor Intelligence registered (competitor.intel_research, Stage 3)")

    value_advisor = ValueCreationAdvisor(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(value_advisor)
    log.info("Value Creation Advisor registered (value.creation_advise, Stage 4)")

    # Sprint 14 enhance: Stage 9 Perfect Webinar + Stage 10 Onboarding
    perfect_webinar = PerfectWebinarDesigner(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(perfect_webinar)
    log.info("Perfect Webinar Designer registered (webinar.design_perfect_90min, Stage 9 Brunson)")

    onboarding = OnboardingOrchestrator(llm=scheduler.llm, memory=scheduler.memory)
    scheduler.register(onboarding)
    log.info("Onboarding Orchestrator registered (onboarding.welcome_sequence/progress_check, Stage 10)")

    # Sprint 13 P2: 7 L2 Cohangai Cohort 1 wizards
    l2_classes = [
        ("L2.1 Vision Clarity", L2VisionClarity, "cohort.vision_clarity"),
        ("L2.2 Niche Validator Student", L2NicheValidatorStudent, "cohort.niche_validate"),
        ("L2.3 Transformation Mapper 7D", L2TransformationMapper7D, "cohort.transformation_map"),
        ("L2.4 VPC Fit Checker", L2VPCFitChecker, "cohort.vpc_fit_check"),
        ("L2.5 MVO Cohort Launcher", L2MVOCohortLauncher, "cohort.mvo_launch_plan"),
        ("L2.6 Offer Engineer Student", L2OfferEngineerStudent, "cohort.offer_engineer"),
        ("L2.7 Referral Engine Template", L2ReferralEngineTemplate, "cohort.referral_engine_design"),
    ]
    for label, klass, event in l2_classes:
        agent = klass(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(agent)
        log.info(f"{label} registered ({event})")

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

    # ───── BreakoutOS v3 agents (added 2026-06-09) ─────
    # Sprint 1: GrowthOS
    try:
        from agents.c1_content_engine import C1ContentEngine
        c1 = C1ContentEngine(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(c1)
        log.info("C1 Content Engine registered (cohort.content_engine + wizard.content_engine)")
    except Exception as exc:
        log.warning("C1 Content Engine register fail: %r", exc)

    try:
        from agents.c2_lead_gen_engine import C2LeadGenEngine
        c2 = C2LeadGenEngine(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(c2)
        log.info("C2 Lead Gen Engine registered (cohort.lead_gen + wizard.lead_gen_engine)")
    except Exception as exc:
        log.warning("C2 Lead Gen Engine register fail: %r", exc)

    # Sprint 2: ScaleOS daily ops
    try:
        from agents.e1_ai_coo import E1AICOO
        e1 = E1AICOO(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(e1)
        log.info("E1 AI COO registered (coo.daily + coo.weekly + coo.monthly + wizard.ai_coo)")
    except Exception as exc:
        log.warning("E1 AI COO register fail: %r", exc)

    # Sprint 3: ScaleOS scale planning
    try:
        from agents.e2_scale_coach import E2ScaleCoach
        e2 = E2ScaleCoach(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(e2)
        log.info("E2 Scale Coach registered (cohort.scale_coach + wizard.scale_coach)")
    except Exception as exc:
        log.warning("E2 Scale Coach register fail: %r", exc)

    # BreakoutOS CHỌN module (What To Sell Engine), spec chốt 2026-06-11
    try:
        from agents.e3_founder_fit import E3FounderFit
        e3 = E3FounderFit(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(e3)
        log.info("E3 Founder Fit registered (cohort.founder_fit + wizard.founder_fit)")
    except Exception as exc:
        log.warning("E3 Founder Fit register fail: %r", exc)

    try:
        from agents.e4_customer_problem import E4CustomerProblem
        e4 = E4CustomerProblem(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(e4)
        log.info("E4 Customer Problem registered (cohort.customer_problem + wizard.customer_problem)")
    except Exception as exc:
        log.warning("E4 Customer Problem register fail: %r", exc)

    try:
        from agents.e5_desire import E5Desire
        e5 = E5Desire(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(e5)
        log.info("E5 Desire registered (cohort.desire + wizard.desire)")
    except Exception as exc:
        log.warning("E5 Desire register fail: %r", exc)

    try:
        from agents.e7_solution_design import E7SolutionDesign
        e7 = E7SolutionDesign(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(e7)
        log.info("E7 Solution Design registered (cohort.solution_design + wizard.solution_design)")
    except Exception as exc:
        log.warning("E7 Solution Design register fail: %r", exc)

    try:
        from agents.e8_financial import E8Financial
        e8 = E8Financial(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(e8)
        log.info("E8 Financial registered (cohort.financial + wizard.financial)")
    except Exception as exc:
        log.warning("E8 Financial register fail: %r", exc)

    try:
        from agents.e9_lifestyle_fit import E9LifestyleFit
        e9 = E9LifestyleFit(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(e9)
        log.info("E9 Lifestyle Fit registered (cohort.lifestyle_fit + wizard.lifestyle_fit)")
    except Exception as exc:
        log.warning("E9 Lifestyle Fit register fail: %r", exc)

    try:
        from agents.e6_market_demand import E6MarketDemand
        e6 = E6MarketDemand(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(e6)
        log.info("E6 Market Demand registered (cohort.market_demand + wizard.market_demand)")
    except Exception as exc:
        log.warning("E6 Market Demand register fail: %r", exc)

    try:
        from agents.e10_decision import E10Decision
        e10 = E10Decision(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(e10)
        log.info("E10 Decision registered (cohort.decision + wizard.decision)")
    except Exception as exc:
        log.warning("E10 Decision register fail: %r", exc)

    try:
        from agents.e11_recommendation import E11Recommendation
        e11 = E11Recommendation(llm=scheduler.llm, memory=scheduler.memory)
        scheduler.register(e11)
        log.info("E11 Recommendation registered (cohort.recommendation + wizard.recommendation)")
    except Exception as exc:
        log.warning("E11 Recommendation register fail: %r", exc)

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
app.include_router(cohort_router, tags=["cohort"])
app.include_router(chon_module_router, tags=["chon-module"])
app.include_router(sdl_router, tags=["sdl"])
app.include_router(freedom_score_router, tags=["freedom-score"])
app.include_router(l1_router, tags=["sdl-l1"])
app.include_router(l2_router, tags=["sdl-l2"])
app.include_router(l3_router, tags=["sdl-l3"])
app.include_router(l4_router, tags=["sdl-l4"])
app.include_router(l5_router, tags=["sdl-l5"])
app.include_router(l6a_router, tags=["sdl-l6a"])
app.include_router(dashboard_router, tags=["dashboard"])
app.include_router(intake_forms_router, tags=["intake-forms"])
app.include_router(validation_router, tags=["validation"])
app.include_router(discovery_router, tags=["sdl-discovery"])
app.include_router(discovery_view_router, tags=["discovery-view"])
app.include_router(day3_router, tags=["day3-challenge"])
app.include_router(day3_view_router, tags=["day3-view"])
mount_cohort_static(app)


# ============================================================
# Error Monitoring middleware (Anna 2026-06-12 priority 6)
# ============================================================
@app.middleware("http")
async def error_monitor_middleware(request, call_next):
    """Catch 500 errors, log to breakoutos.system_errors + Telegram alert."""
    try:
        response = await call_next(request)
        # Track 5xx without exception
        if response.status_code >= 500 and request.url.path.startswith(("/sdl/", "/foundation/")):
            try:
                from routes.sdl_routes import get_pool as _gp
                pool = await _gp()
                await log_system_error(
                    pool, request.url.path, request.method, response.status_code,
                    "HTTP5xx", f"Response {response.status_code}",
                    user_agent=request.headers.get("user-agent", ""),
                    ip_address=request.client.host if request.client else "",
                )
            except Exception:
                pass
        return response
    except Exception as exc:
        import traceback as _tb
        tb_str = _tb.format_exc()
        try:
            from routes.sdl_routes import get_pool as _gp
            pool = await _gp()
            await log_system_error(
                pool, request.url.path, request.method, 500,
                type(exc).__name__, str(exc)[:500], tb_str,
                user_agent=request.headers.get("user-agent", ""),
                ip_address=request.client.host if request.client else "",
            )
        except Exception:
            pass
        log.exception("Middleware caught: %s", exc)
        raise

# BreakoutOS v3: AI COO Dashboard routes (added 2026-06-09)
try:
    from routes.coo_routes import router as coo_router
    app.include_router(coo_router, tags=["coo"])
    log.info("COO routes mounted (/coo/daily, /coo/weekly, /coo/monthly, /coo/run, /coo/reports, /coo/dashboard)")
except Exception as exc:
    log.warning("COO routes mount fail: %r", exc)


@app.get("/")
async def root(request: Request):
    """Public landing page tại os.breakout.live root.

    V3.4 (2026-06-11): Landing 5 tầng (Hiểu Mình / Hiểu Khách / Thiết Kế Hệ Thống /
    Tăng Trưởng / Nhân Bản). Founder Transformation Operating System.
    """
    host = request.headers.get("host", "").lower()
    if host.startswith("os.breakout.live"):
        from fastapi.responses import HTMLResponse
        return HTMLResponse(_render_landing_5_tang())
    return JSONResponse(
        {
            "service": "camas-kernel",
            "version": "0.1.0",
            "status": "running",
            "docs": "/docs",
        }
    )


@app.get("/foundation")
async def foundation_landing(request: Request):
    """Landing khoá Foundation với Digital Assets Foundation angle.

    Anna brief 2026-06-12: Tài sản đầu tiên cần xây không phải website/fanpage
    mà là bộ não thứ hai của chính bạn. Foundation = nền móng cho con người +
    cuộc sống + doanh nghiệp + hệ thống tri thức + tài sản số cá nhân.
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_render_landing_foundation())


def _render_landing_5_tang() -> str:
    """V3.4 Landing 5 tầng. Anna chốt 2026-06-11."""
    return """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BreakoutOS, Hệ điều hành Solo Empire của bạn</title>
<meta name="description" content="Founder Transformation Operating System. 5 tầng trưởng thành: Hiểu Mình, Hiểu Khách, Thiết Kế Hệ Thống, Tăng Trưởng, Nhân Bản. Một người - Một AI - Một Solo Business.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800;900&family=Playfair+Display:ital,wght@0,400;0,500;1,400&display=swap">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Be Vietnam Pro',-apple-system,BlinkMacSystemFont,sans-serif;color:#1a1a1a;line-height:1.65;background:#fafafa}
.container{max-width:1100px;margin:0 auto;padding:0 24px}
.hero{background:linear-gradient(135deg,#0f0f0f 0%,#1a1a1a 60%,#3d1414 100%);color:white;padding:80px 0 100px;position:relative;overflow:hidden}
.hero::before{content:'';position:absolute;top:-50%;right:-20%;width:60%;height:200%;background:radial-gradient(circle,rgba(214,48,49,0.15) 0%,transparent 60%);pointer-events:none}
.hero-content{position:relative;z-index:2}
.brand{font-size:14px;letter-spacing:3px;text-transform:uppercase;color:#ff7e5f;font-weight:700;margin-bottom:18px}
.hero h1{font-family:'Playfair Display',serif;font-size:54px;font-weight:700;line-height:1.15;margin-bottom:20px;max-width:840px}
.hero h1 em{color:#ff7e5f;font-style:italic}
.hero .sub{font-size:20px;opacity:0.85;margin-bottom:32px;max-width:680px;font-weight:400}
.hero .tagline{font-size:18px;color:#ff7e5f;font-weight:600;margin-bottom:48px;letter-spacing:0.5px}
.hero .cta-row{display:flex;gap:14px;flex-wrap:wrap}
.btn-primary{display:inline-block;background:linear-gradient(135deg,#ff7e5f,#d63031);color:white;padding:16px 38px;border-radius:12px;text-decoration:none;font-weight:700;font-size:16px;box-shadow:0 8px 24px rgba(214,48,49,0.4);transition:transform 0.2s}
.btn-primary:hover{transform:translateY(-2px)}
.btn-secondary{display:inline-block;background:rgba(255,255,255,0.1);color:white;padding:16px 28px;border-radius:12px;text-decoration:none;font-weight:600;font-size:16px;border:1px solid rgba(255,255,255,0.2)}
section{padding:80px 0}
section.alt{background:white}
.section-label{font-size:13px;letter-spacing:2px;text-transform:uppercase;color:#d63031;font-weight:700;margin-bottom:14px}
.section-title{font-family:'Playfair Display',serif;font-size:42px;font-weight:700;margin-bottom:24px;line-height:1.2;max-width:780px}
.section-intro{font-size:17px;color:#444;margin-bottom:48px;max-width:720px}
.tang{display:flex;gap:32px;align-items:flex-start;padding:32px;background:white;border-radius:20px;margin-bottom:24px;box-shadow:0 4px 20px rgba(0,0,0,0.04);border-left:6px solid #d63031;transition:transform 0.2s}
.tang:hover{transform:translateX(4px)}
.tang .num{font-family:'Playfair Display',serif;font-size:56px;color:#d63031;font-weight:700;line-height:1;flex-shrink:0;min-width:80px}
.tang-content{flex:1}
.tang-name{font-size:24px;font-weight:700;margin-bottom:8px;color:#1a1a1a}
.tang-question{font-size:16px;color:#d63031;font-style:italic;margin-bottom:16px;font-weight:500}
.tang-desc{font-size:15px;color:#555;line-height:1.7;margin-bottom:14px}
.tang-output{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.tang-output span{background:#fff5f5;color:#d63031;padding:5px 12px;border-radius:8px;font-size:13px;font-weight:500}
.archetypes{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px;margin-top:40px}
.arch{background:white;border-radius:16px;padding:28px;border:2px solid #f0f0f0;transition:all 0.2s}
.arch:hover{border-color:#d63031;transform:translateY(-3px)}
.arch h3{font-size:18px;font-weight:700;margin-bottom:10px;color:#d63031}
.arch p{font-size:14px;color:#555;margin-bottom:10px}
.arch .hook{font-size:13px;color:#1a1a1a;font-weight:600;font-style:italic;border-top:1px solid #f0f0f0;padding-top:10px;margin-top:10px}
.value-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:24px;margin-top:36px}
.value-card{background:#fafafa;padding:28px;border-radius:14px;border-left:4px solid #ff7e5f}
.value-card h4{font-size:18px;font-weight:700;margin-bottom:10px}
.value-card p{font-size:14px;color:#555}
.cta-section{background:linear-gradient(135deg,#0f0f0f,#3d1414);color:white;padding:80px 0;text-align:center}
.cta-section h2{font-family:'Playfair Display',serif;font-size:44px;margin-bottom:20px;max-width:780px;margin-left:auto;margin-right:auto}
.cta-section p{font-size:18px;opacity:0.85;margin-bottom:36px;max-width:640px;margin-left:auto;margin-right:auto}
.pricing-tier{display:inline-block;text-align:left;background:rgba(255,255,255,0.05);padding:24px 32px;border-radius:14px;margin:10px;border:1px solid rgba(255,255,255,0.1)}
.pricing-tier .label{font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#ff7e5f;margin-bottom:6px}
.pricing-tier .name{font-size:22px;font-weight:700;margin-bottom:6px}
.pricing-tier .price{font-size:28px;color:#ff7e5f;font-weight:800;margin-bottom:4px}
.pricing-tier .price s{color:#888;font-weight:400;font-size:18px;margin-right:8px}
.pricing-tier .meta{font-size:13px;opacity:0.7}
footer{background:#0a0a0a;color:rgba(255,255,255,0.6);padding:48px 0;font-size:14px}
footer a{color:#ff7e5f;text-decoration:none}
footer .footer-grid{display:grid;grid-template-columns:2fr 1fr 1fr;gap:32px}
footer h5{color:white;font-size:15px;font-weight:700;margin-bottom:14px;text-transform:uppercase;letter-spacing:1px}
footer .brand-block p{margin-bottom:10px}
@media (max-width: 768px){
  .hero h1{font-size:36px}
  .section-title{font-size:30px}
  .tang{flex-direction:column;gap:14px;padding:24px}
  .tang .num{font-size:42px;min-width:auto}
  footer .footer-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>

<header class="hero">
  <div class="container hero-content">
    <div class="brand">BreakoutOS · Đào Thị Hằng</div>
    <h1>Bạn không cần học thêm. Bạn cần <em>trở thành phiên bản</em> có thể tạo ra khách hàng.</h1>
    <p class="sub">BreakoutOS là Hệ Điều Hành Chuyển Hoá Founder. 5 tầng đưa bạn từ người đi tìm cơ hội đến người tạo ra cơ hội cho người khác.</p>
    <p class="tagline">Một người - Một AI - Một Solo Business</p>
    <div class="cta-row">
      <a href="https://app.breakout.live/so-sanh" class="btn-primary">Vào Cohort 1 Founding 1.5tr</a>
      <a href="#5-tang" class="btn-secondary">Xem 5 tầng</a>
    </div>
  </div>
</header>

<section id="5-tang">
  <div class="container">
    <div class="section-label">Hành trình chuyển hoá</div>
    <h2 class="section-title">5 tầng trưởng thành Founder</h2>
    <p class="section-intro">Mỗi tầng có 1 câu hỏi cốt lõi. Bạn không nhảy cóc được. Bạn không tăng trưởng được nếu chưa hiểu mình. Bạn không thiết kế hệ thống bán được nếu chưa hiểu khách.</p>

    <div class="tang">
      <div class="num">01</div>
      <div class="tang-content">
        <div class="tang-name">Hiểu Mình</div>
        <div class="tang-question">"Tôi là ai và tôi muốn phục vụ ai?"</div>
        <p class="tang-desc">Bắt đầu từ con người, không từ sản phẩm. Tìm Tầm Nhìn 5 năm, Năng lực lõi, Why Statement, Founder Identity, Customer Direction. Đây là nền tảng. Bỏ qua = xây nhà trên cát.</p>
        <div class="tang-output">
          <span>Vision 5 năm</span>
          <span>Why Statement</span>
          <span>Founder Identity</span>
          <span>Core Skills</span>
          <span>Customer Direction</span>
          <span>Founder Archetype</span>
        </div>
      </div>
    </div>

    <div class="tang">
      <div class="num">02</div>
      <div class="tang-content">
        <div class="tang-name">Hiểu Khách</div>
        <div class="tang-question">"Khách hàng của tôi thực sự cần gì?"</div>
        <p class="tang-desc">Biến Customer Direction thành Customer Intelligence sâu. Pain Map 6 trục, Desire Map 5 chiều, Transformation từ X đến Y, Opportunity Score 0 đến 100. Verify nhu cầu bằng data thật từ Google + YouTube + Trends.</p>
        <div class="tang-output">
          <span>Customer Profile</span>
          <span>Pain Map</span>
          <span>Desire Map</span>
          <span>Jobs To Be Done</span>
          <span>Opportunity Score</span>
          <span>Market Demand</span>
        </div>
      </div>
    </div>

    <div class="tang">
      <div class="num">03</div>
      <div class="tang-content">
        <div class="tang-name">Thiết Kế Hệ Thống</div>
        <div class="tang-question">"Tôi nên bán cái gì và bán như thế nào?"</div>
        <p class="tang-desc">Biến hiểu biết khách thành sản phẩm + cỗ máy bán hàng. Statement Một Dòng, Value Ladder 5 tầng, Lead Magnet, Funnel, Email automation, Sales pipeline, Payment system. Sẵn sàng nhận khách đầu tiên.</p>
        <div class="tang-output">
          <span>Statement Một Dòng</span>
          <span>Value Ladder</span>
          <span>Offer Stack</span>
          <span>Lead Magnet</span>
          <span>Funnel</span>
          <span>Email + CRM</span>
        </div>
      </div>
    </div>

    <div class="tang">
      <div class="num">04</div>
      <div class="tang-content">
        <div class="tang-name">Tăng Trưởng</div>
        <div class="tang-question">"Làm sao phát triển mà không kiệt sức?"</div>
        <p class="tang-desc">Biến kinh nghiệm thành lợi thế. AI COO báo mỗi sáng 3 việc cần làm. Knowledge System lưu mọi quyết định, webinar, coaching, feedback. Bộ Não Số riêng bạn. Founder Freedom Score tăng dần. Tự do thay vì kiệt sức.</p>
        <div class="tang-output">
          <span>AI COO daily</span>
          <span>Bộ Não Số</span>
          <span>Asset Vault</span>
          <span>Freedom Score</span>
          <span>Scale Coach</span>
          <span>Founder Dashboard</span>
        </div>
      </div>
    </div>

    <div class="tang">
      <div class="num">05</div>
      <div class="tang-content">
        <div class="tang-name">Nhân Bản</div>
        <div class="tang-question">"Làm sao tạo cơ hội cho người khác?"</div>
        <p class="tang-desc">Tầng cao nhất. Không còn là học, không còn là bán, không còn là kinh doanh cá nhân. Bạn xây hệ sinh thái: Member Directory, Opportunity Marketplace, AI Matching. Từ người đi tìm cơ hội thành người tạo cơ hội.</p>
        <div class="tang-output">
          <span>Member Directory</span>
          <span>Opportunity Marketplace</span>
          <span>AI Matching</span>
          <span>Trust Score</span>
          <span>Contribution Score</span>
        </div>
      </div>
    </div>
  </div>
</section>

<section class="alt">
  <div class="container">
    <div class="section-label">Bạn là ai trong 4 nhóm này</div>
    <h2 class="section-title">Founder Archetypes</h2>
    <p class="section-intro">BreakoutOS adapt theo bạn. Marketing copy + entry level + curriculum khác theo identity của bạn.</p>

    <div class="archetypes">
      <div class="arch">
        <h3>Corporate Escape</h3>
        <p>Nữ văn phòng 30 đến 45. Muốn thu nhập thứ 2, không quit job ngay.</p>
        <div class="hook">"Tự do tài chính + giữ family time"</div>
      </div>
      <div class="arch">
        <h3>Expert Founder</h3>
        <p>Đã có kỹ năng (TA, kế toán, HR, marketing, coaching). Muốn đóng gói thành sản phẩm.</p>
        <div class="hook">"Đóng gói kỹ năng thành SP 5 chữ số"</div>
      </div>
      <div class="arch">
        <h3>Store Owner</h3>
        <p>Đang bán hàng. Bận execute, không có time scale. Muốn hệ thống hoá.</p>
        <div class="hook">"Thoát đứng bán + AI thay 5 nhân viên"</div>
      </div>
      <div class="arch">
        <h3>Creator Founder</h3>
        <p>Đang làm content, có audience. Audience không convert revenue.</p>
        <div class="hook">"Audience đến revenue funnel"</div>
      </div>
    </div>
  </div>
</section>

<section>
  <div class="container">
    <div class="section-label">Khác biệt</div>
    <h2 class="section-title">BreakoutOS không phải LMS</h2>

    <div class="value-grid">
      <div class="value-card">
        <h4>Quản lý GOAL, không phải Lesson</h4>
        <p>LMS quản lý Course, Lesson, Assignment. BreakoutOS quản lý mục tiêu 90 ngày của bạn. AI Coach hỏi mỗi tuần: "Điều gì đưa bạn gần hơn mục tiêu?" thay vì "Bạn muốn học gì?"</p>
      </div>
      <div class="value-card">
        <h4>AI Coach nhớ bạn dài hạn</h4>
        <p>Không phải chatbot generic. AI nhớ toàn bộ vision, khách hàng, sản phẩm, quyết định của bạn. Bạn hỏi "Hằng đã quyết gì 3 tháng trước về X?" AI trả lời ngay.</p>
      </div>
      <div class="value-card">
        <h4>Asset Vault tích lũy</h4>
        <p>Mỗi bài làm trở thành 1 tài sản số. Sau 12 tháng bạn nhìn thấy: "Tôi đã tích luỹ 137 tài sản kinh doanh." Statement, Customer Profile, Offer, Funnel, SOP, AI Agent. Tất cả export Notion được, không lock-in.</p>
      </div>
      <div class="value-card">
        <h4>Founder Freedom Score</h4>
        <p>Hero metric đo mức tự do thật của bạn. 6 thành tố: Doanh thu, Thời gian, Stress, Clarity, Automation, Mission Alignment. Cập nhật mỗi tuần. Mục tiêu cuối không phải doanh thu cao. Là tự do nhiều.</p>
      </div>
    </div>
  </div>
</section>

<section class="alt" id="pricing">
  <div class="container">
    <div class="section-label">Lộ trình đầu tư</div>
    <h2 class="section-title">5 tier, 5 tầng access</h2>
    <p class="section-intro">Bắt đầu từ Foundation. Nâng cấp khi sẵn sàng.</p>

    <div style="display:flex;flex-wrap:wrap;justify-content:center;gap:14px;margin-top:36px;">
      <div class="pricing-tier" style="background:#fff5f5;color:#1a1a1a;border:2px solid #d63031;">
        <div class="label" style="color:#d63031;">Foundation Founding (100 slot)</div>
        <div class="name">L1 + L2</div>
        <div class="price" style="color:#d63031;"><s>3.000.000đ</s>1.500.000đ</div>
        <div class="meta" style="color:#555;">12 tuần · 100 founding student đầu tiên · Save 50%</div>
      </div>
    </div>
    <div style="text-align:center;margin-top:36px;">
      <a href="https://app.breakout.live/so-sanh?source=os_landing" class="btn-primary">Giữ 1 trong 100 slot Founding</a>
    </div>
  </div>
</section>

<section class="cta-section">
  <div class="container">
    <h2>Từ người đi tìm cơ hội. Trở thành người tạo cơ hội cho người khác.</h2>
    <p>Đó là đích đến cao nhất. Bạn không cần biết hết. Bạn cần bắt đầu từ Hiểu Mình.</p>
    <a href="https://app.breakout.live/so-sanh?source=os_landing_bottom" class="btn-primary">Vào Cohort 1 Founding</a>
  </div>
</section>

<footer>
  <div class="container footer-grid">
    <div class="brand-block">
      <h5>BreakoutOS</h5>
      <p>Founder Transformation Operating System.</p>
      <p>Một người - Một AI - Một Solo Business.</p>
      <p style="margin-top:14px;font-size:12px;opacity:0.6;">© 2026 Đào Thị Hằng, Pimpama, Gold Coast QLD, Australia</p>
    </div>
    <div>
      <h5>Hành trình</h5>
      <p><a href="#5-tang">5 tầng trưởng thành</a></p>
      <p><a href="#pricing">Lộ trình đầu tư</a></p>
      <p><a href="/cohort/">Vào hệ thống</a></p>
    </div>
    <div>
      <h5>Liên hệ</h5>
      <p>Zalo Hằng: 0932 093 593</p>
      <p>Email: hang@mail.daothihang.com</p>
      <p style="margin-top:14px;"><a href="/cohort/admin/dashboard">Admin login</a></p>
    </div>
  </div>
</footer>

</body>
</html>"""


def _render_landing_foundation() -> str:
    """Landing khoá Foundation với Digital Assets Foundation angle.

    Anna brief 2026-06-12: Foundation không chỉ là khoá học định hướng.
    Foundation là giai đoạn xây nền móng cho con người + cuộc sống + doanh nghiệp
    + hệ thống tri thức + tài sản số cá nhân.
    """
    return """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Foundation · Xây nền móng trước khi xây doanh thu | BreakoutOS</title>
<meta name="description" content="Nền Móng (Foundation) 7 ngày · 3 triệu · Hằng đồng hành trực tiếp. Khai giảng 22/6 lúc 5h sáng giờ Việt Nam. Xây xong Hệ Điều Hành Sáng Lập trong 1 tuần với Hằng.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root{
  --ink:#0a0a0a;--ink-soft:#2a2a2a;--paper:#fafaf7;--paper-warm:#f0ece0;
  --red:#d63031;--red-deep:#b71c1c;--accent:#d63031;
  --gold:#d4a24a;--gold-deep:#b8860b;
  --line:#e5dfd0;--muted:#5a5453;
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-font-smoothing:antialiased}
body{font-family:'Be Vietnam Pro',-apple-system,sans-serif;line-height:1.75;color:var(--ink);background:var(--paper);font-weight:400;font-size:18px}
.container{max-width:920px;margin:0 auto;padding:0 24px}
h1,h2,h3,h4{font-weight:800;line-height:1.22}
h1{font-size:54px;letter-spacing:-0.8px}
h2{font-size:38px;letter-spacing:-0.4px;margin-bottom:20px}
h3{font-size:24px;margin-bottom:12px}
a{color:var(--red);text-decoration:none}
.btn-primary{display:inline-block;background:var(--red);color:#fff;padding:22px 40px;border-radius:14px;font-weight:800;font-size:20px;box-shadow:0 8px 28px rgba(214,48,49,0.35);transition:transform 0.15s,background 0.15s;letter-spacing:0.2px}
.btn-primary:hover{transform:translateY(-2px);background:var(--red-deep)}
.btn-gold{background:var(--red)}
.btn-gold:hover{background:var(--red-deep)}
.tag{display:inline-block;background:rgba(214,48,49,0.12);color:var(--red);padding:8px 18px;border-radius:999px;font-size:12px;letter-spacing:1.8px;text-transform:uppercase;font-weight:800;margin-bottom:18px}
.en{font-size:0.7em;color:var(--muted);font-weight:500;letter-spacing:normal;text-transform:none;margin-left:4px;font-style:italic}
.os-pillar .en,.vault-card .en,.canonical-card .en,.step .en{color:rgba(255,255,255,0.55);font-weight:500;font-style:italic}
.vault-card .en,.canonical-card .en,.step .en{color:var(--muted)}

section{padding:90px 0;border-bottom:1px solid var(--line)}
.hero{background:linear-gradient(180deg,#fff,#f5f0e3);padding:100px 0 80px;text-align:center}
.hero h1{margin-bottom:22px}
.hero .sub{font-size:22px;color:var(--ink-soft);max-width:680px;margin:0 auto 36px;line-height:1.55}
.hero .meta{font-size:16px;color:var(--muted);margin-top:22px}

.problem{background:#0a0a0a;color:#fff}
.problem h2{color:#fff;text-align:center;margin-bottom:44px;max-width:760px;margin-left:auto;margin-right:auto}
.problem .lede{font-size:20px;text-align:center;opacity:0.9;max-width:720px;margin:0 auto 56px;line-height:1.65}
.scenes{display:grid;gap:18px;max-width:720px;margin:0 auto}
.scene{background:rgba(255,255,255,0.05);border-left:4px solid var(--red);padding:22px 26px;border-radius:0 14px 14px 0}
.scene .act{display:block;font-size:14px;color:var(--red);letter-spacing:1.5px;text-transform:uppercase;font-weight:800;margin-bottom:6px}
.scene .result{font-size:20px;font-weight:600;line-height:1.45}
.problem .punch{text-align:center;font-size:26px;font-weight:800;margin-top:60px;line-height:1.4}
.problem .punch span{color:var(--red)}

.insight{background:var(--paper-warm);text-align:center}
.insight h2{max-width:780px;margin:0 auto 28px}
.insight .body{font-size:21px;max-width:680px;margin:0 auto;color:var(--ink-soft);line-height:1.7}
.insight .body p{margin-bottom:16px}
.insight .highlight{background:#fff;border:3px solid var(--red);border-radius:20px;padding:32px 36px;margin:40px auto 0;max-width:640px;font-size:23px;font-weight:700;line-height:1.5}

.vaults h2{text-align:center;margin-bottom:16px}
.vaults .lede{text-align:center;color:var(--ink-soft);max-width:680px;margin:0 auto 56px;font-size:19px;line-height:1.6}
.vault-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}
.vault-card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:28px 30px;transition:transform 0.15s,box-shadow 0.15s}
.vault-card:hover{transform:translateY(-4px);box-shadow:0 14px 36px rgba(0,0,0,0.08)}
.vault-card .num{display:inline-block;width:40px;height:40px;border-radius:50%;background:var(--red);color:#fff;text-align:center;line-height:40px;font-weight:800;font-size:16px;margin-bottom:16px}
.vault-card h3{font-size:22px;margin-bottom:10px}
.vault-card p{font-size:17px;color:var(--ink-soft);line-height:1.6}

.mantra{background:linear-gradient(135deg,#1a1a1a,#2d2d2d);color:#fff;text-align:center;padding:100px 0}
.mantra .lines{font-size:36px;font-weight:800;line-height:1.55}
.mantra .lines span{display:block;color:var(--red)}

.tools{background:#fff}
.tools h2{text-align:center;margin-bottom:46px}
.tools-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;max-width:760px;margin:0 auto}
.tool{display:flex;align-items:center;gap:16px;background:var(--paper);border-radius:14px;padding:20px 24px;border:1px solid var(--line)}
.tool .dot{width:10px;height:10px;border-radius:50%;background:var(--red);flex-shrink:0}
.tool strong{font-size:18px}
.tool small{display:block;color:var(--muted);font-size:15px;margin-top:3px;line-height:1.5}

.why-ai{background:var(--paper-warm)}
.why-ai h2{text-align:center;margin-bottom:36px;max-width:760px;margin-left:auto;margin-right:auto}
.why-ai .body{max-width:720px;margin:0 auto;font-size:20px;color:var(--ink-soft);line-height:1.7}
.why-ai .body p{margin-bottom:16px}
.why-ai .body strong{color:var(--ink)}

.foundation-5{background:#fff;text-align:center}
.foundation-5 h2{margin-bottom:16px}
.foundation-5 .lede{color:var(--ink-soft);max-width:640px;margin:0 auto 56px;font-size:19px;line-height:1.6}
.pillars{display:grid;grid-template-columns:repeat(5,1fr);gap:16px;max-width:860px;margin:0 auto}
.pillar{background:var(--paper);border-radius:14px;padding:26px 14px;border:1px solid var(--line)}
.pillar .num{font-size:30px;font-weight:800;color:var(--red);margin-bottom:8px}
.pillar h3{font-size:16px;margin-bottom:0;line-height:1.3}

.pricing{background:linear-gradient(180deg,#0a0a0a,#1a1a1a);color:#fff;text-align:center}
.pricing h2{color:#fff;margin-bottom:16px}
.pricing .lede{opacity:0.85;max-width:620px;margin:0 auto 48px;font-size:19px;line-height:1.6}
.price-card{background:rgba(255,255,255,0.04);border:3px solid var(--red);border-radius:24px;padding:48px 40px;max-width:540px;margin:0 auto}
.price-card .tier{font-size:14px;letter-spacing:2.5px;text-transform:uppercase;color:var(--red);font-weight:800;margin-bottom:10px}
.price-card h3{font-size:32px;color:#fff;margin-bottom:22px}
.price-card .price-row{display:flex;align-items:baseline;justify-content:center;gap:10px;margin-bottom:10px}
.price-card .new{font-size:60px;font-weight:800;color:#fff;letter-spacing:-1.5px}
.price-card .meta{font-size:16px;color:rgba(255,255,255,0.75);margin-bottom:28px}
.price-card .includes{text-align:left;background:rgba(0,0,0,0.3);border-radius:14px;padding:22px 26px;margin-bottom:28px}
.price-card .includes li{padding:7px 0;font-size:16px;color:rgba(255,255,255,0.9);list-style:none;display:flex;align-items:flex-start;gap:12px;line-height:1.55}
.price-card .includes li::before{content:"✓";color:var(--red);font-weight:800;flex-shrink:0;font-size:18px}

.cta-final{background:#fff;text-align:center}
.cta-final h2{margin-bottom:22px;max-width:760px;margin-left:auto;margin-right:auto}
.cta-final p{font-size:20px;color:var(--ink-soft);max-width:640px;margin:0 auto 36px;line-height:1.65}

/* Section 4: Founder Foundation (8 canonical files - PHẦN TRUNG TÂM) */
.founder-foundation{background:#fff}
.founder-foundation h2{text-align:center;margin-bottom:18px}
.founder-foundation .lede{text-align:center;color:var(--ink-soft);max-width:720px;margin:0 auto 56px;font-size:20px;line-height:1.65}
.canonical-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:22px}
.canonical-card{background:var(--paper);border-left:5px solid var(--red);border-radius:0 18px 18px 0;padding:28px 30px;transition:transform 0.15s,box-shadow 0.15s}
.canonical-card:hover{transform:translateY(-3px);box-shadow:0 12px 32px rgba(0,0,0,0.08)}
.canonical-card .num{display:inline-block;width:42px;height:42px;border-radius:50%;background:var(--red);color:#fff;text-align:center;line-height:42px;font-weight:800;font-size:18px;margin-bottom:16px}
.canonical-card h3{font-size:24px;margin-bottom:10px;color:var(--ink)}
.canonical-card p{font-size:17px;color:var(--ink-soft);line-height:1.6}

/* Section schedule: lịch 7 ngày với Hằng */
.schedule{background:linear-gradient(135deg,#0a0a0a,#1c1c1c);color:#fff}
.schedule h2{color:#fff;text-align:center;margin-bottom:18px}
.schedule .lede{text-align:center;opacity:0.88;max-width:780px;margin:0 auto 56px;font-size:20px;line-height:1.65;color:rgba(255,255,255,0.92)}
.schedule-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;max-width:980px;margin:0 auto}
.day-card{background:rgba(255,255,255,0.04);border:1px solid rgba(214,48,49,0.25);border-radius:16px;padding:24px 22px}
.day-card.highlight-day{background:rgba(214,48,49,0.12);border:2px solid var(--red);grid-column:span 3}
.day-num{display:inline-block;background:var(--red);color:#fff;font-size:13px;font-weight:800;letter-spacing:1.5px;padding:5px 14px;border-radius:999px;margin-bottom:10px}
.day-when{font-size:14px;color:rgba(255,255,255,0.6);margin-bottom:14px;font-weight:600}
.day-card h3{color:#fff;font-size:21px;margin-bottom:10px}
.day-card p{color:rgba(255,255,255,0.85);font-size:16px;line-height:1.6}
.highlight-day h3{font-size:24px}
.highlight-day p{font-size:18px}
.schedule-summary{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;max-width:880px;margin:60px auto 0}
.summary-item{text-align:center;padding:24px 16px;background:rgba(255,255,255,0.04);border-radius:14px;border:1px solid rgba(255,255,255,0.08)}
.summary-num{font-size:54px;font-weight:800;color:var(--red);line-height:1;margin-bottom:8px}
.summary-label{font-size:15px;color:rgba(255,255,255,0.85);line-height:1.5;font-weight:600}
.reassure-box{max-width:780px;margin:0 auto 50px;background:rgba(214,48,49,0.12);border-left:4px solid var(--red);border-radius:0 14px 14px 0;padding:22px 26px}
.reassure-box p{font-size:18px;color:rgba(255,255,255,0.92);line-height:1.65;margin:0}
.reassure-box strong{color:#fff;font-weight:700}

/* Section 5: Business Foundation (4 câu hỏi định hướng) */
.business-foundation{background:var(--paper-warm)}
.business-foundation h2{text-align:center;margin-bottom:18px}
.business-foundation .lede{text-align:center;color:var(--ink-soft);max-width:760px;margin:0 auto 56px;font-size:20px;line-height:1.65}
.biz-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:22px;max-width:820px;margin:0 auto}
.biz-card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:32px 30px}
.biz-card h3{font-size:22px;margin-bottom:14px;color:var(--red);line-height:1.35}
.biz-card p{font-size:17px;color:var(--ink-soft);line-height:1.65}

/* Section 7: Founder Operating System (kết quả) */
.founder-os{background:linear-gradient(135deg,#0a0a0a,#1c1c1c);color:#fff;text-align:center}
.founder-os h2{color:#fff;margin-bottom:18px}
.founder-os .lede{opacity:0.85;max-width:720px;margin:0 auto 56px;font-size:20px;line-height:1.65}
.os-pillars{display:grid;grid-template-columns:repeat(2,1fr);gap:22px;max-width:860px;margin:0 auto}
.os-pillar{background:rgba(255,255,255,0.05);border:1px solid rgba(214,48,49,0.3);border-radius:18px;padding:32px 28px;text-align:left}
.os-pillar .os-num{display:inline-block;width:42px;height:42px;border-radius:50%;background:var(--red);color:#fff;text-align:center;line-height:42px;font-weight:800;font-size:18px;margin-bottom:16px}
.os-pillar h3{color:#fff;font-size:22px;margin-bottom:10px}
.os-pillar p{color:rgba(255,255,255,0.85);font-size:17px;line-height:1.6}

/* Section 8: Deliverables (bảng nhận được gì cụ thể) */
.deliverables{background:#fff}
.deliverables h2{text-align:center;margin-bottom:50px}
.deliv-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}
.deliv-block{background:var(--paper);border-radius:16px;padding:28px 24px;border:1px solid var(--line)}
.deliv-num{font-size:48px;font-weight:800;color:var(--red);line-height:1;margin-bottom:10px}
.deliv-label{font-size:18px;font-weight:700;color:var(--ink);margin-bottom:10px;line-height:1.3}
.deliv-detail{font-size:15px;color:var(--ink-soft);line-height:1.6}

/* Section 9: Founder Story Hằng */
.founder-story-hang{background:var(--paper-warm)}
.founder-story-hang h2{text-align:center;margin-bottom:40px;max-width:780px;margin-left:auto;margin-right:auto}
.story-body{max-width:680px;margin:0 auto;font-size:19px;color:var(--ink-soft);line-height:1.75}
.story-body p{margin-bottom:18px}
.story-body strong{color:var(--ink);font-weight:700}

/* Section 10: Curriculum (6 tầng BreakoutOS) */
.curriculum{background:#fff}
.curriculum h2{text-align:center;margin-bottom:18px}
.curriculum .lede{text-align:center;color:var(--ink-soft);max-width:720px;margin:0 auto 56px;font-size:19px;line-height:1.65}
.curriculum-steps{display:grid;grid-template-columns:repeat(2,1fr);gap:20px;max-width:880px;margin:0 auto}
.step{background:var(--paper);border-radius:16px;padding:24px 26px;border:1px solid var(--line);position:relative}
.step.active{background:#fff;border:2px solid var(--red);box-shadow:0 8px 24px rgba(214,48,49,0.12)}
.step.active::after{content:"Bạn đang ở đây";position:absolute;top:-12px;right:18px;background:var(--red);color:#fff;font-size:12px;font-weight:800;padding:5px 12px;border-radius:999px;letter-spacing:0.5px}
.step-week{font-size:13px;font-weight:800;color:var(--red);letter-spacing:1.5px;text-transform:uppercase;margin-bottom:8px}
.step h3{font-size:20px;margin-bottom:8px;color:var(--ink)}
.step p{font-size:16px;color:var(--ink-soft);line-height:1.55}

footer{background:#0a0a0a;color:#fff;padding:60px 0 50px;font-size:16px}
footer a{color:rgba(255,255,255,0.75)}
footer .footer-grid{display:grid;grid-template-columns:2fr 1fr 1fr;gap:34px}
footer h5{color:var(--red);font-size:14px;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:16px;font-weight:800}

@media(max-width:680px){
  body{font-size:17px}
  h1{font-size:38px}
  h2{font-size:28px}
  h3{font-size:20px}
  .hero{padding:70px 0 60px}
  .hero .sub{font-size:19px}
  .btn-primary{font-size:18px;padding:20px 30px;display:block;width:100%}
  .vault-grid{grid-template-columns:1fr}
  .canonical-grid{grid-template-columns:1fr}
  .biz-grid{grid-template-columns:1fr}
  .schedule-grid{grid-template-columns:1fr}
  .day-card.highlight-day{grid-column:span 1}
  .schedule-summary{grid-template-columns:repeat(2,1fr)}
  .summary-num{font-size:40px}
  .os-pillars{grid-template-columns:1fr}
  .deliv-grid{grid-template-columns:1fr}
  .curriculum-steps{grid-template-columns:1fr}
  .tools-grid{grid-template-columns:1fr}
  .pillars{grid-template-columns:repeat(2,1fr)}
  .price-card{padding:36px 24px}
  .price-card .new{font-size:48px}
  footer .footer-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>

<section class="hero">
  <div class="container">
    <div class="tag">BreakoutOS · Tầng 1 · Hiểu Mình (Founder OS)</div>
    <h1>Chỉ 1 tuần<br>là xây xong Foundation, với Hằng.</h1>
    <p class="sub">Bạn không biết nên bán gì. Bạn không biết nên phục vụ ai. Bạn không biết mình thực sự muốn xây cuộc đời như thế nào.<br><br>7 ngày tới, Hằng đồng hành trực tiếp cùng bạn xây hệ điều hành đầu tiên cho chính mình.</p>
    <a href="https://app.breakout.live/thanh-toan.html?product=foundation&source=foundation_landing" class="btn-primary btn-gold">Đăng ký Foundation 3 triệu →</a>
    <p class="meta"><strong>Khai giảng Thứ Hai 22/6 lúc 5h sáng giờ Việt Nam</strong><br>Có video quay lại nếu bạn không tham gia LIVE được</p>
  </div>
</section>

<section class="problem">
  <div class="container">
    <h2>Bạn không thiếu nỗ lực.<br>Bạn thiếu sự rõ ràng.</h2>
    <p class="lede">Bạn đang làm việc rất chăm chỉ. Đọc sách, xem video, học khoá này khoá kia, thử mô hình này mô hình khác. Nhưng vẫn cảm thấy mình đang đứng yên. Không phải vì bạn lười. Mà vì bạn đang xây mọi thứ trên một nền móng chưa được làm rõ.</p>

    <div class="scenes">
      <div class="scene"><span class="act">Học rồi quên</span><div class="result">Khoá học, sách, video tích luỹ nhiều nhưng không áp dụng được vào việc của mình.</div></div>
      <div class="scene"><span class="act">Làm rồi bỏ</span><div class="result">Bắt đầu một ý tưởng, vài tuần sau dừng lại, không hiểu vì sao mình không tiếp tục.</div></div>
      <div class="scene"><span class="act">Đổi hướng liên tục</span><div class="result">Tháng này thử coaching, tháng sau thử bán hàng, năm sau lại nhảy sang mảng khác.</div></div>
      <div class="scene"><span class="act">Theo trend liên tục</span><div class="result">Thấy ai làm AI thì làm AI. Thấy ai làm TikTok thì làm TikTok. Rồi không cái nào ra kết quả.</div></div>
      <div class="scene"><span class="act">Không có phương hướng</span><div class="result">Mọi quyết định đều mất nhiều giờ. Cuối ngày mệt nhưng không nhớ mình đã quyết được gì.</div></div>
      <div class="scene"><span class="act">Không chắc mình muốn gì</span><div class="result">Đang xây doanh nghiệp nhưng không chắc đó có phải cuộc sống mình muốn 10 năm tới.</div></div>
    </div>

    <p class="punch">Bạn không phải đang tiến lên.<br><span>Bạn đang liên tục bắt đầu lại từ số 0.</span></p>
  </div>
</section>

<section class="insight">
  <div class="container">
    <div class="tag">Insight</div>
    <h2>Phần lớn người làm kinh doanh<br>xây mọi thứ theo thứ tự ngược.</h2>
    <div class="body">
      <p>Họ xây <strong>website</strong> trước khi biết mình là ai.</p>
      <p>Họ xây <strong>fanpage</strong> trước khi biết mình phục vụ ai.</p>
      <p>Họ chạy <strong>quảng cáo</strong> trước khi biết mình bán cái gì.</p>
      <p>Họ cài <strong>CRM</strong> trước khi biết mình muốn xây loại doanh nghiệp gì.</p>
      <p style="margin-top:22px">Đó là lý do càng đi càng rối.</p>
    </div>
    <div class="highlight">Đúng thứ tự phải là:<br>Con người trước. Cuộc sống trước. Doanh nghiệp trước.<br>Sau đó mới tới công cụ và tri thức.</div>
  </div>
</section>

<section class="founder-foundation">
  <div class="container">
    <div class="tag" style="display:block;text-align:center">Phần 1 · Nền Móng Sáng Lập (Founder Foundation)</div>
    <h2>Trong 7 ngày,<br>bạn xây 8 nền móng cho chính con người mình.</h2>
    <p class="lede">Đây là phần trung tâm của khoá học. Bạn sẽ trả lời 3 câu hỏi gốc rễ: Tôi là ai? Tôi tồn tại để làm gì? Tôi muốn phục vụ ai? Hằng dạy lý thuyết trực tiếp sáng Hai, Tư, Sáu và xem lại + triển khai cùng bạn Chủ nhật. Khi 3 câu gốc rễ này rõ, mọi quyết định kinh doanh phía sau trở nên đơn giản.</p>

    <div class="canonical-grid">
      <div class="canonical-card">
        <div class="num">1</div>
        <h3>Sứ Mệnh Đời <span class="en">(Life Mission)</span></h3>
        <p>Lý do bạn tồn tại trong 10 đến 20 năm tới. Sứ mệnh đời không phụ thuộc bạn đang kinh doanh gì hôm nay. Có thể đổi nghề, đổi sản phẩm, nhưng sứ mệnh đời thì còn nguyên.</p>
      </div>
      <div class="canonical-card">
        <div class="num">2</div>
        <h3>Tầm Nhìn 5 Năm <span class="en">(Vision Statement)</span></h3>
        <p>Bức tranh cuộc sống cụ thể bạn muốn nhìn thấy 5 năm tới. Tầm nhìn có thể đổi khi bạn lớn lên, nhưng phải rõ để mọi việc hôm nay có hướng đi.</p>
      </div>
      <div class="canonical-card">
        <div class="num">3</div>
        <h3>Bản Sắc Sáng Lập <span class="en">(Founder Identity)</span></h3>
        <p>Bạn là ai. Giá trị cốt lõi. Năng lực độc nhất. Loại người sáng lập bạn thực sự là (không phải loại bạn nghĩ mình nên là). Đây là gốc của mọi định vị thương hiệu sau này.</p>
      </div>
      <div class="canonical-card">
        <div class="num">4</div>
        <h3>Nguyên Tắc Quyết Định <span class="en">(Decision Principles)</span></h3>
        <p>5 đến 7 nguyên tắc sống giúp bạn ra quyết định nhanh. Khi có nguyên tắc rõ, bạn không còn mất nhiều giờ cân nhắc mỗi việc nhỏ.</p>
      </div>
      <div class="canonical-card">
        <div class="num">5</div>
        <h3>Điều Tôi Không Muốn <span class="en">(Anti Vision)</span></h3>
        <p>Những điều bạn KHÔNG muốn trở thành. Không muốn có đội ngũ 50 người. Không muốn làm việc 12 giờ một ngày. Không muốn phụ thuộc quảng cáo. Điều không muốn lọc cơ hội tốt hơn cả tầm nhìn.</p>
      </div>
      <div class="canonical-card">
        <div class="num">6</div>
        <h3>Lý Do Cốt Lõi <span class="en">(Why Statement)</span></h3>
        <p>Tại sao bạn làm điều này. Lý do sâu hơn tiền. Khi bạn gặp khó khăn, lý do cốt lõi là thứ duy nhất giữ bạn lại với hành trình.</p>
      </div>
      <div class="canonical-card">
        <div class="num">7</div>
        <h3>Tài Sản Sáng Lập <span class="en">(Founder Assets)</span></h3>
        <p>Tài sản bạn đã tích luỹ trong đời. Kiến thức, kinh nghiệm, chứng chỉ, mối quan hệ, kỹ năng, câu chuyện. Đây là nguyên liệu bạn dùng để xây doanh nghiệp, không phải bắt đầu từ con số 0.</p>
      </div>
      <div class="canonical-card">
        <div class="num">8</div>
        <h3>Câu Chuyện Sáng Lập <span class="en">(Founder Story)</span></h3>
        <p>Câu chuyện hình thành con người bạn. Xuất phát điểm. Bước ngoặt. Hành trình. Câu chuyện sáng lập là tài sản marketing mạnh nhất, sống cùng bạn suốt đời.</p>
      </div>
    </div>
  </div>
</section>

<section class="schedule">
  <div class="container">
    <div class="tag" style="display:block;text-align:center">Lịch học 7 ngày · Khai giảng 22/6/2026</div>
    <h2>3 buổi sáng học lý thuyết.<br>1 ngày Chủ nhật triển khai cùng Hằng.</h2>
    <p class="lede">3 ngày trong tuần (Hai, Tư, Sáu) Hằng dạy lý thuyết LIVE lúc 5h sáng giờ Việt Nam. Có video quay lại đầy đủ nếu bạn không tham gia được. Chủ nhật là ngày Hằng cùng bạn review và triển khai, đồng thời là backup cho ai chưa xây xong Foundation trong tuần.</p>

    <div class="reassure-box">
      <p><strong>Hầu hết học viên xem video lý thuyết là đã có thể tự làm được</strong>. Chủ nhật là ngày dành riêng để Hằng hỗ trợ trực tiếp những ai cần thêm thời gian, hoặc gặp khó khăn ở một file canonical nào đó.</p>
    </div>

    <div class="schedule-grid">
      <div class="day-card highlight-day">
        <div class="day-num">Ngày 1 · Khai giảng</div>
        <div class="day-when">Thứ Hai 22/6 · 5h sáng giờ Việt Nam</div>
        <h3>Buổi lý thuyết 1 · Life Mission + Vision</h3>
        <p>Hằng LIVE chia sẻ cách làm rõ sứ mệnh 10-20 năm và tầm nhìn 5 năm. Bạn nghe + ghi chép trong 1h30 phút, sau đó tự làm bài về nhà. Có video quay lại nếu vắng mặt.</p>
      </div>
      <div class="day-card">
        <div class="day-num">Ngày 2</div>
        <div class="day-when">Thứ Ba · tự làm bài</div>
        <h3>Bài tập Anti Vision + Why</h3>
        <p>Tự viết những điều bạn KHÔNG muốn trở thành. Tự viết lý do sâu hơn tiền. Submit qua app, AI review trước khi Chủ nhật chốt.</p>
      </div>
      <div class="day-card">
        <div class="day-num">Ngày 3</div>
        <div class="day-when">Thứ Tư · 5h sáng giờ Việt Nam</div>
        <h3>Buổi lý thuyết 2 · Founder Identity + Decision Principles</h3>
        <p>Hằng LIVE hướng dẫn cách làm rõ giá trị cốt lõi, năng lực độc nhất, 5 đến 7 nguyên tắc sống. Có video quay lại.</p>
      </div>
      <div class="day-card">
        <div class="day-num">Ngày 4</div>
        <div class="day-when">Thứ Năm · tự làm bài</div>
        <h3>Bài tập Founder Assets</h3>
        <p>Liệt kê tài sản tích luỹ trong đời. Kiến thức, kinh nghiệm, chứng chỉ, network. AI extract giúp bạn không bỏ sót gì.</p>
      </div>
      <div class="day-card">
        <div class="day-num">Ngày 5</div>
        <div class="day-when">Thứ Sáu · 5h sáng giờ Việt Nam</div>
        <h3>Buổi lý thuyết 3 · Founder Story 3 hồi</h3>
        <p>Hằng LIVE hướng dẫn cách dựng câu chuyện founder. Xuất phát điểm, bước ngoặt, hành trình. Đây là tài sản marketing mạnh nhất của bạn. Có video quay lại.</p>
      </div>
      <div class="day-card">
        <div class="day-num">Ngày 6</div>
        <div class="day-when">Thứ Bảy · nghỉ ngấm</div>
        <h3>Để mọi thứ ngấm</h3>
        <p>Một ngày không học. Để những gì đã làm 5 ngày qua ngấm vào tiềm thức. Sáng Chủ nhật bạn quay lại với góc nhìn rõ hơn.</p>
      </div>
      <div class="day-card highlight-day">
        <div class="day-num">Ngày 7 · Triển khai</div>
        <div class="day-when">Chủ nhật · review + triển khai + backup</div>
        <h3>Review và triển khai cùng Hằng</h3>
        <p>Chủ nhật là ngày Hằng cùng bạn xem lại 8 tài liệu gốc đã viết và trả lời 4 câu hỏi định hướng kinh doanh. Đây cũng là ngày dự phòng cho những ai chưa xây xong Nền Móng trong tuần. Cuối ngày bạn rời khoá học với Hệ Điều Hành Sáng Lập hoàn chỉnh.</p>
      </div>
    </div>

    <div class="schedule-summary">
      <div class="summary-item"><div class="summary-num">3</div><div class="summary-label">buổi lý thuyết LIVE<br>(2 - 4 - 6, có video)</div></div>
      <div class="summary-item"><div class="summary-num">1</div><div class="summary-label">Chủ nhật review<br>và triển khai cùng Hằng</div></div>
      <div class="summary-item"><div class="summary-num">7</div><div class="summary-label">ngày<br>để ra output thật</div></div>
      <div class="summary-item"><div class="summary-num">8</div><div class="summary-label">tài liệu gốc<br>đã chốt cuối tuần</div></div>
    </div>
  </div>
</section>

<section class="business-foundation">
  <div class="container">
    <div class="tag" style="display:block;text-align:center">Phần 2 · Nền Móng Kinh Doanh (Business Foundation)</div>
    <h2>Khi đã hiểu mình rõ,<br>việc chọn hướng kinh doanh trở nên đơn giản.</h2>
    <p class="lede">Đây là phần Foundation giúp bạn trả lời 4 câu hỏi định hướng. Không phải tư vấn từ ngoài. Không phải lời khuyên chung chung. Mà là quyết định bạn tự đưa ra dựa trên 8 nền móng cá nhân vừa xây ở Phần 1.</p>

    <div class="biz-grid">
      <div class="biz-card">
        <h3>Tôi nên phục vụ ai?</h3>
        <p>Nhóm khách hàng nào phù hợp với năng lực, giá trị, và cuộc sống bạn muốn. Không phải nhóm nào trả tiền cao nhất, mà nhóm nào bạn có thể phục vụ tốt nhất trong 10 năm tới.</p>
      </div>
      <div class="biz-card">
        <h3>Tôi có quyền phục vụ ai nhất?</h3>
        <p>Có những nhóm khách hàng bạn có quyền phục vụ hơn người khác, vì bạn đã trải qua nỗi đau của họ, có bằng chứng cụ thể, có sự kết nối tự nhiên. Bạn sẽ tìm ra nhóm này.</p>
      </div>
      <div class="biz-card">
        <h3>Tôi nên bắt đầu với mô hình nào?</h3>
        <p>Coaching, dịch vụ, sản phẩm số, cộng đồng, hay phối hợp. Mô hình nào phù hợp với năng lực + cuộc sống + tài sản hiện có của bạn.</p>
      </div>
      <div class="biz-card">
        <h3>Tôi nên xây loại doanh nghiệp nào?</h3>
        <p>Solo với AI. Hay đội ngũ tinh gọn. Hay scale. Mỗi loại doanh nghiệp đi kèm một cuộc sống khác nhau. Bạn cần biết loại nào hợp với mình trước khi chạy vào nó.</p>
      </div>
    </div>

    <p style="text-align:center;margin-top:40px;font-size:19px;color:var(--ink-soft);max-width:680px;margin-left:auto;margin-right:auto;line-height:1.65">Phần 1 trả lời <strong>Bạn là ai</strong>. Phần 2 trả lời <strong>Bạn nên xây gì</strong>. Đây là 2 phần không thể tách rời.</p>
  </div>
</section>

<section class="vaults">
  <div class="container">
    <div class="tag" style="display:block;text-align:center">Phần 3 · Nền Móng Tài Sản Số (Digital Assets Foundation)</div>
    <h2>Mọi thứ bạn xây trong Phần 1 và Phần 2<br>được lưu lại thành tài sản số.</h2>
    <p class="lede">Đây là phần công cụ. Không phải mục tiêu cuối cùng. Mục tiêu cuối cùng là Bản Sắc Sáng Lập và Định Hướng Kinh Doanh rõ ràng. Các kho chỉ là nơi lưu giữ những gì bạn vừa xây, để không bao giờ bị thất thoát.</p>

    <div class="vault-grid">
      <div class="vault-card">
        <div class="num">1</div>
        <h3>Bộ Não Thứ Hai <span class="en">(Second Brain)</span></h3>
        <p>Ý tưởng và ghi chú đời sống được lưu có cấu trúc, không trôi đi như mảnh giấy nhớ rời.</p>
      </div>
      <div class="vault-card">
        <div class="num">2</div>
        <h3>Kho Tri Thức <span class="en">(Knowledge Vault)</span></h3>
        <p>Sách, khoá học, video, bài nói chuyện được tóm tắt và tra cứu lại bất cứ lúc nào qua AI.</p>
      </div>
      <div class="vault-card">
        <div class="num">3</div>
        <h3>Kho Kinh Doanh <span class="en">(Business Vault)</span></h3>
        <p>Nơi lưu 8 tài liệu gốc Nền Móng Sáng Lập và mọi quyết định kinh doanh của bạn.</p>
      </div>
      <div class="vault-card">
        <div class="num">4</div>
        <h3>Kho Khách Hàng <span class="en">(Customer Vault)</span></h3>
        <p>Ghi chú khách hàng được giữ lại để AI hiểu khách của bạn ngày càng sâu theo thời gian.</p>
      </div>
      <div class="vault-card">
        <div class="num">5</div>
        <h3>Kho Nội Dung <span class="en">(Content Vault)</span></h3>
        <p>Bài viết, email, video đã làm được phân loại để tái sử dụng nhiều lần, không phải bắt đầu lại từ đầu mỗi ý.</p>
      </div>
      <div class="vault-card">
        <div class="num">6</div>
        <h3>Kho Học Tập <span class="en">(Learning Vault)</span></h3>
        <p>Buổi tư vấn, hội thảo, ngộ ra cá nhân được lưu cùng AI sinh đôi của bạn để tra cứu khi cần.</p>
      </div>
    </div>
  </div>
</section>

<section class="founder-os">
  <div class="container">
    <div class="tag" style="display:block;text-align:center">Kết quả · Hệ Điều Hành Sáng Lập (Founder Operating System)</div>
    <h2>Sau 7 ngày,<br>bạn sở hữu một Hệ Điều Hành Sáng Lập cá nhân.</h2>
    <p class="lede">Đây không phải khoá học bạn học xong rồi thôi. Đây là một hệ điều hành cá nhân chạy cùng bạn suốt đời. Khi bạn lớn lên, hệ điều hành lớn lên cùng bạn.</p>

    <div class="os-pillars">
      <div class="os-pillar">
        <div class="os-num">1</div>
        <h3>Bản Sắc Sáng Lập <span class="en">(Founder Identity)</span></h3>
        <p>Bạn biết rõ mình là ai, tồn tại để làm gì, và muốn trở thành ai.</p>
      </div>
      <div class="os-pillar">
        <div class="os-num">2</div>
        <h3>Định Hướng Kinh Doanh <span class="en">(Business Direction)</span></h3>
        <p>Bạn biết rõ nên phục vụ ai, bán gì, và xây loại doanh nghiệp nào.</p>
      </div>
      <div class="os-pillar">
        <div class="os-num">3</div>
        <h3>Hệ Thống Tri Thức <span class="en">(Knowledge System)</span></h3>
        <p>Bạn có hệ thống lưu trữ tri thức cá nhân. Học một lần. Dùng nhiều lần.</p>
      </div>
      <div class="os-pillar">
        <div class="os-num">4</div>
        <h3>Hệ Thống Tài Sản Số <span class="en">(Digital Assets System)</span></h3>
        <p>Bạn có kho tài sản số chạy cùng AI, ngày càng giàu theo thời gian.</p>
      </div>
    </div>
  </div>
</section>

<section class="deliverables">
  <div class="container">
    <h2>Bạn nhận được gì cụ thể trong Foundation</h2>
    <div class="deliv-grid">
      <div class="deliv-block">
        <div class="deliv-num">8</div>
        <div class="deliv-label">Tài liệu gốc Nền Móng Sáng Lập</div>
        <div class="deliv-detail">Sứ Mệnh Đời, Tầm Nhìn, Bản Sắc Sáng Lập, Nguyên Tắc Quyết Định, Điều Tôi Không Muốn, Lý Do Cốt Lõi, Tài Sản Sáng Lập, Câu Chuyện Sáng Lập.</div>
      </div>
      <div class="deliv-block">
        <div class="deliv-num">4</div>
        <div class="deliv-label">Câu trả lời Định Hướng Kinh Doanh</div>
        <div class="deliv-detail">Phục vụ ai. Có quyền phục vụ ai nhất. Mô hình kinh doanh phù hợp. Loại doanh nghiệp muốn xây.</div>
      </div>
      <div class="deliv-block">
        <div class="deliv-num">6</div>
        <div class="deliv-label">Kho tri thức cá nhân</div>
        <div class="deliv-detail">Bộ Não Thứ Hai, Kho Tri Thức, Kho Kinh Doanh, Kho Khách Hàng, Kho Nội Dung, Kho Học Tập. Có sẵn mẫu Hằng thiết kế.</div>
      </div>
      <div class="deliv-block">
        <div class="deliv-num">1</div>
        <div class="deliv-label">Kho Tri Thức AI 12 tháng</div>
        <div class="deliv-detail">AI Sinh Đôi truy cập toàn bộ kho của bạn, tìm kiếm thông minh, tra cứu khi cần ra quyết định.</div>
      </div>
      <div class="deliv-block">
        <div class="deliv-num">1</div>
        <div class="deliv-label">Chứng Nhận Sáng Lập</div>
        <div class="deliv-detail">Cấp 1 cuối Chủ nhật. Bạn chốt 8 tài liệu gốc. Sau đó được mở khoá Tầng 2 Hiểu Khách.</div>
      </div>
      <div class="deliv-block">
        <div class="deliv-num">1-1</div>
        <div class="deliv-label">Hằng hỗ trợ Zalo trực tiếp</div>
        <div class="deliv-detail">Cài đặt kho, xem lại tài liệu gốc, gỡ rối khi bạn kẹt. Không phải tự bơi một mình.</div>
      </div>
    </div>
  </div>
</section>

<section class="founder-story-hang">
  <div class="container">
    <div class="tag" style="display:block;text-align:center">Tại sao Hằng tạo Foundation</div>
    <h2>15 năm đào tạo. Xây nhiều thứ.<br>Rồi quay lại bắt đầu từ chính mình.</h2>
    <div class="story-body">
      <p>Hằng từng có đội ngũ lớn. Từng quản lý nhiều người. Từng xây nhiều doanh nghiệp khác nhau trong 15 năm.</p>
      <p>Nhưng đến một lúc Hằng nhận ra: mỗi lần bắt đầu một việc mới, Hằng lại đi lại đúng những bước cũ. Tìm khách hàng. Đoán nỗi đau của họ. Thử offer. Thử landing. Thử ads. Lại quên những gì đã học. Lại bắt đầu lại từ số 0.</p>
      <p>Vấn đề lớn nhất không phải marketing. Không phải sản phẩm. Không phải kỹ năng.</p>
      <p><strong>Vấn đề lớn nhất là không có nền móng.</strong></p>
      <p>Không rõ mình là ai. Không rõ mình muốn phục vụ ai. Không có hệ thống lưu giữ những gì đã học. Mỗi venture là một lần bắt đầu lại từ đầu.</p>
      <p>Khi AI xuất hiện, Hằng quyết định quay lại làm điều đáng lẽ phải làm 15 năm trước. Xây hệ điều hành cho chính mình trước. Sau đó dùng AI để vận hành doanh nghiệp một mình, không cần đội ngũ lớn.</p>
      <p>Hằng đang chạy 6 doanh nghiệp với 1 mình + AI. Mỗi doanh nghiệp đứng trên cùng một Hệ Điều Hành Sáng Lập. Không bắt đầu lại từ số 0 mỗi lần nữa.</p>
      <p><strong>Foundation là phương pháp Hằng đã dùng cho chính mình. Bây giờ Hằng chia sẻ lại cho bạn.</strong></p>
    </div>
  </div>
</section>

<section class="curriculum">
  <div class="container">
    <div class="tag" style="display:block;text-align:center">Foundation trong bức tranh tổng thể</div>
    <h2>Foundation là tầng đầu tiên<br>của BreakoutOS.</h2>
    <p class="lede">BreakoutOS là một hệ điều hành 6 tầng giúp bạn đi từ "không biết mình là ai" đến "founder tự do". Foundation là tầng đầu. Khi xong, bạn được mở khoá các tầng tiếp theo.</p>

    <div class="curriculum-steps">
      <div class="step active">
        <div class="step-week">Tuần 1 · 7 ngày</div>
        <h3>Tầng 1 · Hiểu Mình <span class="en">(Founder OS)</span></h3>
        <p>Bạn đang ở đây. 7 ngày cùng Hằng. Trả lời "Tôi là ai" và "Tôi muốn phục vụ ai".</p>
      </div>
      <div class="step">
        <div class="step-week">Tuần 2-3</div>
        <h3>Tầng 2 · Hiểu Khách <span class="en">(Customer Intelligence OS)</span></h3>
        <p>Hiểu sâu khách hàng. Xây câu nói một dòng định vị và hồ sơ khách hàng chi tiết.</p>
      </div>
      <div class="step">
        <div class="step-week">Tuần 4-5</div>
        <h3>Tầng 3 · Đóng Gói Giá Trị <span class="en">(Value Proposition OS)</span></h3>
        <p>Thiết kế sản phẩm đầu tiên, định vị thương hiệu, định giá, cam kết.</p>
      </div>
      <div class="step">
        <div class="step-week">Tuần 6</div>
        <h3>Tầng 4 · Vận Hành Doanh Nghiệp <span class="en">(Business Operating OS)</span></h3>
        <p>Giám đốc vận hành AI, tự động hoá, quy trình chuẩn. Hệ thống chạy ngầm thay bạn.</p>
      </div>
      <div class="step">
        <div class="step-week">Tuần 7-8</div>
        <h3>Tầng 5 · Tăng Trưởng Doanh Thu <span class="en">(Revenue Growth OS)</span></h3>
        <p>Thu hút khách, lọc khách tiềm năng, bán hàng, giữ chân, lên bậc. Đạt khách hàng trả tiền đầu tiên.</p>
      </div>
      <div class="step">
        <div class="step-week">Tuần 9-11</div>
        <h3>Tầng 6 · Tự Do Sáng Lập <span class="en">(Founder Freedom OS)</span></h3>
        <p>Điểm Tự Do Sáng Lập từ 70 điểm trở lên. Bạn thoát khỏi việc vận hành tay.</p>
      </div>
    </div>
  </div>
</section>

<section class="pricing">
  <div class="container">
    <div class="tag" style="background:rgba(214,48,49,0.2);display:inline-block">Cohort 1 · Bắt đầu khi sẵn sàng</div>
    <h2>Đầu tư một lần.<br>Xây người sáng lập cả đời.</h2>
    <p class="lede">Khai giảng Thứ Hai 22/6 lúc 5h sáng giờ Việt Nam. 3 buổi lý thuyết LIVE có video quay lại. Chủ nhật Hằng review và triển khai cùng bạn. Thanh toán xong Hằng nhắn tin Zalo trong vài giờ để chuẩn bị.</p>

    <div class="price-card">
      <div class="tier">Nền Móng (Foundation)</div>
      <h3>Tầng 1 · Hiểu Mình (Founder OS)</h3>
      <div class="price-row">
        <span class="new">3.000.000đ</span>
      </div>
      <div class="meta"><strong>Khai giảng Thứ Hai 22/6/2026 lúc 5h sáng giờ Việt Nam</strong></div>
      <ul class="includes">
        <li><strong>3 buổi học lý thuyết trực tiếp cùng Hằng</strong> (Hai, Tư, Sáu lúc 5h sáng giờ Việt Nam)</li>
        <li><strong>Video quay lại đầy đủ</strong> nếu bạn không tham gia trực tiếp được</li>
        <li><strong>Chủ nhật xem lại và triển khai cùng Hằng</strong> (dự phòng cho ai chưa xây xong)</li>
        <li>8 tài liệu gốc Nền Móng Sáng Lập (Sứ Mệnh Đời đến Câu Chuyện Sáng Lập)</li>
        <li>4 câu trả lời Định Hướng Kinh Doanh (phục vụ ai, bán gì, mô hình nào)</li>
        <li>6 kho tri thức cá nhân (Bộ Não Thứ Hai đến Kho Học Tập)</li>
        <li>Kho Tri Thức AI + AI Sinh Đôi truy cập 12 tháng</li>
        <li>Chứng Nhận Sáng Lập cuối Chủ nhật (Cấp 1)</li>
        <li>Mở khoá Tầng 2 Hiểu Khách sau khi hoàn thành</li>
      </ul>
      <a href="https://app.breakout.live/thanh-toan.html?product=foundation&source=foundation_landing_pricing" class="btn-primary btn-gold">Đăng ký Foundation 3 triệu →</a>
    </div>
  </div>
</section>

<section class="cta-final">
  <div class="container">
    <h2>Đừng xây doanh nghiệp<br>trước khi xây người sáng lập.</h2>
    <p>Khai giảng Thứ Hai 22/6 lúc 5h sáng giờ Việt Nam. 3 buổi lý thuyết có video quay lại. Chủ nhật Hằng xem lại và triển khai cùng bạn. Cuối tuần bạn rời khoá học với 8 tài liệu gốc đã chốt.</p>
    <a href="https://app.breakout.live/thanh-toan.html?product=foundation&source=foundation_landing_bottom" class="btn-primary btn-gold">Đăng ký Foundation 3 triệu →</a>
  </div>
</section>

<footer>
  <div class="container footer-grid">
    <div>
      <h5>BreakoutOS Foundation</h5>
      <p style="font-size:13px;opacity:0.7">Tầng 1 trong Founder Transformation Operating System.</p>
      <p style="margin-top:12px;font-size:12px;opacity:0.6">© 2026 Đào Thị Hằng, Pimpama, Gold Coast QLD, Australia</p>
    </div>
    <div>
      <h5>Hệ sinh thái</h5>
      <p><a href="/">BreakoutOS 5 tầng</a></p>
      <p><a href="/cohort/">Vào hệ thống</a></p>
    </div>
    <div>
      <h5>Liên hệ</h5>
      <p>Zalo Hằng: 0932 093 593</p>
      <p>Email: hang@mail.daothihang.com</p>
    </div>
  </div>
</footer>

</body>
</html>"""


@app.get("/admin")
async def os_admin(request: Request):
    """Host-based shortcut: `os.breakout.live/admin` → cohort admin dashboard."""
    host = request.headers.get("host", "").lower()
    from fastapi.responses import RedirectResponse
    if host.startswith("os.breakout.live"):
        key = os.environ.get("COHORT_ADMIN_KEY", "")
        return RedirectResponse(f"/cohort/admin/dashboard?key={key}", status_code=302)
    return JSONResponse({"detail": "Not found"}, status_code=404)
