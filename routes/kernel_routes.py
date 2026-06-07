"""Internal control plane endpoints.

POST /kernel/execute   chạy 1 agent sync, trả AgentResult
GET  /kernel/status    health probe (dùng cho Railway healthcheck)
GET  /kernel/agents    liệt kê registered agents + autonomy level
"""
from __future__ import annotations

import os
import secrets as _secrets
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from kernel.base_agent import AgentResult, ExecutionContext
from kernel.scheduler import Scheduler

router = APIRouter()

# Sprint 7 auth: CAMAS_CRON_SECRET header verify for /kernel/execute
_CAMAS_CRON_SECRET = os.getenv("CAMAS_CRON_SECRET", "")


def _verify_cron_secret(x_camas_cron_secret: Optional[str]) -> None:
    """Verify auth header. If CAMAS_CRON_SECRET env empty → skip (backward compat dev).

    Production: env set, header must match. Otherwise 401.
    """
    if not _CAMAS_CRON_SECRET:
        return  # dev mode, no auth required
    if not x_camas_cron_secret:
        raise HTTPException(
            status_code=401,
            detail="Missing X-CAMAS-Cron-Secret header",
        )
    if not _secrets.compare_digest(x_camas_cron_secret, _CAMAS_CRON_SECRET):
        raise HTTPException(
            status_code=401,
            detail="Invalid X-CAMAS-Cron-Secret",
        )


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_name: str
    trigger_event: str
    user_id: Optional[str] = None
    venture_context: str = "all"
    payload: dict[str, Any] = Field(default_factory=dict)
    run_id: Optional[str] = None


def _scheduler(request: Request) -> Scheduler:
    sched = getattr(request.app.state, "scheduler", None)
    if sched is None:
        raise HTTPException(status_code=503, detail="Scheduler chưa boot")
    return sched


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    sched = _scheduler(request)
    return {
        "service": "camas-kernel",
        "running": sched._running,
        "agents_registered": len(sched._agents),
    }


@router.get("/agents")
async def list_agents(request: Request) -> list[dict[str, str]]:
    sched = _scheduler(request)
    return sched.list_agents()


@router.post("/execute", response_model=AgentResult)
async def execute(
    request: Request,
    body: ExecuteRequest,
    x_camas_cron_secret: Optional[str] = Header(None, alias="x-camas-cron-secret"),
) -> AgentResult:
    _verify_cron_secret(x_camas_cron_secret)
    sched = _scheduler(request)
    ctx = ExecutionContext(
        run_id=body.run_id or str(uuid.uuid4()),
        user_id=body.user_id,
        venture_context=body.venture_context,
        trigger_event=body.trigger_event,
        payload=body.payload,
    )
    return await sched.execute(body.agent_name, ctx)
