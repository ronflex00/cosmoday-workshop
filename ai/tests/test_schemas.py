import json
import unittest

from src.common.schemas import AnomalyResult, SensorTelemetry


def payload(**changes):
    data = {"device_id": "sentinel-01", "ts": "2026-10-05T14:30:00Z",
            "temperature": 24.3, "humidity": 46.0, "gas": 173, "motion": False}
    data.update(changes)
    return data


class TelemetryTests(unittest.TestCase):
    def test_valid_telemetry(self):
        telemetry = SensorTelemetry.from_json(json.dumps(payload()).encode())
        self.assertEqual(telemetry.device_id, "sentinel-01")
        self.assertEqual(telemetry.features(), {"temperature": 24.3, "humidity": 46.0, "gas": 173.0})
        self.assertFalse(telemetry.motion)
        self.assertEqual(SensorTelemetry.from_json(json.dumps(telemetry.to_dict())), telemetry)

    def test_invalid_json_and_encoding(self):
        for value in (b"{broken", b"\xff", "null", "[]", '"hello"', "{" * 16385,
                      "[" * 2000 + "]" * 2000):
            with self.subTest(value=repr(value[:20])):
                with self.assertRaises(ValueError):
                    SensorTelemetry.from_json(value)

    def test_missing_fields(self):
        for name in payload():
            data = payload()
            del data[name]
            with self.subTest(field=name), self.assertRaises(ValueError):
                SensorTelemetry.from_json(json.dumps(data))

    def test_invalid_values(self):
        changes = [dict(temperature=True), dict(temperature="24.3"), dict(temperature=None),
                   dict(temperature=float("nan")), dict(temperature=1e100),
                   dict(gas=float("inf")), dict(gas=-1),
                   dict(humidity=101), dict(humidity=-1), dict(motion=1), dict(motion="false"),
                   dict(device_id=" "), dict(device_id=4), dict(ts="bad"),
                   dict(ts="2026-10-05T14:30:00"), dict(ts="2026-10-05T14:30:00+02:00")]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                SensorTelemetry.from_json(json.dumps(payload(**change)))

    def test_anomaly_output_json(self):
        features = {"temperature": 36.0, "humidity": 72.0, "gas": 550.0}
        learning = AnomalyResult("2026-10-05T14:30:00Z", False, False, None, features)
        ready = AnomalyResult("2026-10-05T14:30:00Z", True, True, -0.18, features)
        for result in (learning, ready):
            data = json.loads(json.dumps(result.to_dict(), allow_nan=False))
            self.assertEqual(set(data), {"ts", "anomaly", "ready", "score", "model", "features"})
            self.assertEqual(data["model"], "isolation_forest")
            self.assertEqual(data["features"], features)
        self.assertIsNone(learning.to_dict()["score"])
        self.assertTrue(ready.to_dict()["ready"])


if __name__ == "__main__":
    unittest.main()
