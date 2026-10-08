"""Interpret model persistence separately from Isolation Forest and sensor thresholds.

The reducer is prepared before storage and committed only after the transaction.
It never publishes commands, explains a model's cause, or mutates live state.
"""

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

from ..models.schemas import Alert, AnomalyResult

FRESH_SECONDS = 30
FUTURE_SECONDS = 5
CRITICAL_MESSAGE = "Persistent environmental anomaly detected (at least 2 of 3 Isolation Forest results)"


@dataclass(frozen=True)
class EnvironmentDecision:
    state: dict
    level: str | None = None
    alert: Alert | None = None


class EnvironmentIntelligence:
    def __init__(self, saved: dict | None = None):
        self._state = deepcopy(saved) if saved else {
            "version": 1, "window": [], "last_seen": None,
            "critical_active": False, "normal_streak": 0,
        }

    @property
    def state(self) -> dict:
        return deepcopy(self._state)

    def commit(self, decision: EnvironmentDecision) -> None:
        self._state = deepcopy(decision.state)

    def prepare_disconnect(self) -> EnvironmentDecision:
        state = self.state
        state["window"] = []
        state["normal_streak"] = 0
        return EnvironmentDecision(state)

    def prepare(self, result: AnomalyResult, *, connected: bool,
                now: datetime | None = None, replay: bool = False) -> EnvironmentDecision:
        now = now or datetime.now(timezone.utc)
        state = self.state
        last_seen = datetime.fromisoformat(state["last_seen"]) if state["last_seen"] else None
        # MQTT retries, retained echoes and out-of-order packets must not create
        # persistence or count as the two normal results required to rearm.
        if last_seen is not None and result.ts <= last_seen:
            return EnvironmentDecision(state)
        age = (now - result.ts).total_seconds()
        eligible = result.model == "isolation_forest" and result.ready
        if not replay:
            eligible = eligible and connected and -FUTURE_SECONDS <= age <= FRESH_SECONDS
        if not eligible:
            state["window"] = []
            state["normal_streak"] = 0
            # Do not let an invalid future timestamp block all later real data.
            if replay or age >= -FUTURE_SECONDS:
                state["last_seen"] = result.ts.isoformat()
            return EnvironmentDecision(state)
        state["last_seen"] = result.ts.isoformat()
        window = deque(state["window"], maxlen=3)
        if window and (result.ts - datetime.fromisoformat(window[-1]["ts"])).total_seconds() > FRESH_SECONDS:
            window.clear()
            state["normal_streak"] = 0
        window.append({"ts": result.ts.isoformat(), "anomaly": result.anomaly})
        state["window"] = list(window)
        alert = None
        if state["critical_active"]:
            state["normal_streak"] = 0 if result.anomaly else state["normal_streak"] + 1
            if state["normal_streak"] >= 2:
                state["critical_active"] = False
                state["normal_streak"] = 0
        elif result.anomaly and sum(item["anomaly"] for item in window) >= 2:
            state["critical_active"] = True
            state["normal_streak"] = 0
            if not replay:
                identity = "sentinel/environment-critical:" + result.ts.isoformat()
                alert = Alert(id=str(uuid5(NAMESPACE_URL, identity)), ts=result.ts,
                              type="ENVIRONMENTAL_ANOMALY", severity="critical",
                              message=CRITICAL_MESSAGE)
        level = "CRITICAL" if state["critical_active"] else "WARNING" if result.anomaly else "NORMAL"
        return EnvironmentDecision(state, level, alert)

    @classmethod
    def restore(cls, history: list[AnomalyResult], saved: dict | None = None):
        if saved:
            engine = cls(saved)
            engine.commit(engine.prepare_disconnect())
            return engine
        engine = cls()
        for result in history:
            engine.commit(engine.prepare(result, connected=True, replay=True))
        # Restored samples establish the episode, but never combine with a
        # post-startup normal to imply two uninterrupted live normal results.
        engine.commit(engine.prepare_disconnect())
        return engine
