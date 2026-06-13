-- Migration 012: Business Discovery Reports
-- Day 3 Challenge: AI Business Discovery Engine
-- Aggregates L1 + L2 canonical files → 9-section report
-- Per Anna 2026-06-13: "Biến 'Tôi là ai + Tôi giỏi gì + Tôi muốn phục vụ ai'
-- thành 'cơ hội kinh doanh có xác suất thành công cao nhất'"

CREATE TABLE IF NOT EXISTS breakoutos.discovery_reports (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id       UUID NOT NULL REFERENCES breakoutos.students(id) ON DELETE CASCADE,
  cohort           TEXT,                                  -- e.g. "K2-cohort-1"
  founder_profile_snapshot_json JSONB NOT NULL,           -- L1 5 Tier A + 3 Tier B at run time
  customer_profile_snapshot_json JSONB NOT NULL,          -- L2 4 Tier A + 7 Tier B at run time

  -- 9 sections per Day 3 spec
  section_1_founder_summary_json    JSONB,                -- Bạn là ai + lợi thế + ai phục vụ tốt nhất
  section_2_customer_reality_json   JSONB,                -- Pain + desire + urgency ranked
  section_3_market_demand_json      JSONB,                -- Keyword + intent + trend + opportunity score
  section_4_opportunity_ideas_json  JSONB,                -- ≥10 product + service + coaching + membership + ai
  section_5_validation_matrix_json  JSONB,                -- Score: founder_fit, customer_fit, market_demand, profit, ai_leverage
  section_6_recommended_offer_json  JSONB,                -- TOP 1: why + risk + timeline + first sale strategy
  section_7_one_page_offer_json     JSONB,                -- Tên + KH + vấn đề + giải pháp + kết quả + giá + cam kết + kênh + CTA
  section_8_content_engine_json     JSONB,                -- 30 ideas × 5 channels (content, video, FB, YT, lead magnet)
  section_9_action_plan_json        JSONB,                -- 4 tuần roadmap → khách đầu tiên

  external_data_sources JSONB DEFAULT '{}'::jsonb,        -- Future: google_trends, atp, reddit, youtube, fb_ads
  generation_method TEXT NOT NULL DEFAULT 'ai',           -- 'ai' | 'ai+mocked_apis' | 'ai+live_apis'
  ai_model TEXT,                                          -- e.g. 'claude-sonnet-4-6'
  generation_seconds NUMERIC,                             -- elapsed time
  error_payload JSONB,                                    -- if generation_failed

  status TEXT NOT NULL DEFAULT 'completed',               -- 'running' | 'completed' | 'generation_failed'
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_discovery_reports_student
  ON breakoutos.discovery_reports (student_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_discovery_reports_cohort
  ON breakoutos.discovery_reports (cohort, created_at DESC);

COMMENT ON TABLE breakoutos.discovery_reports IS
  'Day 3 Business Discovery Engine reports. Each row = 1 run aggregating L1+L2 canonical → 9-section AI-generated business opportunity report.';
