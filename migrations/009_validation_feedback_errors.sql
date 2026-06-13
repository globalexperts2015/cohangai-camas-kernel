-- =============================================================
-- Migration 009: Validation, Feedback, Error Monitoring tables
-- =============================================================
-- Per Anna's command 2026-06-12 evening: feature freeze + 10-student validation focus
-- 6 priorities: Demo Mode + Event Tracking + Validation Dashboard +
-- Feedback Module + Founder Dashboard + Error Monitoring
-- =============================================================

SET search_path TO breakoutos, public;

-- ---------------------------------------------------------------
-- feedback table
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS breakoutos.feedback (
  id            BIGSERIAL PRIMARY KEY,
  student_id    UUID REFERENCES breakoutos.students(id) ON DELETE CASCADE,
  target_type   TEXT NOT NULL,       -- 'canonical_file' | 'gate' | 'level' | 'overall_nps' | 'webinar_session'
  target_key    TEXT,                -- file_key | gate_key | level_num | session_id
  rating        INT CHECK (rating BETWEEN 1 AND 10),
  comment       TEXT,
  metadata_json JSONB DEFAULT '{}'::jsonb,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_feedback_student ON breakoutos.feedback(student_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_target ON breakoutos.feedback(target_type, target_key);

-- ---------------------------------------------------------------
-- system_errors table for Error Monitoring
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS breakoutos.system_errors (
  id            BIGSERIAL PRIMARY KEY,
  occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  student_id    UUID,                -- nullable for errors not tied to student
  route         TEXT,                -- '/sdl/l1/intake' etc.
  method        TEXT,                -- 'POST' etc.
  status_code   INT,
  error_type    TEXT,                -- exception class name
  error_message TEXT,
  traceback     TEXT,
  request_body  JSONB,
  user_agent    TEXT,
  ip_address    TEXT,
  notified_telegram BOOLEAN DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_errors_occurred ON breakoutos.system_errors(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_errors_student ON breakoutos.system_errors(student_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_errors_unnotified ON breakoutos.system_errors(occurred_at)
  WHERE notified_telegram = FALSE;

-- ---------------------------------------------------------------
-- demo_students seed (Demo Mode)
-- ---------------------------------------------------------------
-- We just use breakoutos.students with metadata_json.is_demo=true
-- No separate table.

-- ---------------------------------------------------------------
-- validation_snapshots: stores 10-student validation criteria status per cohort
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS breakoutos.validation_snapshots (
  id              BIGSERIAL PRIMARY KEY,
  cohort_id       TEXT NOT NULL,
  snapshot_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  total_students  INT NOT NULL,
  l1_l3_complete  INT NOT NULL,       -- target 10
  statement_pass  INT NOT NULL,       -- target 8
  offer_validated INT NOT NULL,       -- target 6
  first_paid      INT NOT NULL,       -- target 3
  case_studies    INT NOT NULL,       -- target 1
  details_json    JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_val_cohort ON breakoutos.validation_snapshots(cohort_id, snapshot_at DESC);

COMMENT ON TABLE breakoutos.feedback IS 'Student feedback per canonical file / gate / level / overall NPS';
COMMENT ON TABLE breakoutos.system_errors IS 'Error monitoring log + Telegram alert tracking';
COMMENT ON TABLE breakoutos.validation_snapshots IS '10-student validation criteria daily snapshot per cohort';
