"""Push the latest state without letting a slow dashboard block MQTT ingestion."""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..models.schemas import SentinelState

logger = logging.getLogger("WS")
router = APIRouter()


class WebSocketManager:
    def __init__(self, send_timeout: float = 2.0):
        self._clients: dict[WebSocket, asyncio.Queue[str]] = {}
        self.send_timeout = send_timeout

    @staticmethod
    def _encode(state: SentinelState) -> str:
        return '{"type":"state","data":' + state.model_dump_json() + '}'

    def connect(self, websocket: WebSocket, state: SentinelState) -> asyncio.Queue[str]:
        updates: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        self._clients[websocket] = updates
        updates.put_nowait(self._encode(state))
        logger.info("Client connected (%s total)", len(self._clients))
        return updates

    def disconnect(self, websocket: WebSocket) -> None:
        if self._clients.pop(websocket, None) is not None:
            logger.info("Client disconnected (%s remaining)", len(self._clients))

    def broadcast(self, state: SentinelState) -> None:
        if not self._clients:
            return
        payload = self._encode(state)
        for updates in self._clients.values():
            if updates.full():
                updates.get_nowait()
            updates.put_nowait(payload)

    async def send_updates(self, websocket: WebSocket, updates: asyncio.Queue[str]) -> None:
        try:
            while True:
                payload = await updates.get()
                await asyncio.wait_for(websocket.send_text(payload), timeout=self.send_timeout)
        except Exception:
            logger.warning("Cannot send state; closing client")
            try:
                await asyncio.wait_for(websocket.close(code=1013), timeout=self.send_timeout)
            except Exception:
                pass
        finally:
            self.disconnect(websocket)

    async def close(self) -> None:
        clients = list(self._clients)
        await asyncio.gather(*(asyncio.wait_for(client.close(code=1001), self.send_timeout)
                               for client in clients), return_exceptions=True)
        for client in clients:
            self.disconnect(client)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    if origin is not None and origin not in websocket.app.state.settings.cors_origins:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    manager = websocket.app.state.sockets
    # Snapshot and registration have no await between them, avoiding a startup gap.
    updates = manager.connect(websocket, websocket.app.state.store.snapshot())
    sender = asyncio.create_task(manager.send_updates(websocket, updates))
    try:
        while True:
            event = await websocket.receive()
            if event["type"] == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
