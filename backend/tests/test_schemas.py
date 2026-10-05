import json
import unittest

from pydantic import ValidationError

from app.models.schemas import AnomalyResult, SensorTelemetry, VisionResult


def telemetry(**changes):
    data = {"device_id": "sentinel-01", "ts": "2026-10-05T14:30:00Z",
            "temperature": 24.3, "humidity": 46.0, "gas": 173, "motion": False}
    return dict(data, **changes)


def vision(**changes):
    return dict(ts="2026-10-05T14:30:01Z", person_detected=True,
                confidence=0.95, source="camera-0") | changes


def anomaly(**changes):
    return dict(ts="2026-10-05T14:30:02Z", anomaly=True, ready=True, score=-0.18,
                model="isolation_forest", features={"temperature": 37, "humidity": 72, "gas": 550}) | changes


class SchemaTests(unittest.TestCase):
    def test_valid_telemetry(self):
        result = SensorTelemetry.model_validate_json(json.dumps(telemetry()))
        self.assertEqual(result.temperature, 24.3)
        self.assertEqual(result.gas, 173)
        self.assertFalse(result.motion)
        self.assertTrue(result.model_dump(mode="json")["ts"].endswith("Z"))

    def test_invalid_telemetry(self):
        for changes in ({"temperature": "24.3"}, {"temperature": True}, {"temperature": None},
                        {"temperature": float("nan")}, {"gas": float("inf")}, {"humidity": 101},
                        {"motion": "false"}, {"device_id": " "}, {"ts": "bad"}, {"ts": 1728},
                        {"ts": "2026-10-05T14:30:00"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                SensorTelemetry.model_validate_json(json.dumps(telemetry(**changes)))
        for field in telemetry():
            data = telemetry()
            del data[field]
            with self.subTest(missing=field), self.assertRaises(ValidationError):
                SensorTelemetry.model_validate(data)

    def test_vision_confidence(self):
        result = VisionResult.model_validate(vision())
        self.assertTrue(result.person_detected)
        self.assertEqual(result.confidence, 0.95)
        with self.assertRaises(ValidationError):
            VisionResult.model_validate(vision(confidence=1.1))

    def test_anomaly_calibration_accepts_null(self):
        result = AnomalyResult.model_validate(anomaly(ready=False, anomaly=False, score=None))
        self.assertFalse(result.ready)
        self.assertIsNone(result.score)
        self.assertIsNone(result.model_dump(mode="json")["score"])

    def test_anomaly_numeric_and_historical_contract(self):
        result = AnomalyResult.model_validate(anomaly())
        self.assertTrue(result.ready)
        self.assertEqual(result.score, -0.18)
        historical = anomaly()
        del historical["ready"]
        self.assertTrue(AnomalyResult.model_validate(historical).ready)

    def test_inconsistent_anomaly_rejected(self):
        for changes in ({"score": None}, {"ready": False}, {"score": float("nan")}, {"anomaly": "true"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                AnomalyResult.model_validate(anomaly(**changes))


if __name__ == "__main__":
    unittest.main()
