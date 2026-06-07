"""External event ingestion.

POST /webhook/trigger  generic webhook dispatcher
                       payload đi qua scheduler.enqueue lane phù hợp

Sepay, GHL, Tally, Fathom, Zalo OA webhook đều route về đây với
trường source phân biệt. Q3 thêm signature verify per source.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from kernel.base_agent import ExecutionContext
from kernel.scheduler import Scheduler

router = APIRouter()


class TriggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(
        description="sepay | ghl | tally | fathom | zalo | wk | fb | telegram"
    )
    event_type: str = Field(description="Tên event, vd sepay.payment.success")
    target_agent: str = Field(description="Tên agent đăng ký trong scheduler")
    venture_context: str = "all"
    user_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    lane: str = Field(default="llm", description="llm | memory | tool | storage")


def _scheduler(request: Request) -> Scheduler:
    sched = getattr(request.app.state, "scheduler", None)
    if sched is None:
        raise HTTPException(status_code=503, detail="Scheduler chưa boot")
    return sched


@router.post("/trigger")
async def trigger(request: Request, body: TriggerRequest) -> dict[str, str]:
    sched = _scheduler(request)
    ctx = ExecutionContext(
        run_id=str(uuid.uuid4()),
        user_id=body.user_id,
        venture_context=body.venture_context,
        trigger_event=body.event_type,
        payload={"source": body.source, **body.payload},
    )
    try:
        task_id = await sched.enqueue(body.target_agent, ctx, lane=body.lane)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"task_id": task_id, "run_id": ctx.run_id, "status": "enqueued"}
