# CAMAS Kernel Local Setup

## Cerebrum SDK install

### Yêu cầu
- Python 3.10 hoặc 3.11 (Cerebrum cần `>=3.10,<3.12`)
- HDF5 system library (cho dependency `tables`)
- macOS: Homebrew

### Bước cài đặt (đã thực hiện 2026-06-07)

```bash
# 1. Install Python 3.11 (nếu chưa có)
brew install python@3.11

# 2. Install HDF5 dependency
brew install hdf5

# 3. Tạo venv tại cohangai/
cd "/Users/mac/Documents/ANNA SECOND BRAIN/cohangai"
/opt/homebrew/bin/python3.11 -m venv .venv

# 4. Upgrade pip
.venv/bin/pip install --upgrade pip

# 5. Install Cerebrum SDK (PyPI name là `aios-agent-sdk`, KHÔNG phải `cerebrum`)
.venv/bin/pip install aios-agent-sdk
```

### Gotcha quan trọng

| Vấn đề | Nguyên nhân | Giải pháp |
|---|---|---|
| `pip install cerebrum` chạy thành công, import báo SyntaxError print | PyPI có package cũ tên `cerebrum` (Python 2) | Phải dùng tên thật `aios-agent-sdk` |
| Build fail HDF5 not found | `tables` dependency cần libhdf5 | `brew install hdf5` trước |
| Python 3.9 system không hỗ trợ | Cerebrum yêu cầu 3.10-3.11 | Install Python 3.11 qua Homebrew |

### Verify install

```bash
.venv/bin/pip show aios-agent-sdk
# Expected: Name: aios-agent-sdk, Version: 0.0.3
```

```bash
.venv/bin/python -c "import cerebrum; from cerebrum import Cerebrum, Config; print('OK')"
# Expected: OK
```

### Cấu trúc module

Cerebrum module exports (sau khi install):

- `Cerebrum` — main agent class
- `Config` — agent config dataclass
- `client` — HTTP client tới AIOS kernel
- `config` — config loader
- `llm` — LLM layer (Claude/OpenAI/Ollama backend)
- `memory` — Memory layer
- `overrides` — runtime overrides
- `storage` — storage layer
- `tool` — tool registry + MCP client

### Liên kết
- Spec gốc: `cohangai/aios/cerebrum-docs-deep-dive.md`
- Pattern adopt: `cohangai/aios/cerebrum-research-comparison.md`
- Architecture: `cohangai/aios/cohangai-multi-agent-system-design.md`
- Source repo: `raw/git/Cerebrum-main/`
