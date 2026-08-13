-- Migration 019: bang ghi nhan moi lan goi LLM
--
-- Vi sao can: Anna hoi "tien API di vao dau" va khong ai tra loi duoc.
-- Truoc do chi lop Starter OS ghi chi phi, ghi vao JSON trong
-- breakout_challenge.sessions.metadata_json->'api_spend_log', khong co model,
-- khong tach token vao/ra, khong biet agent nao goi. Cac duong con lai
-- (8 file L1, L2, L3, freedom score, cron, 81 agent) khong ghi gi.
--
-- AWS Bedrock chi bao duoc tong tien theo model, KHONG bao duoc agent nao goi.
-- Phan quy trach nhiem bat buoc phai tu ghi.
--
-- Rieng tu: bang nay KHONG chua noi dung prompt, KHONG chua cau tra loi,
-- KHONG chua email hay ten hoc vien. Chi so token va ten noi goi.
--
-- An toan: chi THEM bang moi, khong sua bang nao dang co.

CREATE TABLE IF NOT EXISTS breakoutos.llm_usage_log (
  id                  BIGSERIAL PRIMARY KEY,
  occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  provider            TEXT        NOT NULL,              -- bedrock | anthropic
  model               TEXT        NOT NULL,              -- ten chuan: claude-sonnet-4-6
  model_raw           TEXT,                              -- ma that gui di: au.anthropic.claude-sonnet-4-6
  input_tokens        INTEGER     NOT NULL DEFAULT 0,
  output_tokens       INTEGER     NOT NULL DEFAULT 0,
  cache_read_tokens   INTEGER     NOT NULL DEFAULT 0,
  cache_write_tokens  INTEGER     NOT NULL DEFAULT 0,
  estimated_cost_usd  NUMERIC(12,6),                     -- NULL khi khong biet gia, khong bia so
  caller              TEXT,                              -- routes/l1_routes:_generate_ai_context
  call_group          TEXT,                              -- hoc_vien_lam_bai | chat_lop | cron | agent_noi_bo | test_manual
  student_id          UUID,
  request_id          TEXT,
  success             BOOLEAN     NOT NULL DEFAULT TRUE,
  error_type          TEXT,
  duration_ms         INTEGER
);

-- Bao cao luon truy theo thoi gian truoc, roi moi nhom.
CREATE INDEX IF NOT EXISTS idx_llm_usage_occurred     ON breakoutos.llm_usage_log (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_model_day    ON breakoutos.llm_usage_log (model, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_group_day    ON breakoutos.llm_usage_log (call_group, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_caller_day   ON breakoutos.llm_usage_log (caller, occurred_at DESC);
