"""Bounded alert history, owned by the API event loop."""

import logging
from collections import deque
from uuid import uuid4

from ..models.schemas import Alert, AlertCreate

logger = logging.getLogger("ALERT")


class AlertsService:
    def __init__(self):
        self._history: deque[Alert] = deque(maxlen=50)

    @property
    def latest(self) -> Alert | None:
        return self._history[-1] if self._history else None

    def add(self, payload: AlertCreate) -> Alert:
        return self.record(self.make(payload))

    @staticmethod
    def make(payload: AlertCreate) -> Alert:
        return Alert(id=str(uuid4()), **payload.model_dump())

    def record(self, alert: Alert) -> Alert:
        self._history.append(alert)
        logger.info("%s: %s", alert.type, alert.message)
        return alert

    def recent(self) -> list[Alert]:
        return list(reversed(self._history))

    def contains(self, payload: AlertCreate) -> bool:
        # The API subscribes to alerts it also publishes. Ignore its own echo
        # and repeated incoming events, regardless of lowercase MQTT type.
        return any(alert.model_dump(exclude={"id"}) == payload.model_dump()
                   for alert in self._history)

    def restore(self, alerts: list[Alert]) -> None:
        self._history.clear()
        self._history.extend(alerts)
