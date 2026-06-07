"""Prompt builder for BC2 Voice Guardian agent.

Port nguyên xi từ standalone `cohangai/agents/voice_guardian/prompt_template.py`.
Tách prompt template ra để dễ iterate + version control.

Tham chiếu:
- knowledge_base.md (Anna voice patterns)
- style_rules.md (hard rules)
- story_pool.json (28+ Anna stories)
"""
from __future__ import annotations

import json
from pathlib import Path


VERDICT_THRESHOLDS = {
    "approve": 80,
    "flag": 60,
    # < 60 = reject
}


# Tool schema for structured output, guarantee valid JSON via Anthropic tool_use
SUBMIT_REVIEW_TOOL = {
    "name": "submit_review",
    "description": (
        "Submit voice review verdict with scores, red flags, issues, and "
        "suggested fixes. Use this tool to return your evaluation in a "
        "structured format."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "red_flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of hard-rule violations triggering auto-REJECT. "
                    "Empty if none. Examples: 'em-dash detected', 'Viet kieu "
                    "used', 'visa rate promised', 'William mentioned in "
                    "BMCorner', 'cross-promote Speakout in personal brand "
                    "Hang'."
                ),
            },
            "scores": {
                "type": "object",
                "properties": {
                    "voice_match": {"type": "integer", "minimum": 0, "maximum": 25},
                    "story_authenticity": {"type": "integer", "minimum": 0, "maximum": 25},
                    "cultural_fit": {"type": "integer", "minimum": 0, "maximum": 25},
                    "brand_consistency": {"type": "integer", "minimum": 0, "maximum": 25},
                },
                "required": [
                    "voice_match",
                    "story_authenticity",
                    "cultural_fit",
                    "brand_consistency",
                ],
            },
            "total": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": (
                    "Sum of 4 dimension scores. If red_flags non-empty, "
                    "total = 0."
                ),
            },
            "verdict": {"type": "string", "enum": ["APPROVE", "FLAG", "REJECT"]},
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "dimension": {
                            "type": "string",
                            "enum": [
                                "voice_match",
                                "story_authenticity",
                                "cultural_fit",
                                "brand_consistency",
                            ],
                        },
                        "issue": {"type": "string"},
                    },
                    "required": ["dimension", "issue"],
                },
                "description": "Specific issues per dimension. Empty if no issues.",
            },
            "fixes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "original": {"type": "string"},
                        "suggested": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["original", "suggested", "reason"],
                },
                "description": (
                    "Up to 5 concrete fixes. Each has original text, "
                    "suggested replacement, and reason."
                ),
            },
            "notes": {
                "type": "string",
                "description": "Overall summary note. Max 200 chars.",
            },
        },
        "required": [
            "red_flags",
            "scores",
            "total",
            "verdict",
            "issues",
            "fixes",
            "notes",
        ],
    },
}


def build_review_prompt(
    content: str,
    meta: dict,
    knowledge_base: str,
    style_rules: str,
    story_pool: dict,
) -> str:
    """Build prompt cho Claude review 1 piece of content.

    Args:
        content: AI-generated content to review
        meta: dict with keys channel, persona, topic, venture, language
        knowledge_base: full content of knowledge_base.md
        style_rules: full content of style_rules.md
        story_pool: parsed JSON from story_pool.json

    Returns:
        Full prompt string ready to send to Claude
    """
    story_index = _build_story_index(story_pool)
    language_hint = _resolve_language_hint(meta)

    return f"""Bạn là Brand Voice Guardian cho Đào Thị Hằng (Hằng/Anna).

NHIỆM VỤ: Review 1 piece of AI-generated content và quyết định:
- APPROVE (score >= 80): publish luôn
- FLAG (60-79): cần Anna review trước khi publish
- REJECT (< 60): không phù hợp voice Hằng, AI retry

========================================================================
VOICE HẰNG KNOWLEDGE BASE
========================================================================

{knowledge_base}

========================================================================
STYLE RULES (HARD RULES)
========================================================================

{style_rules}

========================================================================
STORY POOL INDEX (cho check Story Authenticity)
========================================================================

{story_index}

========================================================================
CONTENT CẦN REVIEW
========================================================================

Channel: {meta.get('channel', 'unspecified')}
Persona target: {meta.get('persona', 'unspecified')}
Topic: {meta.get('topic', 'unspecified')}
Venture: {meta.get('venture', 'unspecified')}
Language: {meta.get('language', 'vi')}
Language target: {language_hint}

---CONTENT START---
{content}
---CONTENT END---

========================================================================
NHIỆM VỤ
========================================================================

Step 1: CHECK RED FLAGS (auto-REJECT bat ke score):
- Em-dash "—" xuat hien
- "Viet kieu"
- Hua visa rate cu the (neu Migration)
- Cross-promote Speakout/Breakout trong personal brand Hang (PURE TRUST)
- Dung William trong BMCorner content
- Bia so lieu khong co trong vault
- Sai pronoun (Hang vs Anna theo audience)
- Mention marital status Hang
- Mention team/nhan vien

Neu co RED FLAG => verdict = "REJECT" + total = 0 + ghi ro red_flag.

Step 2: SCORE 4 DIMENSIONS (moi chieu 0-25):

A. VOICE MATCH (0-25):
- Pattern cau, rhythm, word choice match voi Anna voice samples
- Co dung tu dan da Anna (vd "mu hum", "lup dat", "ra riet")?
- Co cau truc Why truoc How?
- Co an du dan da hoac aphorism?
- Co dung "Hang/Anna/Toi" dung register?
- Tone "chi ca" am ap khong corporate?

B. STORY AUTHENTICITY (0-25):
- Co dung story THAT tu pool (check story_index)?
- Ten that, ngay that, dat that?
- Detail cu the (ten nguoi/dat/so/ngay) hay generic?
- Co bia story khong co trong pool?

C. CULTURAL FIT (0-25):
- Tieng Viet thuan khong Anglicism?
- Pronoun dung cho audience?
- Khong tu corporate?
- Phu hop venture target?

D. BRAND CONSISTENCY (0-25):
- Tuan thu style_rules?
- Align voi positioning venture?
- KHONG cross-promote sai?
- CTA dung venture?

Step 3: VERDICT:
- Total = A + B + C + D
- Verdict tu total:
  - >= 80: APPROVE
  - 60-79: FLAG
  - < 60: REJECT
- Neu co RED FLAG: verdict = REJECT bat ke total

Step 4: SUGGEST FIXES (toi da 5):
Voi moi issue, dua ra fix concrete.

========================================================================
SUBMIT KẾT QUẢ
========================================================================

GỌI tool `submit_review` với đầy đủ 7 fields (red_flags, scores, total, verdict, issues, fixes, notes). KHÔNG output text khác ngoài tool call.
"""


def _resolve_language_hint(meta: dict) -> str:
    """Determine language target based on channel + persona + venture."""
    language = meta.get("language", "vi")
    channel = (meta.get("channel") or "").lower()
    persona = (meta.get("persona") or "").lower()
    venture = (meta.get("venture") or "").lower()

    # BMCorner + Australian/local persona = English target
    if venture == "bmcorner" and (
        "australian" in persona
        or "local" in persona
        or "aussie" in persona
        or language == "en"
    ):
        return (
            "English (casual Aussie-friendly, KHÔNG penalty vì không phải tiếng Việt)"
        )

    # Default Vietnamese for VN audiences
    if language == "vi":
        return "Vietnamese (tiếng Việt thuần, từ dân dã miền Trung pattern)"

    return f"Language={language} (theo target audience của channel/persona)"


def _build_story_index(story_pool: dict) -> str:
    """Compact index of stories for prompt (avoid token bloat)."""
    lines = ["Available stories (use ID for reference):"]
    for story in story_pool.get("stories", []):
        story_id = story.get("id", "unknown")
        title = story.get("title", "")
        era = story.get("era", "")
        themes = ", ".join(story.get("themes", []))
        details = ", ".join(story.get("key_details", [])[:3])
        lines.append(
            f"- {story_id}: {title} | {era} | themes={themes} | details={details}"
        )

    lines.append("\nVerification rules:")
    rules = story_pool.get("verification_rules", {})
    for rule in rules.get("story_authenticity_check", []):
        lines.append(f"- {rule}")
    lines.append("\nStory misuse red flags:")
    for flag in rules.get("story_misuse_red_flags", []):
        lines.append(f"- {flag}")

    return "\n".join(lines)


def load_knowledge_base() -> str:
    """Load knowledge_base.md từ folder same."""
    path = Path(__file__).parent / "knowledge_base.md"
    return path.read_text(encoding="utf-8")


def load_style_rules() -> str:
    """Load style_rules.md từ folder same."""
    path = Path(__file__).parent / "style_rules.md"
    return path.read_text(encoding="utf-8")


def load_story_pool() -> dict:
    """Load story_pool.json từ folder same."""
    path = Path(__file__).parent / "story_pool.json"
    return json.loads(path.read_text(encoding="utf-8"))
