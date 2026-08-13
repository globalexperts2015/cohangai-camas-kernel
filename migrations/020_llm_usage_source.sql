-- Migration 020: them cot `source` vao bang ghi nhan LLM
--
-- Vi sao can: tu hom nay ca camas-kernel lan breakout-app deu ghi vao chung
-- bang breakoutos.llm_usage_log. Khong co cot nay thi bao cao khong tach duoc
-- tien cua dich vu nao, ma hai ben lam viec khac han: camas-kernel sinh ho so
-- hoc vien, breakout-app chay chat lop va Gap Report.
--
-- An toan: chi THEM cot moi co gia tri mac dinh, khong sua du lieu dang co.
-- Ban ghi cu (truoc hom nay) deu tu camas-kernel nen mac dinh dung.

ALTER TABLE breakoutos.llm_usage_log
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'camas-kernel';

CREATE INDEX IF NOT EXISTS idx_llm_usage_source_day
  ON breakoutos.llm_usage_log (source, occurred_at DESC);
