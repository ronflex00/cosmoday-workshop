"""Single-writer state: called only from FastAPI's asyncio event loop."""

import logging
from collections import deque
from datetime import datetime, timezone

from pydantic import ValidationError

from ..models.schemas import (
    ANOMALY_TOPIC, TELEMETRY_TOPIC, VISION_TOPIC, Alert, AlertCreate, AnomalyResult,
    SentinelState, SensorTelemetry, SystemStatus, VisionResult,
)
from .alerts import AlertsService

logger = logging.getLogger("MQTT")
SCHEMAS = {TELEMETRY_TOPIC: SensorTelemetry, VISION_TOPIC: VisionResult,
           ANOMALY_TOPIC: AnomalyResult}


class StateService:
    def __init__(self, history_limit: int = 120):
        self.telemetry = None
        self.vision = None
        self.anomaly = None
        self.system = SystemStatus()
        self.history = deque(maxlen=history_limit)
        self.anomaly_history = deque(maxlen=history_limit)
        self.alerts = AlertsService()

    def set_mqtt_connected(self, connected: bool) -> bool:
        if connected == self.system.mqtt_connected:
            return False
        now = datetime.now(timezone.utc)
        self.system = SystemStatus(mqtt_connected=connected,
                                   last_update=now)
        self.alerts.add(AlertCreate(ts=now, type="SYSTEM",
                                   severity="info" if connected else "warning",
                                   message="MQTT connected" if connected else "MQTT disconnected"))
        return True

    def add_alert(self, payload: AlertCreate) -> Alert:
        alert = self.alerts.add(payload)
        self.system = SystemStatus(mqtt_connected=self.system.mqtt_connected,
                                   last_update=datetime.now(timezone.utc))
        return alert

    def apply_message(self, topic: str, payload: bytes) -> bool:
        schema = SCHEMAS.get(topic)
        if schema is None:
            return False
        if len(payload) > 16384:
            logger.warning("Ignoring oversized payload on %s", topic)
            return False
        try:
            message = schema.model_validate_json(payload)
        except ValidationError as exc:
            locations = [".".join(map(str, error["loc"])) or "JSON"
                         for error in exc.errors(include_input=False, include_url=False)]
            logger.warning("Ignoring invalid payload on %s (%s)", topic, ", ".join(locations))
            return False
        if topic == TELEMETRY_TOPIC:
            self.telemetry = message
            self.history.append(message)
        elif topic == VISION_TOPIC:
            if message.person_detected and not (self.vision and self.vision.person_detected):
                self.alerts.add(AlertCreate(ts=message.ts, type="INTRUSION", severity="critical",
                                           message="Human presence detected"))
            self.vision = message
        else:
            if message.ready and message.anomaly and not (self.anomaly and self.anomaly.anomaly):
                self.alerts.add(AlertCreate(ts=message.ts, type="ENVIRONMENTAL_ANOMALY",
                                           severity="warning", message="Environmental anomaly detected"))
            self.anomaly = message
            self.anomaly_history.append(message)
        self.system = SystemStatus(mqtt_connected=self.system.mqtt_connected,
                                   last_update=datetime.now(timezone.utc))
        return True

    def snapshot(self) -> SentinelState:
        return SentinelState(telemetry=self.telemetry, vision=self.vision,
                             anomaly=self.anomaly, system=self.system,
                             history=list(self.history),
                             anomaly_history=list(self.anomaly_history),
                             alerts=self.alerts.recent())
