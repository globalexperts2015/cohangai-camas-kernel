-- =============================================================
-- Migration 006: BreakoutOS Student Data Layer (SDL) MVP
-- =============================================================
-- Anna approved 2026-06-12 with 3 amendments:
--   1. SDL prerequisite infrastructure before Module CHỌN production rollout
--   2. Opportunity score 5 fields: founder_fit + market_demand + monetization + ai_leverage + confidence
--   3. Gate policy: G1 Hard Founder Core / G2 Soft Customer / G2 Hard only after L3 Offer Validation
--
-- Schema: breakoutos (separated from public + cdp)
-- Deploy: extend camas-kernel Railway service
-- Spec: wiki/concepts/breakoutos-student-data-layer-spec.md
-- Master: wiki/concepts/breakoutos-master-architecture.md
-- =============================================================

CREATE SCHEMA IF NOT EXISTS breakoutos;

SET search_path TO breakoutos, public;

-- ---------------------------------------------------------------
-- Shared trigger function for updated_at columns
-- ---------------------------------------------------------------
CREATE OR REPLACE FUNCTION breakoutos.update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$;

-- ---------------------------------------------------------------
-- 1. students (master record per student × cohort × program)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS breakoutos.students (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  person_id       UUID NOT NULL,
  fanhub_person_id UUID,
  program_id      TEXT NOT NULL,
  cohort_id       TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'active',
  current_level   INT  NOT NULL DEFAULT 1,
  current_gate    TEXT,
  archetype       TEXT,
  metadata_json   JSONB DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(person_id, program_id, cohort_id)
);
CREATE INDEX IF NOT EXISTS idx_students_person ON breakoutos.students(person_id);
CREATE INDEX IF NOT EXISTS idx_students_cohort ON breakoutos.students(cohort_id, status);
CREATE TRIGGER trg_students_updated_at BEFORE UPDATE ON breakoutos.students
  FOR EACH ROW EXECUTE FUNCTION breakoutos.update_updated_at();

-- ---------------------------------------------------------------
-- 2. founder_profiles (L1 data)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS breakoutos.founder_profiles (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id            UUID NOT NULL REFERENCES breakoutos.students(id) ON DELETE CASCADE,
  mission               TEXT,
  vision                TEXT,
  why_statement         TEXT,
  identity              TEXT,
  principles_json       JSONB,
  anti_vision_json      JSONB,
  founder_assets_json   JSONB,
  founder_story_json    JSONB,
  structured_data_json  JSONB,
  markdown_path         TEXT,
  status                TEXT DEFAULT 'draft',
  version               INT DEFAULT 1,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(student_id, version)
);
CREATE INDEX IF NOT EXISTS idx_founder_profiles_student ON breakoutos.founder_profiles(student_id, version DESC);
CREATE TRIGGER trg_founder_profiles_updated_at BEFORE UPDATE ON breakoutos.founder_profiles
  FOR EACH ROW EXECUTE FUNCTION breakoutos.update_updated_at();

-- ---------------------------------------------------------------
-- 3. customer_profiles (L2 data)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS breakoutos.customer_profiles (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id                  UUID NOT NULL REFERENCES breakoutos.students(id) ON DELETE CASCADE,
  target_customer             TEXT,
  jobs_json                   JSONB,
  pains_json                  JSONB,
  gains_json                  JSONB,
  buying_triggers_json        JSONB,
  buying_journey_json         JSONB,
  demand_evidence_json        JSONB,
  conversation_evidence_json  JSONB,
  fit_score_json              JSONB,
  structured_data_json        JSONB,
  markdown_path               TEXT,
  status                      TEXT DEFAULT 'draft',
  version                     INT DEFAULT 1,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(student_id, version)
);
CREATE INDEX IF NOT EXISTS idx_customer_profiles_student ON breakoutos.customer_profiles(student_id, version DESC);
CREATE TRIGGER trg_customer_profiles_updated_at BEFORE UPDATE ON breakoutos.customer_profiles
  FOR EACH ROW EXECUTE FUNCTION breakoutos.update_updated_at();

-- ---------------------------------------------------------------
-- 4. opportunity_maps (L2.5 bridge — Anna amendment 5 fields)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS breakoutos.opportunity_maps (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id            UUID NOT NULL REFERENCES breakoutos.students(id) ON DELETE CASCADE,
  opportunities_json    JSONB,
  selected_opportunity  TEXT,
  founder_fit_score     INT,
  market_demand_score   INT,
  monetization_score    INT,
  ai_leverage_score     INT,
  confidence_score      INT,
  total_score           INT GENERATED ALWAYS AS (
    COALESCE(founder_fit_score,0) + COALESCE(market_demand_score,0) +
    COALESCE(monetization_score,0) + COALESCE(ai_leverage_score,0) +
    COALESCE(confidence_score,0)
  ) STORED,
  evidence_json         JSONB,
  structured_data_json  JSONB,
  markdown_path         TEXT,
  status                TEXT DEFAULT 'draft',
  version               INT DEFAULT 1,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_opportunity_maps_student ON breakoutos.opportunity_maps(student_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_opportunity_maps_score ON breakoutos.opportunity_maps(total_score DESC);
CREATE TRIGGER trg_opportunity_maps_updated_at BEFORE UPDATE ON breakoutos.opportunity_maps
  FOR EACH ROW EXECUTE FUNCTION breakoutos.update_updated_at();

-- ---------------------------------------------------------------
-- 5. offers (L3 Value Proposition)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS breakoutos.offers (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id                UUID NOT NULL REFERENCES breakoutos.students(id) ON DELETE CASCADE,
  offer_name                TEXT,
  target_customer           TEXT,
  pain                      TEXT,
  desired_identity          TEXT,
  vehicle                   TEXT,
  transformation            TEXT,
  pricing_json              JSONB,
  value_equation_json       JSONB,
  guarantee_strategy_json   JSONB,
  offer_stack_json          JSONB,
  financial_model_json      JSONB,
  structured_data_json      JSONB,
  markdown_path             TEXT,
  status                    TEXT DEFAULT 'draft',
  version                   INT DEFAULT 1,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_offers_student ON breakoutos.offers(student_id, version DESC);
CREATE TRIGGER trg_offers_updated_at BEFORE UPDATE ON breakoutos.offers
  FOR EACH ROW EXECUTE FUNCTION breakoutos.update_updated_at();

-- ---------------------------------------------------------------
-- 6. positioning_profiles (L3, tách khỏi offer)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS breakoutos.positioning_profiles (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id              UUID NOT NULL REFERENCES breakoutos.students(id) ON DELETE CASCADE,
  category                TEXT,
  enemy                   TEXT,
  unique_angle            TEXT,
  positioning_statement   TEXT,
  statement_one_line      TEXT,
  differentiation_json    JSONB,
  market_context_json     JSONB,
  structured_data_json    JSONB,
  markdown_path           TEXT,
  status                  TEXT DEFAULT 'draft',
  version                 INT DEFAULT 1,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_positioning_student ON breakoutos.positioning_profiles(student_id, version DESC);
CREATE TRIGGER trg_positioning_updated_at BEFORE UPDATE ON breakoutos.positioning_profiles
  FOR EACH ROW EXECUTE FUNCTION breakoutos.update_updated_at();

-- ---------------------------------------------------------------
-- 7. canonical_files (universal registry, 47 file × tier × lock_type)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS breakoutos.canonical_files (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id            UUID NOT NULL REFERENCES breakoutos.students(id) ON DELETE CASCADE,
  level                 INT NOT NULL,
  file_key              TEXT NOT NULL,
  file_name             TEXT NOT NULL,
  file_type             TEXT NOT NULL DEFAULT 'canonical',
  tier                  CHAR(1) NOT NULL,
  lock_type             TEXT NOT NULL DEFAULT 'strategic',
  markdown_content      TEXT,
  structured_data_json  JSONB,
  version               INT DEFAULT 1,
  status                TEXT DEFAULT 'draft',
  generated_by          TEXT,
  reviewed_by           UUID,
  ai_signature          TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(student_id, file_key, version),
  CHECK (tier IN ('A','B','C')),
  CHECK (lock_type IN ('core','strategic','operational')),
  CHECK (status IN ('draft','ai_generated','reviewed','locked','snapshot'))
);
CREATE INDEX IF NOT EXISTS idx_canonical_files_student ON breakoutos.canonical_files(student_id, level, file_key);
CREATE INDEX IF NOT EXISTS idx_canonical_files_tier ON breakoutos.canonical_files(student_id, tier, status);
CREATE TRIGGER trg_canonical_files_updated_at BEFORE UPDATE ON breakoutos.canonical_files
  FOR EACH ROW EXECUTE FUNCTION breakoutos.update_updated_at();

-- ---------------------------------------------------------------
-- 8. canonical_locks (gate state — Anna amendment Soft+Hard)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS breakoutos.canonical_locks (
  id                BIGSERIAL PRIMARY KEY,
  student_id        UUID NOT NULL REFERENCES breakoutos.students(id) ON DELETE CASCADE,
  gate_key          TEXT NOT NULL,
  level             INT NOT NULL,
  locked_files_json JSONB NOT NULL,
  lock_status       TEXT NOT NULL DEFAULT 'soft',
  locked_at         TIMESTAMPTZ DEFAULT now(),
  locked_by         UUID,
  signature         TEXT,
  snapshot_json     JSONB,
  unlock_reason     TEXT,
  unlocked_at       TIMESTAMPTZ,
  recert_required   BOOLEAN DEFAULT FALSE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (lock_status IN ('soft','hard','unlocked'))
);
CREATE INDEX IF NOT EXISTS idx_canonical_locks_student ON breakoutos.canonical_locks(student_id, gate_key, locked_at DESC);
CREATE INDEX IF NOT EXISTS idx_canonical_locks_active ON breakoutos.canonical_locks(student_id, gate_key)
  WHERE unlocked_at IS NULL;

-- ---------------------------------------------------------------
-- 9. student_events (ledger — Tally/AI chat/Homework/Fathom/WK)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS breakoutos.student_events (
  id                    BIGSERIAL PRIMARY KEY,
  student_id            UUID REFERENCES breakoutos.students(id) ON DELETE CASCADE,
  person_id             UUID,
  event_type            TEXT NOT NULL,
  source                TEXT NOT NULL,
  level                 INT,
  payload_json          JSONB NOT NULL,
  extracted_data_json   JSONB,
  extraction_status     TEXT DEFAULT 'pending',
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (extraction_status IN ('pending','extracted','failed','reviewed','skipped'))
);
CREATE INDEX IF NOT EXISTS idx_student_events_student ON breakoutos.student_events(student_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_student_events_type ON breakoutos.student_events(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_student_events_pending ON breakoutos.student_events(extraction_status, created_at)
  WHERE extraction_status = 'pending';

-- =============================================================
-- Seed: Gate registry helper view
-- =============================================================
CREATE OR REPLACE VIEW breakoutos.v_student_gate_status AS
SELECT
  s.id AS student_id,
  s.person_id,
  s.current_level,
  s.current_gate,
  s.cohort_id,
  s.program_id,
  l.gate_key,
  l.lock_status,
  l.locked_at,
  l.unlocked_at,
  l.recert_required
FROM breakoutos.students s
LEFT JOIN LATERAL (
  SELECT * FROM breakoutos.canonical_locks
  WHERE student_id = s.id
  ORDER BY locked_at DESC LIMIT 1
) l ON true;

-- =============================================================
-- Migration meta
-- =============================================================
COMMENT ON SCHEMA breakoutos IS
  'BreakoutOS Student Data Layer (SDL). Founder Business Graph. '
  'Spec: wiki/concepts/breakoutos-student-data-layer-spec.md. '
  'Master: wiki/concepts/breakoutos-master-architecture.md. '
  'D30 boundary: SDL OWNS founder business data, Fan Hub OWNS person relationship. '
  'Migration 006 applied 2026-06-12 with Anna 3 amendments.';
