"""Learn a normal reference once, then score new data with IsolationForest."""

import logging
import os
import tempfile
from pathlib import Path

import joblib
import sklearn

from sklearn.ensemble import IsolationForest

from ..common.schemas import AnomalyResult, SensorTelemetry, utc_timestamp
from .buffer import TrainingBuffer

logger = logging.getLogger("ANOMALY")


class AnomalyDetector:
    def __init__(self, training_samples: int = 20, contamination: float = 0.1,
                 *, model_path: str | Path | None = None, retrain: bool = False):
        self.buffer = TrainingBuffer(training_samples)
        self.model = IsolationForest(n_estimators=100, contamination=contamination,
                                     random_state=42, n_jobs=1)
        self.ready = False
        self.model_path = Path(model_path) if model_path else None
        self._saved = False
        if self.model_path is not None and self.model_path.exists() and not retrain:
            self._load()

    def _load(self) -> None:
        try:
            saved = joblib.load(self.model_path)
            model = saved["model"]
            if (saved["format"] != 1 or saved["sklearn_version"] != sklearn.__version__
                    or saved["features"] != ["temperature", "humidity", "gas"]
                    or not isinstance(model, IsolationForest) or model.n_features_in_ != 3
                    or not hasattr(model, "offset_")):
                raise ValueError("Incompatible model")
        except Exception as exc:
            raise ValueError("Cannot load environment model; use AI_ENVIRONMENT_RETRAIN=true to rebuild it") from exc
        self.model = model
        self.ready = self._saved = True
        logger.info("IsolationForest loaded: %s (trained %s)", self.model_path, saved["trained_at"])

    def _save(self) -> None:
        if self.model_path is None or self._saved:
            return
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        saved = {"format": 1, "sklearn_version": sklearn.__version__,
                 "features": ["temperature", "humidity", "gas"],
                 "trained_at": utc_timestamp(), "training_samples": self.buffer.capacity,
                 "model": self.model}
        # Replace only a complete model; interrupted retraining preserves the old one.
        fd, temporary = tempfile.mkstemp(dir=self.model_path.parent, prefix=".environment-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as output:
                joblib.dump(saved, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.model_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self._saved = True
        logger.info("IsolationForest saved: %s", self.model_path)

    def analyze(self, telemetry: SensorTelemetry) -> AnomalyResult:
        features = telemetry.features()
        if not self.ready:
            self.buffer.add(telemetry)
            logger.info("Training %s/%s", len(self.buffer), self.buffer.capacity)
            if self.buffer.full:
                self.model.fit(self.buffer.samples())
                self.ready = True
                self._save()
                logger.info("IsolationForest ready")
            # All N reference samples are learning data; score starts at N+1.
            return AnomalyResult(utc_timestamp(), False, False, None, features)
        self._save()  # Retry a failed save before publishing inference results.
        row = [[telemetry.temperature, telemetry.humidity, telemetry.gas]]
        score = float(self.model.decision_function(row)[0])
        anomaly = bool(self.model.predict(row)[0] == -1)
        logger.info("anomaly=%s score=%.4f", str(anomaly).lower(), score)
        return AnomalyResult(utc_timestamp(), anomaly, True, score, features)
