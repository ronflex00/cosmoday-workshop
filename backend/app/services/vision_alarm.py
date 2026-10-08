"""One pulse per person episode, rearmed after three seconds of absence."""

from datetime import datetime, timezone

from ..models.schemas import VisionResult
from .environment import FRESH_SECONDS, FUTURE_SECONDS


class VisionAlarm:
    def __init__(self):
        self.active = False
        self.last_sample: datetime | None = None
        self.absent_since: datetime | None = None

    def accept(self, result: VisionResult, *, connected: bool) -> bool:
        age = (datetime.now(timezone.utc) - result.ts).total_seconds()
        if (not connected or not -FUTURE_SECONDS <= age <= FRESH_SECONDS
                or (self.last_sample is not None and result.ts <= self.last_sample)):
            return False
        # A gap in camera results cannot count as confirmed absence.
        if self.last_sample is not None and (result.ts - self.last_sample).total_seconds() > 2:
            self.absent_since = None
        self.last_sample = result.ts
        if result.person_detected:
            self.absent_since = None
            if not self.active:
                self.active = True
                return True
        else:
            if self.absent_since is None:
                self.absent_since = result.ts
            if (result.ts - self.absent_since).total_seconds() >= 3:
                self.active = False
        return False
