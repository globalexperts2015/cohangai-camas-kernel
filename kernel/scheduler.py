"""Scheduler inspired by AIOS FIFOScheduler + Cerebrum auto_inject/auto_extract.

Postgres LISTEN/NOTIFY is the production scheduler (replace polling 30 min).
Hiện scaffold dùng asyncio.Queue cho 4 lane (llm, memory, tool, storage).
Q3 thay implementation drain loop bằng asyncpg LISTEN/NOTIFY.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from kernel.base_agent import AgentResult, BaseBC, ExecutionContext
from kernel.compliance_gate import ComplianceGate, ComplianceVerdict
from kernel.escalation import EscalationService
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer, MemoryRecord
from kernel.tool_layer import ToolLayer
from kernel.voice_gate import VoiceGate, VoiceVerdict

log = logging.getLogger("camas.scheduler")


class SchedulerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_batch_interval_ms: int = 500
    memory_batch_interval_ms: int = 0
    tool_batch_interval_ms: int = 0
    storage_batch_interval_ms: int = 0
    max_workers: int = 32


class Scheduler:
    """Central dispatcher.

    Pipeline cho mỗi execute(ctx, agent):
        1. auto_inject memory vào ctx.injected_memories
        2. agent.execute(ctx) → result
        3. Nếu result.publish_target: chạy VoiceGate + ComplianceGate hook
        4. auto_extract result.emitted_memories vào shared memory
        5. Nếu result.escalation_required: EscalationService.notify
    """

    def __init__(
        self,
        config: Optional[SchedulerConfig] = None,
        memory: Optional[MemoryLayer] = None,
        tools: Optional[ToolLayer] = None,
        llm: Optional[LLMLayer] = None,
        voice_gate: Optional[VoiceGate] = None,
        compliance_gate: Optional[ComplianceGate] = None,
        escalation: Optional[EscalationService] = None,
    ) -> None:
        self.config = config or SchedulerConfig()
        self.memory = memory or MemoryLayer()
        self.tools = tools or ToolLayer()
        self.llm = llm or LLMLayer()
        self.voice_gate = voice_gate or VoiceGate(llm=self.llm)
        self.compliance_gate = compliance_gate or ComplianceGate(llm=self.llm)
        self.escalation = escalation or EscalationService()

        self._agents: dict[str, BaseBC] = {}
        self._running = False
        self._lanes: dict[str, asyncio.Queue[tuple[ExecutionContext, BaseBC]]] = {
            "llm": asyncio.Queue(),
            "memory": asyncio.Queue(),
            "tool": asyncio.Queue(),
            "storage": asyncio.Queue(),
        }
        self._workers: list[asyncio.Task[None]] = []

    def register(self, agent: BaseBC) -> None:
        if agent.name in self._agents:
            raise ValueError(f"Agent {agent.name} đã register")
        self._agents[agent.name] = agent
        log.info("Registered agent %s autonomy=%s", agent.name, agent.autonomy_level)

    def get(self, name: str) -> Optional[BaseBC]:
        return self._agents.get(name)

    def list_agents(self) -> list[dict[str, str]]:
        return [
            {
                "name": a.name,
                "scope": a.scope,
                "autonomy": a.autonomy_level.value,
                "escalate_to": a.escalate_to.value,
            }
            for a in self._agents.values()
        ]

    async def start(self) -> None:
        """Boot lanes. Q3 thay bằng asyncpg LISTEN/NOTIFY loop."""
        if self._running:
            return
        self._running = True
        log.info("Scheduler boot %d lanes", len(self._lanes))

    async def stop(self) -> None:
        self._running = False
        for w in self._workers:
            w.cancel()
        self._workers.clear()

    async def execute(self, agent_name: str, ctx: ExecutionContext) -> AgentResult:
        """Trực tiếp gọi 1 agent qua full pipeline.

        Pattern dùng cho synchronous webhook (Sepay, GHL) cần result immediately.
        Cho cron / event-driven, dùng enqueue() async.
        """
        agent = self._agents.get(agent_name)
        if agent is None:
            return AgentResult(
                success=False,
                error=f"Agent {agent_name} chưa register",
            )

        ctx = await self._auto_inject(ctx)
        result = await agent.execute(ctx)
        # Sprint 8 instrumentation: surface ctx.injected_memories vào response
        if ctx.injected_memories:
            result.injected_memories = list(ctx.injected_memories)
        await self._gate_publish(agent, result, ctx)
        await self._auto_extract(agent, result, ctx)
        await self._maybe_escalate(agent, result, ctx)
        return result

    async def enqueue(
        self,
        agent_name: str,
        ctx: ExecutionContext,
        lane: str = "llm",
    ) -> str:
        """Async fire-and-forget. Returns task_id."""
        if lane not in self._lanes:
            raise ValueError(f"Lane {lane} không hợp lệ")
        agent = self._agents.get(agent_name)
        if agent is None:
            raise KeyError(f"Agent {agent_name} chưa register")
        task_id = str(uuid.uuid4())
        await self._lanes[lane].put((ctx, agent))
        log.info("Enqueued %s lane=%s task=%s", agent_name, lane, task_id)
        return task_id

    async def _auto_inject(self, ctx: ExecutionContext) -> ExecutionContext:
        """Cerebrum auto_inject hook, priority-ordered tier retrieval.

        Sprint 5 System-Wide Personalization (NAACL 2025 Cerebrum):
        Thay vì 1 generic semantic search, inject 4 tier ưu tiên:
            Tier 1 Profile (k=1, customer_id) - long-term identity
            Tier 2 Task (k=3, customer_id, 14 ngày) - short-term goal state
            Tier 3 Conversation (k=5, customer_id, 30 ngày) - recent interaction
            Tier 4 Canonical (k=8, venture) - pricing/policy/schedule/brand facts

        Consumer agent đọc Profile + Task pre-processed thay vì re-analyze, giảm
        token + latency 60-70%. Graceful degrade từng tier độc lập.
        """
        if not self.memory.ready:
            return ctx

        # Parse customer_id (int) từ ctx.user_id nếu numeric
        customer_id: Optional[int] = None
        if ctx.user_id and ctx.user_id.isdigit():
            customer_id = int(ctx.user_id)

        venture = ctx.venture_context if ctx.venture_context != "all" else None

        payload_content = ""
        if ctx.payload:
            raw = ctx.payload.get("content", "")
            if isinstance(raw, str):
                payload_content = raw[:500]
        query = f"{ctx.trigger_event} {payload_content}".strip() or ctx.trigger_event

        # Sprint 8 parallelize: 4 tier chạy song song qua asyncio.gather,
        # cắt ~75% overhead so với serial. Mỗi tier wrap try/except riêng.

        async def _tier_profile() -> Optional[dict[str, Any]]:
            if customer_id is None:
                return None
            try:
                # Sprint 8 bypass threshold: Profile per customer_id luôn relevant
                rows = await self.memory.retrieve(
                    query=query, k=1, category="profile", customer_id=customer_id,
                    relevance_threshold_override=2.0,
                )
                if not rows:
                    return None
                nl = await self.memory.to_natural_language(rows)
                if not nl:
                    return None
                return {"source": "profile", "content": nl, "count": len(rows)}
            except Exception as exc:  # noqa: BLE001
                log.warning("auto_inject profile fail: %r", exc)
                return None

        async def _tier_task() -> Optional[dict[str, Any]]:
            if customer_id is None:
                return None
            try:
                # Sprint 8 bypass threshold: Task per customer_id luôn relevant
                rows = await self.memory.retrieve(
                    query=query, k=3, category="task",
                    customer_id=customer_id, max_age_days=14,
                    relevance_threshold_override=2.0,
                )
                if not rows:
                    return None
                nl = await self.memory.to_natural_language(rows)
                if not nl:
                    return None
                return {"source": "task", "content": nl, "count": len(rows)}
            except Exception as exc:  # noqa: BLE001
                log.warning("auto_inject task fail: %r", exc)
                return None

        async def _tier_conversation() -> Optional[dict[str, Any]]:
            if customer_id is None:
                return None
            try:
                rows = await self.memory.retrieve(
                    query=query, k=5, category="conversation",
                    customer_id=customer_id, max_age_days=30,
                )
                if not rows:
                    return None
                nl = await self.memory.to_natural_language(rows)
                if not nl:
                    return None
                return {"source": "conversation", "content": nl, "count": len(rows)}
            except Exception as exc:  # noqa: BLE001
                log.warning("auto_inject conversation fail: %r", exc)
                return None

        async def _tier_canonical() -> Optional[dict[str, Any]]:
            try:
                rows = await self.memory.retrieve(
                    query=query, k=10,
                    categories=[
                        "pricing", "policy", "schedule", "brand", "bio",
                        "audience", "target", "compliance_audit",
                    ],
                    venture=venture,
                )
                if not rows:
                    return None
                nl = await self.memory.to_natural_language(rows)
                if not nl:
                    return None
                return {"source": "canonical", "content": nl, "count": len(rows)}
            except Exception as exc:  # noqa: BLE001
                log.warning("auto_inject canonical fail: %r", exc)
                return None

        results = await asyncio.gather(
            _tier_profile(), _tier_task(), _tier_conversation(), _tier_canonical(),
            return_exceptions=False,
        )
        injected_groups: list[dict[str, Any]] = [r for r in results if r is not None]

        if not injected_groups:
            return ctx

        return ctx.model_copy(update={"injected_memories": injected_groups})

    async def _auto_extract(
        self,
        agent: BaseBC,
        result: AgentResult,
        ctx: ExecutionContext,
    ) -> None:
        """Lưu emitted_memories vào public.agent_memory.

        Build MemoryRecord từ shape BC2 emit (content_summary + keywords + tags + venture).
        Graceful degrade nếu Voyage/Postgres lỗi.
        """
        if not self.memory.ready or not result.emitted_memories:
            return

        records: list[MemoryRecord] = []
        customer_id: Optional[int] = None
        if ctx.user_id and ctx.user_id.isdigit():
            customer_id = int(ctx.user_id)

        default_venture = (
            ctx.venture_context if ctx.venture_context != "all" else None
        )

        for emitted in result.emitted_memories:
            try:
                content = (
                    emitted.get("content_summary")
                    or emitted.get("content")
                    or ""
                )
                if not content.strip():
                    continue
                record = MemoryRecord(
                    agent_name=emitted.get("agent_name") or agent.name,
                    content=content,
                    keywords=list(emitted.get("keywords") or []),
                    tags=list(emitted.get("tags") or []),
                    venture=emitted.get("venture") or default_venture,
                    customer_id=customer_id,
                    category=emitted.get("category"),
                    context=emitted.get("context") or ctx.trigger_event,
                )
                records.append(record)
            except Exception as exc:  # noqa: BLE001
                log.warning("auto_extract build record fail: %r", exc)

        if not records:
            return

        try:
            await self.memory.store_many(records)
        except Exception as exc:  # noqa: BLE001
            log.warning("auto_extract store_many fail: %r", exc)

    async def _gate_publish(
        self,
        agent: BaseBC,
        result: AgentResult,
        ctx: ExecutionContext,
    ) -> None:
        """BC2 Voice + BC9 Compliance hook chạy pre-publish.

        Conflict resolution per Constitution Section E: BC9 BLOCK thắng BC2 APPROVE.
        """
        if result.publish_target is None or not result.success:
            return

        voice_verdict: VoiceVerdict = VoiceVerdict.SKIP
        compliance_verdict: ComplianceVerdict = ComplianceVerdict.SKIP
        if agent.requires_voice_gate and result.output_text:
            voice_verdict = await self.voice_gate.review(
                text=result.output_text,
                venture_context=ctx.venture_context,
            )
        if agent.requires_compliance_gate and result.output_text:
            compliance_verdict = await self.compliance_gate.review(
                text=result.output_text,
                venture_context=ctx.venture_context,
            )

        if compliance_verdict == ComplianceVerdict.BLOCK:
            result.success = False
            result.error = "BC9 Compliance BLOCK"
            result.output_text = "BLOCKED by BC9"
            result.escalation_required = True
            result.escalation_reason = "compliance_block"
            return
        if voice_verdict == VoiceVerdict.REJECT:
            result.success = False
            result.error = "BC2 Voice REJECT"
            result.escalation_required = True
            result.escalation_reason = "voice_reject"

    async def _maybe_escalate(
        self,
        agent: BaseBC,
        result: AgentResult,
        ctx: ExecutionContext,
    ) -> None:
        if not result.escalation_required:
            return
        try:
            await self.escalation.notify(
                agent_name=agent.name,
                autonomy_level=agent.autonomy_level,
                reason=result.escalation_reason or "unknown",
                ctx_run_id=ctx.run_id,
                summary=result.error or result.output_text or "",
            )
        except NotImplementedError:
            log.warning("Escalation notify chưa wire, agent=%s", agent.name)
