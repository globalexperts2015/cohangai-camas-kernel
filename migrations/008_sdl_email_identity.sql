-- =============================================================
-- Migration 008: Add email/full_name/phone to students for Sepay webhook auto-create
-- =============================================================
-- Anna command 2026-06-12 P0.1: Sepay webhook must auto-INSERT student row.
-- Email becomes primary identifier when person_id (Fan Hub UUID) not yet synced.
-- =============================================================

SET search_path TO breakoutos, public;

-- Make person_id nullable (Fan Hub may not exist yet for new payers)
ALTER TABLE breakoutos.students
  ALTER COLUMN person_id DROP NOT NULL;

-- Add email + full_name + phone
ALTER TABLE breakoutos.students
  ADD COLUMN IF NOT EXISTS email TEXT,
  ADD COLUMN IF NOT EXISTS full_name TEXT,
  ADD COLUMN IF NOT EXISTS phone TEXT,
  ADD COLUMN IF NOT EXISTS venture_id UUID;

-- Drop old uniqueness (person_id might be null now)
ALTER TABLE breakoutos.students DROP CONSTRAINT IF EXISTS students_person_id_program_id_cohort_id_key;

-- New uniqueness: email + program + cohort (when email present)
CREATE UNIQUE INDEX IF NOT EXISTS idx_students_email_program_cohort_unique
  ON breakoutos.students (lower(email), program_id, cohort_id)
  WHERE email IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_students_email ON breakoutos.students (lower(email)) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_students_phone ON breakoutos.students (phone) WHERE phone IS NOT NULL;

COMMENT ON COLUMN breakoutos.students.email IS 'Primary identifier when person_id not yet synced from Fan Hub';
COMMENT ON COLUMN breakoutos.students.person_id IS 'Fan Hub Person UUID, may be null at first payment, filled later';
