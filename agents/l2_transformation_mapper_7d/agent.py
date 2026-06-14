"""L2.3 Transformation Mapper, Trợ Lý AI Thấu Khách (v2 B2 framework).

Production v2 sau Buổi 2 K2 (10/6/2026), refactored để match phương pháp dạy trong Buổi 2:
1. Ba việc khách MUA sản phẩm để đạt (Chức năng + Cảm xúc + Xã hội)
2. Top 3 nỗi đau với Pain Scale 1-10 + khoảng giá tương ứng
3. Phiên bản mới của khách (Từ X trở thành Y)
4. Sản phẩm đề xuất theo công thức Pain + Phiên bản mới + Năng lực lõi founder

Trigger event: cohort.transformation_map
Input: customer_persona (mô tả 1 khách hàng cụ thể)
Output: 4 phần như trên, markdown-rendered cho dashboard.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer

log = logging.getLogger("camas.l2_transformation_mapper_7d")

EXPECTED_EVENTS = {"cohort.transformation_map"}

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 5000
DEFAULT_TIMEOUT = 120.0


SUBMIT_TRANSFORMATION_TOOL = {
    "name": "submit_transformation_7d",
    "description": "Submit Trợ Lý AI Thấu Khách output (B2 framework) cho student",
    "input_schema": {
        "type": "object",
        "properties": {
            "student_id": {"type": "string"},
            "venture": {"type": "string"},
            "customer_persona": {
                "type": "string",
                "description": "Tóm tắt persona khách hàng theo input student",
            },
            "three_jobs_functional": {
                "type": "string",
                "description": "Việc CHỨC NĂNG: khách cần làm gì cụ thể (nội dung 1-3 câu, cụ thể, không generic)",
            },
            "three_jobs_emotional": {
                "type": "string",
                "description": "Việc CẢM XÚC: khách muốn cảm thấy thế nào (1-3 câu, cụ thể về cảm giác)",
            },
            "three_jobs_social": {
                "type": "string",
                "description": "Việc XÃ HỘI: khách muốn được người khác nhìn nhận thế nào (1-3 câu)",
            },
            "top_pain_1_description": {
                "type": "string",
                "description": "Nỗi đau số 1, mô tả cụ thể cảm giác và tình huống",
            },
            "top_pain_1_scale": {
                "type": "integer",
                "description": "Pain Scale 1-10 cho nỗi đau số 1 (7-10 là pain mạnh đủ để bán)",
                "minimum": 1,
                "maximum": 10,
            },
            "top_pain_1_price_range": {
                "type": "string",
                "description": "Khoảng giá khách sẵn sàng trả cho nỗi đau này (vd: '3-6 triệu VND')",
            },
            "top_pain_2_description": {"type": "string"},
            "top_pain_2_scale": {"type": "integer", "minimum": 1, "maximum": 10},
            "top_pain_2_price_range": {"type": "string"},
            "top_pain_3_description": {"type": "string"},
            "top_pain_3_scale": {"type": "integer", "minimum": 1, "maximum": 10},
            "top_pain_3_price_range": {"type": "string"},
            "new_version_from": {
                "type": "string",
                "description": "Phiên bản CŨ của khách (Từ X), mô tả cảm giác + vị thế hiện tại",
            },
            "new_version_to": {
                "type": "string",
                "description": "Phiên bản MỚI của khách (Trở thành Y), mô tả cảm giác + vị thế khao khát",
            },
            "recommended_product_1": {
                "type": "string",
                "description": "Sản phẩm đề xuất số 1: 1 câu mô tả + giải quyết pain nào + tạo phiên bản mới ra sao",
            },
            "recommended_product_2": {"type": "string"},
            "recommended_product_3": {"type": "string"},
            "primary_dream_outcome": {
                "type": "string",
                "description": "Dream outcome cụ thể + có số + có timeline (Hormozi style)",
            },
            "transformation_arc_summary": {
                "type": "string",
                "description": "1-paragraph narrative: Phiên bản cũ → Bridge (offer của bạn) → Phiên bản mới",
            },
            "markdown_visual_map": {
                "type": "string",
                "description": "Markdown đầy đủ 4 phần (3 jobs + Top 3 pains + Phiên bản mới + 3 sản phẩm) cho dashboard render",
            },
            "summary": {"type": "string", "description": "Tóm tắt 1 câu cho memory log"},
        },
        "required": [
            "student_id",
            "venture",
            "customer_persona",
            "three_jobs_functional",
            "three_jobs_emotional",
            "three_jobs_social",
            "top_pain_1_description",
            "top_pain_1_scale",
            "top_pain_1_price_range",
            "top_pain_2_description",
            "top_pain_2_scale",
            "top_pain_2_price_range",
            "top_pain_3_description",
            "top_pain_3_scale",
            "top_pain_3_price_range",
            "new_version_from",
            "new_version_to",
            "recommended_product_1",
            "recommended_product_2",
            "recommended_product_3",
            "primary_dream_outcome",
            "transformation_arc_summary",
            "markdown_visual_map",
            "summary",
        ],
    },
}


def build_transformation_prompt(student_id: str, customer_persona: str, vision_context: dict, niche_context: dict) -> str:
    return f"""Bạn là Trợ Lý AI Thấu Khách của Đào Thị Hằng (Anna), apply phương pháp Buổi 2 Breakout K2 (BÁN CÁI GÌ) version 2026-06-10.

Triết lý cốt lõi: KHÁCH HÀNG KHÔNG MUA SẢN PHẨM, HỌ MUA SỰ THOÁT KHỎI NỖI ĐAU CỦA CHÍNH HỌ. Khách trước, sản phẩm sau.

# Student
ID: {student_id}

# Mô tả khách hàng (input student)
{customer_persona}

# Vision context (nếu có)
{json.dumps(vision_context, ensure_ascii=False, indent=2)[:1000]}

# Niche context (nếu có)
{json.dumps(niche_context, ensure_ascii=False, indent=2)[:1000]}

# Task: Phân tích khách hàng theo 4 phần khung Buổi 2

## PHẦN 1: BA VIỆC KHÁCH MUA SẢN PHẨM ĐỂ ĐẠT

Khách hàng mua sản phẩm để đạt 3 nhóm kết quả:

### Việc CHỨC NĂNG (Functional Job)
Khách cần LÀM gì cụ thể. Đưa ra ĐÚNG 3 ý riêng biệt, mỗi ý 1 dòng bắt đầu bằng "- " (dash space).
Ví dụ format:
- Kiếm thêm 5 triệu mỗi tháng
- Có nguồn thu nhập thứ hai bên cạnh lương cứng
- Dạy con học bài hiệu quả hơn

### Việc CẢM XÚC (Emotional Job)
Khách muốn CẢM THẤY thế nào. Đưa ra ĐÚNG 3 ý riêng biệt, mỗi ý 1 dòng bắt đầu bằng "- ".
Ví dụ format:
- Tự tin về tài chính, không còn lo lắng mỗi đêm
- An toàn về tương lai, biết mình có năng lực kiếm tiền
- Tự hào về chính mình, làm chủ cuộc đời

### Việc XÃ HỘI (Social Job)
Khách muốn được NGƯỜI KHÁC NHÌN NHẬN thế nào. Đưa ra ĐÚNG 3 ý riêng biệt, mỗi ý 1 dòng bắt đầu bằng "- ".
Ví dụ format:
- Chuyên nghiệp trong mắt đồng nghiệp
- Có giá trị trong mắt sếp
- Tấm gương cho con cái

**Quy tắc format**: KHÔNG dùng dấu "..." để nối ý. Mỗi ý 1 bullet riêng để dễ đọc.
**Quy tắc vàng**: Khách trả tiền cho Cảm xúc và Xã hội, Chức năng chỉ là vỏ ngoài.

## PHẦN 2: TOP 3 NỖI ĐAU CỦA KHÁCH + PAIN SCALE 1-10

Liệt kê 3 nỗi đau lớn nhất của khách, mỗi nỗi đau:
- Mô tả cụ thể cảm giác + tình huống
- Chấm điểm Pain Scale 1-10
- Khoảng giá khách sẵn sàng trả

### Pain Scale tham chiếu:
- Mức 1: Khó chịu nhỏ, than vài câu rồi quên
- Mức 3: Bực mình rõ ràng nhưng chưa đủ động lực tìm giải pháp (giá: vài chục nghìn)
- Mức 5: Mất ngủ một đêm, lo lắng nhưng nghĩ tự xử được
- Mức 7: Lo lắng kéo dài một tuần, bắt đầu nghiên cứu phương án (giá: 1-3 triệu)
- Mức 8: Tìm giải pháp ngay trong đêm, phải hành động (giá: 3-8 triệu)
- Mức 10: Đau quá lớn, sẵn sàng cân nhắc mức đầu tư rất cao nếu tin giải pháp đúng (giá: 15-50 triệu+)

### Nguyên tắc:
- Pain mức 7+ mới đáng xây sản phẩm quanh nó
- Pain mức 3 trở xuống = khách không chịu trả → bỏ qua
- Giá tương ứng tỉ lệ thuận với mức pain

## PHẦN 3: PHIÊN BẢN MỚI CỦA KHÁCH

Khách không chỉ muốn giải pháp, khách muốn TRỞ THÀNH MỘT PHIÊN BẢN MỚI của chính họ.

Hoàn thành câu: Khách của bạn TỪ [phiên bản cũ với cảm giác + vị thế hiện tại] TRỞ THÀNH [phiên bản mới với cảm giác + vị thế khao khát].

Ví dụ:
- Từ một nhân viên văn phòng phụ thuộc một nguồn thu nhập, trở thành một solo founder có nhiều nguồn thu và làm chủ thời gian.
- Từ một người ngại nói tiếng Anh trước người nước ngoài, trở thành một người tự tin chủ trì cuộc họp với đối tác quốc tế.

Yêu cầu: cụ thể về cảm giác + vị thế xã hội + mối quan hệ với chính mình.

## PHẦN 4: BA SẢN PHẨM ĐỀ XUẤT

Công thức canonical: Sản phẩm = Giải quyết Top Pain (mức 7-10) + Tạo phiên bản mới + Dùng năng lực lõi của founder.

Đề xuất 3 ý tưởng sản phẩm cụ thể cho khách hàng này:
- Mỗi sản phẩm 1 câu mô tả ngắn gọn
- Liên kết rõ: sản phẩm này giải quyết Pain nào (1, 2, hay 3) + tạo phiên bản mới ra sao
- Sản phẩm phải bắt tay làm được trong vài tuần, không vaporware

## PHẦN 5: MARKDOWN VISUAL MAP

Output markdown đẹp cho dashboard, format như sau:

```markdown
## 🎯 Trợ Lý AI Thấu Khách

### 👤 Khách hàng của bạn
[customer_persona tóm tắt 2-3 câu]

### 💼 Ba việc khách mua sản phẩm để đạt

**Việc Chức năng (khách cần LÀM gì)**
[three_jobs_functional]

**Việc Cảm xúc (khách muốn CẢM thấy gì)**
[three_jobs_emotional]

**Việc Xã hội (khách muốn được NHÌN NHẬN ra sao)**
[three_jobs_social]

> 💡 **Khách trả tiền cho Cảm xúc và Xã hội. Chức năng chỉ là vỏ.**

### 🔥 Top 3 nỗi đau của khách
| # | Nỗi đau | Pain Scale | Khoảng giá |
|---|---|---|---|
| 1 | [top_pain_1_description] | **{{X}}/10** | [top_pain_1_price_range] |
| 2 | [top_pain_2_description] | **{{X}}/10** | [top_pain_2_price_range] |
| 3 | [top_pain_3_description] | **{{X}}/10** | [top_pain_3_price_range] |

> 💡 **Pain mức 7-10 mới là pain bán được.**

### 🌟 Phiên bản mới của khách
**Từ:** [new_version_from]
**Trở thành:** [new_version_to]

### 🚀 Ba sản phẩm đề xuất bạn có thể bắt tay làm ngay
1. [recommended_product_1]
2. [recommended_product_2]
3. [recommended_product_3]

### ✨ Dream Outcome
[primary_dream_outcome]

### 📖 Hành trình chuyển hoá
[transformation_arc_summary]
```

# Quality requirements
- KHÔNG generic ("better life"), MUST cụ thể với data từ persona input
- Tiếng Việt thuần (KHÔNG English thuật ngữ trừ khi đã thành term Việt như AI, online)
- KHÔNG dấu em-dash, dùng dấu phẩy hoặc xuống dòng
- KHÔNG emoji ngoài bảng visual map đã định sẵn
- Pain Scale phải có cơ sở (mô tả pain match với mức số)
- Sản phẩm đề xuất phải concrete + actionable, không vaporware
- Mọi metric phải có số hoặc timeline cụ thể

Output qua tool submit_transformation_7d, fill TẤT CẢ required fields.
"""


class L2TransformationMapper7D(BaseBC):
    """Trợ Lý AI Thấu Khách v2 (B2 framework 2026-06-10)."""

    name = "l2_transformation_mapper_7d"
    scope = "Trợ Lý AI Thấu Khách: phân tích 3 jobs + Pain Scale 1-10 + Phiên bản mới + 3 sản phẩm đề xuất theo phương pháp Buổi 2 K2"
    autonomy_level = AutonomyLevel.L1_AUTO
    escalate_to = EscalationTarget.NONE
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False

    def __init__(
        self,
        llm: LLMLayer,
        memory: MemoryLayer,
        model: str = DEFAULT_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.memory = memory
        self.model = model

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        event = ctx.trigger_event or ""
        if event not in EXPECTED_EVENTS:
            return AgentResult(
                success=False,
                output_text=f"{self.name} không xử lý event này",
                output_payload={
                    "trigger_event": event,
                    "supported": list(EXPECTED_EVENTS),
                },
            )

        payload = ctx.payload or {}
        student_id = payload.get("student_id", "unknown")
        customer_persona = payload.get("customer_persona", "").strip()
        vision_context = payload.get("vision_context", {})
        niche_context = payload.get("niche_context", {})

        if not customer_persona:
            return AgentResult(
                success=False,
                output_text="Missing customer_persona",
                output_payload={"error": "customer_persona empty"},
            )

        if not self.llm.ready:
            return AgentResult(
                success=False,
                output_text="LLM not ready",
                output_payload={"error": "LLM not ready"},
            )

        prompt = build_transformation_prompt(student_id, customer_persona, vision_context, niche_context)

        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[SUBMIT_TRANSFORMATION_TOOL],
                tool_choice={"type": "tool", "name": "submit_transformation_7d"},
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("l2_transformation_mapper LLM fail: %r", exc)
            return AgentResult(
                success=False,
                output_text=f"LLM fail: {exc}",
                output_payload={"error": str(exc)},
            )

        result = self._parse_response(response)
        if "error" in result:
            return AgentResult(success=False, output_text=result["error"], output_payload=result)

        dream = result.get("primary_dream_outcome", "")[:80]
        date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        summary = f"thau_khach_v2 student={student_id} dream='{dream}'"

        memory_entry = {
            "agent_name": self.name,
            "content_summary": json.dumps(result, ensure_ascii=False)[:800],
            "keywords": ["thau_khach_b2", "cohort_1", student_id, customer_persona[:50]],
            "tags": ["l2", "thau_khach", "b2_framework", "cohort_1", date_str],
            "venture": ctx.venture_context or "cohangai",
            "category": "profile",
            "context": f"cohort.transformation_map {date_str} student={student_id}",
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=result,
            emitted_memories=[memory_entry],
        )

    def _parse_response(self, response) -> dict:
        for block in response.content or []:
            if (
                getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == "submit_transformation_7d"
            ):
                return block.input or {}

        return {"error": "No tool_use response from LLM"}
