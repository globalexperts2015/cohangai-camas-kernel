-- ============================================================
-- Migration 004: BreakoutOS v3 tables
-- Created: 2026-06-09
-- Apply: AFTER Anna approve. NOT applied yet.
--
-- Tạo 5 tables cho 6 agents mới (Content Engine, Lead Gen, AI COO,
-- Scale Coach, Capstone Spawn, Fan Hub Setup).
-- ============================================================

BEGIN;

-- ─────────────────────────────────────────────────────────────
-- 1. content_engine_output
--    Cache output của C1 Content Engine agent per student.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.content_engine_output (
  id              SERIAL PRIMARY KEY,
  student_id      VARCHAR(64) NOT NULL,
  pillar_count    INT NOT NULL DEFAULT 7,
  pillars         JSONB,
  reel_ideas      JSONB,             -- 100 ideas
  fb_posts        JSONB,             -- 30 posts
  emails          JSONB,             -- 30 nurture emails
  blog_topics     JSONB,             -- 30 SEO topics
  webinar_topics  JSONB,             -- 12 webinar
  lead_magnets    JSONB,             -- 4 magnets
  calendar_30d    JSONB,             -- 30-day schedule
  cta_by_awareness JSONB,            -- 8-level CTA
  voice_register  VARCHAR(64),
  customer_profile_ref JSONB,        -- snapshot input customer profile
  offer_ref       JSONB,             -- snapshot input offer
  generated_at    TIMESTAMPTZ DEFAULT NOW(),
  version         INT DEFAULT 1,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_content_student ON public.content_engine_output(student_id);
CREATE INDEX IF NOT EXISTS idx_content_generated ON public.content_engine_output(generated_at DESC);

COMMENT ON TABLE public.content_engine_output IS 'BreakoutOS v3 C1 Content Engine output cache per student';

-- ─────────────────────────────────────────────────────────────
-- 2. lead_gen_plan
--    C2 Lead Gen Engine output per student.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.lead_gen_plan (
  id                  SERIAL PRIMARY KEY,
  student_id          VARCHAR(64) NOT NULL,
  primary_channels    JSONB,         -- list of channel slugs
  daily_plan_30d      JSONB,         -- 30 days x action items
  lead_magnets_final  JSONB,         -- 4 adapted magnets
  tally_form_specs    JSONB,
  tag_logic           JSONB,
  referral_strategy   JSONB,
  funnel_map          JSONB,
  budget_monthly_vnd  BIGINT DEFAULT 0,
  student_advantages  JSONB,
  generated_at        TIMESTAMPTZ DEFAULT NOW(),
  version             INT DEFAULT 1,
  created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leadgen_student ON public.lead_gen_plan(student_id);

COMMENT ON TABLE public.lead_gen_plan IS 'BreakoutOS v3 C2 Lead Gen Engine plan per student';

-- ─────────────────────────────────────────────────────────────
-- 3. coo_daily_report
--    E1 AI COO Dashboard archive (daily + weekly + monthly).
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.coo_daily_report (
  id              SERIAL PRIMARY KEY,
  student_id      VARCHAR(64) NOT NULL,
  tenant_id       VARCHAR(64),
  period          VARCHAR(16) NOT NULL,  -- daily | weekly | monthly
  report_date     DATE NOT NULL,
  health_metrics  JSONB,
  top_3_actions   JSONB,
  red_flags       JSONB,
  pipeline_snapshot JSONB,
  raw_data        JSONB,                 -- full aggregator output
  formatted_message TEXT,                -- Telegram MD message rendered
  telegram_message_id BIGINT,            -- if pushed, store Telegram msg_id
  generated_at    TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (student_id, period, report_date)
);

CREATE INDEX IF NOT EXISTS idx_coo_student_date ON public.coo_daily_report(student_id, report_date DESC);
CREATE INDEX IF NOT EXISTS idx_coo_period ON public.coo_daily_report(period, report_date DESC);

COMMENT ON TABLE public.coo_daily_report IS 'BreakoutOS v3 E1 AI COO archive (daily/weekly/monthly)';

-- ─────────────────────────────────────────────────────────────
-- 4. scale_plan
--    E2 Scale Coach output (90-day plan + recommended levers).
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.scale_plan (
  id                       SERIAL PRIMARY KEY,
  student_id               VARCHAR(64) NOT NULL,
  current_customers        INT DEFAULT 0,
  monthly_revenue_vnd      BIGINT DEFAULT 0,
  list_size                INT DEFAULT 0,
  plan_90day               JSONB,
  recommended_lever        VARCHAR(64),       -- webinar | membership | referral | ads
  webinar_template         JSONB,
  membership_design        JSONB,
  referral_program_spec    JSONB,
  affiliate_program_spec   JSONB,
  upsell_ladder            JSONB,
  case_study_collection_form JSONB,
  repeat_purchase_strategy JSONB,
  ai_team_recommended      JSONB,
  hire_decision_tree       JSONB,
  generated_at             TIMESTAMPTZ DEFAULT NOW(),
  version                  INT DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_scale_student ON public.scale_plan(student_id);

COMMENT ON TABLE public.scale_plan IS 'BreakoutOS v3 E2 Scale Coach 90-day plan';

-- ─────────────────────────────────────────────────────────────
-- 5. capstone_instance
--    Capstone spawn record per student.
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.capstone_instance (
  id                     SERIAL PRIMARY KEY,
  student_id             VARCHAR(64) UNIQUE NOT NULL,
  subdomain              VARCHAR(120),       -- e.g. {student_id}.aios.breakout.live
  custom_domain          VARCHAR(120),
  railway_service_id     VARCHAR(64),
  railway_service_name   VARCHAR(120),
  fan_hub_subdomain      VARCHAR(120),       -- {student_id}.fan.breakout.live
  fan_hub_tenant_id      UUID,
  config_voice_profile   TEXT,
  config_style_rules     TEXT,
  config_story_pool      JSONB,
  config_compliance      TEXT,
  config_venture_facts   TEXT,
  status                 VARCHAR(32) DEFAULT 'pending',  -- pending | spawning | live | failed | archived
  status_message         TEXT,
  spawned_at             TIMESTAMPTZ,
  last_health_check      TIMESTAMPTZ,
  last_kernel_update     TIMESTAMPTZ,
  kernel_version         VARCHAR(32),
  admin_magic_link_token UUID,
  admin_url              TEXT,
  created_at             TIMESTAMPTZ DEFAULT NOW(),
  updated_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_capstone_status ON public.capstone_instance(status);

COMMENT ON TABLE public.capstone_instance IS 'BreakoutOS v3 Capstone AIOS instance spawned per student';

-- ─────────────────────────────────────────────────────────────
-- 6. coo_student_config
--    Per-student AI COO settings (enabled? telegram chat_id?)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.coo_student_config (
  student_id          VARCHAR(64) PRIMARY KEY,
  coo_enabled         BOOLEAN DEFAULT TRUE,
  telegram_chat_id    VARCHAR(64),
  telegram_username   VARCHAR(120),
  daily_report_time   TIME DEFAULT '06:00:00',  -- AWST default
  timezone            VARCHAR(64) DEFAULT 'Australia/Perth',
  weekly_report_day   INT DEFAULT 0,   -- 0=Sunday
  monthly_report_day  INT DEFAULT 28,
  last_daily_sent     TIMESTAMPTZ,
  last_weekly_sent    TIMESTAMPTZ,
  last_monthly_sent   TIMESTAMPTZ,
  created_at          TIMESTAMPTZ DEFAULT NOW(),
  updated_at          TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE public.coo_student_config IS 'BreakoutOS v3 Per-student AI COO config';

-- ─────────────────────────────────────────────────────────────
-- Seed: Anna là student #1 (test data)
-- ─────────────────────────────────────────────────────────────
INSERT INTO public.coo_student_config (student_id, coo_enabled, telegram_chat_id, timezone)
VALUES ('anna', TRUE, '-1003813280155', 'Australia/Perth')
ON CONFLICT (student_id) DO UPDATE SET
  coo_enabled = TRUE,
  telegram_chat_id = EXCLUDED.telegram_chat_id,
  updated_at = NOW();

COMMIT;

-- ============================================================
-- ROLLBACK script (if needed):
-- BEGIN;
-- DROP TABLE IF EXISTS public.coo_student_config;
-- DROP TABLE IF EXISTS public.capstone_instance;
-- DROP TABLE IF EXISTS public.scale_plan;
-- DROP TABLE IF EXISTS public.coo_daily_report;
-- DROP TABLE IF EXISTS public.lead_gen_plan;
-- DROP TABLE IF EXISTS public.content_engine_output;
-- COMMIT;
-- ============================================================
