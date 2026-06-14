-- 005_chon_module_tables.sql
-- BreakoutOS Core Module CHỌN ĐÚNG CÁI ĐỂ BÁN (What To Sell Engine)
-- Anna spec chốt 2026-06-11. 9 engines + Opportunity Score 0-100 + re-runnable.

-- =========================================================================
-- Table 1: opportunity_run
-- 1 row mỗi lần student chạy module (re-runnable, có version)
-- =========================================================================
CREATE TABLE IF NOT EXISTS opportunity_run (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    student_id TEXT NOT NULL,
    token TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    label TEXT, -- e.g. "Dược mỹ phẩm scale quốc tế" để compare nhiều opportunity
    inputs_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    founder_profile_json JSONB,
    customer_hypothesis_json JSONB,
    financial_target_vnd BIGINT,
    lifestyle_choice TEXT, -- 'solo_ai' | 'lean_team' | 'growth_team'
    idea_hypothesis TEXT,
    opportunity_score INTEGER, -- 0-100, NULL khi đang chạy
    classification TEXT, -- 'BUILD' | 'HIGH_PRIORITY' | 'TEST_FIRST' | 'RESEARCH_MORE' | 'REJECT'
    status TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'running' | 'completed' | 'failed'
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error_msg TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_opp_run_student ON opportunity_run(student_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_opp_run_status ON opportunity_run(status, started_at DESC);

-- =========================================================================
-- Table 2: opportunity_score_breakdown
-- 1 row per engine output, link tới opportunity_run
-- 9 engines: founder_fit, customer_problem, desire, market_demand,
--   solution_design, financial, lifestyle_fit, decision, recommendation
-- =========================================================================
CREATE TABLE IF NOT EXISTS opportunity_score_breakdown (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES opportunity_run(run_id) ON DELETE CASCADE,
    engine_name TEXT NOT NULL,
    sub_score INTEGER, -- 0-100, NULL cho engine không scoring (recommendation)
    weight_pct INTEGER, -- e.g. 20 for founder_fit (chốt từ spec)
    output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    markdown_report TEXT,
    llm_model TEXT,
    llm_tokens_input INTEGER,
    llm_tokens_output INTEGER,
    duration_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    error_msg TEXT,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    UNIQUE(run_id, engine_name)
);

CREATE INDEX IF NOT EXISTS idx_opp_breakdown_run ON opportunity_score_breakdown(run_id);
CREATE INDEX IF NOT EXISTS idx_opp_breakdown_engine ON opportunity_score_breakdown(engine_name, status);

-- =========================================================================
-- Table 3: market_signal_cache
-- Cache 7 ngày cho external API calls (YouTube + DataForSEO + Google Trends)
-- Share giữa students cùng ngách để giảm cost
-- =========================================================================
CREATE TABLE IF NOT EXISTS market_signal_cache (
    id BIGSERIAL PRIMARY KEY,
    keyword TEXT NOT NULL,
    location_code INTEGER NOT NULL DEFAULT 1028581, -- 1028581 = Vietnam
    language_code TEXT NOT NULL DEFAULT 'vi',
    source TEXT NOT NULL, -- 'dataforseo_volume' | 'dataforseo_serp' | 'youtube_search' | 'google_trends'
    signal_json JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days'),
    UNIQUE(keyword, location_code, language_code, source)
);

CREATE INDEX IF NOT EXISTS idx_market_cache_keyword ON market_signal_cache(keyword, source, expires_at);
CREATE INDEX IF NOT EXISTS idx_market_cache_expires ON market_signal_cache(expires_at);

-- =========================================================================
-- Helper view: latest opportunity run per student
-- =========================================================================
CREATE OR REPLACE VIEW v_student_latest_opportunity AS
SELECT DISTINCT ON (student_id)
    student_id,
    run_id,
    version,
    label,
    opportunity_score,
    classification,
    status,
    completed_at
FROM opportunity_run
WHERE status = 'completed'
ORDER BY student_id, version DESC, completed_at DESC;

-- =========================================================================
-- Comments
-- =========================================================================
COMMENT ON TABLE opportunity_run IS 'BreakoutOS CHỌN module run state. Re-runnable per student, version increment mỗi lần re-run với input mới.';
COMMENT ON TABLE opportunity_score_breakdown IS '9 engines output per run. Sub-scores aggregate thành opportunity_score (weighted: founder 20% + problem 25% + demand 25% + financial 20% + lifestyle 10%).';
COMMENT ON TABLE market_signal_cache IS 'Cache 7 ngày external API responses. Share giữa students cùng keyword + location để giảm cost DataForSEO + YouTube quota.';
