"""Smoke test 6 validation priorities per Anna 2026-06-12."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


BASE = "https://os.breakout.live"
ADMIN_KEY = os.environ.get("BREAKOUTOS_ADMIN_KEY")
if not ADMIN_KEY:
    sys.exit("ERROR: BREAKOUTOS_ADMIN_KEY env var required. Set in .env or shell before running.")


def call(method: str, url: str, body=None, headers=None):
    full = url if url.startswith("http") else BASE + url
    data = json.dumps(body).encode() if body is not None else None
    h = {"User-Agent": "smoke-val/1.0"}
    if body is not None: h["Content-Type"] = "application/json"
    if headers: h.update(headers)
    req = urllib.request.Request(full, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return e.code, {"raw": "non-json"}
    except Exception as e:
        return 0, {"error": str(e)}


def hdr(s): print(f"\n{'='*60}\n{s}\n{'='*60}")

results = []

hdr("1. DEMO MODE — seed demo student")
status, body = call("POST", f"/sdl/admin/demo/seed?key={ADMIN_KEY}")
demo_sid = body.get("demo_student_id")
print(f"HTTP {status} · demo_student_id={demo_sid}")
print(f"Links: {body.get('links', {})}")
results.append(("Demo Mode seed", status == 201 and demo_sid))

hdr("2. EVENT TRACKING — page.view")
status, body = call("POST", "/sdl/events/track", body={
    "student_id": demo_sid, "event_type": "page.view", "source": "frontend",
    "payload": {"path": "/foundation/l1"},
})
print(f"HTTP {status} · event_id={body.get('event_id')}")
results.append(("Event tracking POST", status == 201))

status, body = call("GET", f"/sdl/admin/events?key={ADMIN_KEY}&hours=1&limit=5")
print(f"Events 1h: {len(body) if isinstance(body, list) else 'err'}")
results.append(("Event tracking GET admin", status == 200))

hdr("3. VALIDATION DASHBOARD")
status, body = call("GET", f"/sdl/admin/validation?key={ADMIN_KEY}&cohort_id=cohort_1")
print(f"HTTP {status} · criteria={len(body.get('criteria', []))} · overall_pass={body.get('overall_pass')}")
for c in body.get("criteria", []):
    print(f"  {c['label']}: {c['actual']}/{c['target']}")
results.append(("Validation status", status == 200 and len(body.get("criteria", [])) == 5))

status, body = call("GET", f"/sdl/admin/validation/dashboard?key={ADMIN_KEY}")
print(f"Validation HTML: HTTP {status}")
results.append(("Validation dashboard HTML", status == 200))

hdr("4. FEEDBACK MODULE")
if demo_sid:
    status, body = call("POST", "/sdl/feedback", body={
        "student_id": demo_sid, "target_type": "canonical_file",
        "target_key": "life-mission", "rating": 9, "comment": "Rất hữu ích",
    })
    print(f"Feedback POST: HTTP {status} · feedback_id={body.get('feedback_id')}")
    results.append(("Feedback POST", status == 201))

    status, body = call("POST", "/sdl/feedback", body={
        "student_id": demo_sid, "target_type": "overall_nps",
        "rating": 9, "comment": "Likely to recommend",
    })
    results.append(("Feedback NPS", status == 201))

    status, body = call("GET", f"/sdl/admin/feedback?key={ADMIN_KEY}")
    print(f"Feedback admin: {body.get('feedback_count')} entries · NPS={body.get('nps', {})}")
    results.append(("Feedback admin list", status == 200))

hdr("5. FOUNDER DASHBOARD")
status, body = call("GET", f"/sdl/admin/founder-dashboard?key={ADMIN_KEY}")
print(f"Founder dashboard HTML: HTTP {status}")
results.append(("Founder dashboard", status == 200))

hdr("6. ERROR MONITORING")
status, body = call("GET", f"/sdl/admin/errors?key={ADMIN_KEY}&hours=24")
print(f"Errors 24h: HTTP {status} · count={body.get('total', '?')}")
results.append(("Error monitoring list", status == 200))

# Cleanup demo
hdr("CLEANUP — delete demo students")
status, body = call("DELETE", f"/sdl/admin/demo/cleanup?key={ADMIN_KEY}")
print(f"Cleanup: HTTP {status} · deleted={body.get('deleted')}")
results.append(("Cleanup demo", status == 200))

hdr("RESULTS")
passed = sum(1 for _, ok in results if ok)
print(f"\n{passed}/{len(results)} tests passed\n")
for name, ok in results:
    print(f"  {'✓' if ok else '✗'} {name}")

sys.exit(0 if passed == len(results) else 1)
