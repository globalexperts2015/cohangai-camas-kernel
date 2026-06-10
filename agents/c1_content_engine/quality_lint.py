"""Quality lint for C1 Content Engine output pack.

Regex-based anti-generic check. Catches buzzword/sáo rỗng phrases that
indicate LLM defaulted to template content instead of pulling from the
customer profile + offer + voice register.

Also enforces house style rules: no em-dash, no emoji.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Generic Vietnamese marketing buzzwords that signal non-specific content.
# Case-insensitive match on the lowercased JSON dump of the pack.
GENERIC_PATTERNS: list[str] = [
    r"khách hàng tiềm năng",
    r"chuyển đổi cao",
    r"roi tăng",
    r"đột phá",
    r"tối ưu hoá",
    r"tối ưu hóa",
    r"khai phóng",
    r"tiên phong",
    r"giải pháp toàn diện",
    r"đa dạng",
    r"tăng trưởng vượt bậc",
    r"hàng đầu",
    r"chất lượng cao",
    r"chuyên nghiệp",
    r"hiệu quả cao",
    r"tìm hiểu thêm",
    r"khám phá ngay",
]

# Em-dash (U+2014) is forbidden by Anna's voice rules.
EM_DASH = "—"

# Basic emoji range check (covers most common pictographic ranges).
# We forbid emoji unless Anna explicitly requested them.
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"  # supplemental symbols & pictographs
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002700-\U000027BF"  # dingbats
    "]",
    flags=re.UNICODE,
)


def lint_content_pack(pack: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return (passed, list_of_violations).

    passed=True iff no banned generic phrase, no em-dash, no emoji
    detected anywhere in the serialized pack.

    Args:
        pack: dict shaped like SUBMIT_CONTENT_PACK_TOOL input_schema.

    Returns:
        (passed, violations). violations is a list of human-readable
        strings describing which rule fired. Empty list when passed.
    """
    raw = json.dumps(pack, ensure_ascii=False)
    lowered = raw.lower()
    violations: list[str] = []

    for pattern in GENERIC_PATTERNS:
        if re.search(pattern, lowered):
            violations.append(f"generic_phrase: {pattern}")

    if EM_DASH in raw:
        violations.append("em-dash detected")

    if EMOJI_PATTERN.search(raw):
        violations.append("emoji detected")

    return (len(violations) == 0, violations)
