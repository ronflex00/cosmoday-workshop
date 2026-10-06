"""Bounded reference buffer, containing only the three numeric features."""

from collections import deque

from ..common.schemas import SensorTelemetry


class TrainingBuffer:
    def __init__(self, capacity: int):
        if capacity < 2:
            raise ValueError("At least two training samples are required")
        self.capacity = capacity
        self._samples = deque(maxlen=capacity)

    def add(self, telemetry: SensorTelemetry) -> None:
        self._samples.append((telemetry.temperature, telemetry.humidity, telemetry.gas))

    def __len__(self) -> int:
        return len(self._samples)

    @property
    def full(self) -> bool:
        return len(self) == self.capacity

    def samples(self) -> list[tuple[float, float, float]]:
        return list(self._samples)
