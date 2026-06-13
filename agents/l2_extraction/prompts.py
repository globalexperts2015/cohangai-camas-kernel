"""L2 Customer Intelligence OS prompts.

7 Tier B files AI generate từ 4 Tier A:
- why-this-customer        (Haiku, link L1 lived experience)
- lived-experience         (Haiku, founder timeline)
- customer-empathy-map     (Haiku, emotion + observation)
- demand-evidence          (Haiku, SEARCH side data)
- conversation-evidence    (Haiku, SAY side data)
- buying-journey           (Haiku, Schwartz 5-stage)
- buying-triggers          (Haiku, life-event triggers)
"""

WHY_THIS_CUSTOMER_PROMPT = """Bạn là chuyên gia phân tích Customer Fit.
Phân tích vì sao founder có quyền phục vụ nhóm khách hàng này dựa trên L1 + L2 input.

Tiếng Việt thuần. Không "—". Không "dạy".

INPUT:
Who I Serve (L2):
{who_i_serve}

Founder Identity (L1):
{identity}

Founder Story (L1):
{founder_story}

Founder Assets (L1):
{founder_assets}

OUTPUT JSON SCHEMA:
{{
  "why_this_customer": "1 đoạn ~80 từ, vì sao founder phục vụ nhóm này",
  "lived_experience_link": "1 đoạn, kết nối lived experience của founder với nỗi đau khách",
  "credibility_proof": [<list 3-5 bằng chứng founder có quyền phục vụ>],
  "emotional_resonance": "1 câu, cảm xúc founder với nhóm khách này",
  "confidence_score": <int 0-100>,
  "missing_fields": [<list>],
  "recommendations": [<list>]
}}

Chỉ trả JSON.
"""

LIVED_EXPERIENCE_PROMPT = """Bạn là chuyên gia phân tích trải nghiệm sống của founder.
Liệt kê 5-10 trải nghiệm cụ thể của founder mà liên quan đến customer.

Tiếng Việt thuần.

INPUT:
Founder Story (L1):
{founder_story}

Founder Assets (L1):
{founder_assets}

Who I Serve (L2):
{who_i_serve}

OUTPUT JSON SCHEMA:
{{
  "timeline": [{{"year": "<năm hoặc khoảng thời gian>", "event": "<sự kiện>", "lesson": "<bài học liên quan customer>"}}],
  "pain_overlap": [<list nỗi đau founder đã trải qua giống customer>],
  "transformation_moments": [<list 3-5 khoảnh khắc founder chuyển hoá>],
  "confidence_score": <int 0-100>,
  "missing_fields": [<list>]
}}

Chỉ trả JSON.
"""

EMPATHY_MAP_PROMPT = """Bạn là chuyên gia Customer Empathy Map (Strategyzer).
Dựng empathy map 4 quadrants + Pain + Gain cho customer.

Tiếng Việt thuần.

INPUT:
Customer Profile:
{customer_profile}

Who I Serve:
{who_i_serve}

OUTPUT JSON SCHEMA:
{{
  "thinks_feels": [<list điều khách suy nghĩ và cảm thấy>],
  "sees": [<list điều khách nhìn xung quanh>],
  "says_does": [<list điều khách nói và làm>],
  "hears": [<list điều khách nghe từ người xung quanh>],
  "pains": [<list 5 nỗi đau cụ thể>],
  "gains": [<list 5 mong muốn cụ thể>],
  "confidence_score": <int 0-100>
}}

Chỉ trả JSON.
"""

DEMAND_EVIDENCE_PROMPT = """Bạn là chuyên gia phân tích Market Demand.
Phân tích nhu cầu SEARCH (người TÌM bao nhiêu) từ Google Trends + AnswerThePublic + YouTube Search.

LƯU Ý: data thực phải pull từ API thật. Trong môi trường này, suy luận dựa trên kiến thức + customer profile + thị trường Việt Nam.

INPUT:
Customer Profile:
{customer_profile}

Who I Serve:
{who_i_serve}

OUTPUT JSON SCHEMA:
{{
  "google_trends": [{{"keyword": "...", "volume_estimate": "<thấp/trung/cao>", "trend_12m": "<tăng/ổn định/giảm>"}}],
  "answer_the_public_questions": [<list 8-12 câu hỏi khách thường search>],
  "youtube_search_estimate": [{{"topic": "...", "competition": "<thấp/trung/cao>"}}],
  "demand_score": <int 0-10>,
  "confidence_score": <int 0-100>,
  "note": "Dữ liệu suy luận, chưa verify API thật."
}}

Chỉ trả JSON.
"""

CONVERSATION_EVIDENCE_PROMPT = """Bạn là chuyên gia phân tích Customer Conversation.
Phân tích khách đang NÓI gì từ Reddit + FB Groups + TikTok Comments + Amazon Reviews.

Suy luận từ kiến thức + customer profile + thị trường Việt Nam.

INPUT:
Customer Profile:
{customer_profile}

OUTPUT JSON SCHEMA:
{{
  "reddit_threads": [{{"subreddit": "...", "common_pain": "..."}}],
  "fb_groups": [{{"group_type": "...", "active_conversations": [<topics>]}}],
  "tiktok_comments_patterns": [<list 5-8 pattern bình luận>],
  "amazon_reviews_patterns": [<list 5-8 pain trích từ review giả định>],
  "objection_patterns": [<list 5 objection thường gặp>],
  "wtp_signals": [<list 3-5 dấu hiệu khách sẵn trả tiền>],
  "confidence_score": <int 0-100>
}}

Chỉ trả JSON.
"""

BUYING_JOURNEY_PROMPT = """Bạn là chuyên gia Customer Awareness Stages (Eugene Schwartz).
Dựng buying journey 5 stage cho customer.

INPUT:
Customer Profile:
{customer_profile}

Statement Một Dòng (4 ý L2):
{statement_mot_dong}

OUTPUT JSON SCHEMA:
{{
  "unaware": {{"description": "...", "content_type": "...", "channel": "...", "message": "...", "objection": "...", "cta": "..."}},
  "problem_aware": {{...}},
  "solution_aware": {{...}},
  "product_aware": {{...}},
  "most_aware_buyer": {{...}},
  "key_transitions": [<list 3-5 cách giúp khách chuyển stage>],
  "confidence_score": <int 0-100>
}}

Mỗi stage 5 trường: description, content_type, channel, message, objection, cta. Chỉ trả JSON.
"""

BUYING_TRIGGERS_PROMPT = """Bạn là chuyên gia phân tích Buying Triggers.
Xác định 6-10 life-event triggers khách mua sản phẩm (KHÔNG phải awareness, mà là TIME-based event trigger).

INPUT:
Customer Profile:
{customer_profile}

Who I Serve:
{who_i_serve}

OUTPUT JSON SCHEMA:
{{
  "triggers": [
    {{
      "trigger": "<tên trigger>",
      "category": "life|seasonal|business|crisis",
      "emotional_intensity": <int 1-10>,
      "wtp_spike_pct": <int>,
      "channel": "<channel khách thường ở khi gặp trigger>",
      "content_hook": "<câu mở đầu content target trigger này>"
    }}
  ],
  "top_3_triggers": [<list 3 trigger mạnh nhất>],
  "confidence_score": <int 0-100>
}}

Chỉ trả JSON.
"""


L2_EXTRACTION_REGISTRY = {
    "why-this-customer": {
        "model": "claude-haiku-4-5",
        "prompt": WHY_THIS_CUSTOMER_PROMPT,
        "input_keys": ["who_i_serve", "identity", "founder_story", "founder_assets"],
        "max_tokens": 2000,
    },
    "lived-experience": {
        "model": "claude-haiku-4-5",
        "prompt": LIVED_EXPERIENCE_PROMPT,
        "input_keys": ["founder_story", "founder_assets", "who_i_serve"],
        "max_tokens": 2500,
    },
    "customer-empathy-map": {
        "model": "claude-haiku-4-5",
        "prompt": EMPATHY_MAP_PROMPT,
        "input_keys": ["customer_profile", "who_i_serve"],
        "max_tokens": 2500,
    },
    "demand-evidence": {
        "model": "claude-haiku-4-5",
        "prompt": DEMAND_EVIDENCE_PROMPT,
        "input_keys": ["customer_profile", "who_i_serve"],
        "max_tokens": 2500,
    },
    "conversation-evidence": {
        "model": "claude-haiku-4-5",
        "prompt": CONVERSATION_EVIDENCE_PROMPT,
        "input_keys": ["customer_profile"],
        "max_tokens": 2500,
    },
    "buying-journey": {
        "model": "claude-haiku-4-5",
        "prompt": BUYING_JOURNEY_PROMPT,
        "input_keys": ["customer_profile", "statement_mot_dong"],
        "max_tokens": 3500,
    },
    "buying-triggers": {
        "model": "claude-haiku-4-5",
        "prompt": BUYING_TRIGGERS_PROMPT,
        "input_keys": ["customer_profile", "who_i_serve"],
        "max_tokens": 2500,
    },
}
