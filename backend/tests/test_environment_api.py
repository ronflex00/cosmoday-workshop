"""Additive MQTT/REST/WS/history behavior and durable episode integration."""

import asyncio
import json
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.main import create_app
from app.models.schemas import ALERTS_TOPIC, ANOMALY_TOPIC, TELEMETRY_TOPIC, VISION_TOPIC
from app.mqtt.client import MQTTEvent
from test_api import FakeMQTT
from test_schemas import anomaly, telemetry, vision
from test_websocket import wait_connected


class EnvironmentAPITests(unittest.TestCase):
    def setUp(self):
        self.base = datetime.now(timezone.utc) - timedelta(seconds=10)

    def app(self, *, enabled=False, limit=120, url="sqlite+aiosqlite:///:memory:"):
        return create_app(Settings(ai_auto_alarm=enabled, history_limit=limit, database_url=url))

    def enqueue(self, app, second, abnormal=True, **changes):
        result = anomaly(ts=(self.base + timedelta(seconds=second)).isoformat(),
                         anomaly=abnormal, score=-0.18 if abnormal else 0.12) | changes
        app.state.mqtt.events.put_nowait(MQTTEvent(ANOMALY_TOPIC, json.dumps(result).encode()))
        return result

    def wait(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        self.fail("Expected MQTT/API integration did not complete")

    def critical(self, client):
        return [alert for alert in client.get("/api/v1/alerts").json()
                if alert["type"] == "ENVIRONMENTAL_ANOMALY" and alert["severity"] == "critical"]

    def test_disabled_flag_keeps_overview_vision_websocket_and_history_contracts(self):
        app = self.app()
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            with client.websocket_connect("/ws") as ws:
                initial = ws.receive_json()["data"]
                self.assertEqual(set(initial), {"telemetry", "device", "vision", "anomaly", "system",
                                                "history", "anomaly_history", "alerts",
                                                "alarm_command", "alarm_command_ts"})
                self.assertIsNone(initial["alarm_command"])
                self.assertIsNone(initial["alarm_command_ts"])
                for topic, payload in ((TELEMETRY_TOPIC, telemetry()), (VISION_TOPIC, vision())):
                    app.state.mqtt.events.put_nowait(MQTTEvent(topic, json.dumps(payload).encode()))
                    update = ws.receive_json()["data"]
                self.enqueue(app, 0)
                warning = ws.receive_json()["data"]
                self.assertEqual(warning["alerts"][0]["severity"], "warning")
                self.enqueue(app, 1)
                critical = ws.receive_json()["data"]
                self.assertEqual(critical["alerts"][0]["severity"], "critical")
                self.assertEqual(critical["telemetry"], update["telemetry"])
                self.assertEqual(critical["vision"], update["vision"])
                self.assertEqual(client.get("/api/v1/state").json(), critical)
                self.assertEqual(client.get("/api/v1/ai/status").json()["vision"], critical["vision"])
                self.assertEqual(set(critical["anomaly"]), {"ts", "anomaly", "ready", "score", "model", "features"})
                history = client.get("/api/v1/history/alerts").json()["items"]
                self.assertIn(critical["alerts"][0], [entry["data"] for entry in history])
                self.assertEqual(len(client.get("/api/v1/history/anomalies").json()["items"]), 2)
                self.assertEqual(app.state.mqtt.commands, [])
                for second in (2, 3, 4):
                    self.enqueue(app, second)
                    ws.receive_json()
                self.assertEqual(len(self.critical(client)), 1)
                # Its own critical MQTT echo remains deduplicated.
                payload = critical["alerts"][0].copy()
                payload.pop("id")
                app.state.mqtt.events.put_nowait(MQTTEvent(ALERTS_TOPIC, json.dumps(payload).encode()))
                self.enqueue(app, 5)
                ws.receive_json()
                self.assertEqual(len(self.critical(client)), 1)
            self.assertEqual(client.get("/health").status_code, 200)

    def test_enabled_pulse_once_and_new_episode_after_two_normal_results(self):
        app = self.app(enabled=True, limit=1)
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            self.enqueue(app, 0, False)
            self.enqueue(app, 1)
            self.wait(lambda: len(app.state.store.anomaly_history) == 1 and app.state.store.anomaly.anomaly)
            self.assertEqual(app.state.mqtt.commands, [])
            self.enqueue(app, 2)
            self.wait(lambda: len(app.state.mqtt.commands) == 1)
            self.assertEqual(app.state.mqtt.commands[0], {"buzzer": True, "led": "red"})
            for second in (3, 4, 5):
                self.enqueue(app, second)
            self.wait(lambda: app.state.store.anomaly.ts == self.base + timedelta(seconds=5))
            self.assertEqual(len(app.state.mqtt.commands), 1)
            self.assertEqual(len(self.critical(client)), 1)
            for second, abnormal in ((6, False), (7, False), (8, True), (9, True)):
                self.enqueue(app, second, abnormal)
            self.wait(lambda: len(self.critical(client)) == 2 and not app.state.alarm._starts)
            self.assertEqual(len(app.state.store.anomaly_history), 1)
            self.assertEqual(len(app.state.environment.state["window"]), 3)
            self.assertEqual(len(client.get("/api/v1/history/anomalies").json()["items"]), 10)

    def test_intermittent_positives_are_grouped_until_episode_rearms(self):
        app = self.app()
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            with client.websocket_connect("/ws") as ws:
                ws.receive_json()
                for second, abnormal in enumerate((True, True, False, True, False, True)):
                    self.enqueue(app, second, abnormal)
                    state = ws.receive_json()["data"]
                environmental = [alert for alert in state["alerts"]
                                 if alert["type"] == "ENVIRONMENTAL_ANOMALY"]
                self.assertEqual([alert["severity"] for alert in environmental], ["critical", "warning"])
                durable = client.get("/api/v1/history/alerts").json()["items"]
                self.assertEqual(len([entry for entry in durable
                                     if entry["data"]["type"] == "ENVIRONMENTAL_ANOMALY"]), 2)
                for second, abnormal in ((6, False), (7, False), (8, True)):
                    self.enqueue(app, second, abnormal)
                    state = ws.receive_json()["data"]
                environmental = [alert for alert in state["alerts"]
                                 if alert["type"] == "ENVIRONMENTAL_ANOMALY"]
                self.assertEqual([alert["severity"] for alert in environmental], ["warning", "critical", "warning"])
                durable = client.get("/api/v1/history/alerts").json()["items"]
                warnings = [entry for entry in durable if entry["data"]["type"] == "ENVIRONMENTAL_ANOMALY"
                            and entry["data"]["severity"] == "warning"]
                self.assertEqual(len(warnings), 2)
                published = [alert for alert in app.state.mqtt.alerts if alert["type"] == "environmental_anomaly"]
                self.assertEqual(len(published), 3)
                self.assertEqual(app.state.mqtt.commands, [])

    def test_critical_episode_double_beeps_and_keeps_durable_analysis(self):
        app = self.app(enabled=True)
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            self.enqueue(app, 0)
            self.enqueue(app, 1)
            self.wait(lambda: len(app.state.mqtt.commands) >= 4)
            self.assertEqual(app.state.mqtt.commands[:4], [
                {"buzzer": True, "led": "red"},
                {"buzzer": False, "led": "red"},
                {"buzzer": True, "led": "red"},
                {"buzzer": False, "led": "red"},
            ])
            self.assertEqual(len(self.critical(client)), 1)
            self.assertTrue(app.state.environment.state["critical_active"])
            self.assertEqual(len(client.get("/api/v1/history/anomalies").json()["items"]), 2)
            alerts = client.get("/api/v1/history/alerts").json()["items"]
            self.assertEqual(len([row for row in alerts if row["data"]["severity"] == "critical"]), 1)
            self.assertTrue(client.get("/api/v1/ai/status").json()["anomaly"]["ready"])

    def test_critical_grouping_preserves_other_models_legacy_warning_alerts(self):
        app = self.app()
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            with client.websocket_connect("/ws") as ws:
                ws.receive_json()
                for second, abnormal in ((0, True), (1, True), (2, False)):
                    self.enqueue(app, second, abnormal)
                    ws.receive_json()
                self.enqueue(app, 3, model="another_model")
                state = ws.receive_json()["data"]
                self.assertEqual(state["alerts"][0]["type"], "ENVIRONMENTAL_ANOMALY")
                self.assertEqual(state["alerts"][0]["severity"], "warning")
                self.assertTrue(app.state.environment.state["critical_active"])

    def test_critical_alert_and_physical_on_follow_database_commit(self):
        app = self.app(enabled=True)
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            self.enqueue(app, 0)
            self.wait(lambda: app.state.store.anomaly is not None)
            entered, release = Event(), Event()
            original = app.state.history.append
            async def blocked(*args):
                entered.set()
                while not release.is_set():
                    await asyncio.sleep(0.005)
                await original(*args)
            with client.websocket_connect("/ws") as ws, patch.object(app.state.history, "append", side_effect=blocked):
                ws.receive_json()
                try:
                    self.enqueue(app, 1)
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(self.critical(client), [])
                    self.assertEqual(app.state.mqtt.commands, [])
                finally:
                    release.set()
                critical = ws.receive_json()["data"]["alerts"][0]
                self.assertEqual(critical["severity"], "critical")
                history = client.get("/api/v1/history/alerts").json()["items"]
                self.assertIn(critical, [entry["data"] for entry in history])
                self.wait(lambda: len(app.state.mqtt.commands) == 1)

    def test_stale_after_delayed_database_commit_never_triggers_physical_on(self):
        app = self.app(enabled=True)
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            self.enqueue(app, 0)
            self.wait(lambda: app.state.store.anomaly is not None)
            original = app.state.history.append
            async def delayed(*args):
                await original(*args)
                # Simulates recovery from a long DB outage without waiting 30s.
                fake_datetime.now.return_value = self.base + timedelta(seconds=32)
            with patch("app.main.datetime") as fake_datetime, patch.object(app.state.history, "append", side_effect=delayed):
                fake_datetime.now.return_value = datetime.now(timezone.utc)
                self.enqueue(app, 1)
                self.wait(lambda: len(self.critical(client)) == 1 and not app.state.alarm._starts)
                self.assertEqual(app.state.mqtt.commands, [])

    def test_manual_stop_during_pending_critical_db_commit_prevents_late_ai_activation(self):
        app = self.app(enabled=True)
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            self.enqueue(app, 0)
            self.wait(lambda: app.state.store.anomaly is not None)
            entered, release = Event(), Event()
            original = app.state.history.append
            async def blocked(*args):
                entered.set()
                while not release.is_set():
                    await asyncio.sleep(0.005)
                await original(*args)
            with patch.object(app.state.history, "append", side_effect=blocked):
                try:
                    self.enqueue(app, 1)
                    self.assertTrue(entered.wait(2))
                    self.assertEqual(client.post("/api/v1/commands", json={"buzzer": False, "led": "green"}).status_code, 200)
                finally:
                    release.set()
                self.wait(lambda: len(self.critical(client)) == 1 and not app.state.alarm._starts)
                self.assertEqual(app.state.mqtt.commands, [{"buzzer": False, "led": "green"}])

    def test_restart_restores_episode_without_replaying_pulse_or_duplicate_critical_alert(self):
        with TemporaryDirectory() as directory:
            url = f"sqlite+aiosqlite:///{Path(directory) / 'history.db'}"
            app = self.app(enabled=True, limit=1, url=url)
            with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
                wait_connected(client)
                self.enqueue(app, 0)
                self.enqueue(app, 1)
                self.wait(lambda: len(app.state.mqtt.commands) == 1)
                old = self.critical(client)[0]
            restarted = self.app(enabled=True, limit=1, url=url)
            with patch("app.main.MQTTClient", FakeMQTT), TestClient(restarted) as client:
                wait_connected(client)
                self.assertEqual(restarted.state.mqtt.commands, [])
                self.enqueue(restarted, 2)
                self.wait(lambda: restarted.state.store.anomaly.ts == self.base + timedelta(seconds=2))
                self.assertEqual(self.critical(client), [old])
                self.assertEqual(restarted.state.mqtt.commands, [])

    def test_manual_alarm_survives_backend_restart_and_ai_cleanup(self):
        with TemporaryDirectory() as directory:
            url = f"sqlite+aiosqlite:///{Path(directory) / 'manual.db'}"
            app = self.app(enabled=True, url=url)
            with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
                wait_connected(client)
                command = {"buzzer": True, "led": "red"}
                self.assertEqual(client.post("/api/v1/commands", json=command).json()["command"], command)
            restarted = self.app(enabled=True, url=url)
            with patch("app.main.MQTTClient", FakeMQTT), TestClient(restarted) as client:
                wait_connected(client)
                self.assertEqual(restarted.state.mqtt.commands, [])
                self.enqueue(restarted, 0)
                self.enqueue(restarted, 1)
                self.wait(lambda: len(restarted.state.mqtt.commands) == 1)
                self.assertEqual(restarted.state.mqtt.commands[-1], command)
            self.assertTrue(all(item["buzzer"] for item in restarted.state.mqtt.commands))

    def test_wrong_model_calibration_stale_and_duplicate_results_cannot_pulse(self):
        app = self.app(enabled=True)
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            self.enqueue(app, 0, model="some_other_model")
            self.enqueue(app, 1, model="some_other_model")
            self.enqueue(app, 2, ready=False, anomaly=False, score=None)
            self.enqueue(app, -50)
            self.enqueue(app, 3)
            self.enqueue(app, 3)
            self.wait(lambda: len(client.get("/api/v1/history/anomalies").json()["items"]) == 6)
            self.assertEqual(self.critical(client), [])
            self.assertEqual(app.state.mqtt.commands, [])

    def test_manual_activation_database_failure_returns_503_without_untracked_output(self):
        app = self.app()
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            failure = OperationalError("private SQL", {}, Exception("unavailable"))
            with patch.object(app.state.alarm, "_persist", new=AsyncMock(side_effect=failure)):
                response = client.post("/api/v1/commands", json={"buzzer": True, "led": "red"})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(app.state.mqtt.commands, [])

    def test_uncertain_database_commit_retry_does_not_duplicate_critical_episode(self):
        app = self.app(enabled=True)
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            wait_connected(client)
            self.enqueue(app, 0)
            self.wait(lambda: app.state.store.anomaly is not None)
            original = app.state.history.append
            failed = Event()
            async def commit_then_fail(*args):
                await original(*args)
                if args[2].additional_alerts and not failed.is_set():
                    failed.set()
                    raise OperationalError("write", {}, Exception("lost commit acknowledgement"))
            with patch.object(app.state.history, "append", side_effect=commit_then_fail):
                self.enqueue(app, 1)
                self.assertTrue(failed.wait(2))
                self.wait(lambda: len(app.state.mqtt.commands) == 1)
                self.assertEqual(len(self.critical(client)), 1)
                persisted = client.get("/api/v1/history/alerts").json()["items"]
                critical = [entry for entry in persisted if entry["data"]["type"] == "ENVIRONMENTAL_ANOMALY"
                            and entry["data"]["severity"] == "critical"]
                self.assertEqual(len(critical), 1)


if __name__ == "__main__":
    unittest.main()
