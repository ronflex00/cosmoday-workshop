import asyncio

from fastapi import APIRouter, HTTPException, Request

from ..models.schemas import AIStatus, Alert, AlertCreate, Command, CommandResult, SentinelState, SensorTelemetry

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
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
    alert = request.app.state.store.add_alert(payload)
    request.app.state.sockets.broadcast(request.app.state.store.snapshot())
    request.app.state.mqtt.publish_alert(alert)
    return alert


@router.post("/api/v1/commands", response_model=CommandResult)
async def command(payload: Command, request: Request):
    published = await asyncio.to_thread(request.app.state.mqtt.publish_command, payload)
    if not published:
        raise HTTPException(status_code=503, detail="MQTT command publication unavailable")
    return CommandResult(command=payload)
