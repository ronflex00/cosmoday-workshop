from datetime import datetime, timezone
import unittest

from pydantic import ValidationError

from app.models.schemas import SensorTelemetry
from app.services.trends import Minute
from test_schemas import telemetry


class DistanceTests(unittest.TestCase):
    def test_legacy_no_echo_and_future_presence_are_distinct(self):
        old = SensorTelemetry.model_validate(telemetry())
        self.assertFalse(old.distance_sensor)
        self.assertIsNone(old.presence)
        no_echo = SensorTelemetry.model_validate(dict(telemetry(), distance_sensor=True, distance_cm=None))
        self.assertTrue(no_echo.distance_sensor)
        self.assertIsNone(no_echo.distance_cm)
        detected = SensorTelemetry.model_validate(dict(telemetry(), distance_sensor=True, distance_cm=29.4, presence=True))
        self.assertEqual(detected.distance_cm, 29.4)
        self.assertTrue(detected.presence)
        for fields in ({'distance_cm': -1}, {'presence': 'true'}, {'distance_cm': float('nan')}):
            with self.assertRaises(ValidationError):
                SensorTelemetry.model_validate(dict(telemetry(), **fields))

    def test_distance_summary_ignores_no_echo_and_resumes(self):
        minute = Minute('sentinel-01', datetime.now(timezone.utc))
        for distance, presence in ((20.0, None), (None, False), (40.0, True)):
            minute.add(SensorTelemetry.model_validate(dict(telemetry(), distance_sensor=True, distance_cm=distance, presence=presence)))
        summary = minute.summary()
        self.assertEqual(summary.distance_cm, 30)
        self.assertEqual(summary.distance_sample_count, 2)
        self.assertEqual(summary.no_echo_count, 1)
        self.assertEqual((summary.distance_min_cm, summary.distance_max_cm), (20, 40))
        self.assertEqual(summary.presence_sample_count, 2)
        self.assertEqual(summary.presence_count, 1)
        resumed = Minute('sentinel-01', minute.start)
        resumed.resume(summary)
        resumed.add(SensorTelemetry.model_validate(dict(telemetry(), distance_sensor=True, distance_cm=60.0)))
        self.assertEqual(resumed.summary().distance_cm, 40)
