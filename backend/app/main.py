"""Run from backend/: python -m app.main."""

import asyncio
import logging
from contextlib import asynccontextmanager
from queue import Empty, Queue
from threading import Event
from uuid import uuid4
from datetime import datetime, timezone
from dataclasses import replace

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from .api.routes import router
from .api.websocket import WebSocketManager, router as websocket_router
from .config import Settings
from .models.schemas import ALERTS_TOPIC, ANOMALY_TOPIC
from .mqtt.client import MQTTClient, MQTTEvent
from .services.state import StateService
from .services.history import HistoryStore
from .services.environment import EnvironmentIntelligence, FRESH_SECONDS, FUTURE_SECONDS
from .services.alarm import AlarmOrchestrator

logger = logging.getLogger("API")


async def consume_events(events: Queue[MQTTEvent], store: StateService, stop: Event,
                         sockets: WebSocketManager, mqtt_client: MQTTClient,
                         history: HistoryStore, environment: EnvironmentIntelligence,
                         alarm: AlarmOrchestrator) -> None:
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
                decision = None
                alarm_generation = alarm.generation
                if change.topic == ANOMALY_TOPIC:
                    if (environment.state["critical_active"]
                            and change.message.model == "isolation_forest"
                            and change.alert is not None
                            and change.alert.type == "ENVIRONMENTAL_ANOMALY"
                            and change.alert.severity == "warning"):
                        # Preserve the first warning, then group intermittent
                        # positives into the latched critical episode until its
                        # two fresh normal results rearm the interpretation.
                        change = replace(change, alert=None)
                    transport_connected = (mqtt_client.connected and (event.generation is None
                        or event.generation == mqtt_client.generation))
                    decision = environment.prepare(change.message, connected=store.system.mqtt_connected
                                                   and transport_connected)
                elif change.topic is None and not change.message:
                    decision = environment.prepare_disconnect()
                if decision is not None:
                    change = replace(change, environment_state=decision.state,
                                     additional_alerts=(decision.alert,) if decision.alert else ())
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
                if decision is not None:
                    environment.commit(decision)
                sockets.broadcast(store.snapshot())
                if change.alert is not None and change.topic != ALERTS_TOPIC:
                    mqtt_client.publish_alert(change.alert)
                for alert in change.additional_alerts:
                    mqtt_client.publish_alert(alert)
                if change.topic is None:
                    await alarm.set_connected(change.message)
                elif decision is not None and decision.alert is not None:
                    sample_time = change.message.ts
                    generation = event.generation
                    def still_eligible(sample_time=sample_time, generation=generation):
                        age = (datetime.now(timezone.utc) - sample_time).total_seconds()
                        return (-FUTURE_SECONDS <= age <= FRESH_SECONDS and mqtt_client.connected
                                and (generation is None or generation == mqtt_client.generation))
                    alarm.critical(still_eligible, generation=alarm_generation)
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
        alarm = None
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
            saved_episode = await asyncio.wait_for(history.environment_state("episode"), timeout=6)
            saved_manual = await asyncio.wait_for(history.environment_state("manual"), timeout=6)
            environment = EnvironmentIntelligence.restore(list(app.state.store.anomaly_history), saved_episode)
            app.state.environment = environment
            alarm = AlarmOrchestrator(mqtt_client.publish_command, enabled=settings.ai_auto_alarm,
                                      saved=saved_manual, persist=history.save_alarm_state,
                                      require_manual=app.state.store.system.last_update is not None)
            app.state.alarm = alarm
            consumer = asyncio.create_task(consume_events(events, app.state.store, stop,
                                                          app.state.sockets, mqtt_client, history,
                                                          environment, alarm))
            mqtt_client.start()
            yield
        finally:
            try:
                if alarm is not None:
                    await alarm.close()
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
