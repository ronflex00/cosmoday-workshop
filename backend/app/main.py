"""Run from backend/: python -m app.main."""

import asyncio
import logging
from contextlib import asynccontextmanager
from queue import Empty, Queue
from threading import Event
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from .api.routes import router
from .api.websocket import WebSocketManager, router as websocket_router
from .config import Settings
from .mqtt.client import MQTTClient, MQTTEvent
from .services.state import StateService
from .services.history import HistoryStore

logger = logging.getLogger("API")


async def consume_events(events: Queue[MQTTEvent], store: StateService, stop: Event,
                         sockets: WebSocketManager, mqtt_client: MQTTClient,
                         history: HistoryStore) -> None:
    while not stop.is_set() or not events.empty():
        try:
            event = await asyncio.to_thread(events.get, True, 0.2)
        except Empty:
            continue
        try:
            if event.topic is None:
                change = store.prepare_connection(event.payload)
            else:
                change = store.prepare_message(event.topic, event.payload)
            if change is not None:
                while True:
                    try:
                        await asyncio.wait_for(history.append(event.id, event.received_at, change), timeout=6)
                        break
                    except (SQLAlchemyError, OSError, TimeoutError):
                        if history.available:
                            logger.error("History database unavailable; holding the current event for retry")
                        history.available = False
                        if stop.is_set():
                            logger.error("Database still unavailable at shutdown; pending MQTT events could not be stored")
                            return
                        await asyncio.to_thread(stop.wait, 1)
                store.apply_change(change)
                sockets.broadcast(store.snapshot())
                if change.alert is not None:
                    mqtt_client.publish_alert(change.alert)
        except Exception:
            logger.exception("Cannot process MQTT event; skipping")
        finally:
            events.task_done()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
        logger.info("Sentinel-X backend starting")
        events = Queue(maxsize=128)
        stop = Event()
        history = HistoryStore(settings.database_url)
        app.state.history = history
        consumer = None
        mqtt_client = None
        try:
            try:
                await asyncio.wait_for(history.initialize(), timeout=10)
                app.state.store = StateService(settings.history_limit)
                await asyncio.wait_for(history.restore(app.state.store), timeout=10)
            except (SQLAlchemyError, OSError, TimeoutError):
                raise RuntimeError("Cannot initialize history database; check DATABASE_URL") from None
            mqtt_client = MQTTClient(settings, events)
            app.state.mqtt = mqtt_client
            app.state.sockets = WebSocketManager()
            consumer = asyncio.create_task(consume_events(events, app.state.store, stop,
                                                          app.state.sockets, mqtt_client, history))
            mqtt_client.start()
            yield
        finally:
            try:
                if mqtt_client is not None:
                    await asyncio.to_thread(mqtt_client.stop)
            finally:
                stop.set()
                try:
                    if consumer is not None:
                        await consumer
                        await app.state.sockets.close()
                        change = app.state.store.prepare_connection(False)
                        if change is not None:
                            try:
                                await asyncio.wait_for(history.append(str(uuid4()), datetime.now(timezone.utc), change), timeout=6)
                                app.state.store.apply_change(change)
                            except (SQLAlchemyError, OSError, TimeoutError):
                                logger.error("Could not store the final MQTT disconnection")
                finally:
                    await history.close()
                    logger.info("Sentinel-X backend stopped")

    app = FastAPI(title="Sentinel-X API", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    app.include_router(router)
    app.include_router(websocket_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=app.state.settings.api_host, port=app.state.settings.api_port)
