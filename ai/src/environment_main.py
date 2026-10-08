"""Run from ai/: python -m src.environment_main (no camera or YOLO)."""

import logging
import signal
from queue import Queue
from threading import Event

from .anomaly.detector import AnomalyDetector
from .anomaly.service import process_telemetry
from .common.mqtt_client import MQTTClient
from .config import Config


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    stop = Event()
    client = None
    previous_handlers = {}
    try:
        config = Config.from_env()
        for name in ("AI", "ANOMALY", "MQTT"):
            logging.getLogger(name).setLevel(config.log_level)
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.signal(sig, lambda *_: stop.set())
        telemetry_queue = Queue(maxsize=128)
        detector = AnomalyDetector(config.training_samples, config.contamination,
                                   model_path=config.environment_model_path,
                                   retrain=config.environment_retrain)
        client = MQTTClient(config, telemetry_queue)
        logging.getLogger("AI").info("Starting environment analysis only (no camera)")
        client.start()
        process_telemetry(telemetry_queue, detector, client, stop)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        logging.getLogger("AI").exception("Environment service failed")
        return 1
    finally:
        stop.set()
        if client is not None:
            client.stop()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
