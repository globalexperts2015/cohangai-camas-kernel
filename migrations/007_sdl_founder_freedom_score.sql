-- =============================================================
-- Migration 007: BreakoutOS Founder Freedom Score (North Star Metric)
-- =============================================================
-- Per Anna's full build command 2026-06-12 + Master Architecture V3.5.7 Section 30:
--   - T0 baseline MANDATORY before L1 access
--   - 7 components: Revenue 18 + Time 18 + Stress 13 + Clarity 13 + Auto 10 + Mission 18 + Dependency 10
--   - Total 0-100, graduation ≥70
--   - Block L1 access HTTP 412 if no baseline
--
-- Spec: wiki/concepts/breakoutos-master-architecture.md Section 6 (North Star)
-- =============================================================

SET search_path TO breakoutos, public;

CREATE TABLE IF NOT EXISTS breakoutos.founder_freedom_score (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id                  UUID NOT NULL REFERENCES breakoutos.students(id) ON DELETE CASCADE,
  measured_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
  source                      TEXT NOT NULL,           -- 'self_baseline'|'self_weekly'|'behavior'|'peer'|'ai_compute'
  -- 7 components per V3.5.7 weights
  revenue_score               INT CHECK (revenue_score BETWEEN 0 AND 18),
  time_score                  INT CHECK (time_score BETWEEN 0 AND 18),
  stress_score                INT CHECK (stress_score BETWEEN 0 AND 13),
  clarity_score               INT CHECK (clarity_score BETWEEN 0 AND 13),
  automation_score            INT CHECK (automation_score BETWEEN 0 AND 10),
  mission_alignment_score     INT CHECK (mission_alignment_score BETWEEN 0 AND 18),
  -- Dependency 4 mức D3+D7+D30+D90, max 10
  dependency_d3               INT CHECK (dependency_d3 BETWEEN 0 AND 1),
  dependency_d7               INT CHECK (dependency_d7 BETWEEN 0 AND 3),
  dependency_d30              INT CHECK (dependency_d30 BETWEEN 0 AND 3),
  dependency_d90              INT CHECK (dependency_d90 BETWEEN 0 AND 3),
  dependency_total            INT GENERATED ALWAYS AS (
    COALESCE(dependency_d3,0) + COALESCE(dependency_d7,0) +
    COALESCE(dependency_d30,0) + COALESCE(dependency_d90,0)
  ) STORED,
  -- Total 0-100
  total_score                 INT GENERATED ALWAYS AS (
    COALESCE(revenue_score,0) + COALESCE(time_score,0) +
    COALESCE(stress_score,0) + COALESCE(clarity_score,0) +
    COALESCE(automation_score,0) + COALESCE(mission_alignment_score,0) +
    COALESCE(dependency_d3,0) + COALESCE(dependency_d7,0) +
    COALESCE(dependency_d30,0) + COALESCE(dependency_d90,0)
  ) STORED,
  notes_json                  JSONB DEFAULT '{}'::jsonb,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_freedom_score_student
  ON breakoutos.founder_freedom_score(student_id, measured_at DESC);

CREATE INDEX IF NOT EXISTS idx_freedom_score_baseline
  ON breakoutos.founder_freedom_score(student_id)
  WHERE source = 'self_baseline';

-- Convenience view: latest score per student
CREATE OR REPLACE VIEW breakoutos.v_freedom_score_latest AS
SELECT DISTINCT ON (student_id)
  student_id,
  measured_at,
  source,
  total_score,
  revenue_score, time_score, stress_score, clarity_score,
  automation_score, mission_alignment_score, dependency_total
FROM breakoutos.founder_freedom_score
ORDER BY student_id, measured_at DESC;

-- Baseline (T0) per student
CREATE OR REPLACE VIEW breakoutos.v_freedom_score_baseline AS
SELECT DISTINCT ON (student_id)
  student_id,
  measured_at AS baseline_at,
  total_score AS baseline_score
FROM breakoutos.founder_freedom_score
WHERE source = 'self_baseline'
ORDER BY student_id, measured_at ASC;

COMMENT ON TABLE breakoutos.founder_freedom_score IS
  'BreakoutOS North Star Metric. 7 components, total 0-100. '
  'T0 baseline MANDATORY pre-L1 (per V3.5.7 + Anna build command). '
  'Graduation target ≥70/100 at Gate 6a Founder Freedom Cert.';
