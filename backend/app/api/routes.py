import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from ..models.schemas import (AIStatus, Alert, AlertCreate, Command, CommandResult,
                              HistoryKind, HistoryPage, SentinelState, SensorTelemetry)

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    if not request.app.state.history.available:
        return JSONResponse(status_code=503, content={"status": "degraded", "database": "unavailable"})
    return {"status": "ok"}


@router.get("/api/v1/state", response_model=SentinelState)
async def state(request: Request):
    return request.app.state.store.snapshot()


@router.get("/api/v1/status", response_model=SentinelState)
async def status(request: Request):
    # docs/contracts.md defines this endpoint as the global state.
    return request.app.state.store.snapshot()


@router.get("/api/v1/sensors/latest", response_model=SensorTelemetry | None)
async def latest(request: Request):
    return request.app.state.store.telemetry


@router.get("/api/v1/ai/status", response_model=AIStatus)
async def ai_status(request: Request):
    store = request.app.state.store
    return AIStatus(vision=store.vision, anomaly=store.anomaly)


@router.get("/api/v1/alerts", response_model=list[Alert])
async def alerts(request: Request):
    return request.app.state.store.alerts.recent()


@router.post("/api/v1/alerts", response_model=Alert, status_code=201)
async def create_alert(payload: AlertCreate, request: Request):
    alert = request.app.state.store.alerts.make(payload)
    history = request.app.state.history
    try:
        await asyncio.wait_for(history.append_alert(alert), timeout=6)
    except (SQLAlchemyError, OSError, TimeoutError):
        history.available = False
        raise HTTPException(status_code=503, detail="History database unavailable") from None
    request.app.state.store.record_alert(alert)
    request.app.state.sockets.broadcast(request.app.state.store.snapshot())
    request.app.state.mqtt.publish_alert(alert)
    return alert


@router.post("/api/v1/commands", response_model=CommandResult)
async def command(payload: Command, request: Request):
    published = await request.app.state.alarm.manual(payload)
    if not published:
        raise HTTPException(status_code=503, detail="MQTT command publication or alarm ownership storage unavailable")
    return CommandResult(command=payload)


@router.get("/api/v1/history/{kind}", response_model=HistoryPage, tags=["History"])
async def historical_data(
    kind: HistoryKind, request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    before_id: int | None = Query(default=None, ge=1, le=9223372036854775807),
    start: datetime | None = Query(default=None, description="Inclusive sample timestamp, ISO-8601 with timezone"),
    end: datetime | None = Query(default=None, description="Inclusive sample timestamp, ISO-8601 with timezone"),
    device_id: str | None = Query(default=None, min_length=1, description="Telemetry only"),
):
    for value in (start, end):
        if value is not None and value.tzinfo is None:
            raise HTTPException(status_code=422, detail="start/end must include a timezone")
    if start is not None:
        start = start.astimezone(timezone.utc)
    if end is not None:
        end = end.astimezone(timezone.utc)
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=422, detail="start must be before or equal to end")
    if device_id is not None and kind != "telemetry":
        raise HTTPException(status_code=422, detail="device_id is supported only for telemetry history")
    history = request.app.state.history
    try:
        return await asyncio.wait_for(history.page(kind, limit=limit, before_id=before_id,
                                                   start=start, end=end, device_id=device_id), timeout=6)
    except (SQLAlchemyError, OSError, TimeoutError):
        history.available = False
        raise HTTPException(status_code=503, detail="History database unavailable") from None
