"""L1 Tier B AI extraction + Markdown rendering.

Per Anna's build command + ASSUMPTIONS.md A4:
- Dual output: Markdown + Structured JSON
- Schema-constrained generation via Claude
- Default Haiku 4.5, Opus 4.7 for narrative quality (founder-story)
- Save to canonical_files table + typed founder_profiles column
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from uuid import UUID

import anthropic

from .prompts import EXTRACTION_REGISTRY


log = logging.getLogger("camas.l1_extract")

_CLIENT: anthropic.AsyncAnthropic | None = None

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_CREDENTIAL_RE = re.compile(
    r"\b(?:mba|msc|ma|phd|ielts|pte|certificate|certification|license|licence|"
    r"diploma|degree|chứng chỉ|bằng cấp|cử nhân|thạc sĩ|tiến sĩ)\b",
    re.IGNORECASE,
)


def _precheck_evidence(file_key: str, inputs: dict[str, Any]) -> dict[str, Any] | None:
    lived = str(inputs.get("lived_experience", "") or "").strip()

    if file_key == "founder-story":
        years = sorted(set(_YEAR_RE.findall(lived)))
        if len(years) < 3:
            return {
                "error": "insufficient_evidence",
                "missing": ["≥3 năm cụ thể trong lived_experience"],
                "guidance": (
                    "Bổ sung ít nhất 3 cột mốc với năm, vai trò hoặc địa điểm "
                    "và chi tiết thật, ví dụ 2015, 2018, 2023."
                ),
            }

    if file_key == "founder-assets":
        evidence_count = len(_NUMBER_RE.findall(lived)) + len(_CREDENTIAL_RE.findall(lived))
        if evidence_count < 2:
            return {
                "error": "insufficient_evidence",
                "missing": ["≥2 số liệu cụ thể hoặc credential trong lived_experience"],
                "guidance": (
                    "Bổ sung ít nhất 2 bằng chứng như số năm kinh nghiệm, "
                    "kết quả đo được, quy mô tài sản, bằng cấp hoặc chứng chỉ."
                ),
            }

    return None


def _client() -> anthropic.AsyncAnthropic:
    global _CLIENT
    if _CLIENT is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _CLIENT = anthropic.AsyncAnthropic(api_key=api_key)
    return _CLIENT


async def extract_canonical(
    file_key: str, inputs: dict[str, Any],
) -> dict[str, Any]:
    """Run AI extraction for given file_key.

    Returns structured JSON conformant to schema in prompt.
    Adds metadata: extraction_model, extracted_at.
    """
    if file_key not in EXTRACTION_REGISTRY:
        raise ValueError(f"Unknown file_key: {file_key}")

    evidence_error = _precheck_evidence(file_key, inputs)
    if evidence_error:
        return evidence_error

    cfg = EXTRACTION_REGISTRY[file_key]
    prompt = cfg["prompt"].format(**{
        k: inputs.get(k, "(không có)") for k in cfg["input_keys"]
    })

    try:
        resp = await _client().messages.create(
            model=cfg["model"],
            max_tokens=cfg["max_tokens"],
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIStatusError as exc:
        log.exception("AI extraction failed for %s: %s", file_key, exc)
        if exc.status_code in (400, 429):
            return {
                "error": "api_limit_or_invalid",
                "status_code": exc.status_code,
                "message": str(exc),
            }
        raise

    raw = resp.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()
    # Remove leading "json" language tag
    if raw.startswith("json"):
        raw = raw[4:].strip()

    try:
        structured = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("AI returned non-JSON for %s: %s", file_key, raw[:200])
        return {
            "error": "json_decode_failed",
            "raw_preview": raw[:500],
            "json_error": str(exc),
            "stop_reason": resp.stop_reason,
        }

    structured["_meta"] = {
        "extraction_model": cfg["model"],
        "tokens_used": resp.usage.input_tokens + resp.usage.output_tokens,
        "stop_reason": resp.stop_reason,
    }
    return structured


def render_markdown(file_key: str, structured: dict[str, Any], student_id: UUID) -> str:
    """Render Markdown view from structured JSON.

    Template inline để tránh phụ thuộc Jinja2 file system trong Railway.
    """
    if structured.get("error"):
        return (
            f"# {file_key.replace('-', ' ').title()}\n\n"
            f"> ⚠️ Lỗi sinh nội dung: {structured.get('error')}.\n"
            f"> Vui lòng thử lại hoặc liên hệ Hằng qua Zalo.\n"
        )

    fm = (
        "---\n"
        f"file_key: {file_key}\n"
        f"student_id: {student_id}\n"
        "tier: B\n"
        "lock_type: core\n"
        "locked: false\n"
        "ai_generated: true\n"
        "version: 1\n"
        f"extraction_model: {structured.get('_meta', {}).get('extraction_model', 'unknown')}\n"
        "---\n\n"
    )

    if file_key == "why-statement":
        return fm + (
            f"# Lý Do Cốt Lõi (Why Statement)\n\n"
            f"> {structured.get('why_core', '')}\n\n"
            f"## Mở rộng\n\n"
            f"{structured.get('why_paragraph_1', '')}\n\n"
            f"{structured.get('why_paragraph_2', '')}\n\n"
            f"## Neo cá nhân\n\n"
            f"{structured.get('personal_anchor', '')}\n\n"
            f"---\n"
            f"*Confidence: {structured.get('confidence_score', 0)}/100*\n"
        )

    if file_key == "founder-assets":
        sections = []
        sections.append(f"# Tài Sản Sáng Lập (Founder Assets)\n")
        sections.append(f"\n## Kiến thức\n")
        for k in structured.get("knowledge", []):
            sections.append(f"- {k}\n")
        sections.append(f"\n## Kinh nghiệm\n")
        for exp in structured.get("experience", []):
            sections.append(f"- {exp.get('years', '')} năm · {exp.get('field', '')} · {exp.get('role', '')}\n")
        sections.append(f"\n## Chứng chỉ\n")
        for c in structured.get("certifications", []):
            sections.append(f"- {c}\n")
        net = structured.get("network", {})
        sections.append(f"\n## Mạng lưới\n- {net.get('count', '?')} người · tier {net.get('tier', '?')} · niche {net.get('niche', '?')}\n")
        sections.append(f"\n## Case studies\n")
        for cs in structured.get("case_studies", []):
            sections.append(f"- **{cs.get('title', '')}**: {cs.get('proof', '')}\n")
        sections.append(f"\n## Story tags\n")
        for t in structured.get("story_tags", []):
            sections.append(f"- {t}\n")
        media = structured.get("media", {})
        sections.append(f"\n## Truyền thông\n- FB page: {'✓' if media.get('fb_page') else '✗'}\n")
        sections.append(f"- Email list: {media.get('email_list', 0)}\n")
        sections.append(f"- Podcast: {'✓' if media.get('podcast') else '✗'}\n")
        sections.append(f"\n## Kỹ năng\n")
        for s in structured.get("skills", []):
            sections.append(f"- {s}\n")
        sections.append(f"\n---\n*Asset strength: {structured.get('asset_strength_score', 0)}/100*\n")
        return fm + "".join(sections)

    if file_key == "founder-story":
        return fm + (
            f"# Câu Chuyện Sáng Lập (Founder Story)\n\n"
            f"## Hồi 1 · Xuất phát điểm\n\n{structured.get('act_1_origin', '')}\n\n"
            f"## Hồi 2 · Khủng hoảng\n\n{structured.get('act_2_crisis', '')}\n\n"
            f"## Hồi 3 · Chuyển hoá\n\n{structured.get('act_3_transformation', '')}\n\n"
            f"## Chi tiết cụ thể\n\n"
            + "\n".join(f"- {d}" for d in structured.get("concrete_details", [])) + "\n\n"
            f"## Hook 30 giây\n\n> {structured.get('hook_30s', '')}\n\n"
            f"## Mở đầu webinar 5 phút\n\n{structured.get('opening_5m', '')}\n\n"
            f"---\n*Confidence: {structured.get('confidence_score', 0)}/100*\n"
        )

    # Fallback generic render
    return fm + f"# {file_key}\n\n```json\n{json.dumps(structured, indent=2, ensure_ascii=False)}\n```\n"
