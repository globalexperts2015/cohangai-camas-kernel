-- Migration 013: Day 3 Challenge standalone sessions
-- Public Day 3 form (không cần BreakoutOS login).
-- Student nhập Day 1 + Day 2 inputs → Discovery Engine → 9-section report.

CREATE TABLE IF NOT EXISTS breakoutos.day3_sessions (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email            TEXT,                       -- optional, để Anna follow-up
  full_name        TEXT,
  cohort           TEXT,                       -- 'K2-2026-06'

  who_am_i         TEXT NOT NULL,              -- Day 1: tôi là ai
  core_skills      TEXT NOT NULL,              -- Day 1: năng lực
  target_customer  TEXT NOT NULL,              -- Day 2: tệp khách
  customer_pain    TEXT NOT NULL,              -- Day 2: nỗi đau
  customer_desire  TEXT NOT NULL,              -- Day 2: khát khao

  -- 9-section AI-generated output
  report_json      JSONB,                      -- {section_1, ..., section_9}
  ai_model         TEXT,
  generation_seconds NUMERIC,
  status           TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'completed' | 'failed'
  error_payload    JSONB,

  ip               TEXT,
  user_agent       TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_day3_sessions_email
  ON breakoutos.day3_sessions (email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_day3_sessions_cohort
  ON breakoutos.day3_sessions (cohort, created_at DESC);

COMMENT ON TABLE breakoutos.day3_sessions IS
  'Day 3 Challenge standalone: public form, no BreakoutOS login. Student nhập 5 input → Discovery Engine → 9-section report.';
