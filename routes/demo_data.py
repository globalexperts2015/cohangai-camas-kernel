"""Pre-generated demo outputs for BreakoutOS wizard live demo (K2 Buổi 3 11/06/2026).

Persona: Chị Nhiên (nhienle10@gmail.com), hot lead K2 serious 9/10.
Business: Dược mỹ phẩm Việt + website công ty, đã bán được nội địa, muốn scale quốc tế.
Pain verified từ K2 survey buổi 1 9/6:
  "Làm sao kết nối thêm nhiều khách hàng trên thế giới và tìm ra thêm
   những sản phẩm có thể bán chạy trong tương lai."

Format mirrors actual wizard agent output_payload so frontend renders identically.
"""
from __future__ import annotations

import json

PERSONA_NHIEN = {
    "name": "Chị Nhiên",
    "email": "nhienle10@gmail.com",
    "business": "Dược mỹ phẩm Việt (đã có website công ty)",
    "stage": "S3 — Có business, muốn scale quốc tế",
    "current_state": "12-18 khách B2B nội địa + 30-50tr/tháng + list size ~1000 + website công ty",
    "pain_verified_survey": (
        "Làm sao kết nối thêm nhiều khách hàng trên thế giới và tìm ra "
        "thêm những sản phẩm có thể bán chạy trong tương lai."
    ),
    "next_goal": "Launch 1 sản phẩm ở 1 market quốc tế trong 12 tháng",
}

DEMO_CONTENT_PACK = {
    "pack": {
        "_persona": PERSONA_NHIEN,
        "pillars": [
            {"name": "Founder dược mỹ phẩm Việt scale quốc tế",
             "summary": "Hành trình từ bán nội địa sang xuất khẩu, đăng ký compliance, brand cross-border."},
            {"name": "Compliance từng thị trường",
             "summary": "EU CPNP, FDA Mỹ, ASEAN registration, TGA Úc, NĂM thị trường mỗi quy trình khác nhau."},
            {"name": "Website convert khách quốc tế",
             "summary": "Trust signal cho khách quốc tế khác hoàn toàn khách VN, cấu trúc page + ngôn ngữ + payment."},
            {"name": "Product market fit cross-border",
             "summary": "Cách validate sản phẩm fit market mới TRƯỚC khi bỏ vốn 500tr cho compliance đăng ký."},
            {"name": "B2B distributor outreach",
             "summary": "Cách tìm 5-10 nhà phân phối quốc tế đầu tiên qua LinkedIn + trade show + warm intro."},
            {"name": "Story-led brand cho dược mỹ phẩm",
             "summary": "Founder story làm trust anchor khi khách quốc tế chưa biết brand Việt."},
            {"name": "AI cho quy trình export",
             "summary": "AI agent giúp soạn label compliance + dịch website + reply email partner quốc tế."},
        ],
        "reel_ideas": [
            {"hook": "Tôi đã đốt 500tr cho EU registration. Bài học đắt nhất là...", "pillar": 4, "cta": "Inbox FRAMEWORK"},
            {"hook": "Founder dược mỹ phẩm Việt: chị nghĩ Mỹ là thị trường lớn nhất? Sai rồi.", "pillar": 2, "cta": "Comment MARKET"},
            {"hook": "3 lý do website Việt KHÔNG convert được khách quốc tế", "pillar": 3, "cta": "Save bài này"},
            {"hook": "Cách tôi tìm 5 nhà phân phối ở Úc trong 90 ngày, không trade show", "pillar": 5, "cta": "Inbox PARTNER"},
            {"hook": "Đừng đăng ký FDA. Hãy đăng ký TGA trước. Đây là lý do.", "pillar": 2, "cta": "Comment TGA"},
            {"hook": "Sản phẩm bán chạy ở VN ≠ bán chạy ở Singapore. Cách test trước khi đầu tư.", "pillar": 4, "cta": "Inbox VALIDATE"},
            {"hook": "Founder story = trust signal mạnh nhất cho dược mỹ phẩm cross-border", "pillar": 6, "cta": "Inbox STORY"},
            {"hook": "AI dịch label compliance EU trong 30 phút thay vì 2 tuần thuê lawyer", "pillar": 7, "cta": "Demo AI"},
            {"hook": "Tôi chọn 1 market đầu tiên thế nào? Không phải US, không phải EU.", "pillar": 2, "cta": "Comment MARKET"},
            {"hook": "Khách Singapore search dược mỹ phẩm Việt từ khoá gì? Đây là 5 cái.", "pillar": 3, "cta": "Save bài này"},
            {"hook": "Lỗi compliance KHÔNG sửa được sau khi đã đăng ký. Check 7 điểm trước khi nộp.", "pillar": 2, "cta": "Inbox CHECKLIST"},
            {"hook": "Cách 1 founder Việt đưa kem mỹ phẩm sang Úc với budget 200 triệu", "pillar": 1, "cta": "Inbox CASE"},
        ],
        "fb_posts": [
            {
                "title": "Tôi đã đốt 500 triệu cho EU registration trước khi học bài học này",
                "body": (
                    "Năm 2024, một founder dược mỹ phẩm Việt tôi quen quyết định scale ra EU.\n\n"
                    "Cô ấy đầu tư:\n"
                    "- 500tr cho CPNP registration (Cosmetic Product Notification Portal)\n"
                    "- 200tr cho hồ sơ Responsible Person ở Pháp\n"
                    "- 6 tháng làm việc với compliance consultant\n\n"
                    "Sản phẩm đăng ký xong, push vào market.\n\n"
                    "Doanh thu tháng 1: 8 đơn.\nTháng 2: 12 đơn.\nTháng 6: dừng vì không cover được giá đăng ký.\n\n"
                    "Vấn đề KHÔNG phải EU không phù hợp.\n"
                    "Vấn đề là chưa validate sản phẩm có fit khách EU trước khi đầu tư compliance.\n\n"
                    "Khách EU mua dược mỹ phẩm theo logic khác hẳn khách Việt. Tôi đã tổng hợp 3 cách validate trong 30 ngày, chi phí dưới 30tr, trước khi đặt vé bay sang EU làm thủ tục.\n\n"
                    "Nếu bạn đang muốn đưa dược mỹ phẩm Việt ra thế giới, comment 'CHECKLIST' tôi gửi.\n\n"
                    "Đào Thị Hằng"
                ),
                "cta": "Comment CHECKLIST",
            },
            {
                "title": "Tại sao tôi nói đừng chọn Mỹ làm thị trường đầu tiên",
                "body": (
                    "Tuần trước có chị founder dược mỹ phẩm hỏi tôi:\n"
                    "'Hằng ơi, em định đăng ký FDA để bán Amazon US. Em nên làm gì trước?'\n\n"
                    "Tôi nói: 'Đừng. Tạm dừng đã.'\n\n"
                    "Lý do:\n"
                    "1. FDA registration cho cosmetic Việt = trung bình 18 tháng + 800tr-1.2 tỷ\n"
                    "2. Amazon US dược mỹ phẩm cạnh tranh GIÁ với Korea + China + Đài Loan, mỗi nước trợ giá xuất khẩu, bạn không đỡ nổi\n"
                    "3. Khách Mỹ TRUST brand Mỹ, brand Việt = unknown = phải burn ads cao gấp 3x\n\n"
                    "Tôi khuyên chị ấy làm gì?\n\n"
                    "Bắt đầu Úc (TGA registration đơn giản hơn FDA 10 lần, người Việt đông, brand Việt được trust)\n"
                    "→ Singapore (cluster ASEAN gần)\n"
                    "→ Sau 18 tháng có proof of concept mới đụng đến Mỹ.\n\n"
                    "Roadmap quốc tế của founder Việt KHÔNG phải lúc nào cũng to-bigger-first.\n\n"
                    "Đào Thị Hằng"
                ),
                "cta": "Inbox ROADMAP",
            },
        ],
        "emails": [
            {
                "subject_line": "Sai lầm 500tr tôi thấy ở founder dược mỹ phẩm Việt",
                "preview": "Trước khi bạn đăng ký EU/Mỹ, có 3 việc cần làm trong 30 ngày.",
                "body": (
                    "Chào bạn,\n\n"
                    "Tuần trước tôi gặp một founder dược mỹ phẩm Việt vừa đốt 500tr cho EU registration mà không bán được.\n\n"
                    "Vấn đề không phải EU không phù hợp.\n"
                    "Vấn đề là chưa validate product-market fit trước khi đầu tư.\n\n"
                    "3 việc tôi khuyên làm TRƯỚC khi bỏ vốn đăng ký:\n\n"
                    "1. Test landing page bằng tiếng Anh, ngân sách 5tr ads, đo conversion rate\n"
                    "2. Pre-order 50 khách quốc tế qua warm community (founder Việt overseas, expat group)\n"
                    "3. Phỏng vấn sâu 5 nhà phân phối tiềm năng về criteria họ chọn brand mới\n\n"
                    "Nếu data 3 việc này dương, mới đầu tư compliance.\n\n"
                    "Nếu bạn đang ở giai đoạn 'có sản phẩm + website nội địa, muốn scale quốc tế', tôi mở 30 phút decision call review roadmap cụ thể cho business của bạn.\n\n"
                    "Đặt tại: https://api.leadconnectorhq.com/widget/booking/qx869yEKHc3zUyAIhIcU\n\n"
                    "Đào Thị Hằng\n\n"
                    "P.S. Nếu 12 tháng tới chỉ launch được 1 sản phẩm ở 1 thị trường ngoài VN, đó là sản phẩm gì, ở đâu, vì sao? Câu trả lời này quyết định 80% roadmap."
                ),
            },
        ],
        "lead_magnets": [
            {"title": "Checklist 7 điểm trước khi đăng ký FDA/EU/TGA cho dược mỹ phẩm Việt",
             "format": "PDF 12 trang",
             "promise": "Tránh sai compliance không sửa được, save 6-12 tháng + 200-500tr chi phí lãng phí"},
            {"title": "Roadmap 12 tháng: từ bán nội địa sang launch 1 market quốc tế",
             "format": "Notion template + 5 SOP",
             "promise": "Sequence chuẩn validate-compliance-launch-scale, đã proven qua 3 brand Việt sang Úc + Singapore"},
            {"title": "Validate Product-Market Fit Cross-Border trong 30 ngày",
             "format": "Mini-course email 7 ngày",
             "promise": "3 phương pháp test product fit thị trường mới với ngân sách dưới 30tr trước khi đầu tư compliance"},
            {"title": "Free 1-1 Roadmap Review (30 phút)",
             "format": "Decision call qua Zoom",
             "promise": "Hằng review website + sản phẩm + map roadmap quốc tế 12 tháng cho business của bạn"},
        ],
        "calendar_30d_summary": (
            "Tuần 1: Launch reel pillar 4 (Product Market Fit cross-border) + 1 FB long-form '500tr EU'. "
            "Tuần 2: Lead magnet 1 (Checklist 7 điểm compliance) push qua FB community founder Việt overseas. "
            "Tuần 3: Reel pillar 2 (Compliance từng thị trường, TGA-first hypothesis) + email sequence 5 ngày từ list 1000. "
            "Tuần 4: Webinar 60 phút 'Roadmap quốc tế cho founder dược mỹ phẩm Việt', target 30 đăng ký + 5 close decision call."
        ),
    },
    "lint_passed": True,
    "lint_violations": [],
    "student_id": "nhien",
    "_demo_mode": True,
    "_demo_note": (
        "Pre-generated cho chị Nhiên K2 hot lead 9/10. Pain verified từ survey buổi 1. "
        "Real wizard chạy LIVE LLM cho mỗi student với customer profile của họ."
    ),
}

DEMO_LEAD_GEN_PLAN = {
    "_persona": PERSONA_NHIEN,
    "primary_channels": ["fb_personal", "community", "youtube"],
    "channel_rationale": (
        "FB Personal vì audience founder dược mỹ phẩm Việt active trên FB > LinkedIn. "
        "Community vì founder Việt overseas (Úc, Singapore, EU) tụ tập trong group expat + Vietnam Trade. "
        "YouTube vì search intent 'cách đăng ký FDA cho mỹ phẩm Việt' đang under-served, "
        "long-tail SEO cho khách warm tự tìm đến."
    ),
    "lead_magnets_final": [
        {"title": "Checklist 7 điểm compliance (FDA/EU/TGA) cho dược mỹ phẩm Việt",
         "channel": "fb_personal",
         "expected_optin_rate": "15-20%",
         "estimated_leads_30d": 80},
        {"title": "Roadmap 12 tháng từ nội địa → 1 market quốc tế",
         "channel": "community",
         "expected_optin_rate": "10-14% (warm community)",
         "estimated_leads_30d": 40},
        {"title": "Free 1-1 Roadmap Review 30 phút với Hằng",
         "channel": "fb_personal + community",
         "expected_optin_rate": "6-9% but hot leads",
         "estimated_leads_30d": 25},
        {"title": "Mini-course email 7 ngày: Validate Product Market Fit Cross-Border",
         "channel": "youtube long-tail SEO",
         "expected_optin_rate": "8-12%",
         "estimated_leads_30d": 30},
    ],
    "daily_plan_30d_summary": (
        "T2-T6 push: 1 reel pillar + 1 community comment 200 chữ trong 3 group founder Việt overseas. "
        "T7 push: 1 FB long-form 800-1200 chữ với 1 case study. CN nghỉ. "
        "Tuần 1-2 focus magnet 1 (Checklist), Tuần 3-4 focus magnet 3 (1-1 Decision Call) cho hot leads convert sang Coaching 6 tháng 50tr."
    ),
    "funnel_map": {
        "awareness": {"channel": "FB reel + YouTube long-tail SEO", "target_volume": 12000},
        "interest": {"channel": "Lead magnet download (4 magnets)", "target_volume": 175},
        "decision": {"channel": "Email nurture 5 ngày + retarget", "target_volume": 45},
        "action": {"channel": "Decision Call 30 phút", "target_volume": 12},
    },
    "tagging_logic": {
        "magnet_checklist_compliance": "tag: compliance-aware-cold",
        "magnet_roadmap_12month": "tag: scale-international-warm",
        "magnet_decision_call_book": "tag: hot-decision-call",
        "magnet_validate_minicourse": "tag: pmf-curious-cold",
        "email_open_3plus": "tag: highly-engaged",
        "decision_call_completed": "tag: ready-for-coaching-pitch",
    },
    "referral_strategy": (
        "Sau Decision Call, đề nghị khách giới thiệu 1 founder dược mỹ phẩm Việt khác có pain tương tự, "
        "khách giới thiệu được giảm 10% Coaching 50tr (5tr cash). Target 2-3 referral/tháng từ 12 calls/tháng."
    ),
    "_demo_mode": True,
    "_demo_note": (
        "Pre-generated cho chị Nhiên dược mỹ phẩm scale quốc tế. "
        "Real plan tailored sau khi vào Cohort 1 với data CỦA BẠN (kênh đang dùng, list hiện có, ngân sách)."
    ),
}

DEMO_SCALE_PLAN = {
    "_persona": PERSONA_NHIEN,
    "current_state": {
        "current_customers": 15,
        "revenue_vnd_30d": 45_000_000,
        "list_size": 1000,
        "nps": 8,
        "venture_focus": "Dược mỹ phẩm Việt + website công ty",
        "geographic_scope": "Nội địa VN",
    },
    "recommended_lever": "webinar",
    "rationale": (
        "Chị Nhiên ở ngưỡng 15 khách B2B + 45tr/tháng + list 1000 + website đang convert nội địa. "
        "Đòn bẩy hiệu quả nhất 90 ngày tới là WEBINAR 1-to-many để vừa educate audience về scale quốc tế "
        "(awareness pain compliance + validate trước khi đầu tư) vừa close decision call cho roadmap 12 tháng. "
        "KHÔNG nên: chạy ads scale ngay (chưa optimize landing cho khách quốc tế), "
        "KHÔNG nên: đăng ký FDA/EU vội (validate market trước, cost 500tr-1.2 tỷ nếu sai). "
        "Webinar Brunson Perfect Webinar format push 1000 list → 60 lead webinar → 12 decision call → 3-5 close Coaching."
    ),
    "plan_90_days": {
        "month_1_validate": [
            "Tuần 1: Build webinar 60 phút 'Roadmap 12 tháng từ nội địa → 1 market quốc tế'",
            "Tuần 2: Email sequence 7 ngày pre-webinar + Tally đăng ký",
            "Tuần 3: Launch webinar lần 1 đến list 1000 + 3 community founder Việt overseas",
            "Tuần 4: Decision call 12-15 lead + close 3 khách Coaching 50tr đầu (target 150tr month 1)",
        ],
        "month_2_scale_outreach": [
            "Run webinar 2 lần/tuần (T3 + T7) cho lead mới từ FB reel + YouTube",
            "Referral mechanism: khách Coaching giới thiệu founder khác → giảm 5tr Coaching round 2",
            "Bắt đầu B2B distributor outreach Úc + Singapore (LinkedIn + email warm intro)",
            "Validate 1 sản phẩm với 50 pre-order từ Úc trước khi đăng ký TGA",
        ],
        "month_3_systematize_launch": [
            "TGA registration cho sản phẩm đã validate qua 50 pre-order (cost 80-120tr, far below EU/FDA)",
            "Affiliate partnership với 2 KOL beauty Việt-Úc",
            "Membership tier ra mắt cho founder Việt scale quốc tế (low-tier $20/m, content + Q&A monthly)",
            "Target tích luỹ: 30 khách Coaching + 80tr/tháng + 1 sản phẩm live trên Amazon AU",
        ],
    },
    "templates_available": [
        "webinar_60min_roadmap_quoc_te_dmp.md",
        "email_sequence_7day_pre_webinar.md",
        "post_webinar_close_call_script_dmp.md",
        "tga_compliance_checklist_australia.md",
        "linkedin_warm_intro_distributor.md",
        "pre_order_validation_50_customers.md",
        "amazon_au_listing_starter_dmp.md",
    ],
    "anti_pattern_warnings": [
        "KHÔNG chạy FB ads scale ngay khi chưa optimize landing cho khách quốc tế (burn $1k/tuần thấy ra 0 deal)",
        "KHÔNG đăng ký FDA hoặc EU CPNP trước khi validate (cost 500tr-1.2 tỷ, 18 tháng, rủi ro product không fit)",
        "KHÔNG launch nhiều market cùng lúc (1 market đầu tiên = Úc + Singapore, build proof of concept trước)",
    ],
    "_demo_mode": True,
    "_demo_note": "Pre-generated cho chị Nhiên. Real plan dựa trên số liệu CỦA BẠN sau khi vào Cohort 1.",
}

DEMO_AI_COO_BRIEF = {
    "_persona": PERSONA_NHIEN,
    "date": "2026-06-11",
    "student_id": "nhien",
    "morning_greeting": (
        "Chào chị Nhiên. Đây là brief AI COO 6h sáng cho business dược mỹ phẩm của chị. "
        "3 việc quan trọng nhất hôm nay, 3 việc skip, recap hôm qua."
    ),
    "top_3_actions": [
        {
            "rank": 1,
            "title": "Reply email 1-1 Hằng gửi hôm qua + book Coaching Decision Call 30 phút",
            "why": (
                "Hằng đã gửi email 1-1 sáng qua review roadmap quốc tế cho chị. "
                "Hot intent. Book Call = unblock 12-tháng roadmap với hỗ trợ trực tiếp từ Hằng. "
                "Slot tuần này còn 4, ưu tiên founder đang ở giai đoạn ra quyết định lớn như chị."
            ),
            "estimated_time": "5 phút",
            "blocking_revenue_vnd": 50_000_000,
            "action_link": "https://api.leadconnectorhq.com/widget/booking/qx869yEKHc3zUyAIhIcU",
        },
        {
            "rank": 2,
            "title": "Audit website công ty với 3 tiêu chí trust signal cho khách quốc tế",
            "why": (
                "Website đang Việt-centric. Trước khi push traffic quốc tế, audit 3 điểm: "
                "(1) About page có founder story đủ depth không, "
                "(2) Có English version + ngôn ngữ trust signal quốc tế chưa, "
                "(3) Compliance badge (GMP, HACCP, ISO) có hiển thị prominent không. "
                "Audit này quyết định conversion rate khi push traffic Úc/Singapore."
            ),
            "estimated_time": "60 phút",
            "blocking_revenue_vnd": 0,
        },
        {
            "rank": 3,
            "title": "List 5 founder dược mỹ phẩm Việt đã scale ra ASEAN làm intel reference",
            "why": (
                "Trước khi launch quốc tế, biết 5 case Việt đã đi qua giúp chị shortcut 12 tháng nghiên cứu. "
                "Ai họ chọn market đầu tiên, ngân sách compliance bao nhiêu, kênh distributor nào convert nhất. "
                "Output: 1 Google Doc 1 trang với 5 case + 3 insight."
            ),
            "estimated_time": "45 phút",
            "blocking_revenue_vnd": 0,
        },
    ],
    "skip_today": [
        "Đăng ký FDA hoặc EU CPNP (chưa validate market, cost 500tr-1.2 tỷ nếu sai)",
        "Build mobile app công ty (low priority, website + Zalo đủ cho B2B Việt giai đoạn này)",
        "Hire 1 nhân viên marketing full-time (chưa cần, AI COO + content engine handle 80% volume)",
    ],
    "yesterday_recap": {
        "completed": [
            "Đọc email 1-1 Hằng review roadmap quốc tế (mở 9h sáng 10/6 — confirmed open)",
            "Hoàn thiện survey K2 buổi 2 'Customer Submission' lúc 21h45 VN",
        ],
        "incomplete": [
            "Chưa book Decision Call (action #1 hôm nay)",
            "Chưa update website English version (nằm trong action #2)",
        ],
    },
    "weekly_north_star": (
        "North Star tuần này: Book + complete Decision Call 30 phút với Hằng. "
        "Output cuộc gọi = roadmap 12 tháng cụ thể cho dược mỹ phẩm chị + quyết định Coaching 50tr/6 tháng."
    ),
    "_demo_mode": True,
    "_demo_note": (
        "Pre-generated cho chị Nhiên. Real brief AI COO 6h sáng MỖI ngày cho mỗi student "
        "Cohort 1, tailored theo state hiện tại + goal + activity hôm qua."
    ),
}

DEMO_OUTPUTS = {
    "content_engine": DEMO_CONTENT_PACK,
    "lead_gen_engine": DEMO_LEAD_GEN_PLAN,
    "scale_coach": DEMO_SCALE_PLAN,
    "ai_coo": DEMO_AI_COO_BRIEF,
}


def is_demo_token(student_id: str) -> bool:
    """Token bypass detection: student_id starts with 'demo' or 'nhien' → serve cached sample."""
    if not student_id:
        return False
    s = student_id.lower()
    return s.startswith("demo") or s.startswith("nhien")


def get_demo_output(wizard_name: str) -> dict | None:
    """Return pre-generated demo output for a wizard, or None if not available."""
    return DEMO_OUTPUTS.get(wizard_name)
