"""Test fixtures shared across the camas-kernel suite.

Ensure HMAC_SECRET is present so token-derivation helpers (which now fail loud
when it is unset in production) work deterministically in the focused suite.
"""
import os

os.environ.setdefault(
    "HMAC_SECRET", "test-only-hmac-secret-deterministic-0123456789abcdef"
)
