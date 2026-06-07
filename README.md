# CAMAS Kernel

Cohangai AIOS Multi-Agent System Kernel. Service Railway điều phối 25 agent (7 BC + 10 phòng ban + 5 cron + 1 routine + 1 FB autoreply + 1 healthcheck) qua shared memory + auto inject/extract pattern (Cerebrum NAACL 2025).

Đây là kernel scaffold (v0.1). Mục đích phiên này: dựng skeleton typed + decoupled SDK + native MCP slot, sau đó Q3 wire dần từng layer (Postgres pgvector, Voyage embedding, Anthropic Claude, MCP server vault/CDP/GHL/Sepay).

---

## 1. KIẾN TRÚC TỔNG

```
┌──────────────────────────────────────────────┐
│ EXTERNAL EVENTS                              │
│  Sepay webhook · Zalo OA · GHL · Tally       │
│  Fathom · WK register · FB · Telegram        │
└────────────┬─────────────────────────────────┘
             ↓ POST /webhook/trigger
┌──────────────────────────────────────────────┐
│ CAMAS KERNEL (Railway service)               │
│                                              │
│  ┌────────────────────────────────────────┐ │
│  │ Scheduler (asyncio queue → Postgres    │ │
│  │ LISTEN/NOTIFY Q3)                      │ │
│  │  - auto_inject memory                  │ │
│  │  - agent.execute(ctx)                  │ │
│  │  - Voice Gate hook (BC2)               │ │
│  │  - Compliance Gate hook (BC9)          │ │
│  │  - auto_extract memory                 │ │
│  │  - Escalation Telegram (L1/L2/L3)      │ │
│  └────────────────────────────────────────┘ │
│                                              │
│  4 typed layer (Cerebrum 4 layer dataclass) │
│   - LLMLayer    Anthropic Claude wrapper     │
│   - MemoryLayer pgvector shared memory       │
│   - ToolLayer   registry + MCP client        │
│   - StorageLayer Postgres + R2 backup        │
└────────────┬─────────────────────────────────┘
             ↓ tools
┌──────────────────────────────────────────────┐
│ TOOL UNIVERSE (80 API + 5 MCP)               │
│  Vault MCP · CDP MCP · GHL MCP · Sepay MCP   │
│  Anthropic · Vbee · Creatomate · Telegram    │
└──────────────────────────────────────────────┘
```

Chi tiết kiến trúc canonical: `cohangai/aios/cohangai-multi-agent-system-design.md` (CAMAS), `cohangai/aios/cerebrum-docs-deep-dive.md` (4 layer + Profile/Task/Assistant pattern), `cohangai/aios/aios-architecture-overview.md` (7 tầng + 5 flow).

---

## 2. CẤU TRÚC THƯ MỤC

```
camas-kernel/
├── README.md                Tài liệu này
├── requirements.txt         FastAPI + Pydantic + anthropic + asyncpg
├── Procfile                 Railway/Heroku-style web command
├── railway.json             Railway deploy config + healthcheck path
├── main.py                  FastAPI app entry, mount router
├── kernel/                  Code lõi
│   ├── base_agent.py        BaseBC abstract + AgentResult + ExecutionContext
│   ├── memory_layer.py      MemoryLayer (pgvector) + MemoryRecord schema
│   ├── tool_layer.py        ToolLayer registry + ToolSpec
│   ├── llm_layer.py         LLMLayer Anthropic SDK wrapper
│   ├── scheduler.py         Scheduler dispatcher với auto_inject/extract hook
│   ├── voice_gate.py        BC2 Voice Guardian hook
│   ├── compliance_gate.py   BC9 Compliance Officer hook
│   └── escalation.py        EscalationService → Telegram Breakout Ops
├── agents/                  Implementation 25 agent (Q3 sẽ thêm)
│   └── _example_agent.py    Echo agent minh hoạ contract
├── routes/                  FastAPI router
│   ├── kernel_routes.py     /kernel/execute /kernel/status /kernel/agents
│   └── webhook_routes.py    /webhook/trigger (external events)
└── tests/
    └── test_base_agent.py   Pytest contract BaseBC + Scheduler
```

---

## 3. BASEBC CONTRACT (mọi agent tuân thủ)

Mỗi agent (BC + Phong + cron) subclass `BaseBC` và phải:

1. Set 3 attribute: `name`, `scope`, `autonomy_level` (L1/L2/L3)
2. Set escalation: `escalate_to` (telegram_breakout_ops mặc định)
3. Khai báo whitelist `tools[]` (kernel enforce qua ToolLayer)
4. Set 2 flag gate: `requires_voice_gate`, `requires_compliance_gate`
5. Implement async `run(ctx: ExecutionContext) -> AgentResult`

Kernel handle scaffolding xung quanh run():
- Pre: auto inject shared memory vào `ctx.injected_memories`
- Call: `await agent.run(ctx)`
- Post: Voice Gate + Compliance Gate hook nếu `result.publish_target` khác None
- Post: auto extract `result.emitted_memories` lưu shared memory
- Post: Escalation nếu `result.escalation_required` hoặc gate BLOCK/REJECT

Xem `agents/_example_agent.py` để có pattern tham khảo.

---

## 4. 3 MỨC AUTONOMY (Anna chốt trong Constitution)

| Mức | Nghĩa | Telegram | Ví dụ agent |
|-----|-------|----------|-------------|
| L1  | Auto, không cần Anna duyệt | Rollup 2x/ngày | BC1 Team Leader, Phong 04 GHL, Phong 05 Sepay+ZNS |
| L2  | Anna duyệt 1-click qua Telegram | Per case | BC6 CSKH FAQ ngoài rubric, BC10 share content |
| L3  | Propose only, Anna decide tay | Per case | Phong 07 Refund, Phong 10 Strategy, BC9 BLOCK action, BC4 launch week |

Promote threshold: 14 case L3 thành công → propose L2. 14 case L2 → propose L1. Anna phê duyệt.

---

## 5. SHARED MEMORY SCHEMA (Cerebrum 4 field + Anna 5 extension)

```python
MemoryRecord(
    # Cerebrum baseline
    owner_agent="bc3_profile",
    user_id="customer_uuid",
    memory_type=MemoryType.PROFILE,          # profile | task_context | conversation | venture_state | decision_log | compliance_audit
    sharing_policy=SharingPolicy.SHARED,     # private | shared

    # Anna's extensions
    venture_context="breakout",              # speakout | breakout | cohangai | bmcorner | dahafa | migration | dat_gia_nghia | personal | all
    ventures_active=["speakout", "breakout"],
    stage="paid",
    ltv_vnd=6000000,
    last_event_type="sepay.payment.success",

    content="Customer Hằng (anonymised), Speakout VIP, Breakout VIP, fast decider",
    raw_payload={"name": "...", ...},        # JSON gốc trước NL conversion
)
```

Anti-pattern (Cerebrum experiment validate):
- KHÔNG inject raw JSON, kernel phải convert sang natural language trước
- KHÔNG inter-agent communication trực tiếp, đi qua shared memory
- KHÔNG monolithic user model, tách profile (stable) vs task_context (volatile)
- KHÔNG default shared, default private, opt-in shared

---

## 6. ENDPOINT API

### Internal control plane

| Method | Path | Mô tả |
|--------|------|-------|
| GET    | `/`                | Public probe (service + version + status) |
| GET    | `/kernel/status`   | Health probe (Railway healthcheck dùng) |
| GET    | `/kernel/agents`   | Liệt kê agent đã register |
| POST   | `/kernel/execute`  | Chạy sync 1 agent, trả AgentResult |

### Webhook (external events)

| Method | Path | Mô tả |
|--------|------|-------|
| POST | `/webhook/trigger` | Generic dispatch, enqueue vào lane (llm/memory/tool/storage) |

Body mẫu `POST /webhook/trigger`:

```json
{
  "source": "sepay",
  "event_type": "sepay.payment.success",
  "target_agent": "phong_05_sepay_zns",
  "venture_context": "breakout",
  "user_id": "customer_uuid_xyz",
  "payload": {"order_code": "BRK199-001", "amount": 199000},
  "lane": "tool"
}
```

Q3 thêm signature verify cho từng source (Sepay HMAC, GHL bearer, Zalo OA, FB CAPI).

---

## 7. ENV VAR

| Tên | Mục đích | Bắt buộc lúc nào |
|-----|----------|------------------|
| `ANTHROPIC_API_KEY` | LLMLayer call Claude | Khi agent dùng LLM (sớm Q3) |
| `CDP_DATABASE_URL` | Postgres pgvector shared memory | Khi wire MemoryLayer (Q3 sớm) |
| `TELEGRAM_BOT_TOKEN` | Escalation gửi Breakout Ops group | Khi agent L2/L3 đầu tiên deploy |
| `MCP_VAULT_URL` | Vault MCP server endpoint | Khi Phong 02 cần vault search |
| `MCP_CDP_URL` | CDP MCP server endpoint | Khi Phong 08 data digest |
| `MCP_GHL_URL` | GHL MCP server endpoint | Khi Phong 04 GHL workflow |
| `MCP_SEPAY_URL` | Sepay MCP server endpoint | Khi Phong 05 sync confirm |
| `LOG_LEVEL` | INFO/DEBUG/WARNING | Optional |
| `PORT` | Railway inject tự động | Tự động |

KHÔNG hardcode secret. Mọi key đi qua `os.getenv()`. Tham khảo memory `reference-cohangai-env` cho convention.

---

## 8. CHẠY LOCAL

```bash
cd /Users/mac/Documents/ANNA SECOND BRAIN/cohangai/services/camas-kernel
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set env tối thiểu
export ANTHROPIC_API_KEY=sk-ant-...        # optional, agent dùng LLM mới cần
export CDP_DATABASE_URL=postgresql://...   # optional, memory wire mới cần

uvicorn main:app --reload --port 8080
# Truy cập http://localhost:8080/docs để xem OpenAPI UI
```

Chạy test:

```bash
pytest tests/ -v
```

---

## 9. DEPLOY RAILWAY

Anna đã có project `breakout-funnel-os-staging` (memory `reference-cdp-canonical`, schema `public`). CAMAS Kernel deploy service mới trong **cùng project** để share Postgres pgvector instance.

```bash
railway login
railway link                    # link vào project breakout-funnel-os-staging
railway service create camas-kernel
railway up                      # build + deploy

# Set env qua dashboard hoặc CLI:
railway variables set ANTHROPIC_API_KEY=sk-ant-...
railway variables set TELEGRAM_BOT_TOKEN=...
# CDP_DATABASE_URL được Railway plugin inject tự động khi attach Postgres
```

Healthcheck Railway hit `/kernel/status`, timeout 30s, restart on failure max 5 retries.

KHÔNG deploy service trùng. Trước khi tạo mới, check `railway list` để tránh duplicate (memory `feedback-check-existing-railway-services`).

---

## 10. TRẠNG THÁI STUB (chờ wire Q3)

Mọi component đã typed nhưng nhiều backend trả `NotImplementedError`. Đây là cố ý: cho phép Anna ship contract trước, wire dần khi backend sẵn sàng (per Anna's rule `feedback-root-cause-only` và `feedback-just-do-no-suggestions`).

| Component | Trạng thái | Wire khi |
|-----------|------------|----------|
| BaseBC + ExecutionContext + AgentResult | DONE | Đã chạy |
| Scheduler dispatch sync | DONE | Đã chạy |
| Scheduler enqueue async | DONE (in-memory queue) | Q3 replace LISTEN/NOTIFY |
| ToolLayer register + invoke local | DONE | Đã chạy |
| ToolLayer MCP backend | STUB | Q3 wire FastMCP client |
| MemoryLayer store/retrieve | STUB | Q3 sau khi tạo bảng `public.shared_memory` + Voyage embedding |
| MemoryLayer NL conversion | DONE (bullet list fallback) | Q3 upgrade Haiku format |
| LLMLayer chat | DONE (gated on ANTHROPIC_API_KEY) | Set env xong là chạy |
| VoiceGate review | STUB | Q3 load Anna voice profile vault file |
| ComplianceGate review | STUB | Q3 wire 7 layer rule + facts DB |
| EscalationService notify | DONE (gated on TELEGRAM_BOT_TOKEN) | Set env xong là chạy |

---

## 11. 25 AGENT CHỜ IMPLEMENT (Q3)

Theo CAMAS spec (cohangai-multi-agent-system-design.md mục 3):

### 7 BC
- `bc1_team_leader` (orchestrator + rollup, L1)
- `bc2_voice_guardian` (pre-publish hook, gate)
- `bc3_profile` + `bc3_task` (Profile/Task agent pattern Cerebrum)
- `bc4_k2_launch` (ReAct retry, L3 launch week)
- `bc5_cdp_monitor` (event stream watcher)
- `bc6_cskh_faq` (Haiku FAQ, Assistant agent)
- `bc9_compliance_officer` (pre-publish gate)
- `bc10_coaching_delivery` (Fathom transcript → 2 file summary)

### 10 Phong ban
- `phong_01_fb_ads`
- `phong_02_content` (voice gate + compliance gate required)
- `phong_03_landing`
- `phong_04_comms_ghl`
- `phong_05_sepay_zns`
- `phong_06_cskh_tier2`
- `phong_07_refund` (L3 mãi)
- `phong_08_data_digest`
- `phong_09_compliance_lint`
- `phong_10_strategy` (LangGraph, L3 mãi)

### 5 cron + 1 routine + 1 FB autoreply + 1 healthcheck
- `cron_morning_brief` (6am VN)
- `cron_wk_sync` (15 phút)
- `cron_dedupe` (Sun 2am)
- `cron_stale_alert` (Mon 7am)
- `cron_social_posts` (Sun 8pm)
- `routine_night_audit` (11pm Perth)
- `fb_autoreply_realtime`
- `healthcheck_5min`

---

## 12. TÀI LIỆU THAM CHIẾU CANONICAL

Đọc TRƯỚC khi viết agent mới:

1. `cohangai/aios/constitution.md` v1, 14 section A-N (voice, identity, escalation logic)
2. `cohangai/aios/aios-master-spec-v1.md` (vision 500k AUD, 12 tháng roadmap)
3. `cohangai/aios/cohangai-multi-agent-system-design.md` (CAMAS architecture)
4. `cohangai/aios/cerebrum-docs-deep-dive.md` (4 layer dataclass + shared memory pattern)
5. `cohangai/aios/aios-architecture-overview.md` (7 tầng + 5 flow)
6. `cohangai/aios/agent-inventory-complete.md` (chi tiết 21+ agent định nghĩa)
7. `cohangai/aios/tool-universe-complete.md` (80 API + 5 MCP)
8. `cohangai/aios/memory-map-complete.md` (T0/T1/T2 tier + shared memory schema)

Khi rule trong README này conflict với `constitution.md`, constitution thắng (file canonical, updated thường xuyên hơn).

---

## 13. CONTRIBUTING

Quy ước code:
- Python 3.11+, type hint mọi function, Pydantic typed mọi payload
- Async mọi I/O (FastAPI route, DB call, HTTP)
- Tiếng Việt cho user-facing string + comment giải thích quyết định nghiệp vụ
- ZERO emoji trừ khi Anna yêu cầu (Constitution Section C)
- ZERO dấu gạch ngang dài "—" (Constitution Section C, memory rule cứng)
- Filename: snake_case cho Python (convention thắng dash convention), lowercase-dash cho mọi file khác

Trước khi commit:
- Chạy `pytest tests/ -v` pass hết
- Lint check sẽ thêm Q3 (ruff + mypy)

---

## 14. NEXT STEPS (Q3 sớm)

1. Tạo bảng `public.shared_memory` trên Postgres `breakout-funnel-os-staging` (DDL trong AIOS spec)
2. Wire Voyage AI embedding cho MemoryLayer (1,290 vault file initial + ongoing)
3. Wire 4 MCP server (Vault, CDP, GHL, Sepay) bằng FastMCP framework
4. Implement BC3-Profile + BC3-Task (ProfileAgent + TaskAgent pattern Cerebrum)
5. Implement BC6 CSKH FAQ (AssistantAgent, no retrieval logic)
6. Bench Phase 1 (no shared) vs Phase 2 (shared) trên customer cohort thật
7. Implement Phong 05 Sepay+ZNS (event-driven, đã có service breakout-zns liên thông)

---

Last update: 2026-06-07. Anna review approve khi sẵn sàng.
