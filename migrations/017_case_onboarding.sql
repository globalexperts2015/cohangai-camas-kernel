-- 017_case_onboarding.sql
-- Buyer Onboarding Case (BreakoutOS V5.1 vertical slice).
-- Theo dõi vong doi 1 khach tu luc tra tien den luc duoc cap quyen va verify.
-- Idempotent: CREATE TABLE IF NOT EXISTS, an toan chay lai.
-- Schema breakoutos (cung noi voi payment_orders, ghi boi app.py psycopg2).

CREATE SCHEMA IF NOT EXISTS breakoutos;

CREATE TABLE IF NOT EXISTS breakoutos.case_onboarding (
  order_code      text PRIMARY KEY,
  email           text,
  product         text,
  tag             text,
  expected_tier   text NOT NULL DEFAULT 'free',   -- 'vip' | 'free'
  state           text NOT NULL DEFAULT 'paid',   -- paid|provisioning|access_granted|verified_active|stuck|escalated|closed
  ghl_tag_ok      boolean,
  camas_tier      text,                            -- access_tier quan sat duoc tu CAMAS
  session_exists  boolean,
  verified_ok     boolean,
  verified_at     timestamptz,
  paid_at         timestamptz,
  sla_deadline    timestamptz,
  escalated_at    timestamptz,
  attempts        integer NOT NULL DEFAULT 0,
  last_error      text,
  notes           jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_case_onboarding_state
  ON breakoutos.case_onboarding(state);
CREATE INDEX IF NOT EXISTS idx_case_onboarding_sla
  ON breakoutos.case_onboarding(sla_deadline)
  WHERE state NOT IN ('verified_active','closed');

COMMENT ON TABLE breakoutos.case_onboarding IS
  'BreakoutOS V5.1 Buyer Onboarding Case. Reconciler: breakout/tools/onboarding_case.py';
