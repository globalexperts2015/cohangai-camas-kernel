"""HMAC authentication helpers for student-facing BreakoutOS routes."""
from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import HTTPException, Request


SIGNATURE_HEADER = "X-Student-Signature"
MIN_SECRET_BYTES = 32


def _secret() -> bytes:
    secret = os.environ.get("HMAC_SECRET", "").encode()
    if len(secret) < MIN_SECRET_BYTES:
        raise RuntimeError("HMAC_SECRET must be at least 32 bytes")
    return secret


def sign_student(student_id: str) -> str:
    """Create the short-lived-link signature used in Anna's Zalo onboarding URL."""
    return hmac.new(_secret(), student_id.encode(), hashlib.sha256).hexdigest()[:16]


def _verify_hmac(student_id: str, sig: str) -> bool:
    if not student_id or not sig:
        return False
    expected = sign_student(student_id)
    return hmac.compare_digest(expected, sig)


def request_signature(request: Request, sig: str = "") -> str:
    """Read signature from query string first, then the POST header."""
    return sig or request.headers.get(SIGNATURE_HEADER, "")


def require_student_signature(student_id: str, sig: str) -> None:
    if not _verify_hmac(student_id, sig):
        raise HTTPException(
            status_code=403,
            detail="Đường link không hợp lệ. Liên hệ Hằng qua Zalo.",
        )


SERVICE_KEY_HEADER = "X-Internal-Service-Key"


def _service_key_ok(request: Request) -> bool:
    """True nếu request mang service key hợp lệ (gọi nội bộ: webhook, admin, cron)."""
    expected = os.environ.get("INTERNAL_SERVICE_KEY", "") or os.environ.get(
        "BREAKOUTOS_ADMIN_KEY", ""
    )
    if not expected:
        return False
    provided = request.headers.get(SERVICE_KEY_HEADER, "") or request.query_params.get(
        "key", ""
    )
    return bool(provided) and hmac.compare_digest(provided, expected)


def require_service_key(request: Request) -> None:
    """Dependency cho route hệ thống (create student, lookup, event ingest)."""
    if not _service_key_ok(request):
        raise HTTPException(status_code=401, detail="Service authentication required.")


def require_student_access(student_id, request: Request, sig: str = "") -> None:
    """Dependency cho route student-scoped.

    Cho qua nếu có service key hợp lệ (nội bộ), nếu không thì bắt buộc signed link
    khớp đúng student_id. Khóa toàn bộ SDL + L4-L6a theo yêu cầu launch.
    """
    if _service_key_ok(request):
        return
    require_student_signature(str(student_id), request_signature(request, sig))
