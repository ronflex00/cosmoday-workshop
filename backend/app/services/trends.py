"""Minute summaries of live telemetry; never retain individual readings."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from ..models.schemas import SensorTelemetry, TelemetryTrend

METRICS = ("temperature", "humidity", "gas")


@dataclass
class Minute:
    device_id: str
    start: datetime
    count: int = 0
    sums: dict[str, float] = field(default_factory=lambda: dict.fromkeys(METRICS, 0.0))
    minimum: dict[str, float] = field(default_factory=lambda: dict.fromkeys(METRICS, float("inf")))
    maximum: dict[str, float] = field(default_factory=lambda: dict.fromkeys(METRICS, float("-inf")))
    motion_count: int = 0
    transitions: int = 0
    last_motion: bool | None = None

    @property
    def event_id(self) -> str:
        return str(uuid5(NAMESPACE_URL, f"sentinel:minute:{self.device_id}:{self.start.isoformat()}"))

    def add(self, sample: SensorTelemetry) -> None:
        self.count += 1
        for key in METRICS:
            value = getattr(sample, key)
            self.sums[key] += value
            self.minimum[key] = min(self.minimum[key], value)
            self.maximum[key] = max(self.maximum[key], value)
        self.motion_count += int(sample.motion)
        if self.last_motion is not None and self.last_motion != sample.motion:
            self.transitions += 1
        self.last_motion = sample.motion

    def summary(self) -> TelemetryTrend:
        return TelemetryTrend(
            device_id=self.device_id, ts=self.start,
            **{key: self.sums[key] / self.count for key in METRICS},
            motion=self.motion_count > 0, sample_count=self.count,
            minimum=self.minimum, maximum=self.maximum,
            motion_count=self.motion_count, motion_transitions=self.transitions,
            last_motion=bool(self.last_motion),
        )

    def resume(self, summary: TelemetryTrend) -> None:
        self.count = summary.sample_count
        self.sums = {key: getattr(summary, key) * self.count for key in METRICS}
        self.minimum = summary.minimum.model_dump()
        self.maximum = summary.maximum.model_dump()
        self.motion_count = summary.motion_count
        self.transitions = summary.motion_transitions
        self.last_motion = summary.last_motion
