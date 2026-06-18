-- Migration 015: payment_orders persistent table
-- Replace orders.json ephemeral file storage in breakout-app
-- Root cause: orders.json lost on Railway redeploy → 7 VIP CK K2 era không recover được
-- Date: 2026-06-17
-- Author: Claude session 16-17/6 reconcile work

BEGIN;

CREATE SCHEMA IF NOT EXISTS breakoutos;

CREATE TABLE IF NOT EXISTS breakoutos.payment_orders (
    -- Identity
    order_code TEXT PRIMARY KEY,

    -- Product
    product TEXT NOT NULL,                  -- 'abs-k3-vip', 'foundation', 'customer', etc.
    product_name TEXT NOT NULL,
    amount_vnd BIGINT NOT NULL,
    tag TEXT NOT NULL,                      -- GHL tag to add when paid
    stage_id TEXT,                          -- GHL pipeline stage to move to

    -- Customer
    email TEXT NOT NULL,
    phone TEXT,
    name TEXT,

    -- Lifecycle
    status TEXT NOT NULL DEFAULT 'pending', -- pending|paid|refunded|expired
    paid_at TIMESTAMPTZ,
    refunded_at TIMESTAMPTZ,
    refund_reason TEXT,

    -- Sepay
    sepay_payload JSONB,
    sepay_transaction_id TEXT,
    sepay_reference TEXT,

    -- GHL sync
    ghl_tag_result JSONB,
    ghl_stage_move_result JSONB,
    ghl_contact_id TEXT,

    -- Redirect
    success_redirect TEXT,

    -- Cohort (for K3, K4, K5+)
    cohort_id TEXT,                         -- Link to breakouts.cohorts

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_payment_orders_status ON breakoutos.payment_orders(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payment_orders_email ON breakoutos.payment_orders(email);
CREATE INDEX IF NOT EXISTS idx_payment_orders_paid_at ON breakoutos.payment_orders(paid_at DESC) WHERE status = 'paid';
CREATE INDEX IF NOT EXISTS idx_payment_orders_cohort ON breakoutos.payment_orders(cohort_id, status);
CREATE INDEX IF NOT EXISTS idx_payment_orders_sepay_ref ON breakoutos.payment_orders(sepay_reference) WHERE sepay_reference IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_payment_orders_tx_id ON breakoutos.payment_orders(sepay_transaction_id) WHERE sepay_transaction_id IS NOT NULL;

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION breakoutos.update_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_payment_orders_updated_at ON breakoutos.payment_orders;
CREATE TRIGGER trg_payment_orders_updated_at
    BEFORE UPDATE ON breakoutos.payment_orders
    FOR EACH ROW
    EXECUTE FUNCTION breakoutos.update_updated_at();

-- Webhook event log (for audit + replay)
CREATE TABLE IF NOT EXISTS breakoutos.webhook_events (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,                   -- 'sepay'|'ghl'|'wk'|'meta'
    event_type TEXT NOT NULL,               -- 'payment.received'|'tag.added'|...
    external_id TEXT,                       -- Source's event ID (for idempotency)

    -- Request
    payload JSONB NOT NULL,
    headers JSONB,

    -- Processing
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'received', -- received|processed|failed|duplicate
    result JSONB,
    error TEXT,

    -- Link to order if payment-related
    order_code TEXT REFERENCES breakoutos.payment_orders(order_code)
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_source_received ON breakoutos.webhook_events(source, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_webhook_events_external ON breakoutos.webhook_events(source, external_id);
CREATE INDEX IF NOT EXISTS idx_webhook_events_status ON breakoutos.webhook_events(status, received_at DESC) WHERE status IN ('received', 'failed');

-- Cohorts table (K3, K4, K5+ config-as-data)
CREATE TABLE IF NOT EXISTS breakoutos.cohorts (
    cohort_id TEXT PRIMARY KEY,             -- 'k3-2026-06', 'k4-2026-09'
    name TEXT NOT NULL,                     -- 'K3 Breakout Challenge'

    -- Schedule
    day1_at TIMESTAMPTZ,
    day2_at TIMESTAMPTZ,
    day3_at TIMESTAMPTZ,
    foundation_close_at TIMESTAMPTZ,

    -- Products config (JSONB for flexibility)
    products JSONB NOT NULL DEFAULT '{}',   -- {"vip": {"amount": 199000, "tag": "...", "redirect": "..."}, ...}

    -- Email config
    sender_email TEXT DEFAULT 'hang@breakout.live',
    sender_name TEXT DEFAULT 'Đào Thị Hằng',
    reply_to TEXT DEFAULT 'support@daothihang.com',

    -- Status
    status TEXT NOT NULL DEFAULT 'draft',   -- draft|active|live|closed

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cohorts_status ON breakoutos.cohorts(status, day1_at);

-- Seed K3 cohort
INSERT INTO breakoutos.cohorts (cohort_id, name, day1_at, day2_at, day3_at, foundation_close_at, products, status)
VALUES (
    'k3-2026-06',
    'K3 Breakout Challenge, AI Business Sprint',
    '2026-06-18 13:00:00+00',  -- 20:00 VN = 13:00 UTC
    '2026-06-19 13:00:00+00',
    '2026-06-20 13:00:00+00',
    '2026-06-21 15:00:00+00',  -- CN 22:00 VN
    '{
        "vip": {
            "amount": 199000,
            "tag": "venture-breakout-k3-vip",
            "success_redirect": "https://academy.daothihang.com/courses/products/d7fddc4c-0120-4964-a1b0-27f1b73d7131/categories/f577c9df-493d-445e-946b-3530ebd8bc88/posts/7208aaf5-782a-4169-8884-68191ef2009a",
            "stage_id": "e3194082-baf9-47e2-834f-bb16d5c5810f"
        },
        "foundation": {
            "amount": 3000000,
            "tag": "venture-breakout-k3-foundation",
            "success_redirect": "https://academy.daothihang.com/foundation",
            "stage_id": "75c35e31-d5ff-4614-8761-42c4da9329d6"
        }
    }'::jsonb,
    'live'
)
ON CONFLICT (cohort_id) DO UPDATE
SET products = EXCLUDED.products,
    status = EXCLUDED.status,
    updated_at = NOW();

-- Backfill 5 VIP đã reconcile session 16-17/6
INSERT INTO breakoutos.payment_orders (
    order_code, product, product_name, amount_vnd, tag, stage_id, email, name,
    status, paid_at, sepay_transaction_id, sepay_reference, cohort_id,
    success_redirect, created_at
) VALUES
    ('DHc3d62179665d13e02be3763c', 'abs-k3-vip', 'ABS K3 VIP', 199000, 'venture-breakout-k3-vip', 'e3194082-baf9-47e2-834f-bb16d5c5810f',
     'huonggiang73@gmail.com', 'Tran Huong Giang', 'paid',
     '2026-06-11 10:17:00+00', '62846264', 'FT26162870279918', 'k3-2026-06',
     'https://academy.daothihang.com/courses/products/d7fddc4c-0120-4964-a1b0-27f1b73d7131/categories/f577c9df-493d-445e-946b-3530ebd8bc88/posts/7208aaf5-782a-4169-8884-68191ef2009a',
     '2026-06-11 10:00:00+00'),

    ('DH8d03c027303c992baf560a1d', 'abs-k3-vip', 'ABS K3 VIP', 199000, 'venture-breakout-k3-vip', 'e3194082-baf9-47e2-834f-bb16d5c5810f',
     'unknown-tx3@unknown.com', 'Unknown QR Scan', 'paid',
     '2026-06-11 10:24:00+00', '62847476', 'FT26162424638569', 'k3-2026-06',
     NULL, '2026-06-11 10:24:00+00'),

    ('DH9ab4f97efdf87f5d22c2eb98', 'abs-k3-vip', 'ABS K3 VIP', 199000, 'venture-breakout-k3-vip', 'e3194082-baf9-47e2-834f-bb16d5c5810f',
     'anhthuy171992@gmail.com', 'Nguyễn Thị Thanh Thúy', 'paid',
     '2026-06-16 05:11:00+00', '63606271', 'FT26167035168134', 'k3-2026-06',
     'https://academy.daothihang.com/courses/products/d7fddc4c-0120-4964-a1b0-27f1b73d7131/categories/f577c9df-493d-445e-946b-3530ebd8bc88/posts/7208aaf5-782a-4169-8884-68191ef2009a',
     '2026-06-16 05:00:00+00'),

    ('DH57f1d0f391fd9af2c430e8a3', 'abs-k3-vip', 'ABS K3 VIP', 199000, 'venture-breakout-k3-vip', 'e3194082-baf9-47e2-834f-bb16d5c5810f',
     'phuongspinning@gmail.com', 'Nguyễn Thị Yến Phượng', 'paid',
     '2026-06-16 08:31:00+00', '63632157', 'FT26167813929008', 'k3-2026-06',
     'https://academy.daothihang.com/courses/products/d7fddc4c-0120-4964-a1b0-27f1b73d7131/categories/f577c9df-493d-445e-946b-3530ebd8bc88/posts/7208aaf5-782a-4169-8884-68191ef2009a',
     '2026-06-16 08:00:00+00'),

    ('DHd118b93861c4d0ccbb7d2bfb', 'abs-k3-vip', 'ABS K3 VIP', 199000, 'venture-breakout-k3-vip', 'e3194082-baf9-47e2-834f-bb16d5c5810f',
     'nguyen@hiepthanhplastic.net', 'Võ Thị Tố Nguyên', 'paid',
     '2026-06-16 13:33:00+00', '63680565', 'FT26167485040875', 'k3-2026-06',
     'https://academy.daothihang.com/courses/products/d7fddc4c-0120-4964-a1b0-27f1b73d7131/categories/f577c9df-493d-445e-946b-3530ebd8bc88/posts/7208aaf5-782a-4169-8884-68191ef2009a',
     '2026-06-16 13:00:00+00')

ON CONFLICT (order_code) DO UPDATE
SET status = 'paid',
    paid_at = EXCLUDED.paid_at,
    updated_at = NOW();

-- Pending orphan transactions (TX#6 NCVIP unknown, TX#1 K2 era DH8644)
-- Insert as audit trail, status='pending_identify' (custom for orphans)
INSERT INTO breakoutos.payment_orders (
    order_code, product, product_name, amount_vnd, tag, email, name,
    status, sepay_transaction_id, sepay_reference, cohort_id, created_at
) VALUES
    ('ORPHAN-FT26167241864204', 'abs-k3-vip', 'ABS K3 VIP', 199000, 'venture-breakout-k3-vip',
     'orphan-ncvip@unknown.com', 'Unknown NCVIP Q2QE8GZC', 'pending_identify',
     '63671065', 'FT26167241864204', 'k3-2026-06', '2026-06-16 12:34:00+00'),

    ('DH8644e150b57a5d8d6b2d7852', 'vip', 'VIP K2', 199000, 'breakout-vip',
     'orphan-tx1@unknown.com', 'Unknown 8/6 K2 era', 'pending_identify',
     '62374499', 'FT26159060621488', 'k2-2026-06', '2026-06-08 06:40:00+00')

ON CONFLICT (order_code) DO NOTHING;

COMMIT;

-- Verification queries (run after migration):
-- SELECT cohort_id, status, COUNT(*), SUM(amount_vnd) FROM breakoutos.payment_orders GROUP BY cohort_id, status ORDER BY cohort_id;
-- SELECT * FROM breakoutos.cohorts WHERE status = 'live';
-- SELECT email, name, status, paid_at FROM breakoutos.payment_orders WHERE cohort_id = 'k3-2026-06' ORDER BY created_at DESC;
