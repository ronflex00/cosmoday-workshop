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
    distance_count: int = 0
    distance_sum: float = 0.0
    distance_min: float | None = None
    distance_max: float | None = None
    no_echo_count: int = 0
    presence_samples: int = 0
    presence_count: int = 0

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
        if sample.distance_sensor:
            if sample.distance_cm is None:
                self.no_echo_count += 1
            else:
                self.distance_count += 1
                self.distance_sum += sample.distance_cm
                self.distance_min = sample.distance_cm if self.distance_min is None else min(self.distance_min, sample.distance_cm)
                self.distance_max = sample.distance_cm if self.distance_max is None else max(self.distance_max, sample.distance_cm)
        if sample.presence is not None:
            self.presence_samples += 1
            self.presence_count += int(sample.presence)

    def summary(self) -> TelemetryTrend:
        return TelemetryTrend(
            device_id=self.device_id, ts=self.start,
            **{key: self.sums[key] / self.count for key in METRICS},
            motion=self.motion_count > 0, sample_count=self.count,
            minimum=self.minimum, maximum=self.maximum,
            motion_count=self.motion_count, motion_transitions=self.transitions,
            last_motion=bool(self.last_motion),
            distance_sensor=(self.distance_count + self.no_echo_count) > 0,
            distance_cm=self.distance_sum / self.distance_count if self.distance_count else None,
            distance_sample_count=self.distance_count, distance_min_cm=self.distance_min,
            distance_max_cm=self.distance_max, no_echo_count=self.no_echo_count,
            presence_sample_count=self.presence_samples, presence_count=self.presence_count,
            presence=self.presence_count > 0 if self.presence_samples else None,
        )

    def resume(self, summary: TelemetryTrend) -> None:
        self.count = summary.sample_count
        self.sums = {key: getattr(summary, key) * self.count for key in METRICS}
        self.minimum = summary.minimum.model_dump()
        self.maximum = summary.maximum.model_dump()
        self.motion_count = summary.motion_count
        self.transitions = summary.motion_transitions
        self.last_motion = summary.last_motion
        self.distance_count = summary.distance_sample_count
        self.distance_sum = (summary.distance_cm or 0.0) * self.distance_count
        self.distance_min = summary.distance_min_cm
        self.distance_max = summary.distance_max_cm
        self.no_echo_count = summary.no_echo_count
        self.presence_samples = summary.presence_sample_count
        self.presence_count = summary.presence_count
