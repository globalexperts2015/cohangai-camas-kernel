-- Migration 014: Breakout Challenge K3 sprint infrastructure.
-- Challenge data is draft-only and separate from breakoutos canonical SDL.

CREATE SCHEMA IF NOT EXISTS breakout_challenge;

CREATE OR REPLACE FUNCTION breakout_challenge.update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END $$;

CREATE TABLE IF NOT EXISTS breakout_challenge.sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  fanhub_person_id UUID,
  ghl_contact_id TEXT,
  email_normalized TEXT NOT NULL,
  full_name TEXT,
  phone TEXT,
  cohort_id TEXT NOT NULL DEFAULT 'k3-2026-06',
  access_tier TEXT NOT NULL DEFAULT 'free',
  current_state TEXT NOT NULL DEFAULT 'registered',
  resume_token_hash CHAR(64) NOT NULL UNIQUE,
  selected_idea_json JSONB,
  selected_offer_json JSONB,
  consent_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (email_normalized, cohort_id),
  CHECK (access_tier IN ('free','vip')),
  CHECK (current_state IN (
    'registered',
    'd1_generating','d1_ready','d1_selected',
    'd2_generating','d2_ready','d2_offer_approved',
    'd3_generating','completed'
  ))
);

DROP TRIGGER IF EXISTS trg_challenge_sessions_updated_at
  ON breakout_challenge.sessions;
CREATE TRIGGER trg_challenge_sessions_updated_at
  BEFORE UPDATE ON breakout_challenge.sessions
  FOR EACH ROW EXECUTE FUNCTION breakout_challenge.update_updated_at();

CREATE INDEX IF NOT EXISTS idx_challenge_sessions_cohort_state
  ON breakout_challenge.sessions(cohort_id, current_state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_challenge_sessions_person
  ON breakout_challenge.sessions(fanhub_person_id)
  WHERE fanhub_person_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS breakout_challenge.artifacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES breakout_challenge.sessions(id) ON DELETE CASCADE,
  day_number INT NOT NULL,
  artifact_type TEXT NOT NULL,
  input_json JSONB NOT NULL,
  output_json JSONB,
  markdown_content TEXT,
  evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  evidence_status TEXT NOT NULL DEFAULT 'not_checked',
  confidence_score NUMERIC(5,2),
  status TEXT NOT NULL DEFAULT 'draft',
  version INT NOT NULL DEFAULT 1,
  generated_by TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session_id, artifact_type, version),
  CHECK (day_number BETWEEN 1 AND 3),
  CHECK (status IN ('draft','generating','generated','approved','failed')),
  CHECK (evidence_status IN (
    'not_checked','insufficient','user_reported','partial','verified'
  ))
);

DROP TRIGGER IF EXISTS trg_challenge_artifacts_updated_at
  ON breakout_challenge.artifacts;
CREATE TRIGGER trg_challenge_artifacts_updated_at
  BEFORE UPDATE ON breakout_challenge.artifacts
  FOR EACH ROW EXECUTE FUNCTION breakout_challenge.update_updated_at();

CREATE INDEX IF NOT EXISTS idx_challenge_artifacts_session_day
  ON breakout_challenge.artifacts(session_id, day_number, created_at DESC);

CREATE TABLE IF NOT EXISTS breakout_challenge.events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key TEXT NOT NULL UNIQUE,
  session_id UUID NOT NULL REFERENCES breakout_challenge.sessions(id) ON DELETE CASCADE,
  fanhub_person_id UUID,
  event_type TEXT NOT NULL,
  payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_challenge_events_session_time
  ON breakout_challenge.events(session_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS breakout_challenge.generation_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key TEXT NOT NULL UNIQUE,
  session_id UUID NOT NULL REFERENCES breakout_challenge.sessions(id) ON DELETE CASCADE,
  day_number INT NOT NULL,
  artifact_type TEXT NOT NULL,
  input_json JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 3,
  scheduled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  error TEXT,
  result_artifact_id UUID REFERENCES breakout_challenge.artifacts(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (day_number BETWEEN 1 AND 3),
  CHECK (status IN ('queued','processing','completed','failed','dead'))
);

CREATE INDEX IF NOT EXISTS idx_challenge_jobs_claim
  ON breakout_challenge.generation_jobs(status, scheduled_at, created_at)
  WHERE status IN ('queued','processing');

CREATE TABLE IF NOT EXISTS breakout_challenge.integration_outbox (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key TEXT NOT NULL UNIQUE,
  session_id UUID NOT NULL REFERENCES breakout_challenge.sessions(id) ON DELETE CASCADE,
  target TEXT NOT NULL,
  operation TEXT NOT NULL,
  payload_json JSONB NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 5,
  scheduled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (target IN ('fanhub','ghl')),
  CHECK (status IN ('queued','processing','completed','failed','dead'))
);

CREATE INDEX IF NOT EXISTS idx_challenge_outbox_claim
  ON breakout_challenge.integration_outbox(status, scheduled_at, created_at)
  WHERE status IN ('queued','processing');

-- Shared cache required by the existing E6 market demand clients.
CREATE TABLE IF NOT EXISTS market_signal_cache (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  keyword TEXT NOT NULL,
  location_code INT NOT NULL DEFAULT 1028581,
  language_code TEXT NOT NULL DEFAULT 'vi',
  source TEXT NOT NULL,
  signal_json JSONB NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL DEFAULT now() + INTERVAL '7 days',
  UNIQUE(keyword, location_code, language_code, source)
);

