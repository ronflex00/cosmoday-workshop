import json
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models.schemas import ANOMALY_TOPIC, TELEMETRY_TOPIC, VISION_TOPIC
from app.mqtt.client import MQTTEvent
from test_schemas import anomaly, telemetry, vision


class FakeMQTT:
    def __init__(self, settings, events):
        self.events = events
        self.stopped = False
        self.connected = True
        self.commands = []
        self.alerts = []

    def start(self):
        self.events.put_nowait(MQTTEvent(None, True))

    def stop(self):
        self.stopped = True

    def publish_command(self, command):
        if not self.connected:
            return False
        self.commands.append(command.model_dump(mode="json"))
        return True

    def publish_alert(self, alert):
        self.alerts.append(alert.mqtt_payload())
        return self.connected


class APITests(unittest.TestCase):
    def test_health_and_empty_state(self):
        app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            self.assertEqual(client.get("/health").json(), {"status": "ok"})
            state = client.get("/api/v1/state").json()
            self.assertIsNone(state["telemetry"])
            self.assertIsNone(state["vision"])
            self.assertIsNone(state["anomaly"])
            self.assertEqual(state["history"], [])
            self.assertEqual(client.get("/api/v1/sensors/latest").json(), None)
        self.assertTrue(app.state.mqtt.stopped)

    def test_queue_to_rest_state_and_ai_status(self):
        app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            for topic, payload in ((TELEMETRY_TOPIC, telemetry()), (VISION_TOPIC, vision()),
                                   (ANOMALY_TOPIC, anomaly(ready=False, anomaly=False, score=None))):
                app.state.mqtt.events.put_nowait(MQTTEvent(topic, json.dumps(payload).encode()))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                state = client.get("/api/v1/state").json()
                if state["anomaly"] is not None:
                    break
                time.sleep(0.01)
            self.assertEqual(state["telemetry"]["temperature"], 24.3)
            self.assertEqual(state["vision"]["confidence"], 0.95)
            self.assertIsNone(state["anomaly"]["score"])
            self.assertFalse(state["anomaly"]["ready"])
            self.assertEqual(len(state["anomaly_history"]), 1)
            self.assertEqual(client.get("/api/v1/status").json(), state)
            self.assertEqual(client.get("/api/v1/sensors/latest").json(), state["telemetry"])
            self.assertEqual(client.get("/api/v1/ai/status").json()["vision"], state["vision"])

    def test_cors_allows_only_configured_origin(self):
        app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
            denied = client.get("/health", headers={"Origin": "http://untrusted.test"})
            self.assertEqual(allowed.headers["access-control-allow-origin"], "http://localhost:5173")
            self.assertNotIn("access-control-allow-origin", denied.headers)

    def test_alert_post_get_and_invalid_input(self):
        app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            payload = {"ts": "2026-10-05T14:30:00Z", "type": "intrusion",
                       "severity": "critical", "message": "Human presence detected"}
            response = client.post("/api/v1/alerts", json=payload)
            self.assertEqual(response.status_code, 201)
            alert = response.json()
            self.assertTrue(alert["id"])
            self.assertEqual(alert["type"], "INTRUSION")
            self.assertIn(alert, client.get("/api/v1/alerts").json())
            self.assertIn(payload, app.state.mqtt.alerts)
            before = client.get("/api/v1/alerts").json()
            for changes in ({"message": " "}, {"type": "unknown"}, {"ts": "bad"}):
                self.assertEqual(client.post("/api/v1/alerts", json=payload | changes).status_code, 422)
            self.assertEqual(client.get("/api/v1/alerts").json(), before)

    def test_command_structure_validation_and_offline_response(self):
        app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            for command in ({"buzzer": True, "led": "red"}, {"buzzer": False, "led": "green"}):
                response = client.post("/api/v1/commands", json=command)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"status": "published", "topic": "sentinel/commands",
                                                   "command": command})
                self.assertEqual(client.get("/api/v1/state").json()["alarm_command"], command)
            self.assertEqual(app.state.mqtt.commands, [{"buzzer": True, "led": "red"},
                                                      {"buzzer": False, "led": "green"}])
            for payload in ({"buzzer": "true", "led": "red"}, {"buzzer": True, "led": "blue"},
                            {"led": "red"}, {"buzzer": True, "led": "red", "extra": 1}):
                self.assertEqual(client.post("/api/v1/commands", json=payload).status_code, 422)
            app.state.mqtt.connected = False
            response = client.post("/api/v1/commands", json={"buzzer": True, "led": "red"})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(len(app.state.mqtt.commands), 2)

    def test_cors_post_preflight(self):
        app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            response = client.options("/api/v1/commands", headers={
                "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type"})
            self.assertEqual(response.status_code, 200)
            self.assertIn("POST", response.headers["access-control-allow-methods"])


if __name__ == "__main__":
    unittest.main()
