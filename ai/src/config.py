"""Environment configuration; shell variables take precedence over .env."""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _value(name: str, default: str, legacy: str | None = None) -> str:
    if name in os.environ:
        return os.environ[name]
    return os.environ.get(legacy, default) if legacy else default


def _integer(name: str, default: int, minimum: int = 1, legacy=None) -> int:
    try:
        value = int(_value(name, str(default), legacy))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    value = _value(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"{name} must be true or false")
    return value in {"true", "1", "yes"}


@dataclass(frozen=True)
class Config:
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = field(default="", repr=False)
    mqtt_tls: bool = False
    mqtt_tls_ca: str | None = None
    mqtt_tls_cert: str | None = None
    mqtt_tls_key: str | None = None
    camera_index: int = 0
    camera_width: int = 640
    camera_height: int = 480
    yolo_model: str = "yolov8n.pt"
    confidence: float = 0.55
    inference_size: int = 320
    process_every_n_frames: int = 3
    show_window: bool = False
    vision_stream_host: str = "127.0.0.1"
    vision_stream_port: int = 8765
    vision_stream_origin: str = "http://localhost:5173"
    training_samples: int = 20
    contamination: float = 0.1
    environment_model_path: str = str(Path(__file__).resolve().parents[1] / "models" / "environment.joblib")
    environment_retrain: bool = False
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Config":
        ai_dir = Path(__file__).resolve().parents[1]
        local_env = ai_dir / ".env"
        load_dotenv(local_env if local_env.is_file() else ai_dir.parent / ".env",
                    override=False)
        tls = _boolean("MQTT_TLS")
        port = _integer("MQTT_PORT", 8883 if tls else 1883)
        if port > 65535:
            raise ValueError("MQTT_PORT must be <= 65535")
        try:
            confidence = float(_value("AI_CONFIDENCE", "0.55"))
        except ValueError as exc:
            raise ValueError("AI_CONFIDENCE must be a number") from exc
        if not math.isfinite(confidence) or not 0 < confidence <= 1:
            raise ValueError("AI_CONFIDENCE must be in (0, 1]")
        try:
            contamination = float(_value("AI_CONTAMINATION", "0.1"))
        except ValueError as exc:
            raise ValueError("AI_CONTAMINATION must be a number") from exc
        if not math.isfinite(contamination) or not 0 < contamination <= 0.5:
            raise ValueError("AI_CONTAMINATION must be in (0, 0.5]")
        host = _value("MQTT_HOST", "localhost").strip()
        model = _value("AI_YOLO_MODEL", "yolov8n.pt", "AI_MODEL").strip()
        stream_host = _value("AI_VISION_STREAM_HOST", "127.0.0.1").strip()
        stream_port = _integer("AI_VISION_STREAM_PORT", 8765)
        stream_origin = _value("AI_VISION_STREAM_ORIGIN", "http://localhost:5173").strip()
        if stream_port > 65535:
            raise ValueError("AI_VISION_STREAM_PORT must be <= 65535")
        if not host or not model or not stream_host or not stream_origin:
            raise ValueError("MQTT_HOST, AI_YOLO_MODEL, AI_VISION_STREAM_HOST and "
                             "AI_VISION_STREAM_ORIGIN must not be empty")
        username = _value("MQTT_USERNAME", "")
        password = _value("MQTT_PASSWORD", "")
        if password and not username:
            raise ValueError("MQTT_USERNAME is required when MQTT_PASSWORD is set")
        cert = _value("MQTT_TLS_CERT", "") or None
        key = _value("MQTT_TLS_KEY", "") or None
        if bool(cert) != bool(key):
            raise ValueError("Set both MQTT_TLS_CERT and MQTT_TLS_KEY for mutual TLS")
        log_level = _value("AI_LOG_LEVEL", "INFO").strip().upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("AI_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")
        return cls(
            mqtt_host=host, mqtt_port=port, mqtt_username=username,
            mqtt_password=password, mqtt_tls=tls,
            mqtt_tls_ca=_value("MQTT_TLS_CA", "") or None,
            mqtt_tls_cert=cert, mqtt_tls_key=key,
            camera_index=_integer("AI_CAMERA_INDEX", 0, 0, "CAMERA_INDEX"),
            camera_width=_integer("AI_CAMERA_WIDTH", 640),
            camera_height=_integer("AI_CAMERA_HEIGHT", 480),
            yolo_model=model, confidence=confidence,
            inference_size=_integer("AI_INFERENCE_SIZE", 320),
            process_every_n_frames=_integer("AI_PROCESS_EVERY_N_FRAMES", 3,
                                           legacy="AI_FRAME_SKIP"),
            show_window=_boolean("AI_SHOW_WINDOW"),
            vision_stream_host=stream_host,
            vision_stream_port=stream_port,
            vision_stream_origin=stream_origin,
            training_samples=_integer("AI_TRAINING_SAMPLES", 20, minimum=2),
            contamination=contamination,
            environment_model_path=_value("AI_ENVIRONMENT_MODEL_PATH", str(ai_dir / "models" / "environment.joblib")),
            environment_retrain=_boolean("AI_ENVIRONMENT_RETRAIN"),
            log_level=log_level,
        )
