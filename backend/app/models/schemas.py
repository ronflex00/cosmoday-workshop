"""MQTT contract, including the validated AI calibration extension."""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator, model_validator

TELEMETRY_TOPIC = "sentinel/telemetry"
VISION_TOPIC = "sentinel/ai/vision"
ANOMALY_TOPIC = "sentinel/ai/anomaly"
COMMANDS_TOPIC = "sentinel/commands"
ALERTS_TOPIC = "sentinel/alerts"
INPUT_TOPICS = (TELEMETRY_TOPIC, VISION_TOPIC, ANOMALY_TOPIC)
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class PayloadModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, allow_inf_nan=False)


class Timestamped(PayloadModel):
    ts: datetime

    @field_validator("ts", mode="before")
    @classmethod
    def timestamp_type(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError("ts must be an ISO-8601 UTC timestamp")
        return value

    @field_validator("ts")
    @classmethod
    def timestamp_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError("ts must include a UTC timezone")
        return value


class SensorFeatures(PayloadModel):
    temperature: Number
    humidity: Number = Field(ge=0, le=100)
    gas: Number = Field(ge=0)


class SensorTelemetry(Timestamped, SensorFeatures):
    device_id: StrictStr = Field(min_length=1)
    motion: StrictBool

    @field_validator("device_id")
    @classmethod
    def device_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("device_id must not be blank")
        return value


class VisionResult(Timestamped):
    person_detected: StrictBool
    confidence: Number = Field(ge=0, le=1)
    source: StrictStr = Field(min_length=1)


class AnomalyResult(Timestamped):
    anomaly: StrictBool
    ready: StrictBool = True  # Historical contract has no ready field.
    score: Number | None
    model: StrictStr = Field(min_length=1)
    features: SensorFeatures

    @model_validator(mode="after")
    def calibration_consistency(self):
        if self.ready and self.score is None:
            raise ValueError("score must be numeric when ready=true")
        if not self.ready and (self.anomaly or self.score is not None):
            raise ValueError("Calibration requires anomaly=false and score=null")
        return self


class SystemStatus(PayloadModel):
    mqtt_connected: bool = False
    last_update: datetime | None = None


class AIStatus(PayloadModel):
    vision: VisionResult | None = None
    anomaly: AnomalyResult | None = None


class AlertCreate(Timestamped):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    type: Literal["INTRUSION", "ENVIRONMENTAL_ANOMALY", "SYSTEM"]
    severity: Literal["info", "warning", "critical"]
    message: StrictStr = Field(min_length=1, max_length=256)

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value):
        # Accept the lowercase MQTT contract and the uppercase dashboard format.
        return value.upper() if isinstance(value, str) else value

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


class Alert(AlertCreate):
    id: str

    def mqtt_payload(self) -> dict:
        payload = self.model_dump(mode="json", exclude={"id"})
        payload["type"] = self.type.lower()
        return payload


class Command(PayloadModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    buzzer: StrictBool
    led: Literal["red", "green"]


class CommandResult(PayloadModel):
    status: Literal["published"] = "published"
    topic: Literal["sentinel/commands"] = COMMANDS_TOPIC
    command: Command


class SentinelState(PayloadModel):
    telemetry: SensorTelemetry | None = None
    vision: VisionResult | None = None
    anomaly: AnomalyResult | None = None
    system: SystemStatus = Field(default_factory=SystemStatus)
    history: list[SensorTelemetry] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)
