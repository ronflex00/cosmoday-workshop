"""Publish test sensor values; only the AI service decides whether they are anomalous."""

import argparse
import logging
import math
import random
import signal
import sys
import time
from pathlib import Path
from threading import Event

# Also works when launched as: python scripts/send_fake_telemetry.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.mqtt_client import MQTTClient
from src.common.schemas import TELEMETRY_TOPIC, SensorTelemetry, utc_timestamp
from src.config import Config

logger = logging.getLogger("FAKE")


def make_telemetry(rng: random.Random, mode: str, device_id: str) -> SensorTelemetry:
    if mode == "normal":
        temperature, humidity, gas = rng.uniform(22, 25), rng.uniform(40, 50), rng.uniform(100, 180)
    elif mode == "anomaly":
        temperature, humidity, gas = rng.uniform(36, 40), rng.uniform(65, 80), rng.uniform(450, 650)
    else:
        raise ValueError("Generation mode must be normal or anomaly")
    return SensorTelemetry(device_id, utc_timestamp(), round(temperature, 2),
                           round(humidity, 2), round(gas, 2), False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", type=str.lower, choices=("normal", "anomaly", "demo"), default="demo")
    parser.add_argument("--count", type=int, help="Message count for normal/anomaly (defaults: 20/5)")
    parser.add_argument("--normal-count", type=int, help="Demo reference count (default: AI_TRAINING_SAMPLES)")
    parser.add_argument("--interval", type=float, default=0.5, help="Seconds between messages (default: 0.5)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device-id", default="sentinel-01")
    args = parser.parse_args()
    if args.count is not None and args.count < 1:
        parser.error("--count must be >= 1")
    if args.normal_count is not None and args.normal_count < 2:
        parser.error("--normal-count must be >= 2")
    if not math.isfinite(args.interval) or args.interval < 0:
        parser.error("--interval must be a finite number >= 0")
    if not args.device_id.strip():
        parser.error("--device-id must not be empty")
    if args.mode == "demo" and args.count is not None:
        parser.error("Use --normal-count for demo mode")
    if args.mode != "demo" and args.normal_count is not None:
        parser.error("--normal-count is only available in demo mode")
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    stop = Event()
    previous_handlers = {}
    client = None
    try:
        config = Config.from_env()
        client = MQTTClient(config)
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.signal(sig, lambda signum, frame: stop.set())
        client.start()
        deadline = time.monotonic() + 15
        while not client.connected.is_set():
            if stop.wait(0.1):
                return 0
            if time.monotonic() >= deadline:
                raise RuntimeError("Broker unavailable after 15 seconds; check MQTT configuration")
        rng = random.Random(args.seed)
        if args.mode == "demo":
            phases = [("normal", args.normal_count or config.training_samples), ("anomaly", 5)]
        else:
            count = args.count or (20 if args.mode == "normal" else 5)
            phases = [(args.mode, count)]
        for phase_index, (mode, count) in enumerate(phases):
            if phase_index:
                logger.info("Waiting 2 seconds before sending extreme values")
                if stop.wait(2):
                    break
            for index in range(count):
                if stop.is_set():
                    break
                telemetry = make_telemetry(rng, mode, args.device_id)
                if not client.publish_json(TELEMETRY_TOPIC, telemetry.to_dict(), wait=True):
                    raise RuntimeError("Telemetry publication failed; broker may be disconnected")
                logger.info("%s %s/%s temperature=%.2f humidity=%.2f gas=%.2f",
                            mode.upper(), index + 1, count, telemetry.temperature,
                            telemetry.humidity, telemetry.gas)
                if index + 1 < count and stop.wait(args.interval):
                    break
        return 0
    except KeyboardInterrupt:
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        logger.error("%s", exc)
        return 1
    finally:
        if client is not None:
            client.stop()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    sys.exit(main())
