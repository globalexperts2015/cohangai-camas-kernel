"""Output → Action Sprint 15-16 P0.5 PILOT, deploy wizard output sang artifact thật.

PILOT 1 wizard: offer_engineer → HTML landing page với CTA Zalo deeplink.

Future Sprint 15-16 expand:
- mvo_cohort → GHL workflow welcome 30 ngày
- vpc_fit_checker → customer avatar PDF export
- referral_engine → GHL affiliate program setup
- offer_engineer → Tally form integration (v2)
"""
from __future__ import annotations

import html
import logging
import uuid
from typing import Optional

log = logging.getLogger("camas.output_actions")

ZALO_PHONE_DEFAULT = "0932093593"  # Anna Zalo per outline-tong-3-buoi


def _esc(s: str) -> str:
    return html.escape(str(s or ""), quote=True)


def _list_html(items: list, css_class: str = "stack-item") -> str:
    if not items:
        return ""
    parts = []
    for item in items:
        if isinstance(item, dict):
            name = item.get("name") or item.get("title") or item.get("description", "")
            value = item.get("value") or item.get("price_vnd") or item.get("worth")
            line = f"<li class='{css_class}'>{_esc(name)}"
            if value:
                line += f" <span class='value'>({_esc(value)})</span>"
            line += "</li>"
        else:
            line = f"<li class='{css_class}'>{_esc(item)}</li>"
        parts.append(line)
    return f"<ul class='stack-list'>{''.join(parts)}</ul>"


def generate_offer_landing_html(
    offer_payload: dict,
    student_id: str,
    landing_id: str,
    zalo_phone: str = ZALO_PHONE_DEFAULT,
    zalo_keyword: Optional[str] = None,
) -> str:
    """Build HTML landing page từ offer_engineer wizard output.

    Args:
        offer_payload: full output_payload từ l2_offer_engineer_student agent
        student_id: student ID for analytics + Zalo deeplink prefill
        landing_id: unique ID cho landing URL
        zalo_phone: Anna Zalo phone CTA (default 0932093593)
        zalo_keyword: Zalo deeplink keyword (default extract từ offer name)

    Returns:
        HTML string, mobile-responsive, ready to serve.
    """
    offer_name = offer_payload.get("offer_name") or offer_payload.get("magic_name") or "Offer của bạn"
    headline = offer_payload.get("headline") or offer_payload.get("big_promise") or ""
    transformation = offer_payload.get("transformation_promise") or offer_payload.get("dream_outcome") or ""
    bonuses = offer_payload.get("bonuses") or offer_payload.get("bonus_stack") or []
    price_vnd = offer_payload.get("price_vnd") or offer_payload.get("price") or ""
    anchor_value = offer_payload.get("anchor_value_vnd") or offer_payload.get("total_value") or ""
    guarantee = offer_payload.get("guarantee") or ""
    scarcity = offer_payload.get("scarcity") or ""
    why_now = offer_payload.get("why_now") or offer_payload.get("urgency_reason") or ""

    if not zalo_keyword:
        zalo_keyword = (offer_name.split()[0] if offer_name else "OFFER").upper().replace("ĐĂNG", "DK")[:12]

    zalo_msg = f"{zalo_keyword} {student_id}"
    zalo_deeplink = f"https://zalo.me/{zalo_phone}?msg={_esc(zalo_msg)}"

    bonuses_html = _list_html(bonuses, "bonus-item")
    price_block = ""
    if price_vnd:
        price_block = f"<div class='price'>{_esc(price_vnd)} VND</div>"
        if anchor_value:
            price_block = f"<div class='anchor'>Giá trị tổng: <s>{_esc(anchor_value)} VND</s></div>" + price_block

    scarcity_block = f"<div class='scarcity'>⏰ {_esc(scarcity)}</div>" if scarcity else ""
    why_now_block = f"<p class='why-now'>{_esc(why_now)}</p>" if why_now else ""
    guarantee_block = f"<div class='guarantee'>🛡️ {_esc(guarantee)}</div>" if guarantee else ""
    transformation_block = f"<p class='transformation'>{_esc(transformation)}</p>" if transformation else ""

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(offer_name)}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.6;color:#222;background:#fafafa;padding:0}}
.container{{max-width:680px;margin:0 auto;padding:24px 20px;background:white}}
.headline{{font-size:32px;font-weight:700;line-height:1.2;margin-bottom:16px;color:#0a0a0a}}
.transformation{{font-size:18px;color:#444;margin-bottom:24px}}
.section{{margin:32px 0}}
.section h2{{font-size:22px;margin-bottom:12px;color:#0a0a0a;border-left:4px solid #0066ff;padding-left:12px}}
.stack-list{{list-style:none;padding:0}}
.stack-list li{{padding:12px 0;border-bottom:1px solid #eee;display:flex;align-items:center}}
.stack-list li::before{{content:"✓";color:#0066ff;font-weight:bold;margin-right:12px;font-size:20px}}
.value{{color:#0066ff;font-weight:600;margin-left:auto}}
.price{{font-size:48px;font-weight:700;color:#e63946;text-align:center;margin:16px 0}}
.anchor{{text-align:center;color:#999;font-size:18px;margin-bottom:8px}}
.scarcity{{background:#fff3cd;color:#856404;padding:14px;border-radius:8px;text-align:center;font-weight:600;margin:20px 0}}
.guarantee{{background:#d4edda;color:#155724;padding:14px;border-radius:8px;text-align:center;font-weight:600;margin:20px 0}}
.why-now{{background:#f0f8ff;padding:16px;border-radius:8px;margin:20px 0;font-size:16px}}
.cta-btn{{display:block;width:100%;background:#0066ff;color:white;font-size:20px;font-weight:600;padding:18px;border-radius:12px;text-align:center;text-decoration:none;margin:24px 0;transition:background 0.2s}}
.cta-btn:hover{{background:#0052cc}}
.footer{{text-align:center;color:#999;font-size:13px;padding:20px 0;margin-top:40px;border-top:1px solid #eee}}
.badge{{display:inline-block;background:#0066ff;color:white;font-size:12px;padding:4px 10px;border-radius:12px;margin-bottom:16px;font-weight:600}}
@media(max-width:600px){{.headline{{font-size:24px}}.price{{font-size:36px}}}}
</style>
</head>
<body>
<div class="container">
  <div class="badge">⚡ Generated by AI from your founder vision</div>
  <h1 class="headline">{_esc(offer_name)}</h1>
  {transformation_block}

  {f'<div class="section"><p style="font-size:18px">{_esc(headline)}</p></div>' if headline else ''}

  <div class="section">
    <h2>Bạn sẽ nhận được</h2>
    {bonuses_html if bonuses_html else '<p style="color:#999">Stack chi tiết đang được generate...</p>'}
  </div>

  {f'<div class="section"><h2>Vì sao cần đăng ký ngay</h2>{why_now_block}</div>' if why_now_block else ''}

  <div class="section">
    {price_block}
    {scarcity_block}
    {guarantee_block}
  </div>

  <a class="cta-btn" href="{zalo_deeplink}" target="_blank">
    📱 Đăng ký ngay qua Zalo
  </a>
  <p style="text-align:center;color:#666;font-size:14px">Cú pháp: <strong>{_esc(zalo_msg)}</strong></p>

  <div class="footer">
    Generated by Cohangai AI Wizard · Landing ID: {_esc(landing_id)}<br>
    <span style="font-size:11px">Đây là draft do AI build từ vision của bạn. Vui lòng review trước khi share public.</span>
  </div>
</div>
</body>
</html>"""


def generate_landing_id(student_id: str, wizard_name: str) -> str:
    """Generate unique landing_id from student + wizard + uuid hash."""
    suffix = uuid.uuid4().hex[:8]
    student_short = (student_id or "anon")[:16].replace("-", "")
    return f"lp-{student_short}-{wizard_name[:6]}-{suffix}"


# === Sprint 15-16 Tech Stack Generators ===

def generate_email_sequence_html(
    mvo_payload: dict,
    student_id: str,
    landing_id: str,
) -> str:
    """Build 5-email sequence template from mvo_cohort wizard output.

    Emails: Welcome, Abandon Cart, Post-purchase, Cross-sell, Win-back.
    Ready paste vào Brevo/Mailchimp/GHL workflow.
    """
    offer_name = (
        mvo_payload.get("offer_name")
        or mvo_payload.get("cohort_name")
        or mvo_payload.get("product_name")
        or "Khoá của bạn"
    )
    transformation = (
        mvo_payload.get("transformation_promise")
        or mvo_payload.get("dream_outcome")
        or "kết quả bạn mong đợi"
    )
    bonuses = mvo_payload.get("bonuses") or mvo_payload.get("bonus_stack") or []
    price_vnd = mvo_payload.get("price_vnd") or mvo_payload.get("price") or "[giá khoá]"

    emails = [
        {
            "key": "welcome",
            "label": "Email 1 · Chào mừng (gửi ngay sau đăng ký)",
            "subject": f"Chào mừng bạn vào {_esc(offer_name)} ✨",
            "body": f"""Chào {{{{first_name}}}},

Cảm ơn bạn đã tin và đồng hành cùng tôi…

Bạn vừa bước vào hành trình {_esc(offer_name)}, nơi bạn sẽ {_esc(transformation)}.

3 việc bạn nên làm ngay hôm nay:
1. Vào link khoá học (gửi riêng email kế tiếp)
2. Tham gia group hỗ trợ (link bên trong)
3. Đặt lịch 1 buổi học đầu trong 3 ngày tới

Hành trình đẹp nhất là khi mình đi cùng nhau.

Hằng""",
        },
        {
            "key": "abandon",
            "label": "Email 2 · Nhắc giỏ hàng bỏ quên (gửi 4h sau add to cart không thanh toán)",
            "subject": f"Bạn còn 1 bước nữa thôi với {_esc(offer_name)}",
            "body": f"""Chào {{{{first_name}}}},

Hằng thấy bạn ghé trang {_esc(offer_name)} nhưng chưa hoàn thành đăng ký.

Có gì khiến bạn còn lăn tăn không?
- Lo về thời gian học? → Khoá quay sẵn, học tốc độ của bạn
- Lo về kết quả? → Có cam kết hoàn 100% trong 14 ngày
- Lo về giá? → Bạn có thể trả 2 lần

Bạn click lại link đăng ký dưới đây nhé:
[LINK_DANG_KY]

Có gì cần hỏi, inbox Zalo Hằng nha.

Hằng""",
        },
        {
            "key": "post_purchase",
            "label": "Email 3 · Sau khi mua (gửi 1h sau thanh toán thành công)",
            "subject": f"Đã nhận tiền của bạn rồi… bây giờ mở khoá nhé",
            "body": f"""Chào {{{{first_name}}}},

Cảm ơn bạn đã đầu tư vào chính mình hôm nay.

Hằng đã mở khoá {_esc(offer_name)} cho bạn:
🔗 Link truy cập: [LINK_KHOA_HOC]
🔑 Mật khẩu: gửi trong email kế tiếp

Bonus đi kèm:
{_format_bonus_list(bonuses)}

3 buổi đầu là nền tảng, đừng bỏ. Hành trình {_esc(transformation)} bắt đầu từ đây.

Hẹn gặp bạn trong khoá.

Hằng""",
        },
        {
            "key": "cross_sell",
            "label": "Email 4 · Bán thêm (gửi 14 ngày sau khi hoàn thành module đầu)",
            "subject": f"Bạn đã đi được 1/3 chặng… còn 2/3 phía trước",
            "body": f"""Chào {{{{first_name}}}},

Hằng vừa xem progress của bạn, bạn đã hoàn thành module đầu của {_esc(offer_name)}.

Tự hào về bạn…

Nếu bạn muốn đi xa hơn, sẵn sàng cho tier tiếp theo, Hằng có chương trình kế tiếp dành riêng cho alumni:
- Mentoring 1-on-1 mỗi tháng
- Workshop nội bộ chỉ alumni
- Access database case study

Giá đặc biệt cho alumni: [GIA_ALUMNI]

Inbox Hằng nếu bạn cảm thấy sẵn sàng.

Hằng""",
        },
        {
            "key": "win_back",
            "label": "Email 5 · Kéo lại khách rời (gửi 30 ngày sau không hoạt động)",
            "subject": f"Hằng có 1 câu hỏi cho bạn…",
            "body": f"""Chào {{{{first_name}}}},

Hằng để ý bạn đã không vào lại {_esc(offer_name)} 30 ngày rồi.

Hằng không gửi để bán thêm. Hằng gửi để hỏi thật lòng:

Có gì khiến bạn chững lại không?
- Quá bận với việc khác?
- Khoá chưa phù hợp?
- Bạn cần thêm hỗ trợ?

Trả lời email này 1 dòng thôi cũng được. Hằng đọc hết.

Nếu bạn muốn thử lại với 1 buổi 1-on-1 free (15 phút), Hằng dành cho bạn.

Vẫn ở đây nếu bạn cần.

Hằng""",
        },
    ]

    emails_html = "".join(
        f"""
        <article class="email-card" id="email-{e['key']}">
          <h2>{_esc(e['label'])}</h2>
          <div class="email-meta">
            <span class="meta-label">Tiêu đề:</span>
            <code class="email-subject">{_esc(e['subject'])}</code>
            <button class="copy-btn" data-target="subj-{e['key']}">📋 Copy tiêu đề</button>
            <input type="hidden" id="subj-{e['key']}" value="{_esc(e['subject'])}">
          </div>
          <div class="email-body-wrap">
            <span class="meta-label">Nội dung:</span>
            <button class="copy-btn copy-body" data-target="body-{e['key']}">📋 Copy nội dung</button>
            <pre id="body-{e['key']}">{_esc(e['body'])}</pre>
          </div>
        </article>"""
        for e in emails
    )

    return _wrap_artifact_page(
        title=f"5 Chuỗi Email cho {offer_name}",
        intro="Template ready paste vào Brevo/GHL/Mailchimp. Customize {{first_name}} + link với CRM của bạn. KHÔNG copy-paste cứng, sửa giọng cho phù hợp khách hàng bạn.",
        landing_id=landing_id,
        content=f"""
        <div class="emails-grid">{emails_html}</div>

        <script>
        document.querySelectorAll('.copy-btn').forEach(btn => {{
          btn.addEventListener('click', async () => {{
            const target = document.getElementById(btn.dataset.target);
            const text = target.tagName === 'INPUT' ? target.value : target.textContent;
            await navigator.clipboard.writeText(text);
            const orig = btn.textContent;
            btn.textContent = '✅ Đã copy';
            setTimeout(() => {{ btn.textContent = orig; }}, 2000);
          }});
        }});
        </script>
        """,
        extra_css="""
        .emails-grid { display: flex; flex-direction: column; gap: 24px; }
        .email-card { background: white; border: 1px solid #e8eaed; border-radius: 14px; padding: 20px; }
        .email-card h2 { font-size: 16px; color: #c1121f; margin-bottom: 14px; }
        .email-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
        .meta-label { font-size: 12px; color: #666; font-weight: 600; }
        .email-subject { background: #fff5f5; padding: 6px 12px; border-radius: 8px; font-size: 14px; flex: 1; min-width: 200px; }
        .copy-btn { background: linear-gradient(135deg, #c1121f, #6a040f); color: white; border: none; padding: 6px 12px; border-radius: 8px; cursor: pointer; font-size: 12px; font-weight: 600; }
        .copy-btn:hover { background: linear-gradient(135deg, #e63946, #c1121f); }
        .email-body-wrap { background: #f9fafb; border-radius: 10px; padding: 14px; position: relative; }
        .email-body-wrap .copy-body { position: absolute; top: 10px; right: 10px; }
        pre { white-space: pre-wrap; font-family: -apple-system, BlinkMacSystemFont, sans-serif; line-height: 1.6; color: #333; font-size: 14px; margin-top: 24px; }
        """,
    )


def generate_payment_landing_html(
    mvo_payload: dict,
    student_id: str,
    landing_id: str,
) -> str:
    """Build payment checkout landing với Sepay-pattern QR + bank info form.

    Student customize bank info + QR sau khi clone.
    """
    offer_name = (
        mvo_payload.get("offer_name")
        or mvo_payload.get("cohort_name")
        or mvo_payload.get("product_name")
        or "Khoá của bạn"
    )
    price_vnd = mvo_payload.get("price_vnd") or mvo_payload.get("price") or "1,990,000"

    content = f"""
    <div class="checkout-card">
      <h2>{_esc(offer_name)}</h2>
      <p class="price-line">Số tiền cần chuyển: <strong>{_esc(price_vnd)} VND</strong></p>

      <div class="payment-section">
        <h3>💳 Cách 1: Quét QR (khuyến nghị)</h3>
        <div class="qr-placeholder">
          [QR Code đây - student gen qua Sepay/MoMo/Vietcombank QR + paste vào]
        </div>
        <p class="hint">Mở app ngân hàng, quét QR, số tiền tự nhập.</p>
      </div>

      <div class="payment-section">
        <h3>🏦 Cách 2: Chuyển khoản thủ công</h3>
        <div class="bank-info">
          <div class="bank-row"><span class="bank-label">Ngân hàng:</span> <code>[Tên ngân hàng]</code></div>
          <div class="bank-row"><span class="bank-label">Chủ tài khoản:</span> <code>[TÊN ĐẦY ĐỦ]</code></div>
          <div class="bank-row"><span class="bank-label">Số tài khoản:</span> <code>[Số TK]</code></div>
          <div class="bank-row"><span class="bank-label">Nội dung CK:</span> <code class="highlight">{_esc(offer_name).upper()[:20].replace(' ', '-')} {{phone}}</code></div>
        </div>
        <p class="hint">Nội dung chuyển khoản phải có số điện thoại bạn dùng đăng ký để hệ thống tự nhận diện.</p>
      </div>

      <div class="payment-section">
        <h3>📱 Cách 3: Liên hệ trực tiếp</h3>
        <a class="zalo-btn" href="https://zalo.me/[YOUR_PHONE]?text={_esc(offer_name).replace(' ', '+')}">Inbox Zalo để được hướng dẫn</a>
      </div>

      <div class="confirmation-section">
        <h3>✅ Sau khi chuyển khoản</h3>
        <ol>
          <li>Chụp màn hình giao dịch thành công</li>
          <li>Gửi qua Zalo SDT [YOUR_PHONE]</li>
          <li>Trong 30 phút, hệ thống auto mở khoá truy cập</li>
          <li>Email xác nhận + link khoá sẽ gửi vào hộp thư</li>
        </ol>
      </div>
    </div>

    <div class="customize-notice">
      <h4>⚠️ Hướng dẫn customize</h4>
      <p>Template này có placeholder [bracket]. Bạn cần thay:</p>
      <ul>
        <li><code>[Tên ngân hàng]</code>, <code>[TÊN ĐẦY ĐỦ]</code>, <code>[Số TK]</code> — info bank thực của bạn</li>
        <li><code>[YOUR_PHONE]</code> — số Zalo nhận thông báo</li>
        <li>QR Code — generate trên app ngân hàng (VCB/MB/TCB...) hoặc Sepay merchant</li>
        <li>Webhook auto-confirm: cần backend riêng (Sepay API hoặc Webhook merchant). Tạm thời confirm thủ công.</li>
      </ul>
    </div>
    """

    return _wrap_artifact_page(
        title=f"Trang thanh toán {offer_name}",
        intro="Template trang checkout cho khoá học của bạn. Customize bank info + QR code. Backend webhook auto-confirm là phần Sprint sau, hiện tại confirm thủ công qua Zalo screenshot.",
        landing_id=landing_id,
        content=content,
        extra_css="""
        .checkout-card { background: white; border-radius: 16px; padding: 28px; box-shadow: 0 4px 16px rgba(0,0,0,0.06); }
        .checkout-card h2 { font-size: 24px; color: #2d0008; margin-bottom: 8px; }
        .price-line { font-size: 18px; color: #5a6273; margin-bottom: 24px; }
        .price-line strong { color: #c1121f; font-size: 24px; }
        .payment-section { margin-bottom: 24px; padding: 16px; background: #fafbfd; border-radius: 12px; }
        .payment-section h3 { font-size: 16px; color: #2d0008; margin-bottom: 12px; }
        .qr-placeholder { background: #fff; border: 2px dashed #c8cdd6; border-radius: 12px; padding: 60px 20px; text-align: center; color: #999; font-style: italic; }
        .bank-info { background: white; border-radius: 10px; padding: 14px; }
        .bank-row { display: flex; gap: 8px; padding: 6px 0; align-items: center; }
        .bank-label { font-weight: 600; color: #666; min-width: 130px; }
        code { background: #fff5f5; padding: 4px 10px; border-radius: 6px; font-family: monospace; }
        .highlight { background: #fee; color: #c1121f; font-weight: 600; }
        .hint { font-size: 13px; color: #666; margin-top: 8px; font-style: italic; }
        .zalo-btn { display: inline-block; background: linear-gradient(135deg, #c1121f, #6a040f); color: white; padding: 12px 24px; border-radius: 10px; text-decoration: none; font-weight: 600; }
        .confirmation-section ol { margin-left: 20px; line-height: 2; }
        .customize-notice { margin-top: 24px; padding: 20px; background: #fff3cd; border-left: 4px solid #ffc107; border-radius: 8px; }
        .customize-notice h4 { color: #856404; margin-bottom: 10px; }
        .customize-notice ul { margin-left: 20px; line-height: 1.8; color: #6c5400; }
        """,
    )


def generate_crm_workflow_doc(
    referral_payload: dict,
    student_id: str,
    landing_id: str,
) -> str:
    """Build CRM customer care workflow spec (JSON + Markdown doc).

    Importable structure cho student adapt to GHL/ActiveCampaign/etc.
    """
    program_name = (
        referral_payload.get("program_name")
        or referral_payload.get("referral_name")
        or "Hệ thống chăm sóc khách"
    )

    workflows = [
        {"name": "Welcome Flow", "trigger": "Tag added: customer", "delay": "Ngay", "actions": ["Send Email Welcome", "Tag: onboarding-started", "Wait 24h", "Send SMS/Zalo: Nhắc check email"]},
        {"name": "Onboarding Day 3-7", "trigger": "Tag: onboarding-started + 3 days passed", "delay": "Day 3", "actions": ["Send Email: Module 1 reminder", "If opened → tag: engaged-day3", "If not opened → re-send day 5", "Day 7: check progress → branch"]},
        {"name": "Cart Abandon", "trigger": "Add to cart + no checkout 4h", "delay": "4h", "actions": ["Send Email reminder", "Wait 24h", "Send 10% discount voucher (only once per customer)", "Wait 48h", "Final reminder + close cart message"]},
        {"name": "Post-Purchase Nurture", "trigger": "Payment confirmed", "delay": "1h", "actions": ["Send receipt + access link", "Tag: customer-active", "Add to alumni group", "Wait 14 days", "Request testimonial via email", "Wait 30 days", "Cross-sell next tier"]},
        {"name": "Refund Handler", "trigger": "Refund request submitted", "delay": "Ngay", "actions": ["Notify Hằng Telegram", "Send acknowledgement email", "Schedule 1-on-1 call within 48h", "If refund approved → process + tag: refunded", "Survey: why refund?"]},
        {"name": "Win-back Inactive", "trigger": "No activity 30 days", "delay": "30d", "actions": ["Send personalized email from Hằng", "Offer free 1-on-1 audit 15 phút", "If respond → schedule call", "If no respond after 60 days → archive contact"]},
    ]

    workflows_html = "".join(
        f"""
        <article class="workflow-card">
          <h3>{_esc(w['name'])}</h3>
          <div class="workflow-row"><span class="w-label">Trigger:</span> <code>{_esc(w['trigger'])}</code></div>
          <div class="workflow-row"><span class="w-label">Delay:</span> <code>{_esc(w['delay'])}</code></div>
          <div class="workflow-actions">
            <span class="w-label">Actions:</span>
            <ol>
              {"".join(f'<li>{_esc(a)}</li>' for a in w['actions'])}
            </ol>
          </div>
        </article>"""
        for w in workflows
    )

    import json as _json
    workflows_json = _json.dumps(workflows, ensure_ascii=False, indent=2)

    return _wrap_artifact_page(
        title=f"Hệ thống chăm sóc khách hàng",
        intro="6 workflow tự động cho lifecycle khách (Welcome → Cart Abandon → Post-purchase → Win-back → Refund). Adapt sang CRM của bạn (GHL/ActiveCampaign/Mailchimp tự lo phần trigger config).",
        landing_id=landing_id,
        content=f"""
        <div class="workflows-grid">{workflows_html}</div>

        <div class="json-export">
          <h3>📦 JSON Export (cho dev/integrator)</h3>
          <p>Copy JSON dưới để import vào CRM hỗ trợ schema chuẩn:</p>
          <button class="copy-btn" id="copy-json">📋 Copy JSON</button>
          <pre id="json-payload">{_esc(workflows_json)}</pre>
        </div>

        <script>
        document.getElementById('copy-json').addEventListener('click', async () => {{
          await navigator.clipboard.writeText(document.getElementById('json-payload').textContent);
          const btn = document.getElementById('copy-json');
          const orig = btn.textContent;
          btn.textContent = '✅ Đã copy JSON';
          setTimeout(() => {{ btn.textContent = orig; }}, 2000);
        }});
        </script>
        """,
        extra_css="""
        .workflows-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin-bottom: 32px; }
        .workflow-card { background: white; border-radius: 12px; padding: 18px; border-left: 4px solid #c1121f; box-shadow: 0 2px 8px rgba(0,0,0,0.04); }
        .workflow-card h3 { font-size: 16px; color: #2d0008; margin-bottom: 12px; }
        .workflow-row { padding: 4px 0; font-size: 13px; }
        .w-label { font-weight: 600; color: #666; }
        code { background: #fff5f5; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
        .workflow-actions ol { margin-left: 20px; font-size: 13px; line-height: 1.7; }
        .json-export { background: #2d0008; color: white; border-radius: 12px; padding: 20px; }
        .json-export h3 { color: white; margin-bottom: 10px; }
        .json-export p { color: rgba(255,255,255,0.8); font-size: 14px; }
        .copy-btn { background: white; color: #2d0008; border: none; padding: 8px 14px; border-radius: 8px; cursor: pointer; font-weight: 600; margin: 12px 0; }
        #json-payload { background: rgba(0,0,0,0.3); padding: 14px; border-radius: 8px; font-size: 11px; max-height: 400px; overflow: auto; color: #ffc8cc; white-space: pre-wrap; word-break: break-all; }
        """,
    )


def generate_lead_scoring_doc(
    referral_payload: dict,
    student_id: str,
    landing_id: str,
) -> str:
    """Build lead scoring framework document.

    Markdown-style doc với scoring formula + tier thresholds + implementation per CRM.
    """
    content = """
    <div class="scoring-section">
      <h2>📊 Công thức chấm điểm</h2>
      <p>Mỗi khách hàng tiềm năng có 1 điểm số. Điểm cao = hot lead = ưu tiên follow-up.</p>

      <table class="scoring-table">
        <thead><tr><th>Hành động khách</th><th>Điểm</th></tr></thead>
        <tbody>
          <tr><td>Đăng ký webinar miễn phí</td><td>+10</td></tr>
          <tr><td>Tham gia webinar đến cuối</td><td>+20</td></tr>
          <tr><td>Mở email (mỗi lần)</td><td>+1</td></tr>
          <tr><td>Click link trong email</td><td>+3</td></tr>
          <tr><td>Xem trang bán hàng &gt;30s</td><td>+5</td></tr>
          <tr><td>Add to cart không thanh toán</td><td>+15</td></tr>
          <tr><td>Inbox hỏi qua Zalo/FB</td><td>+25</td></tr>
          <tr><td>Mua khoá đầu (Foundation)</td><td>+50</td></tr>
          <tr><td>Mua khoá tier cao (Customer/Growth)</td><td>+100</td></tr>
          <tr><td>Hoàn thành module trong khoá</td><td>+10/module</td></tr>
          <tr><td>Giới thiệu bạn thành công</td><td>+30/referral</td></tr>
          <tr><td>Viết testimonial</td><td>+20</td></tr>
          <tr><td>Không hoạt động 14 ngày</td><td>-5</td></tr>
          <tr><td>Không hoạt động 30 ngày</td><td>-15</td></tr>
        </tbody>
      </table>
    </div>

    <div class="scoring-section">
      <h2>🏷️ Tier phân loại</h2>
      <div class="tier-grid">
        <div class="tier-card tier-hot">
          <div class="tier-emoji">🔥</div>
          <h3>HOT</h3>
          <div class="tier-range">≥ 50 điểm</div>
          <p>Khách sẵn sàng mua. Follow-up trong 24h. Anna gọi voice cá nhân.</p>
        </div>
        <div class="tier-card tier-warm">
          <div class="tier-emoji">☕</div>
          <h3>WARM</h3>
          <div class="tier-range">30 - 49 điểm</div>
          <p>Khách quan tâm, chưa quyết định. Nurture sequence + invite event riêng.</p>
        </div>
        <div class="tier-card tier-cold">
          <div class="tier-emoji">❄️</div>
          <h3>COLD</h3>
          <div class="tier-range">&lt; 30 điểm</div>
          <p>Khách mới biết, đang khám phá. Email education + content value tuần.</p>
        </div>
      </div>
    </div>

    <div class="scoring-section">
      <h2>⚙️ Cách triển khai theo CRM</h2>

      <h3>Nếu dùng GHL (HighLevel)</h3>
      <ul>
        <li>Tạo custom field <code>lead_score</code> (Number type)</li>
        <li>Mỗi workflow trigger, dùng action "Update Custom Field" cộng điểm</li>
        <li>Tạo smart list filter theo tier: Hot ≥50, Warm 30-49, Cold &lt;30</li>
        <li>Cron daily: notify hot leads qua Telegram/Slack</li>
      </ul>

      <h3>Nếu dùng ActiveCampaign / Mailchimp</h3>
      <ul>
        <li>Native lead scoring có sẵn → bật + import bảng điểm trên</li>
        <li>Automation rules: tag Hot/Warm/Cold theo threshold</li>
        <li>Webhook khi tier change → notify sales team</li>
      </ul>

      <h3>Nếu DIY (Google Sheets + Zapier)</h3>
      <ul>
        <li>Sheet với cột: email + score + tier + last_action_at</li>
        <li>Zapier trigger: mỗi action → +điểm vào sheet</li>
        <li>Apps Script chạy daily: re-compute tier + send Telegram alert</li>
      </ul>
    </div>

    <div class="scoring-section">
      <h2>📈 Best practices</h2>
      <ul>
        <li><strong>Reset score</strong> mỗi 90 ngày để tránh "ngủ đông" lead inflate điểm cũ.</li>
        <li><strong>Decay rate</strong>: trừ điểm theo thời gian không hoạt động (per bảng trên).</li>
        <li><strong>Behavioral &gt; Demographic</strong>: chấm theo hành động thực, không theo profile tuổi/giới tính.</li>
        <li><strong>Override manual</strong>: cho phép Anna boost điểm bằng tay khi gặp khách qua event/networking.</li>
        <li><strong>Audit weekly</strong>: review top 10 hot leads xem có thật sự hot không, tune công thức nếu false positive nhiều.</li>
      </ul>
    </div>
    """

    return _wrap_artifact_page(
        title="Hệ thống đánh giá khách tự động",
        intro="Framework chấm điểm khách 3 tier (Hot/Warm/Cold) + implementation guidance per CRM. Customize công thức cho ngành của bạn.",
        landing_id=landing_id,
        content=content,
        extra_css="""
        .scoring-section { margin-bottom: 32px; background: white; padding: 24px; border-radius: 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
        .scoring-section h2 { font-size: 20px; color: #2d0008; margin-bottom: 16px; border-bottom: 2px solid #c1121f; padding-bottom: 8px; }
        .scoring-section h3 { font-size: 15px; color: #c1121f; margin: 16px 0 8px; }
        .scoring-table { width: 100%; border-collapse: collapse; font-size: 14px; }
        .scoring-table th, .scoring-table td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #eee; }
        .scoring-table th { background: linear-gradient(135deg, #c1121f, #6a040f); color: white; }
        .scoring-table td:last-child { font-weight: 700; color: #c1121f; text-align: right; }
        .tier-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
        .tier-card { padding: 20px; border-radius: 14px; text-align: center; }
        .tier-hot { background: linear-gradient(135deg, #ffe5e7, #ffccd0); border: 2px solid #c1121f; }
        .tier-warm { background: linear-gradient(135deg, #fff3cd, #ffe69a); border: 2px solid #d9a916; }
        .tier-cold { background: linear-gradient(135deg, #cfe2ff, #9ec5fe); border: 2px solid #0a58ca; }
        .tier-emoji { font-size: 36px; margin-bottom: 8px; }
        .tier-card h3 { font-size: 18px; margin-bottom: 4px; }
        .tier-range { font-size: 14px; font-weight: 700; margin-bottom: 8px; }
        .tier-card p { font-size: 12px; line-height: 1.5; }
        code { background: #fff5f5; padding: 2px 8px; border-radius: 4px; font-size: 13px; }
        ul, ol { margin-left: 20px; line-height: 1.8; }
        """,
    )


# ===== Helpers =====

def _format_bonus_list(bonuses) -> str:
    """Format bonuses list (text style for email body)."""
    if not bonuses:
        return "- (bonus stack)"
    lines = []
    for b in bonuses[:8]:
        if isinstance(b, dict):
            name = b.get("name") or b.get("title") or "Bonus"
            value = b.get("value") or b.get("price_vnd")
            lines.append(f"✓ {name}" + (f" ({value})" if value else ""))
        else:
            lines.append(f"✓ {b}")
    return "\n".join(lines)


def _wrap_artifact_page(title: str, intro: str, landing_id: str, content: str, extra_css: str = "") -> str:
    """Common wrapper cho all artifact pages (email, payment, workflow, scoring)."""
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;line-height:1.6;color:#222;background:linear-gradient(180deg,#fafbfd,#f0f2f7);padding:0;min-height:100vh}}
.container{{max-width:900px;margin:0 auto;padding:32px 20px}}
.badge{{display:inline-block;background:linear-gradient(135deg,#c1121f,#6a040f);color:white;font-size:11px;padding:4px 12px;border-radius:12px;margin-bottom:16px;font-weight:600;letter-spacing:1px}}
.title{{font-size:30px;font-weight:800;color:#2d0008;margin-bottom:12px}}
.intro{{font-size:15px;color:#5a6273;margin-bottom:28px;line-height:1.6}}
.footer{{text-align:center;color:#999;font-size:13px;padding:20px 0;margin-top:40px;border-top:1px solid #eee}}
.footer code{{background:#fff5f5;padding:2px 8px;border-radius:4px}}
{extra_css}
@media(max-width:600px){{.title{{font-size:22px}}}}
</style>
</head>
<body>
<div class="container">
  <div class="badge">⚡ Generated by BreakoutOS Tech Stack</div>
  <h1 class="title">{_esc(title)}</h1>
  <p class="intro">{_esc(intro)}</p>

  {content}

  <div class="footer">
    Generated by Cohangai AI · Artifact ID: <code>{_esc(landing_id)}</code><br>
    <span style="font-size:11px">Template do AI build từ output wizard. Vui lòng customize trước khi sử dụng public.</span>
  </div>
</div>
</body>
</html>"""


# === Action registry: wizard_name → list of action handlers ===
# Support multi-action per wizard (Sprint 15-16 expand)

WIZARD_ACTION_HANDLERS = {
    "offer_engineer": [
        {
            "action_type": "html_landing",
            "label": "Tạo trang bán hàng từ offer này",
            "handler": generate_offer_landing_html,
        },
    ],
    "mvo_cohort": [
        {
            "action_type": "email_sequence",
            "label": "Tạo 5 chuỗi email nuôi khách",
            "handler": generate_email_sequence_html,
        },
        {
            "action_type": "payment_landing",
            "label": "Tạo trang thanh toán",
            "handler": generate_payment_landing_html,
        },
    ],
    "referral_engine": [
        {
            "action_type": "crm_workflow",
            "label": "Tạo hệ thống chăm sóc khách",
            "handler": generate_crm_workflow_doc,
        },
        {
            "action_type": "lead_scoring",
            "label": "Tạo hệ thống đánh giá khách",
            "handler": generate_lead_scoring_doc,
        },
    ],
}


def get_actions_for_wizard(wizard_name: str) -> list[dict]:
    """Return list of action configs for wizard. Empty list if not supported."""
    return WIZARD_ACTION_HANDLERS.get(wizard_name, [])


def get_action_for_wizard(wizard_name: str) -> Optional[dict]:
    """Return FIRST action config (backward compat single-action callers).

    NEW callers should use get_actions_for_wizard() to support multi-action.
    """
    actions = WIZARD_ACTION_HANDLERS.get(wizard_name, [])
    return actions[0] if actions else None


def get_action_by_type(wizard_name: str, action_type: str) -> Optional[dict]:
    """Look up specific action by type within wizard's action list."""
    for action in WIZARD_ACTION_HANDLERS.get(wizard_name, []):
        if action["action_type"] == action_type:
            return action
    return None
