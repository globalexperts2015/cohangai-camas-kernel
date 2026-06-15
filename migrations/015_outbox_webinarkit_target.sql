-- 015: allow 'webinarkit' as an integration_outbox target (K3 register → WebinarKit sync).
-- Migration 014 created CHECK (target IN ('fanhub','ghl')); widen it. Idempotent.

ALTER TABLE breakout_challenge.integration_outbox
  DROP CONSTRAINT IF EXISTS integration_outbox_target_check;

ALTER TABLE breakout_challenge.integration_outbox
  ADD CONSTRAINT integration_outbox_target_check
  CHECK (target IN ('fanhub', 'ghl', 'webinarkit'));
