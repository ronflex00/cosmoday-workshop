import random
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sklearn.ensemble import IsolationForest

from scripts.send_fake_telemetry import make_telemetry
from src.anomaly.buffer import TrainingBuffer
from src.anomaly.detector import AnomalyDetector
from src.common.schemas import SensorTelemetry


class AnomalyTests(unittest.TestCase):
    def training_data(self, count=20):
        rng = random.Random(42)
        return [make_telemetry(rng, "normal", "sentinel-01") for _ in range(count)]

    def test_buffer_contains_only_features_and_is_bounded(self):
        buffer = TrainingBuffer(2)
        data = self.training_data(3)
        for telemetry in data:
            buffer.add(telemetry)
        self.assertTrue(buffer.full)
        self.assertEqual(len(buffer), 2)
        self.assertEqual(buffer.samples(), [(t.temperature, t.humidity, t.gas) for t in data[1:]])

    def test_learning_and_model_readiness(self):
        detector = AnomalyDetector()
        self.assertIsInstance(detector.model, IsolationForest)
        for index, telemetry in enumerate(self.training_data()):
            result = detector.analyze(telemetry)
            self.assertFalse(result.ready)
            self.assertFalse(result.anomaly)
            self.assertIsNone(result.score)
            self.assertEqual(detector.ready, index == 19)
        self.assertEqual(detector.model.n_features_in_, 3)

    def test_normal_and_extreme_data_are_scored_by_forest(self):
        detector = AnomalyDetector()
        for telemetry in self.training_data():
            detector.analyze(telemetry)
        reference = detector.buffer.samples()
        normal = SensorTelemetry("sentinel-01", "2026-10-05T14:30:00Z", 23.5, 45.0, 140.0, False)
        result = detector.analyze(normal)
        self.assertTrue(result.ready)
        self.assertFalse(result.anomaly)
        self.assertGreaterEqual(result.score, 0)
        rng = random.Random(7)
        for _ in range(5):
            telemetry = make_telemetry(rng, "anomaly", "sentinel-01")
            result = detector.analyze(telemetry)
            self.assertTrue(result.ready)
            self.assertTrue(result.anomaly)
            self.assertLess(result.score, 0)
            row = [[telemetry.temperature, telemetry.humidity, telemetry.gas]]
            self.assertAlmostEqual(result.score, float(detector.model.decision_function(row)[0]))
            self.assertEqual(result.anomaly, bool(detector.model.predict(row)[0] == -1))
        self.assertEqual(detector.buffer.samples(), reference)

    def test_training_sample_count_is_configurable(self):
        detector = AnomalyDetector(training_samples=5)
        for telemetry in self.training_data(5):
            detector.analyze(telemetry)
        self.assertTrue(detector.ready)
        self.assertEqual(len(detector.buffer), 5)

    def test_model_survives_restart_without_training(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "models" / "environment.joblib"
            detector = AnomalyDetector(training_samples=5, model_path=path)
            data = self.training_data(6)
            for sample in data[:5]:
                detector.analyze(sample)
            expected = detector.analyze(data[-1])
            restored = AnomalyDetector(training_samples=300, model_path=path)
            result = restored.analyze(data[-1])
            self.assertTrue(result.ready)
            self.assertEqual(len(restored.buffer), 0)
            self.assertEqual(result.score, expected.score)
            self.assertEqual(result.anomaly, expected.anomaly)

    def test_interrupted_retraining_keeps_previous_model_and_save_retries(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "environment.joblib"
            first = AnomalyDetector(training_samples=2, model_path=path)
            data = self.training_data(5)
            for sample in data[:2]:
                first.analyze(sample)
            original = path.read_bytes()
            new = AnomalyDetector(training_samples=3, model_path=path, retrain=True)
            self.assertFalse(new.ready)
            for sample in data[:2]:
                new.analyze(sample)
            self.assertEqual(path.read_bytes(), original)
            with patch("src.anomaly.detector.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    new.analyze(data[2])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob(".environment-*.tmp")), [])
            new.analyze(data[3])
            self.assertTrue(AnomalyDetector(model_path=path).ready)
            self.assertNotEqual(path.read_bytes(), original)

    def test_invalid_saved_model_requires_explicit_retraining(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "environment.joblib"
            path.write_bytes(b"invalid model")
            with self.assertRaisesRegex(ValueError, "AI_ENVIRONMENT_RETRAIN"):
                AnomalyDetector(model_path=path)
            self.assertFalse(AnomalyDetector(model_path=path, retrain=True).ready)


if __name__ == "__main__":
    unittest.main()
