"""Ghi nhan moi lan goi LLM: token, chi phi uoc tinh, ai goi.

Vi sao co file nay (2026-08-13):
    Anna hoi "tien API di vao dau" va khong ai tra loi duoc. Truoc do chi lop
    Starter OS ghi chi phi, ghi vao JSON trong bang phien, khong co model,
    khong tach token vao/ra. Cac duong con lai (8 file L1, L2, L3, freedom
    score, cron, 81 agent) khong ghi gi.

    AWS chi bao duoc tong tien theo model, KHONG bao duoc agent nao goi. Phan
    quy trach nhiem bat buoc phai tu ghi.

Nguyen tac: KHONG BAO GIO lam hong lenh goi that.
    Moi thu trong file nay boc trong try/except, loi ghi nhan chi log warning
    roi di tiep. Hoc vien khong bao gio thay khac biet.

Rieng tu: chi ghi so token va ten noi goi. KHONG ghi noi dung prompt,
    KHONG ghi cau tra loi, KHONG ghi email hay ten hoc vien.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import time
from typing import Any, Optional

log = logging.getLogger("camas.llm_usage")

# Lop ghi nhan nam sau cung, khong biet dang phuc vu hoc vien nao. Route dat
# gia tri nay o dau request, moi lan goi LLM ben trong tu doc ra.
# Dung contextvars nen an toan voi asyncio: hai request chay song song khong
# giam du lieu cua nhau.
_STUDENT: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "llm_usage_student_id", default=None
)


def set_student(student_id: Any) -> None:
    """Route goi ham nay o dau request. Hong cung khong duoc lam gay request."""
    try:
        _STUDENT.set(str(student_id) if student_id else None)
    except Exception:  # noqa: BLE001
        pass


def current_student() -> Optional[str]:
    try:
        return _STUDENT.get()
    except Exception:  # noqa: BLE001
        return None

# Gia USD tren 1 trieu token, lay tu AWS Bedrock ngay 2026-08-13
# (list_foundation_model_agreement_offers, vung ap-southeast-2).
_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-fable-5": (10.0, 50.0),
}

# Doi ma Bedrock nguoc ve ten model de tra gia.
_BEDROCK_PREFIXES = ("au.", "apac.", "global.", "us.", "eu.", "anthropic.")


def _base_model_name(model: str) -> str:
    """au.anthropic.claude-sonnet-4-6 -> claude-sonnet-4-6"""
    if not isinstance(model, str):
        return "unknown"
    m = model
    for _ in range(3):
        for p in _BEDROCK_PREFIXES:
            if m.startswith(p):
                m = m[len(p):]
                break
        else:
            break
    # bo duoi phien ban kieu -20251001-v1:0
    for suffix in ("-20251001-v1:0", "-20250929-v1:0", "-v1:0", "-v1"):
        if m.endswith(suffix):
            m = m[: -len(suffix)]
    return m


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    """Uoc tinh chi phi. Tra None khi khong biet gia, de bao cao khong bia so."""
    price = _PRICING.get(_base_model_name(model))
    if price is None:
        return None
    return input_tokens / 1e6 * price[0] + output_tokens / 1e6 * price[1]


# Nhung goi/thu muc coi la "khong phai nguoi goi that", bo qua khi truy nguon.
_SKIP_MODULES = ("kernel/llm_usage", "kernel/llm_provider", "anthropic/", "asyncio/", "botocore/")


def caller_hint() -> tuple[str, str]:
    """Truy nguoc ngan xep tim ai goi. Tra (ten_noi_goi, nhom).

    Khong dung inspect.stack() vi no doc file nguon, rat cham. Dung sys._getframe.
    """
    try:
        depth = 2
        while depth < 40:
            try:
                f = sys._getframe(depth)
            except ValueError:
                break
            path = (f.f_code.co_filename or "").replace("\\", "/")
            if not any(s in path for s in _SKIP_MODULES):
                short = "/".join(path.rsplit("/", 2)[-2:]).removesuffix(".py")
                return f"{short}:{f.f_code.co_name}", _group_of(path)
            depth += 1
    except Exception:
        pass
    return "unknown", "khong_ro"


def _group_of(path: str) -> str:
    """Xep lenh goi vao nhom nghiep vu de bao cao doc duoc."""
    p = path.replace("\\", "/")
    # Chay tay: python -c, heredoc, REPL, script roi. Deu la nguoi go tay, khong
    # phai he thong tu chay, nen gop vao mot nhom de khong lam nhieu bao cao.
    if p.startswith("<") or "/" not in p:
        return "test_manual"
    if "/tests/" in p or "/tools/" in p:
        return "test_manual"
    if "/agents/cron_" in p or "/cron_" in p:
        return "cron"
    if "challenge_k3" in p or "day3_challenge" in p:
        return "chat_lop"
    if any(k in p for k in ("l1_routes", "l2_routes", "l3_routes", "l1_extraction",
                            "l2_extraction", "freedom_score", "intake_forms", "discovery_routes")):
        return "hoc_vien_lam_bai"
    if "/agents/" in p:
        return "agent_noi_bo"
    if "/routes/" in p:
        return "route_khac"
    return "khong_ro"


# ---- Ghi xuong Postgres (tuy chon) -------------------------------------------
# main.py goi set_pool(pool) luc khoi dong. Khong co pool thi chi ghi ra log.
_POOL: Any = None


def set_pool(pool: Any) -> None:
    global _POOL
    _POOL = pool


_INSERT = """
INSERT INTO breakoutos.llm_usage_log
  (occurred_at, provider, model, model_raw, input_tokens, output_tokens,
   cache_read_tokens, cache_write_tokens, estimated_cost_usd, caller, call_group,
   student_id, request_id, success, error_type, duration_ms)
VALUES (now(), $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
"""


async def record(
    *,
    provider: str,
    model_raw: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    student_id: Optional[str] = None,
    request_id: Optional[str] = None,
    success: bool = True,
    error_type: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> None:
    """Ghi mot lan goi. Khong bao gio nem loi ra ngoai."""
    try:
        caller, group = caller_hint()
        model = _base_model_name(model_raw)
        cost = estimate_cost_usd(model_raw, input_tokens, output_tokens)
        if student_id is None:
            student_id = current_student()

        # Luon ghi mot dong JSON ra log. Chay duoc o moi noi, khong phu thuoc DB.
        log.info(
            "llm_usage %s",
            json.dumps(
                {
                    "provider": provider,
                    "model": model,
                    "in": input_tokens,
                    "out": output_tokens,
                    "cache_read": cache_read_tokens,
                    "cost_usd": round(cost, 6) if cost is not None else None,
                    "caller": caller,
                    "group": group,
                    "student_id": student_id,
                    "request_id": request_id,
                    "ok": success,
                    "err": error_type,
                    "ms": duration_ms,
                },
                ensure_ascii=False,
            ),
        )

        if _POOL is None:
            return
        async with _POOL.acquire() as conn:
            await conn.execute(
                _INSERT, provider, model, model_raw, input_tokens, output_tokens,
                cache_read_tokens, cache_write_tokens, cost, caller, group,
                student_id, request_id, success, error_type, duration_ms,
            )
    except Exception as exc:  # noqa: BLE001 - ghi nhan hong khong duoc lam hong viec that
        log.warning("llm_usage ghi that bai, bo qua: %s", exc)


def now_ms() -> int:
    return int(time.time() * 1000)


def enabled() -> bool:
    """Cho phep tat han bang bien moi truong neu can."""
    return os.environ.get("LLM_USAGE_LOG", "1").strip().lower() not in ("0", "false", "off")
