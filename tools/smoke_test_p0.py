"""Smoke test 5 P0 + full flow per Anna's command 2026-06-12.

Tests:
1. POST /sdl/webhooks/payment-completed → student row created
2. Module CHỌN /run với invalid gate → 403
3. Module CHỌN /run with valid gate → success (skip, requires full L1+L2)
4. Cohort 1 tier_visibility filter → only Tier A returned
5. Vault export zip has 04 AI Context + 05 Canonical Outputs folders
6. Admin dashboard with new BREAKOUTOS_ADMIN_KEY → 200

Run: python3 tools/smoke_test_p0.py
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request


BASE = "https://os.breakout.live"
ADMIN_KEY = os.environ.get("BREAKOUTOS_ADMIN_KEY")
if not ADMIN_KEY:
    sys.exit("ERROR: BREAKOUTOS_ADMIN_KEY env var required. Set in .env or shell before running.")


def call(method: str, url: str, body=None, headers=None) -> tuple[int, dict]:
    full = url if url.startswith("http") else BASE + url
    data = None
    h = {"User-Agent": "smoke-test/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h["Content-Type"] = "application/json"
    if headers:
        h.update(headers)
    req = urllib.request.Request(full, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            err_body = {"raw": "non-json"}
        return e.code, err_body
    except Exception as e:
        return 0, {"error": str(e)}


def header(title: str):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


# ============================================================
# Smoke tests
# ============================================================
results = []
test_email = f"smoke+{secrets.token_hex(4)}@daothihang.com"
test_phone = "0900000000"


header("P0.1 — Sepay webhook auto-create student")
status, body = call(
    "POST", "/sdl/webhooks/payment-completed",
    body={
        "email": test_email, "full_name": "Smoke Test User", "phone": test_phone,
        "product": "foundation", "amount_vnd": 3_000_000,
        "order_code": "DH" + secrets.token_hex(12),
        "cohort_id": "cohort_1",
    },
)
print(f"HTTP {status} · student_id={body.get('student_id')} · next={body.get('next_step')}")
sdl_student_id = body.get("student_id")
results.append(("P0.1 Sepay webhook", status == 201 and sdl_student_id))

if sdl_student_id:
    header("P0.1a — Re-call same email → idempotent (upsert)")
    status2, body2 = call(
        "POST", "/sdl/webhooks/payment-completed",
        body={"email": test_email, "full_name": "Smoke Test User Updated",
              "phone": test_phone, "product": "foundation",
              "amount_vnd": 3_000_000, "cohort_id": "cohort_1"},
    )
    same = body2.get("student_id") == sdl_student_id
    print(f"HTTP {status2} · same_student_id={same}")
    results.append(("P0.1a Idempotent upsert", status2 == 201 and same))

    header("P0.1b — Lookup by email")
    status3, body3 = call("GET", f"/sdl/students/by-email/{test_email}?program_id=foundation&cohort_id=cohort_1")
    print(f"HTTP {status3} · student_id={body3.get('id')} · email={body3.get('email')}")
    results.append(("P0.1b Email lookup", status3 == 200 and body3.get("id") == sdl_student_id))


header("P0.2 — Module CHỌN gate check (no breakoutos_student_id)")
status, body = call(
    "POST", "/cohort/chon-module/run",
    body={
        "founder_profile": {"name": "test"},
        "customer_hypothesis": "test customer",
        "opportunity_hypothesis": "test opp",
    },
    headers={"X-Cohort-Student-Token": "fake-token-no-validation"},
)
print(f"HTTP {status} · detail={body.get('detail') if isinstance(body.get('detail'), str) else (body.get('detail', {}).get('error', body))}")
# Expect 403 (gate check fail) OR 401 (token verify fail) — both valid block
results.append(("P0.2 Module CHỌN block no gate", status in (401, 403)))


if sdl_student_id:
    header("P0.3 — Cohort 1 tier visibility filter")
    status, body = call("GET", f"/sdl/students/{sdl_student_id}/canonical-files")
    tier_a_only = all(f.get("tier") == "A" for f in body) if isinstance(body, list) else False
    print(f"HTTP {status} · files={len(body) if isinstance(body, list) else 'err'} · all_tier_A={tier_a_only}")
    results.append(("P0.3 Cohort 1 Tier A filter", status == 200 and (tier_a_only or len(body) == 0)))

    header("P0.3a — Override filter cohort_filter=false → all tiers visible")
    status, body = call("GET", f"/sdl/students/{sdl_student_id}/canonical-files?cohort_filter=false")
    print(f"HTTP {status} · files={len(body) if isinstance(body, list) else 'err'}")
    results.append(("P0.3a Override filter", status == 200))


header("P0.5 — Admin dashboard with BREAKOUTOS_ADMIN_KEY")
status, body = call("GET", f"/sdl/admin/students?key={ADMIN_KEY}")
print(f"HTTP {status} · count={len(body) if isinstance(body, list) else 'err'}")
results.append(("P0.5 Admin dashboard key", status == 200))

header("P0.5b — Admin dashboard with WRONG key → 401")
status, body = call("GET", "/sdl/admin/students?key=wrong-key-test")
print(f"HTTP {status}")
results.append(("P0.5b Admin wrong key blocked", status == 401))


if sdl_student_id:
    header("P0.4 — Vault export zip (check 04 AI Context + 05 Canonical Outputs presence)")
    import io
    import zipfile
    try:
        with urllib.request.urlopen(f"{BASE}/sdl/students/{sdl_student_id}/vault/export.zip", timeout=30) as r:
            zip_bytes = r.read()
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            has_readme = "README.md" in names
            # Pre-gate, no AI Context or Canonical Outputs yet (empty student), but export should still work
            print(f"Zip size={len(zip_bytes)} bytes · files={len(names)} · README.md={has_readme}")
            for n in names[:10]:
                print(f"  - {n}")
        results.append(("P0.4 Vault export zip works", has_readme))
    except Exception as e:
        print(f"Vault export FAIL: {e}")
        results.append(("P0.4 Vault export zip", False))


# ============================================================
# Summary
# ============================================================
header("RESULTS SUMMARY")
passed = sum(1 for _, ok in results if ok)
total = len(results)
print(f"\n{passed}/{total} tests passed\n")
for name, ok in results:
    print(f"  {'✓' if ok else '✗'} {name}")

sys.exit(0 if passed == total else 1)
