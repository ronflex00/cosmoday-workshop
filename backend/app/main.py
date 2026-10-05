"""Run from backend/: python -m app.main."""

import asyncio
import logging
from contextlib import asynccontextmanager
from queue import Empty, Queue
from threading import Event

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router
from .api.websocket import WebSocketManager, router as websocket_router
from .config import Settings
from .mqtt.client import MQTTClient, MQTTEvent
from .services.state import StateService

logger = logging.getLogger("API")


async def consume_events(events: Queue[MQTTEvent], store: StateService, stop: Event,
                         sockets: WebSocketManager, mqtt_client: MQTTClient) -> None:
    while not stop.is_set():
        try:
            event = await asyncio.to_thread(events.get, True, 0.2)
        except Empty:
            continue
        try:
            previous_alert = store.alerts.latest
            if event.topic is None:
                changed = store.set_mqtt_connected(event.payload)
            else:
                changed = store.apply_message(event.topic, event.payload)
            if changed:
                sockets.broadcast(store.snapshot())
                if store.alerts.latest is not previous_alert:
                    mqtt_client.publish_alert(store.alerts.latest)
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
        app.state.store = StateService(settings.history_limit)
        app.state.mqtt = MQTTClient(settings, events)
        app.state.sockets = WebSocketManager()
        consumer = asyncio.create_task(consume_events(events, app.state.store, stop,
                                                      app.state.sockets, app.state.mqtt))
        try:
            app.state.mqtt.start()
            yield
        finally:
            stop.set()
            try:
                await asyncio.to_thread(app.state.mqtt.stop)
            finally:
                await consumer
                await app.state.sockets.close()
                app.state.store.set_mqtt_connected(False)
                logger.info("Sentinel-X backend stopped")

    app = FastAPI(title="Sentinel-X API", version="0.1.0", lifespan=lifespan)
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
