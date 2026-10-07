"""ESP MQTT events must reach REST/WS without creating alert echo loops."""

import asyncio
import json
import os
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models.schemas import ALERTS_TOPIC, DEVICE_STATUS_TOPIC, TELEMETRY_TOPIC
from app.mqtt.client import MQTTEvent
from app.services.history import HistoryStore
from app.services.state import StateService
from test_api import FakeMQTT
from test_schemas import telemetry
from test_websocket import wait_connected


def alert(**changes):
    return dict(ts="2026-10-07T13:06:15Z", type="intrusion", severity="warning",
                message="ESP: presence de proximite HC-SR04") | changes


class MQTTExposureTests(unittest.TestCase):
    def test_device_last_will_reaches_rest_and_websocket(self):
        app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            with client.websocket_connect("/ws") as ws:
                self.assertIsNone(ws.receive_json()["data"]["device"])
                for online in (True, False, True):
                    payload = {"device_id": "sentinel-01", "online": online}
                    if online:
                        payload.update(ip="172.20.10.4", rssi=-51)
                    app.state.mqtt.events.put_nowait(MQTTEvent(DEVICE_STATUS_TOPIC, json.dumps(payload).encode()))
                    state = ws.receive_json()["data"]
                    self.assertEqual(state["device"]["online"], online)
                    self.assertEqual(client.get("/api/v1/status").json()["device"], state["device"])
                self.assertEqual(client.get("/api/v1/history/telemetry").json()["items"], [])

    def test_external_alert_is_persisted_and_broadcast_without_republication(self):
        app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            with client.websocket_connect("/ws") as ws:
                ws.receive_json()
                publication_count = len(app.state.mqtt.alerts)
                payload = json.dumps(alert()).encode()
                app.state.mqtt.events.put_nowait(MQTTEvent(ALERTS_TOPIC, payload))
                state = ws.receive_json()["data"]
                received = state["alerts"][0]
                self.assertEqual(received["message"], alert()["message"])
                self.assertEqual(received["type"], "INTRUSION")
                self.assertEqual(client.get("/api/v1/alerts").json()[0], received)
                self.assertEqual(len(app.state.mqtt.alerts), publication_count)
                app.state.mqtt.events.put_nowait(MQTTEvent(ALERTS_TOPIC, payload))
                # A later telemetry event proves the duplicate was consumed first.
                app.state.mqtt.events.put_nowait(MQTTEvent(TELEMETRY_TOPIC, json.dumps(telemetry()).encode()))
                state = ws.receive_json()["data"]
                self.assertIsNotNone(state["telemetry"])
                self.assertEqual(len([a for a in state["alerts"] if a["id"] == received["id"]]), 1)
                history = client.get("/api/v1/history/alerts").json()["items"]
                self.assertEqual(len([entry for entry in history if entry["data"]["id"] == received["id"]]), 1)

    def test_rest_alert_echo_does_not_duplicate_or_republish(self):
        app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"))
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            created = client.post("/api/v1/alerts", json=alert()).json()
            publication_count = len(app.state.mqtt.alerts)
            app.state.mqtt.events.put_nowait(MQTTEvent(ALERTS_TOPIC, json.dumps(alert()).encode()))
            app.state.mqtt.events.put_nowait(MQTTEvent(TELEMETRY_TOPIC, json.dumps(telemetry()).encode()))
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if client.get("/api/v1/sensors/latest").json() is not None:
                    break
                time.sleep(0.01)
            self.assertIsNotNone(client.get("/api/v1/sensors/latest").json())
            alerts = client.get("/api/v1/alerts").json()
            self.assertEqual(len([a for a in alerts if a["message"] == created["message"]]), 1)
            self.assertEqual(len(app.state.mqtt.alerts), publication_count)

    def test_invalid_status_and_alert_do_not_replace_valid_state(self):
        store = StateService()
        valid = dict(device_id="sentinel-01", online=True, ip="172.20.10.4", rssi=-51)
        store.apply_message(DEVICE_STATUS_TOPIC, json.dumps(valid).encode())
        before = store.snapshot()
        for payload in (valid | {"online": "true"}, valid | {"ip": "invalid"},
                        {"device_id": "sentinel-01", "online": True}, valid | {"rssi": -200}):
            with self.assertLogs("MQTT", level="WARNING"):
                self.assertFalse(store.apply_message(DEVICE_STATUS_TOPIC, json.dumps(payload).encode()))
            self.assertEqual(store.snapshot(), before)
        with self.assertLogs("MQTT", level="WARNING"):
            self.assertFalse(store.apply_message(ALERTS_TOPIC, json.dumps(alert(severity="bad")).encode()))
        self.assertEqual(store.snapshot(), before)

    def test_secret_file_support_hides_values_and_preserves_password_spaces(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "password"
            path.write_text(" test-secret-value \n", encoding="utf-8")
            with patch.dict(os.environ, {"MQTT_PASSWORD_FILE": str(path), "MQTT_USERNAME": "sentinel-api"}, clear=True), patch("app.config.load_dotenv"):
                settings = Settings.from_env()
                self.assertEqual(settings.mqtt_password, " test-secret-value ")
                self.assertNotIn("test-secret-value", repr(settings))
                with patch.dict(os.environ, {"MQTT_PASSWORD": "conflicting-test-value"}), self.assertRaises(ValueError):
                    Settings.from_env()
                path.write_text("", encoding="utf-8")
                with self.assertRaises(ValueError):
                    Settings.from_env()


class AlertHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_external_alert_retry_and_restore(self):
        with TemporaryDirectory() as directory:
            url = f"sqlite+aiosqlite:///{Path(directory) / 'history.db'}"
            history = HistoryStore(url)
            try:
                await history.initialize()
                store = StateService()
                change = store.prepare_message(ALERTS_TOPIC, json.dumps(alert()).encode())
                for _ in range(2):
                    await history.append(str(uuid4()), datetime.now(timezone.utc), change)
                self.assertEqual(len((await history.page("alerts")).items), 1)
                restored = StateService()
                await history.restore(restored)
                self.assertEqual(restored.alerts.latest.message, alert()["message"])
                self.assertIsNone(restored.prepare_message(ALERTS_TOPIC, json.dumps(alert()).encode()))
                self.assertIsNone(restored.device)
            finally:
                await history.close()
