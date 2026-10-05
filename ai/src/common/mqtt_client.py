"""Nonblocking MQTT connection and JSON publication using Paho 2 callbacks."""

import json
import logging
from queue import Full, Queue
from threading import Event

import paho.mqtt.client as mqtt

from ..config import Config
from .schemas import TELEMETRY_TOPIC, SensorTelemetry

logger = logging.getLogger("MQTT")


class MQTTClient:
    def __init__(self, config: Config, telemetry_queue: Queue[SensorTelemetry] | None = None):
        self.config = config
        self.telemetry_queue = telemetry_queue
        self.connected = Event()
        self.subscribed = Event()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.on_subscribe = self._on_subscribe
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        if config.mqtt_username:
            self.client.username_pw_set(config.mqtt_username, config.mqtt_password)
        if config.mqtt_tls:
            self.client.tls_set(ca_certs=config.mqtt_tls_ca,
                                certfile=config.mqtt_tls_cert,
                                keyfile=config.mqtt_tls_key)

    def start(self) -> None:
        self.client.connect_async(self.config.mqtt_host, self.config.mqtt_port,
                                  keepalive=30)
        self.client.loop_start()
        logger.info("Connecting to %s:%s (TLS=%s)", self.config.mqtt_host,
                    self.config.mqtt_port, self.config.mqtt_tls)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.connected.clear()
            logger.warning("Connection rejected: %s; retrying", reason_code)
            return
        self.connected.set()
        logger.info("Connected to %s:%s", self.config.mqtt_host, self.config.mqtt_port)
        if self.telemetry_queue is not None:
            self.subscribed.clear()
            result, _ = client.subscribe(TELEMETRY_TOPIC, qos=0)
            if result != mqtt.MQTT_ERR_SUCCESS:
                logger.warning("Subscription failed: %s", mqtt.error_string(result))

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        if any(code.is_failure for code in reason_codes):
            logger.warning("Subscription rejected: %s", reason_codes)
            return
        self.subscribed.set()
        logger.info("Subscribed to %s", TELEMETRY_TOPIC)

    def _on_message(self, client, userdata, message):
        if message.topic != TELEMETRY_TOPIC or self.telemetry_queue is None:
            return
        try:
            telemetry = SensorTelemetry.from_json(message.payload)
        except ValueError as exc:
            logger.warning("Ignoring invalid telemetry: %s", exc)
            return
        try:
            self.telemetry_queue.put_nowait(telemetry)
        except Full:
            logger.warning("Telemetry queue full; dropping incoming sample")

    def _on_connect_fail(self, client, userdata):
        logger.warning("Broker unavailable at %s:%s; retrying automatically",
                       self.config.mqtt_host, self.config.mqtt_port)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected.clear()
        self.subscribed.clear()
        if reason_code.is_failure:
            logger.warning("Disconnected: %s; reconnecting automatically", reason_code)

    def publish_json(self, topic: str, payload: dict, *, wait: bool = False) -> bool:
        if not self.connected.is_set():
            return False
        # QoS 0, no retain: never queue stale camera states while disconnected.
        info = self.client.publish(topic, json.dumps(payload, allow_nan=False),
                                   qos=0, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.warning("Publication failed: %s", mqtt.error_string(info.rc))
            return False
        if wait:
            info.wait_for_publish(timeout=5)
            if not info.is_published():
                logger.warning("Publication timed out")
                return False
        return True

    def stop(self) -> None:
        try:
            self.client.disconnect()
        finally:
            try:
                self.client.loop_stop()
            finally:
                self.connected.clear()
                self.subscribed.clear()
                logger.info("Stopped")
