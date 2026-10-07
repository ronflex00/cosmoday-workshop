"""Paho callbacks enqueue events; they never mutate API state."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from uuid import uuid4

import paho.mqtt.client as mqtt

from ..config import Settings
from ..models.schemas import ALERTS_TOPIC, COMMANDS_TOPIC, INPUT_TOPICS, Alert, Command

logger = logging.getLogger("MQTT")


@dataclass(frozen=True)
class MQTTEvent:
    topic: str | None
    payload: bytes | bool
    id: str = field(default_factory=lambda: str(uuid4()))
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MQTTClient:
    def __init__(self, settings: Settings, events: Queue[MQTTEvent]):
        self.settings = settings
        self.events = events
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        if settings.mqtt_tls:
            self.client.tls_set(ca_certs=settings.mqtt_tls_ca,
                                certfile=settings.mqtt_tls_cert,
                                keyfile=settings.mqtt_tls_key)

    def start(self) -> None:
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=30)
        self.client.loop_start()
        logger.info("Connecting %s:%s (TLS=%s)", self.settings.mqtt_host,
                    self.settings.mqtt_port, self.settings.mqtt_tls)

    def _enqueue(self, event: MQTTEvent) -> None:
        try:
            self.events.put_nowait(event)
        except Full:
            if event.topic is None:
                # Keep the latest connection status even during a telemetry burst.
                try:
                    self.events.get_nowait()
                    self.events.task_done()
                except Empty:
                    pass
                try:
                    self.events.put_nowait(event)
                    return
                except Full:
                    pass
            logger.warning("Event queue full; dropping incoming MQTT event")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self._enqueue(MQTTEvent(None, False))
            logger.warning("Connection rejected: %s; retrying", reason_code)
            return
        self._enqueue(MQTTEvent(None, True))
        logger.info("Connected %s:%s", self.settings.mqtt_host, self.settings.mqtt_port)
        result, _ = client.subscribe([(topic, 0) for topic in INPUT_TOPICS])
        if result != mqtt.MQTT_ERR_SUCCESS:
            logger.warning("Subscription request failed: %s", mqtt.error_string(result))

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            logger.warning("Subscription rejected: %s", reason_codes)
            return
        for topic in INPUT_TOPICS:
            logger.info("Subscribed %s", topic)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._enqueue(MQTTEvent(None, False))
        if reason_code.is_failure:
            logger.warning("Disconnected: %s; reconnecting", reason_code)

    def _on_connect_fail(self, client, userdata):
        self._enqueue(MQTTEvent(None, False))
        logger.warning("Broker unavailable %s:%s; retrying", self.settings.mqtt_host,
                       self.settings.mqtt_port)

    def _on_message(self, client, userdata, message):
        if message.topic not in INPUT_TOPICS:
            return
        if len(message.payload) > 16384:
            logger.warning("Ignoring oversized payload on %s", message.topic)
            return
        self._enqueue(MQTTEvent(message.topic, message.payload))

    def _publish_json(self, topic: str, payload: dict, *, wait: bool) -> bool:
        if not self.client.is_connected():
            return False
        try:
            info = self.client.publish(topic, json.dumps(payload, allow_nan=False), qos=0, retain=False)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                return False
            if wait:
                info.wait_for_publish(timeout=2.0)
                return info.is_published()
            return True
        except (OSError, RuntimeError, ValueError):
            logger.warning("Publication failed on %s", topic)
            return False

    def publish_command(self, command: Command) -> bool:
        published = self._publish_json(COMMANDS_TOPIC, command.model_dump(mode="json"), wait=True)
        if published:
            logging.getLogger("COMMAND").info("Published %s", COMMANDS_TOPIC)
        return published

    def publish_alert(self, alert: Alert) -> bool:
        # Alerts are stored locally even if the broker is offline. Do not replay them.
        published = self._publish_json(ALERTS_TOPIC, alert.mqtt_payload(), wait=False)
        if not published:
            logger.warning("Alert kept in memory; %s publication unavailable", ALERTS_TOPIC)
        return published

    def stop(self) -> None:
        try:
            self.client.disconnect()
        finally:
            self.client.loop_stop()
            logger.info("Stopped")
