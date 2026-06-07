"""Verify BaseBC + Scheduler contract.

Pytest async tests. Không hit network, không cần DB.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from agents._example_agent import ExampleEchoAgent
from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.scheduler import Scheduler


def _make_ctx(event: str = "test.ping") -> ExecutionContext:
    return ExecutionContext(
        run_id=str(uuid.uuid4()),
        user_id="anna_test",
        venture_context="cohangai",
        trigger_event=event,
        payload={"hello": "world"},
    )


def test_basebc_requires_name_and_scope() -> None:
    class Broken(BaseBC):
        async def run(self, ctx: ExecutionContext) -> AgentResult:
            return AgentResult(success=True)

    with pytest.raises(ValueError):
        Broken()


def test_example_agent_metadata() -> None:
    agent = ExampleEchoAgent()
    assert agent.name == "example_echo"
    assert agent.autonomy_level == AutonomyLevel.L1_AUTO
    assert agent.escalate_to == EscalationTarget.NONE
    assert agent.requires_voice_gate is False
    assert agent.requires_compliance_gate is False


@pytest.mark.asyncio
async def test_example_agent_run_returns_echo() -> None:
    agent = ExampleEchoAgent()
    ctx = _make_ctx("test.echo")
    result = await agent.execute(ctx)
    assert result.success is True
    assert "test.echo" in (result.output_text or "")
    assert result.output_payload == {"echo": {"hello": "world"}}


@pytest.mark.asyncio
async def test_scheduler_register_and_execute() -> None:
    sched = Scheduler()
    agent = ExampleEchoAgent()
    sched.register(agent)
    assert sched.get("example_echo") is agent
    listing = sched.list_agents()
    assert any(a["name"] == "example_echo" for a in listing)

    ctx = _make_ctx("scheduler.test")
    result = await sched.execute("example_echo", ctx)
    assert result.success is True
    assert "scheduler.test" in (result.output_text or "")


@pytest.mark.asyncio
async def test_scheduler_returns_error_for_missing_agent() -> None:
    sched = Scheduler()
    result = await sched.execute("ghost_agent", _make_ctx())
    assert result.success is False
    assert result.error is not None
    assert "ghost_agent" in result.error


@pytest.mark.asyncio
async def test_scheduler_double_register_raises() -> None:
    sched = Scheduler()
    sched.register(ExampleEchoAgent())
    with pytest.raises(ValueError):
        sched.register(ExampleEchoAgent())


@pytest.mark.asyncio
async def test_scheduler_enqueue_returns_task_id() -> None:
    sched = Scheduler()
    sched.register(ExampleEchoAgent())
    task_id = await sched.enqueue("example_echo", _make_ctx(), lane="llm")
    assert isinstance(task_id, str)
    assert len(task_id) > 0


@pytest.mark.asyncio
async def test_crashing_agent_escalates() -> None:
    class Boom(BaseBC):
        name = "boom"
        scope = "force exception"
        autonomy_level = AutonomyLevel.L3_PROPOSE
        escalate_to = EscalationTarget.TELEGRAM_OPS

        async def run(self, ctx: ExecutionContext) -> AgentResult:
            raise RuntimeError("boom!")

    sched = Scheduler()
    sched.register(Boom())
    result = await sched.execute("boom", _make_ctx())
    assert result.success is False
    assert result.escalation_required is True
    assert result.escalation_reason == "unhandled_exception"


if __name__ == "__main__":
    asyncio.run(test_example_agent_run_returns_echo())
