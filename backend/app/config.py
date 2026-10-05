"""Environment-only configuration; do not log credentials."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


def _port(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not 1 <= value <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"{name} must be true or false")
    return value in {"true", "1", "yes"}


@dataclass(frozen=True)
class Settings:
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = field(default="", repr=False)
    mqtt_tls: bool = False
    mqtt_tls_ca: str | None = None
    mqtt_tls_cert: str | None = None
    mqtt_tls_key: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)
    history_limit: int = 120

    @classmethod
    def from_env(cls) -> "Settings":
        backend_dir = Path(__file__).resolve().parents[1]
        local_env = backend_dir / ".env"
        load_dotenv(local_env if local_env.is_file() else backend_dir.parent / ".env",
                    override=False)
        tls = _boolean("MQTT_TLS")
        host = os.environ.get("MQTT_HOST", "localhost").strip()
        api_host = os.environ.get("API_HOST", "127.0.0.1").strip()
        if not host or not api_host:
            raise ValueError("MQTT_HOST and API_HOST must not be empty")
        username = os.environ.get("MQTT_USERNAME", "")
        password = os.environ.get("MQTT_PASSWORD", "")
        if password and not username:
            raise ValueError("MQTT_USERNAME is required when MQTT_PASSWORD is set")
        cert = os.environ.get("MQTT_TLS_CERT") or None
        key = os.environ.get("MQTT_TLS_KEY") or None
        if bool(cert) != bool(key):
            raise ValueError("Set both MQTT_TLS_CERT and MQTT_TLS_KEY")
        origins = tuple(value.strip() for value in os.environ.get(
            "CORS_ORIGINS", "http://localhost:5173").split(",") if value.strip())
        for origin in origins:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
                raise ValueError("CORS_ORIGINS must contain explicit HTTP(S) origins")
        try:
            history_limit = int(os.environ.get("API_HISTORY_LIMIT", "120"))
        except ValueError as exc:
            raise ValueError("API_HISTORY_LIMIT must be an integer") from exc
        if not 1 <= history_limit <= 120:
            raise ValueError("API_HISTORY_LIMIT must be between 1 and 120")
        return cls(mqtt_host=host, mqtt_port=_port("MQTT_PORT", 8883 if tls else 1883),
                   mqtt_username=username, mqtt_password=password, mqtt_tls=tls,
                   mqtt_tls_ca=os.environ.get("MQTT_TLS_CA") or None,
                   mqtt_tls_cert=cert, mqtt_tls_key=key,
                   api_host=api_host, api_port=_port("API_PORT", 8000),
                   cors_origins=origins, history_limit=history_limit)
