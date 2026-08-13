"""Guard cho cơ chế tạm khoá học viên (trả góp quá hạn, Anna chốt 2026-08-13).

Kiểm hai thứ quan trọng nhất:
1. Kiểm tra trạng thái phải FAIL-OPEN. Lỗi DB, không có bản ghi, hay status lạ
   đều phải cho học viên vào. Khoá nhầm người đã trả đủ tiền tốn kém hơn nhiều
   so với việc một người nợ còn vào được thêm vài ngày.
2. Mọi form Foundation student-facing đều phải gọi kiểm tra đó, nếu không thì
   "khoá quyền" chỉ là hình thức.

Chạy tĩnh, không cần DB. Phần fail-open chạy thật với pool giả.
"""
import asyncio
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDL = (ROOT / "routes" / "sdl_routes.py").read_text(encoding="utf-8")
INTAKE = (ROOT / "routes" / "intake_forms.py").read_text(encoding="utf-8")
FREEDOM = (ROOT / "routes" / "freedom_score_routes.py").read_text(encoding="utf-8")


def test_endpoint_doi_trang_thai_can_service_key():
    assert '@router.post("/internal/student-status"' in SDL, "Thiếu endpoint đổi trạng thái học viên"
    i = SDL.index('@router.post("/internal/student-status"')
    head = SDL[i:i + 200]
    assert "require_service_key" in head, \
        "Endpoint đổi trạng thái PHẢI yêu cầu service key, không được để mở"


def test_chi_nhan_hai_trang_thai():
    i = SDL.index("async def set_student_status(")
    block = SDL[i:i + 1800]
    assert 'status not in ("active", "suspended")' in block, \
        "Chỉ được nhận đúng active và suspended, tránh gõ nhầm làm hỏng bộ lọc nơi khác"
    assert "lower(email) = $1" in block, "Phải đổi theo email chuẩn hoá chữ thường"


def test_kiem_tra_trang_thai_la_fail_open():
    i = SDL.index("async def require_student_active(")
    block = SDL[i:SDL.index("async def require_level_access(")]
    # Không đọc được DB thì cho qua
    assert "except Exception:\n        return" in block, "Lỗi DB phải cho qua, không được khoá nhầm"
    # Không có bản ghi thì cho qua
    assert "if not row:\n        return" in block, "Không có bản ghi phải cho qua"
    # Chỉ chặn khi đúng chữ suspended
    assert '!= "suspended"' in block, "Chỉ được chặn khi status đúng là suspended"


def test_moi_form_foundation_deu_kiem_trang_thai():
    # 3 form L1, L2, L3 trong intake_forms
    assert INTAKE.count("_suspended_page(pool, student_uuid)") == 3, \
        f"Phải có đủ 3 form gọi kiểm tra, đang có {INTAKE.count('_suspended_page(pool, student_uuid)')}"
    assert "require_student_active" in INTAKE, "intake_forms chưa nhập hàm kiểm tra"
    # form baseline nằm ở freedom_score_routes
    assert "require_student_active" in FREEDOM, "Form baseline chưa kiểm trạng thái"
    i = FREEDOM.index("async def baseline_form(")
    block = FREEDOM[i:i + 2500]
    assert "require_student_active(pool" in block, \
        "Form baseline phải kiểm trạng thái ngay sau khi xác thực chữ ký"


def test_thong_bao_cho_hoc_vien_khong_do_loi():
    """Chỉ soi CÂU GỬI CHO HỌC VIÊN, không soi chú thích nội bộ của lập trình viên."""
    i = SDL.index("async def require_student_active(")
    block = SDL[i:SDL.index("async def require_level_access(")]
    m = re.search(r'"message":\s*\((.*?)\),\s*\n\s*\},', block, re.S)
    assert m, "Không tìm thấy câu thông báo gửi học viên"
    msg = m.group(1)
    assert "tạm khoá" in msg, "Thông báo phải nói rõ là tạm khoá"
    assert "Zalo" in msg, "Phải cho học viên một đường liên hệ"
    for xau in ["nợ", "quỵt", "vi phạm", "kém"]:
        assert xau not in msg.lower(), f"Không dùng từ nặng nề với học viên: {xau}"


def test_fail_open_chay_that():
    """Chạy thật require_student_active với pool giả, kiểm ba tình huống."""
    import sys
    sys.path.insert(0, str(ROOT))
    from fastapi import HTTPException
    from routes.sdl_routes import require_student_active

    class _Conn:
        def __init__(self, row):
            self._row = row
        async def fetchrow(self, *a, **k):
            if isinstance(self._row, Exception):
                raise self._row
            return self._row

    class _Acq:
        def __init__(self, row):
            self._row = row
        async def __aenter__(self):
            return _Conn(self._row)
        async def __aexit__(self, *a):
            return False

    class _Pool:
        def __init__(self, row):
            self._row = row
        def acquire(self):
            return _Acq(self._row)

    async def _run(row):
        try:
            await require_student_active(_Pool(row), "00000000-0000-0000-0000-000000000000")
            return "cho_qua"
        except HTTPException:
            return "chan"

    assert asyncio.run(_run(None)) == "cho_qua", "Không có bản ghi phải cho qua"
    assert asyncio.run(_run({"status": "active"})) == "cho_qua", "Học viên active phải cho qua"
    assert asyncio.run(_run({"status": "la_gi_do"})) == "cho_qua", "Status lạ phải cho qua"
    assert asyncio.run(_run(RuntimeError("db chet"))) == "cho_qua", "Lỗi DB phải cho qua"
    assert asyncio.run(_run({"status": "suspended"})) == "chan", "Đúng suspended thì phải chặn"
    assert asyncio.run(_run({"status": "SUSPENDED"})) == "chan", "Phải chặn không phân biệt hoa thường"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} passed")
    raise SystemExit(0 if passed == len(fns) else 1)
