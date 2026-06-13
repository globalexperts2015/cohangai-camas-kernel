"""L2 Customer Intelligence OS extraction."""
from __future__ import annotations

import json
import logging
import os
from typing import Any
from uuid import UUID

import anthropic

from .prompts import L2_EXTRACTION_REGISTRY


log = logging.getLogger("camas.l2_extract")
_CLIENT: anthropic.AsyncAnthropic | None = None


def _client() -> anthropic.AsyncAnthropic:
    global _CLIENT
    if _CLIENT is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        _CLIENT = anthropic.AsyncAnthropic(api_key=api_key)
    return _CLIENT


async def extract_l2_canonical(file_key: str, inputs: dict[str, Any]) -> dict[str, Any]:
    if file_key not in L2_EXTRACTION_REGISTRY:
        raise ValueError(f"Unknown L2 file_key: {file_key}")
    cfg = L2_EXTRACTION_REGISTRY[file_key]
    prompt = cfg["prompt"].format(**{
        k: json.dumps(inputs.get(k, "(không có)"), ensure_ascii=False) if isinstance(inputs.get(k), (dict, list)) else str(inputs.get(k, "(không có)"))
        for k in cfg["input_keys"]
    })

    try:
        resp = await _client().messages.create(
            model=cfg["model"], max_tokens=cfg["max_tokens"],
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIStatusError as exc:
        log.exception("L2 extraction failed %s: %s", file_key, exc)
        return {"error": "api_error", "status_code": exc.status_code, "message": str(exc)}

    raw = resp.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()
    if raw.startswith("json"):
        raw = raw[4:].strip()

    try:
        structured = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"error": "json_decode", "raw_preview": raw[:500], "json_error": str(exc)}

    structured["_meta"] = {
        "extraction_model": cfg["model"],
        "tokens_used": resp.usage.input_tokens + resp.usage.output_tokens,
    }
    return structured


def render_l2_markdown(file_key: str, structured: dict[str, Any], student_id: UUID) -> str:
    if structured.get("error"):
        return f"# {file_key}\n\n> ⚠️ Lỗi sinh nội dung: {structured.get('error')}. Liên hệ Hằng Zalo.\n"

    fm = (
        "---\n"
        f"file_key: {file_key}\n"
        f"student_id: {student_id}\n"
        "tier: B\nlock_type: strategic\nlocked: false\nai_generated: true\nversion: 1\n"
        f"extraction_model: {structured.get('_meta', {}).get('extraction_model', 'unknown')}\n"
        "---\n\n"
    )

    if file_key == "why-this-customer":
        return fm + (
            f"# Vì Sao Khách Này (Why This Customer)\n\n"
            f"## Lý do gốc\n\n{structured.get('why_this_customer', '')}\n\n"
            f"## Kết nối trải nghiệm sống\n\n{structured.get('lived_experience_link', '')}\n\n"
            f"## Bằng chứng founder có quyền phục vụ\n\n"
            + "\n".join(f"- {p}" for p in structured.get("credibility_proof", [])) + "\n\n"
            f"## Cộng hưởng cảm xúc\n\n> {structured.get('emotional_resonance', '')}\n"
        )

    if file_key == "lived-experience":
        sections = [f"# Trải Nghiệm Sống (Lived Experience)\n\n## Dòng thời gian\n"]
        for tl in structured.get("timeline", []):
            sections.append(f"- **{tl.get('year', '')}** · {tl.get('event', '')} · *bài học: {tl.get('lesson', '')}*\n")
        sections.append("\n## Nỗi đau founder đã trải qua giống khách\n")
        for p in structured.get("pain_overlap", []):
            sections.append(f"- {p}\n")
        sections.append("\n## Khoảnh khắc chuyển hoá\n")
        for t in structured.get("transformation_moments", []):
            sections.append(f"- {t}\n")
        return fm + "".join(sections)

    if file_key == "customer-empathy-map":
        return fm + (
            f"# Bản Đồ Đồng Cảm (Customer Empathy Map)\n\n"
            f"## Nghĩ & Cảm\n" + "\n".join(f"- {x}" for x in structured.get("thinks_feels", [])) + "\n\n"
            f"## Nhìn\n" + "\n".join(f"- {x}" for x in structured.get("sees", [])) + "\n\n"
            f"## Nói & Làm\n" + "\n".join(f"- {x}" for x in structured.get("says_does", [])) + "\n\n"
            f"## Nghe\n" + "\n".join(f"- {x}" for x in structured.get("hears", [])) + "\n\n"
            f"## Nỗi đau\n" + "\n".join(f"- {x}" for x in structured.get("pains", [])) + "\n\n"
            f"## Mong muốn\n" + "\n".join(f"- {x}" for x in structured.get("gains", [])) + "\n"
        )

    if file_key == "demand-evidence":
        sections = [f"# Bằng Chứng Nhu Cầu (Demand Evidence)\n\n*Đo người TÌM*\n\n"]
        sections.append("## Google Trends\n")
        for g in structured.get("google_trends", []):
            sections.append(f"- `{g.get('keyword', '')}` · {g.get('volume_estimate', '')} · {g.get('trend_12m', '')}\n")
        sections.append("\n## Câu hỏi khách thường search (AnswerThePublic)\n")
        for q in structured.get("answer_the_public_questions", []):
            sections.append(f"- {q}\n")
        sections.append("\n## YouTube Search\n")
        for y in structured.get("youtube_search_estimate", []):
            sections.append(f"- `{y.get('topic', '')}` · cạnh tranh {y.get('competition', '')}\n")
        sections.append(f"\n**Demand score:** {structured.get('demand_score', 0)}/10\n")
        return fm + "".join(sections)

    if file_key == "conversation-evidence":
        sections = [f"# Bằng Chứng Hội Thoại (Conversation Evidence)\n\n*Đo khách đang NÓI gì*\n\n"]
        sections.append("## Reddit / Facebook Groups\n")
        for r in structured.get("reddit_threads", []):
            sections.append(f"- r/{r.get('subreddit', '?')} · {r.get('common_pain', '')}\n")
        sections.append("\n## Patterns bình luận TikTok\n")
        for p in structured.get("tiktok_comments_patterns", []):
            sections.append(f"- {p}\n")
        sections.append("\n## Pattern đánh giá Amazon\n")
        for a in structured.get("amazon_reviews_patterns", []):
            sections.append(f"- {a}\n")
        sections.append("\n## Pattern phản đối thường gặp\n")
        for o in structured.get("objection_patterns", []):
            sections.append(f"- {o}\n")
        sections.append("\n## Dấu hiệu WTP\n")
        for w in structured.get("wtp_signals", []):
            sections.append(f"- {w}\n")
        return fm + "".join(sections)

    if file_key == "buying-journey":
        stages = ["unaware", "problem_aware", "solution_aware", "product_aware", "most_aware_buyer"]
        stage_labels = ["Unaware (Chưa biết)", "Problem Aware (Biết có vấn đề)",
                        "Solution Aware (Biết có giải pháp)", "Product Aware (Biết sản phẩm)",
                        "Most Aware / Buyer (Sẵn sàng mua)"]
        sections = [f"# Hành Trình Mua (Buying Journey)\n\n*Schwartz 5-stage awareness*\n\n"]
        for key, label in zip(stages, stage_labels):
            s = structured.get(key, {})
            sections.append(f"## {label}\n\n")
            sections.append(f"- **Mô tả:** {s.get('description', '')}\n")
            sections.append(f"- **Loại content:** {s.get('content_type', '')}\n")
            sections.append(f"- **Kênh:** {s.get('channel', '')}\n")
            sections.append(f"- **Thông điệp:** {s.get('message', '')}\n")
            sections.append(f"- **Phản đối:** {s.get('objection', '')}\n")
            sections.append(f"- **CTA:** {s.get('cta', '')}\n\n")
        return fm + "".join(sections)

    if file_key == "buying-triggers":
        sections = [f"# Trigger Mua Hàng (Buying Triggers)\n\n*Life-event triggers theo thời điểm*\n\n"]
        for t in structured.get("triggers", []):
            sections.append(
                f"### {t.get('trigger', '')}\n"
                f"- Loại: {t.get('category', '')}\n"
                f"- Cảm xúc: {t.get('emotional_intensity', 0)}/10\n"
                f"- WTP spike: +{t.get('wtp_spike_pct', 0)}%\n"
                f"- Kênh: {t.get('channel', '')}\n"
                f"- Hook content: *\"{t.get('content_hook', '')}\"*\n\n"
            )
        sections.append("## Top 3 trigger mạnh nhất\n")
        for t3 in structured.get("top_3_triggers", []):
            sections.append(f"- {t3}\n")
        return fm + "".join(sections)

    return fm + f"# {file_key}\n\n```json\n{json.dumps(structured, indent=2, ensure_ascii=False)}\n```\n"
