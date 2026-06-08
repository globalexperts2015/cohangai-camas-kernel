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


# Action registry: wizard_name → action handler function
WIZARD_ACTION_HANDLERS = {
    "offer_engineer": {
        "action_type": "html_landing",
        "label": "Tạo trang bán hàng từ offer này",
        "handler": generate_offer_landing_html,
    },
    # Future Sprint 15-16:
    # "mvo_cohort": {"action_type": "ghl_workflow", "label": "...", "handler": ...},
    # "vpc_fit_checker": {"action_type": "pdf_export", ...},
    # "referral_engine": {"action_type": "ghl_affiliate", ...},
}


def get_action_for_wizard(wizard_name: str) -> Optional[dict]:
    """Return action config nếu wizard support deploy-action, else None."""
    return WIZARD_ACTION_HANDLERS.get(wizard_name)
