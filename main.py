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
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

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
from routes.coaching_landing import router as coaching_router
from routes.challenge_k3 import (
    challenge_worker_loop,
    router as challenge_k3_router,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("camas.main")
BASE_DIR = Path(__file__).resolve().parent


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
    challenge_stop = __import__("asyncio").Event()
    challenge_worker = __import__("asyncio").create_task(
        challenge_worker_loop(challenge_stop)
    )
    from routes.k3_bridge import bridge_scheduler_loop
    bridge_task = __import__("asyncio").create_task(
        bridge_scheduler_loop(challenge_stop)
    )
    try:
        yield
    finally:
        challenge_stop.set()
        try:
            await __import__("asyncio").wait_for(challenge_worker, timeout=10)
        except __import__("asyncio").TimeoutError:
            challenge_worker.cancel()
        try:
            await __import__("asyncio").wait_for(bridge_task, timeout=10)
        except __import__("asyncio").TimeoutError:
            bridge_task.cancel()
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
app.include_router(challenge_k3_router, tags=["challenge-k3"])
from routes.k3_bridge import router as k3_bridge_router
app.include_router(k3_bridge_router, tags=["k3-bridge"])
app.include_router(coaching_router, tags=["coaching-landing"])
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

    2026-06-19: Redirect root → /foundation-system. Lý do: landing V3.4 5 tầng
    (Hiểu Mình / Hiểu Khách / Thiết Kế Hệ Thống / Tăng Trưởng / Nhân Bản) đã
    out of sync với canonical V3.5.7 (6 OS layers, Founder Freedom Score North
    Star). Foundation System là entry point Anna đang push K3 → Foundation
    conversion. Khi V3.5.7 root landing sẵn sàng (rewrite về 6 tầng đúng tên),
    bỏ redirect này, restore _render_landing_5_tang() hoặc render landing mới.
    """
    host = request.headers.get("host", "").lower()
    if host.startswith("os.breakout.live"):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/foundation-system", status_code=302)
    return JSONResponse(
        {
            "service": "camas-kernel",
            "version": "0.1.0",
            "status": "running",
            "docs": "/docs",
        }
    )


@app.get("/foundation-system")
@app.get("/foundation")
async def foundation_landing(request: Request):
    """Landing khoá Foundation với Digital Assets Foundation angle.

    Anna brief 2026-06-12: Tài sản đầu tiên cần xây không phải website/fanpage
    mà là bộ não thứ hai của chính bạn. Foundation = nền móng cho con người +
    cuộc sống + doanh nghiệp + hệ thống tri thức + tài sản số cá nhân.
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_render_landing_foundation())


@app.get("/foundation-assets/vault-structure.png")
async def foundation_vault_image():
    return FileResponse(BASE_DIR / "static" / "foundation" / "vault-structure.png")


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
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Foundation System, Hệ điều hành Solo Biz đầu tiên cùng AI | BreakoutOS</title>
<meta name="description" content="Một người. Một AI. Một Solo Biz. Sau 7 ngày, bạn xây xong nền móng Solo Biz đầu tiên cùng AI. Lịch học 2-4-6 sáng và Chủ nhật.">
<style>
  :root{
    --ink:#15181f; --muted:#5b6472; --line:#e7e9ee; --bg:#ffffff; --soft:#f6f7f9;
    --brand:#e11d2a; --brand-dark:#b3121e; --accent:#fff4e6; --accent-line:#ffd9a8;
    --ok:#1f9d63; --warn:#d9433f; --maxw:760px;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html{scroll-behavior:smooth}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;color:var(--ink);background:var(--bg);line-height:1.6;font-size:18px;-webkit-font-smoothing:antialiased}
  .wrap{max-width:var(--maxw);margin:0 auto;padding:0 22px}
  section{padding:54px 0;border-bottom:1px solid var(--line)}
  h1{font-size:42px;line-height:1.12;font-weight:800;letter-spacing:-0.5px;margin-bottom:18px}
  h2{font-size:26px;line-height:1.2;font-weight:800;margin-bottom:18px;letter-spacing:-0.3px}
  p{margin-bottom:12px}
  .eyebrow{display:inline-block;font-size:13px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--brand);background:#fdeaec;padding:6px 12px;border-radius:999px;margin-bottom:20px}
  .lead{font-size:20px;color:var(--ink)}
  .muted{color:var(--muted)}
  .big{font-size:22px;font-weight:700}
  .stack p{margin-bottom:6px}
  .gap{height:14px}
  /* hero */
  .hero{background:linear-gradient(180deg,#fff5f5 0%,#ffffff 100%);text-align:center;padding-top:64px}
  .hero .sub{font-size:20px;color:var(--ink);max-width:560px;margin:0 auto 8px}
  .hero .nots{color:var(--muted);font-size:18px;margin:14px auto 26px}
  /* buttons */
  .cta{display:inline-block;background:var(--brand);color:#fff;font-size:19px;font-weight:700;text-decoration:none;padding:16px 30px;border-radius:12px;box-shadow:0 8px 22px rgba(225,29,42,.30);transition:transform .12s ease,background .2s}
  .cta:hover{background:var(--brand-dark);transform:translateY(-1px)}
  .cta-note{font-size:15px;color:var(--muted);margin-top:12px}
  .center{text-align:center}
  /* image placeholder */
  .imgph{border:2px dashed #c3c9d6;background:var(--soft);border-radius:14px;padding:40px 20px;text-align:center;color:var(--muted);font-size:15px;margin:8px 0 22px}
  .imgph strong{display:block;color:#3a4252;font-size:16px;margin-bottom:4px}
  .shot{width:100%;border:1px solid var(--line);border-radius:14px;box-shadow:0 10px 30px rgba(20,24,31,.08);margin:8px 0 8px;display:block}
  .cap{font-size:14px;color:var(--muted);text-align:center;margin:0 0 22px}
  /* before after */
  .ba{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:8px}
  .card{border:1px solid var(--line);border-radius:14px;padding:22px}
  .card h3{font-size:15px;letter-spacing:.5px;text-transform:uppercase;margin-bottom:14px}
  .card.before{background:#fff7f7;border-color:#f3d6d4}
  .card.before h3{color:var(--warn)}
  .card.after{background:#f2fbf6;border-color:#cdeedd}
  .card.after h3{color:var(--ok)}
  .card ul{list-style:none}
  .card li{padding:6px 0 6px 26px;position:relative;font-size:17px}
  .card.before li:before{content:"\\2717";position:absolute;left:0;color:var(--warn);font-weight:700}
  .card.after li:before{content:"\\2713";position:absolute;left:0;color:var(--ok);font-weight:700}
  /* quote */
  .pull{background:var(--accent);border:1px solid var(--accent-line);border-radius:14px;padding:20px 22px;font-size:20px;font-weight:700;margin:22px 0}
  /* tiers */
  .tier{border-left:3px solid var(--brand);padding:6px 0 6px 18px;margin-bottom:18px}
  .tier .t{font-weight:800;font-size:18px}
  .tier .heart{display:inline-block;background:#fff0f3;color:#d6336c;font-size:12px;font-weight:700;padding:2px 8px;border-radius:999px;margin-left:6px;vertical-align:middle}
  .own{background:var(--soft);border-radius:14px;padding:20px 22px;margin-top:8px}
  .own p{margin-bottom:6px}
  /* days */
  .day{display:flex;gap:14px;padding:12px 0;border-bottom:1px solid var(--line)}
  .day:last-child{border-bottom:0}
  .day .d{min-width:118px;font-weight:700;color:var(--brand);font-size:15px}
  .levels .lv{padding:12px 0;border-bottom:1px solid var(--line)}
  .levels .lv:last-child{border-bottom:0}
  .levels .lv b{color:var(--ink)}
  /* obj */
  .obj{margin-bottom:16px}
  .obj .q{font-weight:700}
  /* price */
  .pricebox{background:var(--soft);border:1px solid var(--line);border-radius:16px;padding:26px}
  .pricebox ul{list-style:none;margin-bottom:16px}
  .pricebox li{padding:7px 0 7px 26px;position:relative}
  .pricebox li:before{content:"\\2713";position:absolute;left:0;color:var(--ok);font-weight:700}
  .price-final{font-size:22px;font-weight:800;margin-top:6px}
  .price-final .old{color:var(--muted);font-weight:600;font-size:18px}
  /* sticky */
  .sticky{position:fixed;left:0;right:0;bottom:0;background:rgba(255,255,255,.96);backdrop-filter:blur(8px);border-top:1px solid var(--line);padding:12px 16px;text-align:center;z-index:50}
  .sticky a{font-size:17px;padding:13px 24px}
  body{padding-bottom:86px}
  .limit{background:#fff7ed;border:1px solid #ffe0b8;border-radius:14px;padding:20px 22px}
  @media(max-width:620px){
    h1{font-size:33px}
    body{font-size:17px}
    .ba{grid-template-columns:1fr}
    .hero{padding-top:44px}
    section{padding:40px 0}
  }
</style>
</head>
<body>

<!-- HERO -->
<section class="hero">
  <div class="wrap">
    <span class="eyebrow">BreakoutOS, Tầng 1, Foundation System</span>
    <h1>Một người. Một AI. Một Solo Biz.</h1>
    <p class="sub" style="font-weight:700;font-size:23px;color:var(--ink)">Không còn bắt đầu lại từ đầu mỗi lần mở AI (ChatGPT, Claude, Gemini).</p>
    <p class="nots">Bạn không cần thêm người.<br>Bạn cần một hệ thống AI hiểu bạn, nhớ thay bạn và làm việc cùng bạn mỗi ngày.<br>Sau 7 ngày, bạn ngừng làm việc một mình.</p>
    <a class="cta" href="https://app.breakout.live/thanh-toan.html?product=foundation&source=landing_hero">Đăng ký Foundation System 3 triệu</a>
    <p class="cta-note">Lịch học Thứ Hai, Thứ Tư, Thứ Sáu từ 5h đến 6h30 sáng giờ Việt Nam. Chủ nhật từ 9h sáng đến 3h chiều giờ Việt Nam. Có video quay lại.</p>
  </div>
</section>

<!-- PROOF -->
<section>
  <div class="wrap">
    <h2>Đây là vault thật Hằng đang dùng để vận hành</h2>
    <img class="shot" src="/foundation-assets/vault-structure.png" alt="Vault Second Brain thật của Hằng với cấu trúc raw, wiki, boards, cohangai và migration">
    <p class="cap">Vault Second Brain thật của Hằng. Đây là nơi dữ liệu, tri thức, dự án và hệ thống AI được giữ có cấu trúc.</p>
    <p>Bạn đang nhìn vào nền móng phía sau hệ thống của Hằng.</p>
    <p>Một vault giữ raw data. Một wiki giữ tri thức đã xử lý. Các project giữ từng venture. Các agent và workflow biến dữ liệu đó thành hành động.</p>
    <p class="big">Ý tưởng. Khách hàng. Nội dung. Quy trình. Tri thức. Quyết định.</p>
    <p>Hệ thống này giúp Hằng vận hành nhiều dự án cùng lúc mà không phải bắt đầu lại từ đầu mỗi lần mở AI.</p>
    <p>Đây không phải chatbot. Không phải prompt.<br><strong>Đây là cách một người vận hành như một công ty.</strong></p>
    <p>7 ngày tới, bạn xây phiên bản đầu tiên của chính mình.</p>
  </div>
</section>

<!-- BEFORE / AFTER -->
<section>
  <div class="wrap">
    <h2>7 ngày nữa, cuộc sống bạn khác thế nào</h2>
    <div class="ba">
      <div class="card before">
        <h3>Hôm nay</h3>
        <ul>
          <li>Viết bài từ đầu, mỗi lần</li>
          <li>Quên khách hàng đã nói gì</li>
          <li>Học rồi quên</li>
          <li>Ý tưởng nằm rải rác khắp nơi</li>
          <li>Làm việc một mình</li>
        </ul>
      </div>
      <div class="card after">
        <h3>Sau Foundation System</h3>
        <ul>
          <li>Có AI viết đúng hành văn của bạn, kể câu chuyện của bạn</li>
          <li>Có bộ nhớ khách hàng</li>
          <li>Có kho tri thức riêng</li>
          <li>Có hệ thống trợ lý AI làm việc cùng bạn</li>
        </ul>
      </div>
    </div>
    <div class="gap"></div>
    <p>Bạn ngừng phải làm mọi thứ một mình.<br>Bạn có lại thời gian. Cho khách. Cho con. Cho chính mình.</p>
    <div class="pull">Breakout Challenge giúp bạn tìm ra ý tưởng. Foundation System giúp bạn xây nền móng vận hành cho Solo Biz đầu tiên từ ý tưởng đó.</div>
  </div>
</section>

<!-- CHATGPT -->
<section>
  <div class="wrap">
    <h2>Tại sao AI (ChatGPT, Claude, Gemini) chưa giúp bạn kiếm được tiền</h2>
    <p>AI không thiếu. Prompt cũng không thiếu.</p>
    <p class="big">Vấn đề là mọi thứ không được sắp xếp và lưu trữ có hệ thống theo thời gian.</p>
    <p>Hôm nay bạn hỏi một câu. Ngày mai bạn hỏi lại từ đầu.</p>
    <p class="stack">
      Nó không nhớ bạn là ai.<br>
      Không nhớ khách của bạn.<br>
      Không nhớ bạn đang xây gì.
    </p>
    <p>Mỗi lần là một lần bắt đầu lại.</p>
    <p>Foundation System khác ở chỗ đó. Bạn không hỏi AI từng câu lẻ. Bạn xây một bộ não số và một hệ thống AI có ngữ cảnh riêng về bạn, khách hàng và dự án của bạn, dựa trên dữ liệu bạn nạp vào, để làm việc cùng bạn.</p>
    <div class="pull">AI trả lời bạn. Hệ thống AI mà Foundation System xây, sẽ làm việc cùng bạn.</div>
  </div>
</section>

<!-- REFRAME: Foundation is installation, not course -->
<section>
  <div class="wrap">
    <h2>Đây không phải khoá học để ngồi nghe</h2>
    <p class="lead">Đây là sprint 7 ngày cài hệ điều hành Solo Biz cho riêng bạn, có hướng dẫn, mẫu sẵn và buổi ráp hệ thống cùng Hằng.</p>
    <p>Khoá học cho bạn kiến thức để bạn về tự dựng. Phần lớn không dựng được, hoặc dựng nửa chừng rồi bỏ.</p>
    <p>Foundation System khác. Trong 7 ngày, Hằng đồng hành để bạn <strong>cài đặt</strong> hệ thống thật trên màn hình của bạn. Bạn không học để biết. Bạn cài để bắt đầu vận hành.</p>
    <div class="pull">Bạn không bước ra với một xấp ghi chú. Bạn bước ra với một hệ thống đang chạy.</div>
  </div>
</section>

<!-- 5 THINGS YOU INSTALL -->
<section>
  <div class="wrap">
    <h2>5 thứ bạn cài đặt trong 7 ngày</h2>
    <p class="muted">Đây không phải nội dung học. Đây là 5 thứ bạn lắp xong, mỗi cái có trên màn hình của bạn.</p>
    <div class="gap"></div>
    <div class="tier"><span class="t">1. Hồ sơ Sáng Lập</span><br>AI phỏng vấn bạn về câu chuyện, kinh nghiệm, thế mạnh, giá trị, mục tiêu. Sau khi điền xong, AI tự sinh cho bạn một trang "Bạn là ai" bằng giọng của chính bạn. Lần đầu tiên bạn đọc, bạn sẽ cảm giác có ai đó cuối cùng đã hiểu mình.</div>
    <div class="tier"><span class="t">2. Kho dữ liệu cá nhân</span><br>Bạn nạp vào bộ não số 10 đến 20 tài liệu đầu tiên (nạp thêm sau tuỳ bạn). CV, bio, nhật ký, sách đã đọc, ghi chú cũ, transcript video, khoá học từng tham gia. Đây là nhiên liệu cho AI hiểu bạn ngày càng sâu.</div>
    <div class="tier"><span class="t">3. Cô Hằng AI phiên bản của riêng bạn</span><span class="heart">Trái tim của Foundation System</span><br>Sau khi nạp dữ liệu, bạn có một AI Assistant chạy trên Bộ não số của bạn. Bạn hỏi sách đã đọc, hỏi bài học cũ, hỏi khách hàng, hỏi nội dung. Nó trả lời dựa trên dữ liệu bạn đã nạp và cấu trúc bạn dựng, không phải kho của Internet, cũng không phải một tài khoản AI tách rời.</div>
    <div class="tier"><span class="t">4. 6 hệ thống cài sẵn</span><br>Bạn không phải tự xây từ con số 0. Hằng phát template sẵn cho 6 hệ thống. Nhiệm vụ của bạn chỉ là điền dữ liệu của mình vào.</div>
    <div class="tier"><span class="t">5. Thói quen vận hành</span><br>Phần quan trọng nhất, vì rất nhiều người setup xong rồi không dùng. Cuối khoá bạn có 4 quy trình rõ. Cộng với AI Morning Brief, mỗi sáng 6h, "Cô Hằng AI của bạn" tự đẩy 3 việc cần focus hôm nay vào điện thoại của bạn. Bạn không phải tự nhớ mở hệ thống.</div>
  </div>
</section>

<!-- OUTPUT 6 SYSTEMS -->
<section>
  <div class="wrap">
    <h2>Bạn bước ra với nền móng Solo Biz đầu tiên</h2>
    <p class="muted">Sau 7 ngày, 3 thứ này hoàn chỉnh và dùng được ngay. 6 hệ thống con đã có khung sẵn để bạn tiếp tục điền sau khoá.</p>
    <div class="gap"></div>
    <p style="font-weight:700">3 đầu ra hoàn chỉnh sau 7 ngày:</p>
    <div class="own">
      <p><strong>1. Hồ sơ Sáng Lập.</strong> Trang "Bạn là ai" do AI sinh bằng giọng của chính bạn.</p>
      <p><strong>2. Kho dữ liệu cá nhân có cấu trúc.</strong> Bộ não số đã nạp dữ liệu, AI tra cứu lại được.</p>
      <p><strong>3. Bản đồ Solo Biz 12 tháng (bản nháp).</strong> Hướng đi, thị trường, sản phẩm, kênh bán để bạn thử và sửa tiếp.</p>
    </div>
    <div class="gap"></div>
    <p style="font-weight:700">6 khung hệ thống đã cài sẵn để bạn điền tiếp:</p>
    <div class="own">
      <p><strong>1. Hệ thống ghi chép, bộ não thứ hai.</strong> Nơi mọi ý tưởng, ghi chú đời sống được giữ có cấu trúc.</p>
      <p><strong>2. Hệ thống quản lý tri thức.</strong> Sách, khoá, video, bài học được tóm tắt và tra cứu lại bằng AI.</p>
      <p><strong>3. Hệ thống quản lý khách hàng.</strong> Hồ sơ và ghi chú khách để AI hiểu khách ngày càng sâu.</p>
      <p><strong>4. Hệ thống quản lý công việc.</strong> Việc cần làm, quy trình, theo dõi tiến độ.</p>
      <p><strong>5. Hệ thống quản lý nội dung.</strong> Bài viết, email, video được phân loại để tái sử dụng.</p>
      <p><strong>6. Hệ thống vận hành Solo Biz.</strong> Mục tiêu, KPI, cơ hội kinh doanh, sản phẩm, doanh thu, tất cả ở một cockpit. AI đọc dữ liệu và đề xuất hành động hàng ngày.</p>
    </div>
    <div class="pull">Sau 7 ngày bạn có phiên bản đầu tiên của hệ thống vận hành Solo Biz, đủ để dùng, thử, sửa và phát triển tiếp.</div>
    <div class="center"><a class="cta" href="https://app.breakout.live/thanh-toan.html?product=foundation&source=landing_mid">Tôi muốn cài hệ điều hành Solo Biz</a></div>
  </div>
</section>

<!-- FOR WHOM -->
<section>
  <div class="wrap">
    <h2>Foundation System dành cho những ai?</h2>
    <p>Hằng nói thẳng.</p>
    <p>Foundation System không dành cho người đã có doanh nghiệp lớn.<br><strong>Foundation System dành cho người muốn xây Solo Biz đầu tiên cùng AI. Người muốn tăng hiệu suất làm việc của mình x3, x5.</strong></p>
    <p>Bạn là giáo viên. Là nhân viên văn phòng. Là mẹ bỉm. Là người muốn khởi nghiệp.</p>
    <div class="gap"></div>
    <p><strong>Nếu bạn chưa biết bán gì.</strong><br>Hệ thống giúp bạn nhìn lại chính mình, tìm nhóm khách hàng phù hợp, và tạo ra những ý tưởng đầu tiên để kiểm chứng.</p>
    <p><strong>Nếu bạn đã có sản phẩm mà còn chông chênh.</strong><br>Hệ thống giúp bạn ngừng tự hỏi mình có đang đi đúng không.</p>
    <p><strong>Nếu bạn đang bán mà ngập việc.</strong><br>Hệ thống gánh bớt việc lặp đi lặp lại, để bạn rảnh tay quay lại với khách.</p>
    <p>Dù bạn là ai trong ba người đó, bạn đều cần một doanh nghiệp gọn nhẹ, một người vẫn vận hành được.</p>
    <div class="gap"></div>
    <p><strong>Phù hợp nhất nếu</strong> bạn đã có chuyên môn, kinh nghiệm, câu chuyện hoặc ý tưởng ban đầu, và muốn biến nó thành Solo Biz có hệ thống cùng AI.</p>
    <p class="muted">Chương trình không phù hợp nếu bạn muốn Hằng chọn ngành, chọn sản phẩm, hoặc cam kết doanh thu thay bạn. Foundation dựng nền vận hành, phần quyết định kinh doanh vẫn là của bạn. Foundation cũng không giúp bạn kiếm tiền ngay, nó xây nền để sau đó bạn tìm khách và bán nhất quán hơn.</p>
  </div>
</section>

<!-- 7 DAYS -->
<section>
  <div class="wrap">
    <h2>Lịch học 7 ngày</h2>
    <p class="muted">3 buổi LIVE T2 T4 T6 sáng sớm. 2 ngày tự làm theo video. Chủ nhật cùng Hằng ráp hệ thống của bạn.</p>
    <div class="gap"></div>
    <div class="day"><div class="d">T2, 5h-6h30 sáng</div><div><strong>LIVE.</strong> Khởi tạo Bộ não số. Làm Hồ sơ Sáng Lập. AI phỏng vấn để rút bạn là ai, phục vụ ai.</div></div>
    <div class="day"><div class="d">T3, tự làm</div><div>Đổ 10 đến 20 tài liệu đầu tiên vào kho tri thức và kho tài sản cá nhân (nạp thêm sau tuỳ bạn). 30-60 phút.</div></div>
    <div class="day"><div class="d">T4, 5h-6h30 sáng</div><div><strong>LIVE.</strong> Dựng Cô Hằng AI phiên bản của bạn. Hằng demo sống cách biến AI từ hỏi đáp thành đội ngũ.</div></div>
    <div class="day"><div class="d">T5, tự làm</div><div>Ráp đủ 6 hệ thống con. Có mẫu sẵn để điền, bạn không xây từ số 0. 30-60 phút.</div></div>
    <div class="day"><div class="d">T6, 5h-6h30 sáng</div><div><strong>LIVE.</strong> Dựng Bản đồ Solo Biz 12 tháng. AI đọc toàn bộ kho rồi đề xuất mục tiêu, thị trường, sản phẩm, kênh bán.</div></div>
    <div class="day"><div class="d">T7, nghỉ ngấm</div><div>Một ngày không học mới. Dùng thử trợ lý AI của bạn vào một việc thật.</div></div>
    <div class="day"><div class="d">CN, 9h-3h chiều</div><div><strong>Ráp hệ thống cùng Hằng.</strong> Hằng review theo checklist 5 điểm (hồ sơ sáng lập, kho dữ liệu, cấu trúc hệ thống, bản đồ Solo Biz, bước tiếp theo), ráp tại chỗ, chốt hướng đi. Trao Chứng Nhận Sáng Lập.</div></div>
    <div class="gap"></div>
    <p class="muted">Mọi giờ ở trên là giờ Việt Nam. Có video quay lại đầy đủ. Lỡ buổi LIVE nào bạn xem replay rồi gặp Hằng Chủ nhật.</p>
  </div>
</section>

<!-- CONTROL -->
<section>
  <div class="wrap">
    <h2>Bạn luôn nắm quyền</h2>
    <p>Nhiều người sợ một điều. Giao cho AI, lỡ nó làm bậy thì sao.</p>
    <p>Hằng dạy bạn chia việc thành 3 mức.</p>
    <div class="levels">
      <div class="lv"><b>Mức 1.</b> Việc AI tự làm. Việc nhỏ, sai cũng không sao.</div>
      <div class="lv"><b>Mức 2.</b> Việc AI hỏi bạn một cái. Bạn bấm đồng ý hoặc không.</div>
      <div class="lv"><b>Mức 3.</b> Việc AI chỉ được đề xuất. Việc quan trọng, bạn quyết.</div>
    </div>
    <div class="pull">Bạn là chỉ huy. AI là cánh tay nối dài. Tướng vẫn là bạn.</div>
  </div>
</section>

<!-- WHY HANG -->
<section>
  <div class="wrap">
    <h2>Tại sao là Hằng</h2>
    <p>Hằng là Đào Thị Hằng, sinh ra bên sông Thạch Hãn ở Quảng Trị, đang sống ở Úc. 15 năm kinh doanh, 33 nghìn người Việt đã đi qua các chương trình của Hằng.</p>
    <p>Có một thời Hằng đứng đầu một công ty hơn 70 nhân sự. Tuyển CEO, tuyển phòng kế toán, thuê agency marketing. Doanh số nhìn ngoài là triệu đô, ai cũng nghĩ Hằng đang ăn nên làm ra.</p>
    <p>Bên trong, mỗi tháng Hằng phải bán dần từng miếng đất, rồi bán cả căn nhà, để có tiền trả lương cho 70 con người đó. Hằng tưởng đó là kinh doanh. Hoá ra đó là cái lồng Hằng tự dựng rồi tự nhốt mình vào.</p>
    <p>Một ngày Hằng quyết định đóng cửa. Lùi lại 3 năm. Không đi học thêm khoá nào, không tìm thêm mentor. Hằng chỉ ngồi yên với một câu hỏi mà đáng lẽ Hằng phải trả lời 15 năm trước. Hằng thật sự là ai. Hằng thật sự muốn phục vụ ai.</p>
    <p>Rồi AI tới đúng thời điểm.</p>
    <p>Hằng không dùng AI để hỏi vu vơ từng câu lẻ. Hằng dựng AI thành một hệ thống chạy ngầm phía sau mình. Hằng chỉ giữ hai thứ quan trọng nhất, chiến lược và quyết định. AI gánh phần lớn việc lặp đi lặp lại của cả phòng ban cũ.</p>
    <p>Bây giờ Hằng vận hành nhiều dự án cùng lúc, một mình, mà không còn kiệt sức như xưa, và lần đầu tiên có lại cuộc sống.</p>
    <p><strong>Foundation System là cách Hằng đã làm cho chính mình trong 3 năm đó. Bây giờ Hằng gói lại 7 ngày, trao cho bạn, để bạn không phải trả cái giá Hằng đã trả.</strong></p>
  </div>
</section>

<!-- OBJECTIONS -->
<section>
  <div class="wrap">
    <h2>Nếu bạn đang nghĩ</h2>
    <div class="obj"><p class="q">"Em chưa biết bán gì."</p><p>Hợp. Chưa biết bán gì là lý do nên vào, không phải lý do đứng ngoài.</p></div>
    <div class="obj"><p class="q">"Em tự làm với AI (ChatGPT, Claude, Gemini) được."</p><p>AI trả lời xong, bạn vẫn tự làm hết. Hệ thống của bạn thì nhớ bạn, hiểu khách bạn, làm cùng bạn.</p></div>
    <div class="obj"><p class="q">"Em không rành công nghệ."</p><p>Không cần giỏi công nghệ. Bạn chỉ cần làm theo từng bước, mỗi ngày 30 đến 60 phút. Có mẫu sẵn để điền và Hằng hỗ trợ qua Zalo.</p></div>
    <div class="obj"><p class="q">"Em không có thời gian."</p><p>Mỗi ngày 30 đến 60 phút, trong 7 ngày. Đổi 5 giờ một tuần lấy một nền móng dùng nhiều năm.</p></div>
    <div class="obj"><p class="q">"Em chưa kiếm được đồng nào, đầu tư có đáng không?"</p><p>Đây không phải chi phí học. Đây là đầu tư xây một tài sản dùng nhiều năm. Có cam kết hoàn tiền sau 7 ngày (xem điều kiện ở phần cam kết).</p></div>
  </div>
</section>

<!-- BONUS STACK -->
<section>
  <div class="wrap">
    <h2>Bonus đi kèm khi bạn đăng ký</h2>
    <p class="muted">Đây là phần Hằng kèm sẵn, không tính thêm phí. Để bạn không cần đi tìm tool, tài liệu hay group ngoài.</p>
    <div class="gap"></div>
    <div class="tier"><span class="t">Bonus 1. Group Breakout Founders 6 tháng</span><br>Cộng đồng học viên đã tốt nghiệp. Hằng vào trả lời mỗi tuần. Giá trị riêng 3 triệu.</div>
    <div class="tier"><span class="t">Bonus 2. Mini course "5 trợ lý AI Hằng dùng hàng ngày"</span><br>Workflow ready to clone. Bạn không xây trợ lý từ con số 0. Giá trị riêng 3 triệu.</div>
    <div class="gap"></div>
    <h2 style="color:var(--brand);margin-top:20px">Bonus đặc biệt cho người đăng ký sớm</h2>
    <div class="tier" style="border-left-color:var(--brand-dark)"><span class="t">Fast Action, đăng ký trong 48 giờ đầu</span><br>30 phút 1-1 với Hằng để review Bản đồ Solo Biz 12 tháng của bạn sau khoá. Giá trị riêng 5 triệu.</div>
    <div class="tier" style="border-left-color:var(--brand-dark)"><span class="t">Early Bird, 5 người đăng ký đầu tiên</span><br>Truy cập BreakoutOS Premium Model trong 1 tháng. Giá trị riêng 1,5 triệu.</div>
  </div>
</section>

<!-- PRICE -->
<section>
  <div class="wrap">
    <h2>Bạn nhận được gì và học phí</h2>
    <div class="pricebox">
      <p style="font-weight:700;margin-bottom:14px;font-size:18px">Phần lõi của Foundation System:</p>
      <ul>
        <li>3 buổi LIVE 90 phút sáng T2 T4 T6 (5h-6h30 giờ Việt Nam)</li>
        <li>Buổi Chủ nhật 6 tiếng cùng Hằng ráp hệ thống của bạn (9h-3h chiều)</li>
        <li>Hằng review theo checklist 5 điểm cho từng người trong buổi ráp Chủ nhật</li>
        <li>Bộ não số với 3 đầu ra lõi hoàn chỉnh + 6 khung hệ thống để điền tiếp</li>
        <li>Trợ lý AI đầu tiên cộng 5 mẫu trợ lý Hằng dùng hàng ngày</li>
        <li>Bản đồ Solo Biz 12 tháng (bản nháp) cho Solo Biz của bạn</li>
        <li>Chứng Nhận Sáng Lập có tên và chữ ký Hằng</li>
        <li>Replay trọn đời và workbook đầy đủ để xem lại bất cứ lúc nào</li>
      </ul>
      <p style="margin-top:14px;color:var(--muted);font-size:15px">Cộng 3 Bonus đi kèm + 2 Bonus đặc biệt cho người đăng ký sớm (xem phần trên).</p>
      <div class="gap"></div>
      <p class="price-final"><span class="old">Riêng phần bonus đi kèm đã hơn 7 triệu.</span><br>Đợt mở đầu giá <strong style="color:var(--brand)">3 triệu</strong>. Đợt sau giá tăng.</p>
    </div>
    <div class="gap"></div>
    <p class="muted">Hằng không bán rẻ hơn. AI chạy là chi phí thật. Hằng review theo checklist cho từng người là thời gian thật. 6 tháng đồng hành là cam kết thật.</p>
  </div>
</section>

<!-- LIMIT -->
<section>
  <div class="wrap">
    <h2>Giới hạn thật</h2>
    <div class="limit">
      <p><strong>Mỗi đợt Foundation System chỉ nhận 20 người.</strong></p>
      <p>Lý do thật. Hằng review theo checklist 5 điểm cho từng người trong buổi ráp Chủ nhật 6 tiếng. Quá 20, Hằng làm không kỹ được. Đủ 20, Hằng đóng đăng ký.</p>
      <p><strong>Hai mốc cần nhớ:</strong></p>
      <p>1. <strong>5 người đăng ký đầu tiên</strong> nhận truy cập BreakoutOS Premium Model trong 1 tháng (trị giá 1,5 triệu).</p>
      <p>2. <strong>48 giờ đầu kể từ khi mở đăng ký</strong> nhận thêm 30 phút 1-1 với Hằng review Bản đồ Solo Biz 12 tháng của bạn sau khoá.</p>
      <p>Lịch học Thứ Hai, Thứ Tư, Thứ Sáu từ 5h đến 6h30 sáng giờ Việt Nam. Chủ nhật từ 9h sáng đến 3h chiều giờ Việt Nam.</p>
    </div>
  </div>
</section>

<!-- GUARANTEE -->
<section>
  <div class="wrap">
    <h2>Hằng cam kết</h2>
    <p>Hằng không hứa bạn 100 triệu tháng đầu. Không hứa AI làm thay hết. Không hứa thành công mà không cần nỗ lực.</p>
    <p><strong>Hằng cam kết một điều cụ thể.</strong></p>
    <p>Sau 7 ngày, nếu bạn đã làm đủ phần của mình (hoàn thành checklist mỗi ngày, nạp tối thiểu 10 tài liệu, dự hoặc xem lại đủ các buổi, và nộp hệ thống cho Hằng review trong buổi Chủ nhật) mà vẫn không có hệ thống chạy được, demo được trên màn hình của bạn, Hằng hoàn 100 phần trăm. Cộng thêm 30 phút coaching 1-1 cùng Hằng để rà soát bạn đang vướng ở đâu.</p>
    <p>Lý do Hằng dám cam kết như vậy: hệ thống này Hằng đã chạy thật trên 5 venture của mình. Không phải lý thuyết.</p>
  </div>
</section>

<!-- BRIDGE Customer System -->
<section>
  <div class="wrap">
    <h2>Sau Foundation System thì sao?</h2>
    <p>Foundation System dựng xong cho bạn một hệ thống Solo Biz vận hành được. Nhưng hệ thống đó đang rỗng khách.</p>
    <p>Bước tiếp theo là Customer System. Đó là nơi mình đổ khách thật vào hệ thống, để có doanh thu đầu tiên.</p>
    <p>Hằng sẽ mở Customer System cho học viên Foundation System trước, không bán rộng. Không phải bây giờ, không phải tuần sau. Khi nào học viên Foundation System đầu tiên hoàn thành đã.</p>
    <p class="muted">Đây không phải pitch. Hằng chỉ muốn bạn biết hành trình tiếp theo trông như thế nào, để bạn không phải quay lại tự loay hoay tìm sau khi dựng xong nền móng.</p>
  </div>
</section>

<!-- CLOSE -->
<section style="border-bottom:0">
  <div class="wrap center">
    <h2><strong>Breakout Challenge tìm ra ý tưởng.</strong><br><strong>Foundation System xây nền móng Solo Biz.</strong></h2>
    <p>Không phải bằng cách làm nhiều hơn.<br>Mà bằng cách có một hệ thống AI làm việc cùng bạn.</p>
    <p class="big">Đợt này chỉ nhận 20 người.</p>
    <div class="gap"></div>
    <a class="cta" href="https://app.breakout.live/thanh-toan.html?product=foundation&source=landing_bottom">Đăng ký, còn 20 suất</a>
    
  </div>
</section>

<!-- STICKY CTA -->
<div class="sticky">
  <a class="cta" href="https://app.breakout.live/thanh-toan.html?product=foundation&source=landing_sticky">Giữ chỗ Foundation System</a>
</div>

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

# Deploy cache-bust 1781356115
