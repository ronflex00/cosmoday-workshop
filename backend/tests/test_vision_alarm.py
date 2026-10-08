import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models.schemas import VISION_TOPIC, VisionResult
from app.mqtt.client import MQTTEvent
from app.services.vision_alarm import VisionAlarm
from test_api import FakeMQTT
from test_schemas import vision
from test_websocket import wait_connected


class VisionAlarmTests(unittest.TestCase):
    def setUp(self):
        self.base = datetime.now(timezone.utc) - timedelta(seconds=15)

    def result(self, second, present=True):
        return VisionResult.model_validate(vision(ts=(self.base + timedelta(seconds=second)).isoformat(),
                                                person_detected=present))

    def test_flicker_does_not_repeat_and_confirmed_absence_rearms(self):
        alarm = VisionAlarm()
        self.assertTrue(alarm.accept(self.result(0), connected=True))
        for second, present in ((1, True), (2, False), (3, True), (4, False),
                                (5, False), (6, False), (7, False)):
            self.assertFalse(alarm.accept(self.result(second, present), connected=True))
        self.assertTrue(alarm.accept(self.result(8), connected=True))

    def test_stale_disconnected_duplicate_and_missing_frames(self):
        alarm = VisionAlarm()
        self.assertFalse(alarm.accept(self.result(-60), connected=True))
        self.assertFalse(alarm.accept(self.result(0), connected=False))
        self.assertTrue(alarm.accept(self.result(0), connected=True))
        self.assertFalse(alarm.accept(self.result(0), connected=True))
        alarm.accept(self.result(1, False), connected=True)
        alarm.accept(self.result(8, False), connected=True)
        self.assertFalse(alarm.accept(self.result(9), connected=True))

    def test_api_vision_pulse_and_environment_flag_independent(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                app = create_app(Settings(ai_vision_alarm=enabled, ai_auto_alarm=False,
                                         database_url="sqlite+aiosqlite:///:memory:"))
                with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
                    wait_connected(client)
                    for second in range(4):
                        payload = self.result(second).model_dump(mode="json")
                        app.state.mqtt.events.put_nowait(MQTTEvent(VISION_TOPIC, json.dumps(payload).encode()))
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        if app.state.store.vision is not None and app.state.store.vision.ts == self.result(3).ts:
                            if not enabled or app.state.mqtt.commands:
                                break
                        time.sleep(0.01)
                    self.assertIsNotNone(app.state.store.vision)
                    self.assertEqual(app.state.mqtt.commands,
                                     [{"buzzer": True, "led": "red"}] if enabled else [])
                    if enabled:
                        deadline = time.monotonic() + 2
                        while time.monotonic() < deadline and len(app.state.mqtt.commands) < 2:
                            time.sleep(0.01)
                        self.assertEqual(app.state.mqtt.commands[-1], {"buzzer": False, "led": "red"})
                        response = client.post("/api/v1/commands", json={"buzzer": False, "led": "green"})
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(app.state.mqtt.commands[-1], {"buzzer": False, "led": "green"})
