# BC11 Spec, Tròn Vuông VPC Builder

## Mục tiêu
Build Tròn Vuông Value Proposition Canvas 6 component per persona, encode Eagle Camp VPC + Anna CIS Module 2 JTBD framework.

## Framework encoded
- **Phạm Thành Long Eagle Camp Tròn Vuông VPC**: 6 component canvas
- **Anna CIS Module 2 JTBD**: 3 loại Jobs (Functional/Social/Emotional)
- **Anna CIS Module 3 Pain System**: 4 loại Pain + 3 Rào cản + 3 Rủi ro
- **Anna CIS Module 4 Joy/Gains**: 4 loại Gains (Required/Expected/Desired/Unexpected)

## Input schema

```json
{
  "agent_name": "bc11_vpc_builder",
  "trigger_event": "vpc.build_canvas",
  "venture_context": "breakout",
  "payload": {
    "persona_name": "Nhân viên văn phòng VN 28-45",
    "customer_data": {
      "demographics": {...},
      "transactions": [...],
      "feedback": [...]
    }
  }
}
```

## Output schema (validated via tool_use submit_canvas)

```json
{
  "persona_name": "...",
  "venture": "...",
  "trong_khach_hang": {
    "jobs": {
      "functional": ["...", "..."],
      "social": ["..."],
      "emotional": ["..."]
    },
    "pains": {
      "functional": [...], "social": [...], "emotional": [...], "ancillary": [...]
    },
    "barriers": {"time": "...", "money": "...", "skills": "..."},
    "risks": {"financial": "...", "social": "...", "time": "..."},
    "gains": {
      "required": [...], "expected": [...], "desired": [...], "unexpected": [...]
    }
  },
  "vuong_san_pham": {
    "products_services": [...],
    "pain_relievers": [{"feature": "...", "addresses_pain": "..."}],
    "gain_creators": [{"feature": "...", "creates_gain": "..."}]
  },
  "fit_score": 85,
  "orphan_pains": [],
  "orphan_gains": [],
  "anna_persona_match": "nhan_vien_vp",
  "summary": "..."
}
```

## Quality criteria (validate canvas)

- [ ] 6 component đầy đủ
- [ ] Jobs: ≥2 functional + ≥1 social + ≥1 emotional
- [ ] Pains: ≥2 trong mỗi 4 loại
- [ ] Gains: ≥1 required + ≥1 expected
- [ ] Pain Relievers ≥3
- [ ] Gain Creators ≥2
- [ ] Mỗi Pain có ≥1 Reliever (orphan_pains empty hoặc < 2)
- [ ] Mỗi Required/Expected Gain có Creator (orphan_gains empty hoặc < 2)
- [ ] Fit score ≥80
- [ ] KHÔNG em-dash, "mẹ đơn thân", "Perth/Adelaide"
- [ ] Specific not generic

## Escalation logic

- fit_score < 60 → escalation_required=True → Anna review qua Telegram Breakout Ops
- orphan_pains + orphan_gains ≥ 3 → quality_check.passes_quality=False
- has_em_dash or has_forbidden_term → BC2 voice gate sẽ reject (post-emit downstream)

## Memory output

```json
{
  "category": "profile",
  "venture": "breakout",
  "tags": ["bc11", "vpc", "tron-vuong", "persona", "fit-85"],
  "content": <full canvas JSON>
}
```

Downstream consumers:
- BC13 Pain Severity Scorer: input pain_matrix
- BC14 Joy/Gain Mapper: input pain_matrix + persona_context
- BC16 Value Ladder Designer: input persona + pain + joy
- BC17 Grand Slam Offer Builder: input persona + pain + joy

## Test cases

### Test 1: Anna's NV VP persona
Input: persona_name="Nhân viên văn phòng VN 28-45", venture="breakout"
Expected: anna_persona_match="nhan_vien_vp", fit_score ≥85, jobs functional có "thu nhập thêm" + "thoát 8-5"

### Test 2: Anna's Mẹ bỉm sữa persona
Input: persona_name="Mẹ bỉm sữa 25-40", venture="breakout"
Expected: anna_persona_match="me_bim_sua", pain emotional có "tự ti, vô dụng"

### Test 3: Anna's Chủ shop persona
Input: persona_name="Chủ shop truyền thống 35-55", venture="breakout"
Expected: anna_persona_match="chu_shop", pain functional có "ecommerce khó vận hành"

### Test 4: Custom persona (Cohort 1 student)
Input: persona_name="Chủ quán bánh mì Sài Gòn", venture="bms-saigon"
Expected: anna_persona_match="custom", canvas generated từ scratch không reference Anna persona

### Test 5: Edge case empty customer_data
Input: persona_name="Default", customer_data={}
Expected: canvas vẫn generate dựa knowledge_base + canonical fact, fit_score thấp (60-70)

## Performance benchmark

- Latency p50: < 30s (Opus 4.7 + 3500 max tokens)
- Latency p99: < 90s
- Token usage typical: ~3000-5000 input + ~2000-3000 output
- Cost per canvas: ~$0.05-0.08 USD

## Production deployment checklist

- [ ] knowledge_base.md loaded (~5KB rich content)
- [ ] prompt_template.py importable + tool schema valid
- [ ] agent.py registered trong main.py + scheduler
- [ ] Memory layer wired (canonical fact retrieve)
- [ ] Smoke test 5 sample pass (3 Anna persona + 1 custom + 1 edge)
- [ ] Anna validate output quality
- [ ] Telegram alert chain wired (escalation fit_score < 60)
- [ ] Logging structured (agent_name + venture + fit_score)
