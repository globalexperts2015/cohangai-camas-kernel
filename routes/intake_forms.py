"""Student-facing HTML intake forms for L1 + L2 + L3.

Routes:
- GET /foundation/l1?student={id}    L1 intake form
- GET /foundation/l2?student={id}    L2 intake form
- GET /foundation/l3?student={id}    L3 intake form
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from routes._auth import _verify_hmac
from routes.freedom_score_routes import has_baseline
from routes.sdl_routes import check_gate_passed, get_pool, require_level_access


router = APIRouter(tags=["intake-forms"])


def _error_page(message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Đường link không hợp lệ</title><style>{_CSS}</style></head>
<body><div class="container"><div class="card">
<h1>Không thể mở trang</h1><p class="sub">{message}</p>
</div></div></body></html>"""


def _validated_student(student: str, sig: str) -> UUID | None:
    if not student or not _verify_hmac(student, sig):
        return None
    try:
        return UUID(student)
    except ValueError:
        return None


_CSS = """
:root{--red:#d63031;--red-deep:#b71c1c;--ink:#0a0a0a;--paper:#fafaf7;--line:#e5dfd0;--muted:#5a5453}
*{box-sizing:border-box;margin:0;padding:0;font-family:'Be Vietnam Pro',system-ui}
body{background:var(--paper);color:var(--ink);padding:40px 20px;font-size:17px;line-height:1.7}
.container{max-width:820px;margin:0 auto}
.tag{display:inline-block;background:rgba(214,48,49,0.12);color:var(--red);padding:8px 18px;border-radius:999px;font-size:12px;letter-spacing:1.5px;text-transform:uppercase;font-weight:800;margin-bottom:14px}
h1{font-size:34px;font-weight:800;line-height:1.25;margin-bottom:12px}
.sub{font-size:18px;color:var(--muted);margin-bottom:30px}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:24px 26px;margin-bottom:18px}
.card h3{font-size:19px;margin-bottom:6px;color:var(--ink)}
.card .hint{font-size:14px;color:var(--muted);margin-bottom:14px}
label{display:block;font-weight:700;margin-bottom:8px;font-size:14px}
input[type=text],input[type=number],textarea,select{width:100%;border:1.5px solid var(--line);border-radius:10px;padding:14px;font-size:16px;font-family:inherit;line-height:1.5}
textarea{min-height:110px;resize:vertical}
input:focus,textarea:focus{outline:none;border-color:var(--red)}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.add-btn{background:transparent;border:1.5px dashed var(--red);color:var(--red);padding:10px 16px;border-radius:10px;cursor:pointer;font-weight:700;font-size:14px;font-family:inherit}
button[type=submit]{display:block;width:100%;padding:22px;background:var(--red);color:#fff;border:none;border-radius:14px;font-size:20px;font-weight:800;cursor:pointer;margin-top:24px;box-shadow:0 8px 28px rgba(214,48,49,0.35)}
button[type=submit]:hover{background:var(--red-deep)}
button[type=submit]:disabled{opacity:0.5;cursor:wait}
.scale{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.scale label{flex:1;min-width:38px;text-align:center;cursor:pointer;border:1.5px solid var(--line);border-radius:8px;padding:10px 2px;font-weight:700;background:#fafaf7;font-size:13px;margin:0}
.scale label:has(input:checked){border-color:var(--red);background:#fff5f5;color:var(--red)}
.scale input{display:none}
.result{display:none;background:linear-gradient(135deg,#0a0a0a,#2d2d2d);color:#fff;border-radius:18px;padding:30px;margin-top:24px;text-align:center}
.result.show{display:block}
.result a{color:#fff;background:var(--red);padding:14px 24px;border-radius:10px;text-decoration:none;font-weight:700;display:inline-block;margin-top:14px}
.removable{position:relative}
.removable .x{position:absolute;right:8px;top:8px;cursor:pointer;color:var(--red);font-weight:800;background:transparent;border:none;font-size:16px}
"""


# ============================================================
# L1 Founder OS form
# ============================================================
@router.get("/foundation/l1", response_class=HTMLResponse)
async def l1_form(
    student: str = "",
    sig: str = "",
    pool=Depends(get_pool),
) -> HTMLResponse:
    student_uuid = _validated_student(student, sig)
    if student_uuid is None:
        return HTMLResponse(
            _error_page("Đường link không hợp lệ. Liên hệ Hằng qua Zalo."),
            status_code=403,
        )
    if not await has_baseline(pool, student_uuid):
        return RedirectResponse(
            f"/foundation/baseline?student={student}&sig={sig}",
            status_code=303,
        )

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Tầng 1 · Founder OS · Hiểu mình</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{_CSS}</style></head>
<body><div class="container">

<div class="tag">Tầng 1 · Founder OS · Hiểu mình</div>
<h1>Xác định điều bạn muốn xây và cách bạn muốn sống</h1>
<p class="sub">Bạn trả lời 5 phần. AI dùng chính câu trả lời và bằng chứng của bạn để tạo 3 bản nháp. Bạn sẽ xem, sửa và duyệt đủ 8 hồ sơ trước khi chốt Tầng 1.</p>

<form id="l1-form">
  <input type="hidden" name="student_id" value="{student}">
  <input type="hidden" name="signature" value="{sig}">

  <div class="card"><h3>1. Sứ Mệnh Đời (Life Mission)</h3><p class="hint">Lý do bạn tồn tại 10-20 năm tới, độc lập với việc đang kinh doanh gì hôm nay.</p>
    <textarea name="life_mission" required placeholder="VD: Giúp các chủ tiệm nhỏ ở quê sống được bằng nghề và truyền nghề cho thế hệ sau."></textarea></div>

  <div class="card"><h3>2. Tầm Nhìn 5 Năm (Vision Statement)</h3><p class="hint">Bức tranh cuộc sống cụ thể bạn muốn nhìn thấy 5 năm tới.</p>
    <textarea name="vision_statement" required placeholder="VD: 5 năm tới tôi làm việc 4 giờ mỗi ngày, có một dòng thu nhập ổn định và đủ thời gian cho gia đình."></textarea></div>

  <div class="card"><h3>3. Bản Sắc Sáng Lập (Founder Identity)</h3><p class="hint">Bạn là ai. Giá trị cốt lõi. Năng lực độc nhất. Loại founder bạn thực sự là.</p>
    <textarea name="founder_identity" required placeholder="VD: Tôi là người dạy nghề, không phải người bán hàng. Mạnh nhất khi xây quy trình giúp người khác học nhanh."></textarea></div>

  <div class="card"><h3>4. Nguyên Tắc Quyết Định (Decision Principles)</h3><p class="hint">5-7 nguyên tắc sống. Mỗi dòng một nguyên tắc.</p>
    <textarea name="decision_principles_text" required placeholder="Một nguyên tắc mỗi dòng. VD:&#10;Chọn việc mình giỏi nhất, từ chối phần còn lại&#10;Không nhận khách mà chưa rõ kết quả mình giao được&#10;Mỗi tuần dành 1 buổi không làm việc..."></textarea></div>

  <div class="card"><h3>5. Điều Tôi Không Muốn (Anti Vision)</h3><p class="hint">5-10 điều bạn KHÔNG muốn trở thành. Mỗi dòng một điều.</p>
    <textarea name="anti_vision_text" required placeholder="VD:&#10;phụ thuộc 1 khách lớn&#10;làm việc tối thứ Bảy và Chủ Nhật&#10;chạy theo trend không hợp giá trị..."></textarea></div>

  <div class="card"><h3>Bổ sung context để AI sinh chất lượng hơn (optional)</h3>
    <label>Lived experience tóm tắt (background bạn)</label>
    <textarea name="lived_experience" placeholder="Quá trình bạn đi đến đây..."></textarea>
    <label style="margin-top:14px">Customer direction (giả thuyết ban đầu)</label>
    <input type="text" name="customer_direction" placeholder="Nhóm người bạn đang nghĩ tới, chưa cần chốt. Tầng 2 sẽ kiểm chứng.">
  </div>

  <button type="submit" id="submit-btn">Lưu bản nháp và tạo hồ sơ Founder OS</button>
</form>

<div class="result" id="result">
  <div class="tag" style="background:rgba(214,48,49,0.2)">L1 đã lưu</div>
  <h3 style="font-size:22px;margin:14px 0">5 file Tier A đã lưu. AI đang sinh 3 file Tier B...</h3>
  <p style="opacity:0.8">Why Statement + Founder Assets + Founder Story sẽ có trong 1-2 phút.</p>
  <a id="canonical-link" href="#">Xem 8 canonical files</a>
</div>

</div>
<script>
document.getElementById('l1-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const btn = document.getElementById('submit-btn');
  btn.disabled = true; btn.textContent = 'Đang lưu...';
  const fd = new FormData(e.target);
  const sid = fd.get('student_id');
  const sig = fd.get('signature');
  if (!sid) {{ alert('Thiếu student_id. Mở đường link từ Hằng Zalo.'); btn.disabled=false; btn.textContent='Lưu L1 →'; return; }}
  const payload = {{
    student_id: sid,
    life_mission: fd.get('life_mission'),
    vision_statement: fd.get('vision_statement'),
    founder_identity: fd.get('founder_identity'),
    decision_principles: fd.get('decision_principles_text').split('\\n').filter(s=>s.trim()),
    anti_vision: fd.get('anti_vision_text').split('\\n').filter(s=>s.trim()),
    lived_experience: fd.get('lived_experience') || '',
    customer_direction: fd.get('customer_direction') || '',
  }};
  try {{
    const r = await fetch('/sdl/l1/intake', {{method:'POST', headers:{{
      'Content-Type':'application/json',
      'X-Student-Signature': sig,
    }}, body: JSON.stringify(payload)}});
    if (r.status === 412) {{
      const errorData = await r.json();
      const redirect = errorData.redirect || (errorData.detail && errorData.detail.redirect);
      if (redirect) {{ window.location.href = redirect; return; }}
    }}
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    document.getElementById('canonical-link').href = `/sdl/students/${{sid}}/output/L1?sig=${{encodeURIComponent(sig)}}`;
    e.target.style.display='none';
    document.getElementById('result').classList.add('show');
    window.scrollTo({{top:0, behavior:'smooth'}});
  }} catch(err) {{ alert('Lỗi: '+err.message); btn.disabled=false; btn.textContent='Lưu L1 →'; }}
}});
</script>
</body></html>""")


# ============================================================
# L2 Customer Intelligence form
# ============================================================
def _scale(name: str, max_val: int = 10) -> str:
    return '<div class="scale">' + "".join(
        f'<label><input type="radio" name="{name}" value="{i}"{" required" if i==0 else ""}>{i}</label>'
        for i in range(0, max_val + 1)
    ) + '</div>'


# L2 Opportunity Map: dropdown chấm điểm 0-10 dễ bấm trên điện thoại, thay format
# textarea "Tên · 9 · 8 ·..." (dấu · khó gõ, hay ra 0 hết => kẹt gate L2).
_OPP_CSS = (
    ".opp{border:1px solid #e5e2dd;border-radius:12px;padding:14px;margin-bottom:14px;background:#fcfcfa}"
    ".opp-pick{display:flex;align-items:center;gap:8px;font-weight:600;color:#0a0a0a;margin-bottom:10px}"
    ".opp-pick input{width:auto;margin:0}"
    ".opp input[type=text]{margin-bottom:10px}"
    ".opp-scores{display:grid;gap:8px}"
    ".score-row{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:14px;color:#5a5453}"
    ".score-row span{flex:1}"
    ".score-sel{width:88px;padding:8px;border:1px solid #d8d4ce;border-radius:8px;font-size:16px;background:#fff}"
    ".opp-total{margin-top:10px;font-size:14px;color:#5a5453}"
    ".opp-total .opp-sum{color:#d63031;font-size:16px;font-weight:700}"
    ".opp-warning{display:none;margin-top:10px;color:#fff;background:#d63031;padding:10px 12px;border-radius:8px;font-size:14px}"
)


def _score_select(name: str, max_val: int = 10) -> str:
    opts = "".join(f'<option value="{i}">{i}</option>' for i in range(0, max_val + 1))
    return f'<select name="{name}" class="score-sel">{opts}</select>'


def _opp_block(idx: int) -> str:
    req = " required" if idx == 0 else ""
    checked = " checked" if idx == 0 else ""
    dims = [("fit", "Founder fit (hợp với bạn)"), ("demand", "Market demand (thị trường cần)"),
            ("monet", "Monetization (dễ ra tiền)"), ("ai", "AI leverage (AI gánh được)"),
            ("conf", "Confidence (bạn tự tin)")]
    rows = "".join(
        f'<label class="score-row"><span>{lbl}</span>{_score_select(f"opp{idx}_{key}")}</label>'
        for key, lbl in dims
    )
    return (
        f'<div class="opp" data-idx="{idx}">'
        f'<label class="opp-pick"><input type="radio" name="selected_opp" value="{idx}"{checked}> Chọn cơ hội này làm chính</label>'
        f'<input type="text" name="opp{idx}_name" placeholder="Tên cơ hội {idx + 1}"{req}>'
        f'<div class="opp-scores">{rows}</div>'
        f'<p class="opp-total">Tổng điểm: <strong class="opp-sum">0</strong>/50</p>'
        f'</div>'
    )


@router.get("/foundation/l2", response_class=HTMLResponse)
async def l2_form(
    student: str = "",
    sig: str = "",
    pool=Depends(get_pool),
) -> HTMLResponse:
    student_uuid = _validated_student(student, sig)
    if student_uuid is None:
        return HTMLResponse(
            _error_page("Đường link không hợp lệ. Liên hệ Hằng qua Zalo."),
            status_code=403,
        )
    try:
        await require_level_access(pool, student_uuid, 2, "L2 Customer Intelligence OS")
    except HTTPException as exc:
        return HTMLResponse(
            _error_page(exc.detail.get("message") if isinstance(exc.detail, dict) else str(exc.detail)),
            status_code=403,
        )
    if not await check_gate_passed(pool, student_uuid, "gate_1_founder"):
        return RedirectResponse(
            f"/sdl/students/{student_uuid}/output/L1?sig={sig}",
            status_code=303,
        )
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>L2 Customer Intelligence OS</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{_CSS}</style><style>{_OPP_CSS}</style></head><body><div class="container">

<div class="tag">Tầng 2 · Customer Intelligence · 4 file cốt lõi</div>
<h1>Khách nào bạn có quyền phục vụ nhất?</h1>
<p class="sub">4 file Tier A bạn fill. AI sinh tiếp 7 file (Empathy Map + Demand + Conversation + Buying Journey + Triggers + 2 more).</p>

<form id="l2-form"><input type="hidden" name="student_id" value="{student}">
<input type="hidden" name="signature" value="{sig}">

<div class="card"><h3>1. Tôi phục vụ ai (Who I Serve)</h3>
  <p class="hint">Mô tả ngắn gọn 1-2 đoạn về khách hàng cốt lõi.</p>
  <textarea name="who_i_serve" required placeholder="VD: Phụ nữ văn phòng Việt 30-45 tuổi muốn nguồn thu nhập thứ hai, đã thử nhiều cách nhưng không có kết quả..."></textarea>
</div>

<div class="card"><h3>2. Customer Profile chi tiết</h3>
  <p class="hint">Persona đại diện: tuổi, nghề, thu nhập, hành vi, môi trường sống.</p>
  <textarea name="customer_profile_text" required placeholder="VD: Tên đại diện Mai, 38 tuổi, nhân viên VP HCM thu nhập 25tr/tháng..."></textarea>
</div>

<div class="card"><h3>3. Customer Jobs (Strategyzer VPC)</h3>
  <label>Functional Jobs (chức năng) - mỗi dòng 1 job</label>
  <textarea name="jobs_functional" placeholder="VD: Tìm cách kiếm thêm thu nhập&#10;Quản lý thời gian khi vừa work vừa side hustle"></textarea>
  <label style="margin-top:14px">Emotional Jobs (cảm xúc)</label>
  <textarea name="jobs_emotional" placeholder="VD: Cảm thấy tự tin về tương lai&#10;Không bị lệ thuộc sếp"></textarea>
  <label style="margin-top:14px">Social Jobs (xã hội)</label>
  <textarea name="jobs_social" placeholder="VD: Được con cháu nhìn nhận là người độc lập"></textarea>
</div>

<div class="card"><h3>4. Customer Pains (3 nhóm VPC)</h3>
  <label>Obstacles (cản trở)</label>
  <textarea name="pains_obstacles" placeholder="Mỗi dòng 1 cản trở"></textarea>
  <label style="margin-top:14px">Risks (rủi ro tiềm ẩn)</label>
  <textarea name="pains_risks"></textarea>
  <label style="margin-top:14px">Frustrations (đau hằng ngày)</label>
  <textarea name="pains_frustrations"></textarea>
</div>

<div class="card"><h3>5. Customer Gains (4 nhóm VPC)</h3>
  <label>Required Gains (bắt buộc có)</label>
  <textarea name="gains_required"></textarea>
  <label style="margin-top:14px">Expected Gains (nghĩ là sẽ có)</label>
  <textarea name="gains_expected"></textarea>
  <label style="margin-top:14px">Desired Gains (mong có)</label>
  <textarea name="gains_desired"></textarea>
  <label style="margin-top:14px">Unexpected Gains (wow factor)</label>
  <textarea name="gains_unexpected"></textarea>
</div>

<div class="card"><h3>6. Customer Fit Score (Anna V3.5, KHÔNG pain-first)</h3>
  <p class="hint">Đo độ phù hợp giữa bạn và khách trên 6 chiều. Mỗi chiều 0-10.</p>
  <label>Lived Experience (30%) - founder đã trải qua nỗi đau khách</label>{_scale('fit_lived')}
  <label style="margin-top:14px">Empathy (20%)</label>{_scale('fit_empathy')}
  <label style="margin-top:14px">Credibility (15%)</label>{_scale('fit_credibility')}
  <label style="margin-top:14px">Pain (15%) - nỗi đau khách mạnh không</label>{_scale('fit_pain')}
  <label style="margin-top:14px">Reach (10%) - tiếp cận khách dễ không</label>{_scale('fit_reach')}
  <label style="margin-top:14px">WTP (10%) - khả năng trả tiền</label>{_scale('fit_wtp')}
</div>

<div class="card"><h3>7. Statement Một Dòng (4 ý V3.5.3)</h3>
  <p class="hint">WHO + CURRENT PAIN + DESIRED IDENTITY + VEHICLE. AI sẽ ráp lại thành 1 câu hoàn chỉnh.</p>
  <label>WHO (khách là ai)</label>
  <input type="text" name="stmt_who" required placeholder="phụ nữ văn phòng muốn nguồn thu nhập thứ hai">
  <label style="margin-top:12px">CURRENT PAIN (đau hiện tại)</label>
  <input type="text" name="stmt_pain" required placeholder="đã thử nhiều cách nhưng không ra kết quả">
  <label style="margin-top:12px">DESIRED IDENTITY (muốn trở thành ai)</label>
  <input type="text" name="stmt_identity" required placeholder="người sở hữu doanh nghiệp một người vận hành bằng AI">
  <label style="margin-top:12px">VEHICLE (phương tiện)</label>
  <input type="text" name="stmt_vehicle" required placeholder="BreakoutOS">
</div>

<div class="card"><h3>8. Opportunity Map (chấm điểm 1-3 cơ hội)</h3>
  <p class="hint">Nhập 1-3 cơ hội bạn đang cân nhắc. Mỗi cơ hội chọn điểm 0-10 cho 5 tiêu chí. Chọn 1 cơ hội làm chính. Cơ hội chính phải đạt tổng <strong>≥ 30/50</strong> mới qua được cổng L2.</p>
  {_opp_block(0)}
  {_opp_block(1)}
  {_opp_block(2)}
  <p id="opp-warning" class="opp-warning"></p>
</div>

<button type="submit" id="submit-btn">Lưu L2 và sinh 7 file AI →</button>
</form>

<div class="result" id="result">
  <h3 style="font-size:22px;margin-bottom:14px">L2 đã lưu</h3>
  <p style="opacity:0.85" id="fit-msg">Fit Score: <strong id="fit-total">-</strong>/100</p>
  <p style="opacity:0.85;margin-top:10px" id="stmt-msg"></p>
  <a id="canonical-link" href="#">Xem 11 canonical files</a>
</div>

</div>
<script>
document.getElementById('l2-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const btn = document.getElementById('submit-btn');
  btn.disabled = true; btn.textContent = 'Đang lưu...';
  const fd = new FormData(e.target);
  const sid = fd.get('student_id');
  const sig = fd.get('signature');
  if (!sid) {{ alert('Thiếu student_id'); btn.disabled=false; btn.textContent='Lưu L2 →'; return; }}

  const splitLines = (k) => (fd.get(k)||'').split('\\n').filter(s=>s.trim());
  const oppVal = (idx,k) => parseInt((document.querySelector('[name="opp'+idx+'_'+k+'"]')||{{}}).value || 0);
  const oppName = (idx) => ((document.querySelector('[name="opp'+idx+'_name"]')||{{}}).value || '').trim();
  const opps = [0,1,2].map(idx => ({{
      name: oppName(idx),
      founder_fit_score: oppVal(idx,'fit'),
      market_demand_score: oppVal(idx,'demand'),
      monetization_score: oppVal(idx,'monet'),
      ai_leverage_score: oppVal(idx,'ai'),
      confidence_score: oppVal(idx,'conf'),
  }})).filter(o => o.name);
  const selRadio = document.querySelector('input[name="selected_opp"]:checked');
  const selIdx = selRadio ? selRadio.value : '0';
  const selName = oppName(selIdx);
  const warn = document.getElementById('opp-warning');
  const resetBtn = () => {{ btn.disabled=false; btn.textContent='Lưu L2 và sinh 7 file AI →'; }};
  if (!selName) {{ warn.textContent='Nhập tên cơ hội chính và bấm chọn nó làm cơ hội chính.'; warn.style.display='block'; resetBtn(); return; }}
  const selSum = oppVal(selIdx,'fit')+oppVal(selIdx,'demand')+oppVal(selIdx,'monet')+oppVal(selIdx,'ai')+oppVal(selIdx,'conf');
  if (selSum < 30) {{ warn.textContent='Cơ hội chính mới đạt '+selSum+'/50. Cần tổng \\u2265 30 để qua cổng L2. Tăng điểm 5 tiêu chí cho cơ hội bạn tin nhất.'; warn.style.display='block'; resetBtn(); return; }}
  warn.style.display='none';

  const payload = {{
    student_id: sid,
    who_i_serve: fd.get('who_i_serve'),
    customer_profile_text: fd.get('customer_profile_text'),
    customer_jobs: {{
      functional: splitLines('jobs_functional'),
      emotional: splitLines('jobs_emotional'),
      social: splitLines('jobs_social'),
    }},
    customer_pains: {{
      obstacles: splitLines('pains_obstacles'),
      risks: splitLines('pains_risks'),
      frustrations: splitLines('pains_frustrations'),
    }},
    customer_gains: {{
      required: splitLines('gains_required'),
      expected: splitLines('gains_expected'),
      desired: splitLines('gains_desired'),
      unexpected: splitLines('gains_unexpected'),
    }},
    customer_fit: {{
      lived_experience: parseInt(fd.get('fit_lived') || 0),
      empathy: parseInt(fd.get('fit_empathy') || 0),
      credibility: parseInt(fd.get('fit_credibility') || 0),
      pain: parseInt(fd.get('fit_pain') || 0),
      reach: parseInt(fd.get('fit_reach') || 0),
      wtp: parseInt(fd.get('fit_wtp') || 0),
    }},
    statement_mot_dong: {{
      who: fd.get('stmt_who'),
      current_pain: fd.get('stmt_pain'),
      desired_identity: fd.get('stmt_identity'),
      vehicle: fd.get('stmt_vehicle'),
    }},
    opportunities: opps,
    selected_opportunity: selName,
  }};
  try {{
    const r = await fetch('/sdl/l2/intake', {{method:'POST', headers:{{
      'Content-Type':'application/json',
      'X-Student-Signature': sig,
    }}, body: JSON.stringify(payload)}});
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    document.getElementById('fit-total').textContent = d.fit_score_total;
    document.getElementById('stmt-msg').innerHTML = '<em>' + (d.statement_mot_dong || '') + '</em>';
    document.getElementById('canonical-link').href = `/sdl/students/${{sid}}/output/L2?sig=${{encodeURIComponent(sig)}}`;
    e.target.style.display='none';
    document.getElementById('result').classList.add('show');
    window.scrollTo({{top:0, behavior:'smooth'}});
  }} catch(err) {{ alert('Lỗi: '+err.message); btn.disabled=false; btn.textContent='Lưu L2 →'; }}
}});

// Tổng điểm hiển thị trực tiếp khi đổi dropdown từng cơ hội
document.querySelectorAll('.opp').forEach(div => {{
  const idx = div.dataset.idx;
  const sumEl = div.querySelector('.opp-sum');
  const recompute = () => {{
    let s = 0;
    ['fit','demand','monet','ai','conf'].forEach(k => {{
      const el = div.querySelector('[name="opp'+idx+'_'+k+'"]');
      if (el) s += parseInt(el.value || 0);
    }});
    sumEl.textContent = s;
  }};
  div.querySelectorAll('.score-sel').forEach(sel => sel.addEventListener('change', recompute));
  recompute();
}});
</script>
</body></html>""")


# ============================================================
# L3 Value Proposition form
# ============================================================
@router.get("/foundation/l3", response_class=HTMLResponse)
async def l3_form(
    student: str = "",
    sig: str = "",
    pool=Depends(get_pool),
) -> HTMLResponse:
    student_uuid = _validated_student(student, sig)
    if student_uuid is None:
        return HTMLResponse(
            _error_page("Đường link không hợp lệ. Liên hệ Hằng qua Zalo."),
            status_code=403,
        )
    try:
        await require_level_access(pool, student_uuid, 3, "L3 Value Proposition OS")
    except HTTPException as exc:
        return HTMLResponse(
            _error_page(exc.detail.get("message") if isinstance(exc.detail, dict) else str(exc.detail)),
            status_code=403,
        )
    if not await check_gate_passed(pool, student_uuid, "gate_2_customer_soft"):
        return RedirectResponse(
            f"/sdl/students/{student_uuid}/output/L2?sig={sig}",
            status_code=303,
        )
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>L3 Value Proposition OS</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>{_CSS}</style></head><body><div class="container">

<div class="tag">Tầng 3 · Value Proposition · 4 file cốt lõi</div>
<h1>Bạn tạo transformation gì cho khách?</h1>
<p class="sub">AI Opus sẽ sinh thêm Hormozi Value Equation + Guarantee + Offer Stack + Financial Model.</p>

<form id="l3-form"><input type="hidden" name="student_id" value="{student}">
<input type="hidden" name="signature" value="{sig}">

<div class="card"><h3>1. Core Offer</h3>
  <label>Tên offer</label><input type="text" name="core_offer_name" required placeholder="VD: BreakoutOS Foundation 7 ngày">
  <label style="margin-top:12px">Mô tả ngắn</label>
  <textarea name="core_offer_description" required placeholder="Mô tả 1-2 đoạn về offer chính"></textarea>
  <div class="row" style="margin-top:12px">
    <div><label>Target customer</label><input type="text" name="target_customer" required></div>
    <div><label>Current pain</label><input type="text" name="pain" required></div>
  </div>
  <div class="row" style="margin-top:12px">
    <div><label>Desired identity</label><input type="text" name="desired_identity" required></div>
    <div><label>Vehicle</label><input type="text" name="vehicle" required></div>
  </div>
  <label style="margin-top:12px">Transformation (X → Y)</label>
  <input type="text" name="transformation" required placeholder="VD: Từ 'không biết bán gì' → 'có sản phẩm sẵn sàng bán'">
</div>

<div class="card"><h3>2. Pricing Strategy</h3>
  <div class="row">
    <div><label>Tier</label><input type="text" name="pricing_tier" value="Foundation"></div>
    <div><label>Price VND</label><input type="number" name="price_vnd" required value="3000000" min="100000"></div>
  </div>
  <label style="margin-top:12px">Lý do giá này</label>
  <textarea name="pricing_rationale" required></textarea>
</div>

<div class="card"><h3>3. Positioning Statement (Category + Frame + POD + RTB)</h3>
  <label>Category position</label>
  <input type="text" name="positioning_category" required placeholder="VD: Operating System for Solo Founder with AI">
  <label style="margin-top:12px">Frame of reference (so với gì)</label>
  <input type="text" name="positioning_frame" required placeholder="VD: thay vì agency 50 người hoặc course platform">
  <label style="margin-top:12px">Point of difference (USP)</label>
  <input type="text" name="positioning_pod" required placeholder="VD: 1 founder × 1 AI × portfolio ventures">
  <label style="margin-top:12px">Reason to believe (proof)</label>
  <input type="text" name="positioning_rtb" required placeholder="VD: Anna's 6 ventures running on it">
</div>

<button type="submit" id="submit-btn">Lưu L3 và sinh 4 file Opus →</button>
</form>

<div class="result" id="result">
  <h3 style="font-size:22px;margin-bottom:14px">L3 đã lưu</h3>
  <p style="opacity:0.85" id="pos-msg"></p>
  <a id="canonical-link" href="#">Xem 8 canonical files</a>
</div>

</div>
<script>
document.getElementById('l3-form').addEventListener('submit', async (e) => {{
  e.preventDefault();
  const btn = document.getElementById('submit-btn');
  btn.disabled = true; btn.textContent = 'Đang lưu...';
  const fd = new FormData(e.target);
  const sid = fd.get('student_id');
  const sig = fd.get('signature');
  if (!sid) {{ alert('Thiếu student_id'); btn.disabled=false; btn.textContent='Lưu L3 →'; return; }}
  const payload = {{}};
  for (const [k,v] of fd.entries()) {{
    if (k === 'price_vnd') payload[k] = parseInt(v);
    else payload[k] = v;
  }}
  try {{
    const r = await fetch('/sdl/l3/intake', {{method:'POST', headers:{{
      'Content-Type':'application/json',
      'X-Student-Signature': sig,
    }}, body: JSON.stringify(payload)}});
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    document.getElementById('pos-msg').innerHTML = '<em>' + (d.positioning_statement || '') + '</em>';
    document.getElementById('canonical-link').href = `/sdl/students/${{sid}}/output/L3?sig=${{encodeURIComponent(sig)}}`;
    e.target.style.display='none';
    document.getElementById('result').classList.add('show');
    window.scrollTo({{top:0, behavior:'smooth'}});
  }} catch(err) {{ alert('Lỗi: '+err.message); btn.disabled=false; btn.textContent='Lưu L3 →'; }}
}});
</script>
</body></html>""")
