"""Prompt builder + tool schema cho BC9 Compliance Officer.

Layer 2 (LLM semantic check) chạy SAU Layer 1 (deterministic regex).
LLM được given context của 7 layer rule + content + violations đã catch ở layer 1,
để paraphrased / semantic violations không lọt qua.

Tham chiếu briefing: cohangai/agents/_briefing/bc9-compliance-officer-brief.md
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml


# Structured tool output schema, Claude trả verdict qua tool_use.
COMPLIANCE_TOOL = {
    "name": "submit_compliance_review",
    "description": (
        "Submit compliance review verdict for 7 layer check "
        "(MARA + Privacy + Financial + Platform + LegendCom + Brand + Facts). "
        "Verdict APPROVE = clean, FLAG = soft issues Anna review, "
        "BLOCK = hard violation cannot publish."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["APPROVE", "FLAG", "BLOCK"],
                "description": (
                    "Overall verdict. BLOCK if any HARD violation. "
                    "FLAG if soft violations only. APPROVE if clean."
                ),
            },
            "layers": {
                "type": "object",
                "description": "Verdict per layer: clean | soft | hard",
                "properties": {
                    "mara": {"type": "string"},
                    "privacy": {"type": "string"},
                    "financial": {"type": "string"},
                    "platform": {"type": "string"},
                    "legend_com": {"type": "string"},
                    "brand": {"type": "string"},
                    "facts": {"type": "string"},
                },
                "required": [
                    "mara",
                    "privacy",
                    "financial",
                    "platform",
                    "legend_com",
                    "brand",
                    "facts",
                ],
            },
            "violations": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Danh sách rule_id hoặc mô tả vi phạm. Empty nếu clean."
                ),
            },
            "suggested_fixes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "original": {"type": "string"},
                        "suggested": {"type": "string"},
                        "rule_id": {"type": "string"},
                    },
                    "required": ["original", "suggested", "rule_id"],
                },
                "description": (
                    "Suggested rewrites cho violations. Tiếng Việt. "
                    "Max 5 fixes. Empty nếu không có violation."
                ),
            },
            "notes": {
                "type": "string",
                "description": "Tổng kết ngắn (max 200 ký tự).",
            },
        },
        "required": ["verdict", "layers", "violations"],
    },
}


def load_rules(rules_dir: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    """Load 7 file YAML từ rules/ folder.

    Returns:
        dict layer_name -> rule_set dict
    """
    if rules_dir is None:
        rules_dir = Path(__file__).parent / "rules"
    rule_files = [
        "mara",
        "privacy",
        "financial",
        "platform",
        "legend_com",
        "brand",
        "facts",
    ]
    rules: dict[str, dict[str, Any]] = {}
    for name in rule_files:
        path = rules_dir / f"{name}.yaml"
        if not path.exists():
            continue
        rules[name] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return rules


def build_rule_summary(rules: dict[str, dict[str, Any]]) -> str:
    """Compact text summary cho prompt LLM (avoid token bloat)."""
    lines: list[str] = []
    for layer_name, ruleset in rules.items():
        desc = ruleset.get("description", "")
        lines.append(f"## Layer {layer_name.upper()}: {desc}")
        banned = ruleset.get("banned_phrases") or []
        if banned:
            lines.append("Hard rules (BLOCK):")
            for rule in banned:
                if rule.get("severity") != "hard":
                    continue
                rid = rule.get("id", "")
                reason = rule.get("reason", "")
                lines.append(f"  - {rid}: {reason}")
        soft = (ruleset.get("soft_warnings") or []) + [
            r for r in banned if r.get("severity") == "soft"
        ]
        if soft:
            lines.append("Soft rules (FLAG):")
            for rule in soft:
                rid = rule.get("id", "")
                reason = rule.get("reason", "")
                lines.append(f"  - {rid}: {reason}")
        lines.append("")
    return "\n".join(lines)


def build_review_prompt(
    content: str,
    meta: dict,
    rules: dict[str, dict[str, Any]],
    deterministic_violations: list[dict[str, Any]],
) -> str:
    """Build prompt cho Claude semantic review.

    Args:
        content: AI-generated content cần review
        meta: dict {venture, channel, language, persona, topic}
        rules: parsed 7 layer rules
        deterministic_violations: violation list từ layer 1 regex
    """
    rule_summary = build_rule_summary(rules)

    if deterministic_violations:
        det_lines = [
            f"- Layer={v['layer']} rule={v['rule_id']} severity={v['severity']} match={v['match'][:60]!r}"
            for v in deterministic_violations
        ]
        det_block = "\n".join(det_lines)
    else:
        det_block = "(Không có violation deterministic, content sạch lớp regex.)"

    venture = meta.get("venture", "unspecified")
    channel = meta.get("channel", "unspecified")
    language = meta.get("language", "vi")

    return f"""Bạn là BC9 Compliance Officer cho Đào Thị Hằng (Anna), Cohangai AIOS Kernel.

NHIỆM VỤ: Review content trước khi publish public, qua 7 layer compliance.
Verdict:
- APPROVE: content sạch, publish OK
- FLAG: có soft issue, Anna review trong 30 phút
- BLOCK: có hard violation, KHÔNG publish

Lưu ý conflict resolution per Constitution Section E: BC9 BLOCK thắng BC2 voice APPROVE.

========================================================================
7 LAYER RULES (SUMMARY)
========================================================================

{rule_summary}

========================================================================
LAYER 1 RESULT (DETERMINISTIC REGEX SCAN)
========================================================================

{det_block}

========================================================================
CONTENT METADATA
========================================================================

Venture: {venture}
Channel: {channel}
Language: {language}
Persona: {meta.get('persona', 'unspecified')}
Topic: {meta.get('topic', 'unspecified')}

========================================================================
CONTENT CẦN REVIEW
========================================================================

---CONTENT START---
{content}
---CONTENT END---

========================================================================
NHIỆM VỤ
========================================================================

Step 1: ĐỌC kỹ content + layer 1 violations. Layer 1 đã catch hard pattern,
nhưng paraphrased / semantic violation có thể lọt. Kiểm thêm 7 layer:

1. MARA: visa rate, personal advice, eligibility assessment, shortcut.
2. PRIVACY: PII raw (card, TFN, DOB), email/phone cụ thể trong content public.
3. FINANCIAL: guarantee refund vô điều kiện, đảm bảo lãi, fake permanent discount.
4. PLATFORM: ZNS template chưa approved, FB Ads banned terms, spam CTA.
5. LEGEND_COM: quote Migration Act/MSI/PAM3 raw >200 ký tự, nhắc 'LegendCom' công khai.
6. BRAND: marital status (mẹ đơn thân/ly thân), city (Perth/Adelaide), Việt kiều,
   wrong display name (Hằng Coaching/Anna Đào), team mention, William trong BMCorner,
   em-dash "—", cross-promote Speakout/Breakout trong personal brand Hằng.
7. FACTS: số liệu Speakout (33k+ contacts, 5k paid), Breakout pricing 5 tier,
   MARA license 1/2027, Master Adelaide, Coaching 6 tháng.

Step 2: VERDICT từng layer (clean / soft / hard).
Step 3: Tổng hợp verdict:
- BLOCK nếu BẤT KỲ layer = hard
- FLAG nếu chỉ có soft (≥1 layer)
- APPROVE nếu tất cả clean

Step 4: Suggest fixes tiếng Việt cho violations (max 5). Format object
{{original, suggested, rule_id}}. KHÔNG tự sửa số liệu Anna đã nói
(per feedback-no-change-facts-without-asking), chỉ FLAG.

========================================================================
SUBMIT KẾT QUẢ
========================================================================

GỌI tool `submit_compliance_review` với verdict + layers + violations
(+ suggested_fixes + notes nếu có). KHÔNG output text ngoài tool call.
"""
