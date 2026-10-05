"""Learn a normal reference once, then score new data with IsolationForest."""

import logging

from sklearn.ensemble import IsolationForest

from ..common.schemas import AnomalyResult, SensorTelemetry, utc_timestamp
from .buffer import TrainingBuffer

logger = logging.getLogger("ANOMALY")


class AnomalyDetector:
    def __init__(self, training_samples: int = 20, contamination: float = 0.1):
        self.buffer = TrainingBuffer(training_samples)
        self.model = IsolationForest(n_estimators=100, contamination=contamination,
                                     random_state=42, n_jobs=1)
        self.ready = False

    def analyze(self, telemetry: SensorTelemetry) -> AnomalyResult:
        features = telemetry.features()
        if not self.ready:
            self.buffer.add(telemetry)
            logger.info("Training %s/%s", len(self.buffer), self.buffer.capacity)
            if self.buffer.full:
                self.model.fit(self.buffer.samples())
                self.ready = True
                logger.info("IsolationForest ready")
            # All N reference samples are learning data; score starts at N+1.
            return AnomalyResult(utc_timestamp(), False, False, None, features)
        row = [[telemetry.temperature, telemetry.humidity, telemetry.gas]]
        score = float(self.model.decision_function(row)[0])
        anomaly = bool(self.model.predict(row)[0] == -1)
        logger.info("anomaly=%s score=%.4f", str(anomaly).lower(), score)
        return AnomalyResult(utc_timestamp(), anomaly, True, score, features)
