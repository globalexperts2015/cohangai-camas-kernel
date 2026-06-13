-- =============================================================
-- Migration 010: Founder Freedom Score V3.6 rebuild
-- =============================================================
-- Per Anna BREAKOUTOS V3.6 (2026-06-12): 10 questions × 0-10 = 100 total.
-- Replace 7-component weighted (18/13/10) với 10 chiều bằng nhau.
-- Add AI-generated Founder Freedom Report after submit.
-- =============================================================

SET search_path TO breakoutos, public;

ALTER TABLE breakoutos.founder_freedom_score
  ADD COLUMN IF NOT EXISTS q1_income          INT CHECK (q1_income          BETWEEN 0 AND 10),
  ADD COLUMN IF NOT EXISTS q2_profit          INT CHECK (q2_profit          BETWEEN 0 AND 10),
  ADD COLUMN IF NOT EXISTS q3_time_free       INT CHECK (q3_time_free       BETWEEN 0 AND 10),
  ADD COLUMN IF NOT EXISTS q4_peace           INT CHECK (q4_peace           BETWEEN 0 AND 10),
  ADD COLUMN IF NOT EXISTS q5_clarity         INT CHECK (q5_clarity         BETWEEN 0 AND 10),
  ADD COLUMN IF NOT EXISTS q6_customer        INT CHECK (q6_customer        BETWEEN 0 AND 10),
  ADD COLUMN IF NOT EXISTS q7_system_ai       INT CHECK (q7_system_ai       BETWEEN 0 AND 10),
  ADD COLUMN IF NOT EXISTS q8_independence    INT CHECK (q8_independence    BETWEEN 0 AND 10),
  ADD COLUMN IF NOT EXISTS q9_growth          INT CHECK (q9_growth          BETWEEN 0 AND 10),
  ADD COLUMN IF NOT EXISTS q10_meaning        INT CHECK (q10_meaning        BETWEEN 0 AND 10),
  ADD COLUMN IF NOT EXISTS total_v2           INT,
  ADD COLUMN IF NOT EXISTS classification_v2  TEXT,
  ADD COLUMN IF NOT EXISTS report_json        JSONB,
  ADD COLUMN IF NOT EXISTS schema_version     TEXT DEFAULT 'v1';

-- Add generated column for total_v2 (not via ADD COLUMN GENERATED to avoid conflict with old data)
-- Use trigger to keep total_v2 in sync
CREATE OR REPLACE FUNCTION breakoutos.update_total_v2() RETURNS TRIGGER AS $$
BEGIN
  IF NEW.q1_income IS NOT NULL OR NEW.q2_profit IS NOT NULL OR NEW.q3_time_free IS NOT NULL THEN
    NEW.total_v2 := COALESCE(NEW.q1_income,0) + COALESCE(NEW.q2_profit,0)
                  + COALESCE(NEW.q3_time_free,0) + COALESCE(NEW.q4_peace,0)
                  + COALESCE(NEW.q5_clarity,0) + COALESCE(NEW.q6_customer,0)
                  + COALESCE(NEW.q7_system_ai,0) + COALESCE(NEW.q8_independence,0)
                  + COALESCE(NEW.q9_growth,0) + COALESCE(NEW.q10_meaning,0);
    -- Classification 5 levels
    NEW.classification_v2 := CASE
      WHEN NEW.total_v2 BETWEEN 0  AND 20  THEN 'tim_loi_di'
      WHEN NEW.total_v2 BETWEEN 21 AND 40  THEN 'thu_nghiem'
      WHEN NEW.total_v2 BETWEEN 41 AND 60  THEN 'dang_van_hanh'
      WHEN NEW.total_v2 BETWEEN 61 AND 80  THEN 'co_he_thong'
      WHEN NEW.total_v2 BETWEEN 81 AND 100 THEN 'tu_do'
      ELSE NULL END;
    NEW.schema_version := 'v2';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_freedom_score_v2_total ON breakoutos.founder_freedom_score;
CREATE TRIGGER trg_freedom_score_v2_total
  BEFORE INSERT OR UPDATE ON breakoutos.founder_freedom_score
  FOR EACH ROW EXECUTE FUNCTION breakoutos.update_total_v2();

-- Drop + recreate views (column structure changed)
DROP VIEW IF EXISTS breakoutos.v_freedom_score_latest;
DROP VIEW IF EXISTS breakoutos.v_freedom_score_baseline;

CREATE VIEW breakoutos.v_freedom_score_latest AS
SELECT DISTINCT ON (student_id)
  student_id,
  measured_at,
  source,
  schema_version,
  COALESCE(total_v2, total_score) AS total_score,
  total_score AS total_score_v1,
  total_v2,
  classification_v2,
  -- v2 columns
  q1_income, q2_profit, q3_time_free, q4_peace, q5_clarity,
  q6_customer, q7_system_ai, q8_independence, q9_growth, q10_meaning,
  report_json,
  -- legacy v1 columns
  revenue_score, time_score, stress_score, clarity_score,
  automation_score, mission_alignment_score, dependency_total
FROM breakoutos.founder_freedom_score
ORDER BY student_id, measured_at DESC;

CREATE VIEW breakoutos.v_freedom_score_baseline AS
SELECT DISTINCT ON (student_id)
  student_id,
  measured_at AS baseline_at,
  schema_version,
  COALESCE(total_v2, total_score) AS baseline_score,
  classification_v2 AS baseline_classification
FROM breakoutos.founder_freedom_score
WHERE source = 'self_baseline'
ORDER BY student_id, measured_at ASC;

COMMENT ON COLUMN breakoutos.founder_freedom_score.total_v2 IS
  'V3.6 total: sum of 10 questions × 0-10 = max 100. Replace v1 weighted formula.';
