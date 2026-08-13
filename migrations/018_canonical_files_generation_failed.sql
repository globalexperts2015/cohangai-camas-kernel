-- Migration 018: cho phép status 'generation_failed' trên canonical_files
--
-- Vì sao cần: routes/l1_routes.py::_persist_tier_b ghi status 'generation_failed'
-- khi AI sinh file Tier B thất bại, nhưng CHECK constraint ở migration 006 chỉ
-- nhận ('draft','ai_generated','reviewed','locked','snapshot'). Kết quả là chính
-- đường GHI NHẬN LỖI cũng ném CheckViolationError, nên hệ thống không lưu nổi
-- bằng chứng rằng nó đã hỏng.
--
-- Hậu quả thật (phát hiện 2026-08-13): học viên nguyenhangvtpt27@gmail.com trả
-- 3 triệu ngày 03/08, AI sinh Tier B thất bại vì tài khoản Anthropic hết credit,
-- lỗi không ghi được xuống DB, chạy nền nên cũng không ai thấy. Học viên kẹt ở
-- Gate 1 suốt 10 ngày mà không có dấu vết nào trong dữ liệu.
--
-- An toàn: chỉ NỚI RỘNG tập giá trị hợp lệ, không sửa dòng nào đang có.

ALTER TABLE breakoutos.canonical_files
  DROP CONSTRAINT IF EXISTS canonical_files_status_check;

ALTER TABLE breakoutos.canonical_files
  ADD CONSTRAINT canonical_files_status_check
  CHECK (status IN ('draft','ai_generated','reviewed','locked','snapshot','generation_failed'));
