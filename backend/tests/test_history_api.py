import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.main import create_app
from app.models.schemas import ANOMALY_TOPIC, TELEMETRY_TOPIC, VISION_TOPIC
from app.mqtt.client import MQTTEvent
from test_api import FakeMQTT
from test_schemas import anomaly, telemetry, vision
from test_websocket import wait_connected


class HistoryAPITests(unittest.TestCase):
    def app(self, url="sqlite+aiosqlite:///:memory:"):
        return create_app(Settings(database_url=url, history_limit=2))

    def enqueue(self, app, topic, payload):
        app.state.mqtt.events.put_nowait(MQTTEvent(topic, json.dumps(payload).encode()))

    def wait_state(self, client, predicate):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            state = client.get("/api/v1/state").json()
            if predicate(state):
                return state
            time.sleep(0.01)
        self.fail("Message was not processed")

    def test_history_query_validation_and_empty_response(self):
        app = self.app()
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            self.assertEqual(client.get("/api/v1/history/telemetry").json(),
                             {"items": [], "limit": 100, "next_before_id": None})
            for path in ("vision", "anomalies"):
                self.assertEqual(client.get(f"/api/v1/history/{path}").json()["items"], [])
            for params in ({"limit": 0}, {"limit": 501}, {"before_id": -1}, {"before_id": 2**64},
                           {"start": "2026-10-05T14:30:00"}, {"start": "bad"},
                           {"start": "2026-10-06T00:00:00Z", "end": "2026-10-05T00:00:00Z"}):
                with self.subTest(params=params):
                    self.assertEqual(client.get("/api/v1/history/telemetry", params=params).status_code, 422)
            self.assertEqual(client.get("/api/v1/history/vision", params={"device_id": "node"}).status_code, 422)
            self.assertEqual(client.get("/api/v1/history/unknown").status_code, 422)
            self.assertEqual(client.get("/health").status_code, 200)

    def test_database_commit_precedes_live_state_and_websocket_publication(self):
        app = self.app()
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            entered, release = Event(), Event()
            original = app.state.history.append
            async def delayed_write(*args):
                entered.set()
                while not release.is_set():
                    await asyncio.sleep(0.01)
                await original(*args)
            with client.websocket_connect("/ws") as socket, patch.object(app.state.history, "append", side_effect=delayed_write):
                socket.receive_json()
                try:
                    self.enqueue(app, TELEMETRY_TOPIC, telemetry())
                    self.assertTrue(entered.wait(2))
                    self.assertIsNone(client.get("/api/v1/sensors/latest").json())
                    self.assertEqual(client.get("/api/v1/history/telemetry").json()["items"], [])
                finally:
                    release.set()
                update = socket.receive_json()["data"]
                stored = client.get("/api/v1/history/telemetry").json()["items"]
                self.assertEqual(stored[0]["data"], update["telemetry"])
                self.assertEqual(len(stored), 1)

    def test_transient_storage_failure_retries_without_losing_or_duplicating_sample(self):
        app = self.app()
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            failed = Event()
            original = app.state.history.append
            async def fail_once(*args):
                if not failed.is_set():
                    failed.set()
                    raise OperationalError("write", {}, Exception("unavailable"))
                await original(*args)
            with patch.object(app.state.history, "append", side_effect=fail_once):
                self.enqueue(app, TELEMETRY_TOPIC, telemetry())
                self.assertTrue(failed.wait(2))
                self.assertIsNone(client.get("/api/v1/sensors/latest").json())
                self.wait_state(client, lambda state: state["telemetry"] is not None)
            self.assertEqual(len(client.get("/api/v1/history/telemetry").json()["items"]), 1)
            self.assertEqual(client.get("/health").status_code, 200)

    def test_restart_restores_all_recent_types_and_keeps_full_history_accessible(self):
        with TemporaryDirectory() as directory:
            url = f"sqlite+aiosqlite:///{Path(directory) / 'persistent.db'}"
            app = self.app(url)
            with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
                for gas in range(5):
                    self.enqueue(app, TELEMETRY_TOPIC, telemetry(gas=gas))
                self.enqueue(app, VISION_TOPIC, vision())
                self.enqueue(app, ANOMALY_TOPIC, anomaly(ready=False, anomaly=False, score=None))
                old_state = self.wait_state(client, lambda state: state["anomaly"] is not None)
                old_vision_id = client.get("/api/v1/history/vision").json()["items"][0]["id"]
            restarted = self.app(url)
            with patch("app.main.MQTTClient", FakeMQTT), TestClient(restarted) as client:
                state = client.get("/api/v1/state").json()
                self.assertEqual(state["telemetry"], old_state["telemetry"])
                self.assertEqual(state["vision"], old_state["vision"])
                self.assertEqual(state["anomaly"], old_state["anomaly"])
                self.assertEqual([point["gas"] for point in state["history"]], [3, 4])
                self.assertEqual(client.get("/api/v1/history/vision").json()["items"][0]["id"], old_vision_id)
                first = client.get("/api/v1/history/telemetry", params={"limit": 2}).json()
                second = client.get("/api/v1/history/telemetry", params={"limit": 2, "before_id": first["next_before_id"]}).json()
                self.assertEqual([entry["data"]["gas"] for entry in first["items"] + second["items"]], [4, 3, 2, 1])

    def test_invalid_messages_are_not_persisted_and_filters_return_real_values(self):
        app = self.app()
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            app.state.mqtt.events.put_nowait(MQTTEvent(TELEMETRY_TOPIC, b"{broken"))
            self.enqueue(app, TELEMETRY_TOPIC, telemetry())
            self.wait_state(client, lambda state: state["telemetry"] is not None)
            page = client.get("/api/v1/history/telemetry", params={
                "device_id": "sentinel-01", "start": "2026-10-05T14:30:00Z", "end": "2026-10-05T16:30:00+02:00"}).json()
            self.assertEqual(len(page["items"]), 1)
            self.assertEqual(page["items"][0]["data"]["temperature"], 24.3)
            self.assertEqual(client.get("/api/v1/history/telemetry", params={"device_id": "missing"}).json()["items"], [])

    def test_storage_error_returns_503_and_manual_alert_is_not_announced_as_saved(self):
        app = self.app()
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            before = client.get("/api/v1/alerts").json()
            failure = OperationalError("private SQL", {"password": "do-not-expose"}, Exception("unavailable"))
            with patch.object(app.state.history, "page", new=AsyncMock(side_effect=failure)):
                response = client.get("/api/v1/history/telemetry")
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("do-not-expose", response.text)
                self.assertEqual(client.get("/health").status_code, 503)
            with patch.object(app.state.history, "append_alert", new=AsyncMock(side_effect=failure)):
                response = client.post("/api/v1/alerts", json={"ts": "2026-10-05T14:30:00Z", "type": "system",
                                                            "severity": "info", "message": "Manual note"})
                self.assertEqual(response.status_code, 503)
            self.assertEqual(client.get("/api/v1/alerts").json(), before)
            self.assertEqual(client.get("/api/v1/history/telemetry").status_code, 200)
            self.assertEqual(client.get("/health").status_code, 200)


if __name__ == "__main__":
    unittest.main()
