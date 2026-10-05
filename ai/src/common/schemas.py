"""MQTT payloads defined by docs/contracts.md."""

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

VISION_TOPIC = "sentinel/ai/vision"
TELEMETRY_TOPIC = "sentinel/telemetry"
ANOMALY_TOPIC = "sentinel/ai/anomaly"


def _number(data: dict, name: str) -> float:
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a JSON number")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc
    # IsolationForest converts its input to float32 internally.
    if not math.isfinite(value) or abs(value) > 3.4e38:
        raise ValueError(f"{name} must be finite and representable as float32")
    return value


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class VisionResult:
    ts: str
    person_detected: bool
    confidence: float
    source: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SensorTelemetry:
    device_id: str
    ts: str
    temperature: float
    humidity: float
    gas: float
    motion: bool

    @classmethod
    def from_json(cls, payload: bytes | str) -> "SensorTelemetry":
        if len(payload) > 16384:
            raise ValueError("Telemetry payload exceeds 16 KiB")
        try:
            data = json.loads(payload)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise ValueError("Invalid telemetry JSON or encoding") from exc
        if not isinstance(data, dict):
            raise ValueError("Telemetry must be a JSON object")
        device_id = data.get("device_id")
        if not isinstance(device_id, str) or not device_id.strip():
            raise ValueError("device_id must be a nonempty string")
        timestamp = data.get("ts")
        if not isinstance(timestamp, str):
            raise ValueError("ts must be an ISO-8601 UTC timestamp")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("ts must be an ISO-8601 UTC timestamp") from exc
        if parsed.utcoffset() != timedelta(0):
            raise ValueError("ts must include a UTC timezone")
        if not isinstance(data.get("motion"), bool):
            raise ValueError("motion must be a JSON boolean")
        temperature = _number(data, "temperature")
        humidity = _number(data, "humidity")
        gas = _number(data, "gas")
        if not 0 <= humidity <= 100:
            raise ValueError("humidity must be between 0 and 100 percent")
        if gas < 0:
            raise ValueError("gas must be nonnegative")
        return cls(device_id, timestamp, temperature, humidity, gas, data["motion"])

    def features(self) -> dict[str, float]:
        return {"temperature": self.temperature, "humidity": self.humidity, "gas": self.gas}

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AnomalyResult:
    ts: str
    anomaly: bool
    ready: bool
    score: float | None
    features: dict[str, float]
    model: str = "isolation_forest"

    def to_dict(self) -> dict:
        return asdict(self)
