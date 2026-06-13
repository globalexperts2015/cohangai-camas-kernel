-- =============================================================
-- Migration 011: Founder Freedom Score V3.6.5 weighted formula
-- =============================================================
-- Anna 2026-06-13: trở về kiến trúc 7 thành phần V3.5.7 với trọng số.
-- 10 input questions × 0-10, nhưng tính FFS theo weighted formula 100%.
-- q6_customer = diagnostic only, KHÔNG cộng vào FFS.
--   Sứ mệnh 18%  (q10_meaning)
--   Bình an 13%  (q4_peace)
--   Rõ ràng 13%  (q5_clarity)
--   Tài chính 18% = AVG(Thu nhập q1, Dòng tiền q2) × 18%
--   Vận hành 10%  = AVG(Hệ thống q7, AI q9) × 10%
--   Độc lập 10%   (q8_independence)
--   Thời gian 18% (q3_time_free)
-- =============================================================

SET search_path TO breakoutos, public;

CREATE OR REPLACE FUNCTION breakoutos.update_total_v2() RETURNS TRIGGER AS $$
BEGIN
  IF NEW.q1_income IS NOT NULL OR NEW.q2_profit IS NOT NULL OR NEW.q3_time_free IS NOT NULL
     OR NEW.q4_peace IS NOT NULL OR NEW.q10_meaning IS NOT NULL THEN
    NEW.total_v2 := ROUND(
        COALESCE(NEW.q10_meaning,     0)::numeric * 1.8
      + COALESCE(NEW.q4_peace,        0)::numeric * 1.3
      + COALESCE(NEW.q5_clarity,      0)::numeric * 1.3
      + (COALESCE(NEW.q1_income,    0) + COALESCE(NEW.q2_profit,   0))::numeric * 0.9
      + (COALESCE(NEW.q7_system_ai, 0) + COALESCE(NEW.q9_growth,   0))::numeric * 0.5
      + COALESCE(NEW.q8_independence, 0)::numeric * 1.0
      + COALESCE(NEW.q3_time_free,    0)::numeric * 1.8
    )::INT;
    NEW.classification_v2 := CASE
      WHEN NEW.total_v2 BETWEEN 0  AND 20  THEN 'tim_loi_di'
      WHEN NEW.total_v2 BETWEEN 21 AND 40  THEN 'thu_nghiem'
      WHEN NEW.total_v2 BETWEEN 41 AND 60  THEN 'dang_van_hanh'
      WHEN NEW.total_v2 BETWEEN 61 AND 80  THEN 'co_he_thong'
      WHEN NEW.total_v2 BETWEEN 81 AND 100 THEN 'tu_do'
      ELSE NULL END;
    NEW.schema_version := 'v2_weighted';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

COMMENT ON COLUMN breakoutos.founder_freedom_score.total_v2 IS
  'V3.6.5 weighted FFS: Sứ mệnh 18% + Bình an 13% + Rõ ràng 13% + AVG(Income, Profit) 18% + AVG(System, AI) 10% + Độc lập 10% + Thời gian tự do 18% = 100. Câu Khách hàng (q6) là diagnostic, không tính vào FFS.';
