"""Keep model training and inference outside Paho's network callbacks."""

import logging
from queue import Empty, Queue
from threading import Event

from ..common.mqtt_client import MQTTClient
from ..common.schemas import ANOMALY_TOPIC, SensorTelemetry
from .detector import AnomalyDetector

logger = logging.getLogger("ANOMALY")


def process_telemetry(telemetry_queue: Queue[SensorTelemetry],
                      detector: AnomalyDetector, mqtt_client: MQTTClient,
                      stop: Event) -> None:
    while not stop.is_set():
        try:
            telemetry = telemetry_queue.get(timeout=0.2)
        except Empty:
            continue
        try:
            if stop.is_set():
                break
            result = detector.analyze(telemetry)
            if not stop.is_set() and not mqtt_client.publish_json(ANOMALY_TOPIC, result.to_dict()):
                logger.warning("Result dropped while MQTT is unavailable")
        except Exception:
            logger.exception("Cannot process telemetry; skipping sample")
        finally:
            telemetry_queue.task_done()
    logger.info("Worker stopped")
