"""Prepare updates before persistence; apply the live state after the DB commit."""

import logging
from collections import deque
from dataclasses import dataclass
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


@dataclass(frozen=True)
class StateChange:
    topic: str | None
    message: SensorTelemetry | VisionResult | AnomalyResult | bool
    alert: Alert | None


class StateService:
    def __init__(self, history_limit: int = 120):
        self.telemetry = None
        self.vision = None
        self.anomaly = None
        self.system = SystemStatus()
        self.history = deque(maxlen=history_limit)
        self.anomaly_history = deque(maxlen=history_limit)
        self.alerts = AlertsService()

    def prepare_connection(self, connected: bool) -> StateChange | None:
        if connected == self.system.mqtt_connected:
            return None
        alert = self.alerts.make(AlertCreate(ts=datetime.now(timezone.utc), type="SYSTEM",
                                            severity="info" if connected else "warning",
                                            message="MQTT connected" if connected else "MQTT disconnected"))
        return StateChange(None, connected, alert)

    def set_mqtt_connected(self, connected: bool) -> bool:
        change = self.prepare_connection(connected)
        if change is None:
            return False
        self.apply_change(change)
        return True

    def add_alert(self, payload: AlertCreate) -> Alert:
        return self.record_alert(self.alerts.make(payload))

    def record_alert(self, alert: Alert) -> Alert:
        self.alerts.record(alert)
        self.system = SystemStatus(mqtt_connected=self.system.mqtt_connected,
                                   last_update=datetime.now(timezone.utc))
        return alert

    def prepare_message(self, topic: str, payload: bytes) -> StateChange | None:
        schema = SCHEMAS.get(topic)
        if schema is None:
            return None
        if len(payload) > 16384:
            logger.warning("Ignoring oversized payload on %s", topic)
            return None
        try:
            message = schema.model_validate_json(payload)
        except ValidationError as exc:
            locations = [".".join(map(str, error["loc"])) or "JSON"
                         for error in exc.errors(include_input=False, include_url=False)]
            logger.warning("Ignoring invalid payload on %s (%s)", topic, ", ".join(locations))
            return None
        alert = None
        if topic == VISION_TOPIC and message.person_detected and not (self.vision and self.vision.person_detected):
            alert = self.alerts.make(AlertCreate(ts=message.ts, type="INTRUSION", severity="critical",
                                                message="Human presence detected"))
        elif topic == ANOMALY_TOPIC and message.ready and message.anomaly and not (self.anomaly and self.anomaly.anomaly):
            alert = self.alerts.make(AlertCreate(ts=message.ts, type="ENVIRONMENTAL_ANOMALY",
                                                severity="warning", message="Environmental anomaly detected"))
        return StateChange(topic, message, alert)

    def apply_change(self, change: StateChange) -> None:
        if change.topic is None:
            self.system = SystemStatus(mqtt_connected=change.message,
                                       last_update=datetime.now(timezone.utc))
        elif change.topic == TELEMETRY_TOPIC:
            self.telemetry = change.message
            self.history.append(change.message)
        elif change.topic == VISION_TOPIC:
            self.vision = change.message
        else:
            self.anomaly = change.message
            self.anomaly_history.append(change.message)
        if change.alert:
            self.alerts.record(change.alert)
        self.system = SystemStatus(mqtt_connected=self.system.mqtt_connected,
                                   last_update=datetime.now(timezone.utc))

    def apply_message(self, topic: str, payload: bytes) -> bool:
        change = self.prepare_message(topic, payload)
        if change is None:
            return False
        self.apply_change(change)
        return True

    def restore(self, telemetry: list[SensorTelemetry], vision: VisionResult | None,
                anomalies: list[AnomalyResult], alerts: list[Alert], last_update: datetime | None) -> None:
        self.history.clear()
        self.history.extend(telemetry)
        self.anomaly_history.clear()
        self.anomaly_history.extend(anomalies)
        self.telemetry = self.history[-1] if self.history else None
        self.vision = vision
        self.anomaly = self.anomaly_history[-1] if self.anomaly_history else None
        self.alerts.restore(alerts)
        self.system = SystemStatus(mqtt_connected=False, last_update=last_update)

    def snapshot(self) -> SentinelState:
        return SentinelState(telemetry=self.telemetry, vision=self.vision,
                             anomaly=self.anomaly, system=self.system,
                             history=list(self.history),
                             anomaly_history=list(self.anomaly_history),
                             alerts=self.alerts.recent())
