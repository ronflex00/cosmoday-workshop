"""Run from ai/: python -m src.main."""

import logging
import os
import signal
import sys
import time
from queue import Queue
from threading import Event, Thread

import cv2

from .anomaly.detector import AnomalyDetector
from .anomaly.service import process_telemetry
from .common.mqtt_client import MQTTClient
from .common.schemas import VISION_TOPIC, VisionResult, utc_timestamp
from .config import Config
from .vision.camera import Camera
from .vision.detector import PersonDetector

logger = logging.getLogger("AI")


class VisionPublisher:
    """Publish every second, or immediately when the detected state changes."""

    def __init__(self, mqtt_client: MQTTClient, source: str):
        self.mqtt = mqtt_client
        self.source = source
        self.last_state = None
        self.last_publication = float("-inf")

    def publish(self, detection, now: float) -> bool:
        state = detection.person_detected
        if state == self.last_state and now - self.last_publication < 1.0:
            return False
        result = VisionResult(utc_timestamp(), state, detection.confidence, self.source)
        if not self.mqtt.publish_json(VISION_TOPIC, result.to_dict()):
            return False
        if state != self.last_state:
            logging.getLogger("VISION").info("Person detected=%s confidence=%.2f",
                                             state, detection.confidence)
        self.last_state = state
        self.last_publication = now
        return True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    logger.info("Starting Sentinel-X AI service (vision + anomalies)")
    stop = Event()
    mqtt_client = None
    anomaly_worker = None
    camera = None
    show_window = False
    window_open = False
    previous_handlers = {}
    try:
        config = Config.from_env()
        for name in ("AI", "VISION", "ANOMALY", "MQTT"):
            logging.getLogger(name).setLevel(config.log_level)
        show_window = config.show_window
        if show_window and sys.platform.startswith("linux") and not (
                os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            raise RuntimeError("No graphical session; set AI_SHOW_WINDOW=false")
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.signal(sig, lambda signum, frame: stop.set())
        telemetry_queue = Queue(maxsize=128)
        anomaly_detector = AnomalyDetector(config.training_samples, config.contamination)
        mqtt_client = MQTTClient(config, telemetry_queue)
        anomaly_worker = Thread(target=process_telemetry,
                                args=(telemetry_queue, anomaly_detector, mqtt_client, stop),
                                name="anomaly-worker")
        anomaly_worker.start()
        mqtt_client.start()
        detector = PersonDetector(config.yolo_model, config.confidence,
                                  config.inference_size)
        if stop.is_set():
            return 0
        camera = Camera(config.camera_index, config.camera_width, config.camera_height)
        camera.open()
        publisher = VisionPublisher(mqtt_client, f"camera-{config.camera_index}")
        frame_number = 0
        while not stop.is_set():
            frame = camera.read()
            process = frame_number % config.process_every_n_frames == 0
            frame_number += 1
            if not process:
                continue
            detection = detector.detect(frame)
            if stop.is_set():
                break
            publisher.publish(detection, time.monotonic())
            if show_window:
                cv2.imshow("Sentinel-X - press Q to stop", detector.annotate(frame, detection))
                window_open = True
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    stop.set()
    except KeyboardInterrupt:
        stop.set()
    except Exception:
        # SIGINT/SIGTERM can interrupt a native camera read and make it fail.
        if stop.is_set():
            logger.info("Shutdown requested")
            return 0
        logger.exception("Service stopped because of an error")
        return 1
    finally:
        stop.set()
        if camera is not None:
            try:
                camera.close()
            except Exception:
                logger.exception("Could not release the camera")
        if window_open:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                logger.warning("Could not close the debug window", exc_info=True)
        if anomaly_worker is not None and anomaly_worker.ident is not None:
            anomaly_worker.join()
        if mqtt_client is not None:
            try:
                mqtt_client.stop()
            except Exception:
                logger.exception("Could not stop MQTT cleanly")
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        logger.info("Stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
