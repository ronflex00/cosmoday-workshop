import json
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.main import create_app
from app.models.schemas import TELEMETRY_TOPIC
from app.services.history import HistoryStore
from app.services.state import StateService
from test_api import FakeMQTT
import test_history_api as history_tests
from test_schemas import telemetry


class TrendStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_samples_summarized_without_raw_rows_and_restart_merges(self):
        history = HistoryStore("sqlite:///:memory:", trends_only=True)
        state = StateService()
        minute = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)
        try:
            await history.initialize()
            for i, (temp, motion) in enumerate([(20, False), (30, True), (10, False)]):
                sample = dict(telemetry(), temperature=temp, motion=motion)
                change = state.prepare_message(TELEMETRY_TOPIC, json.dumps(sample).encode())
                await history.append(str(i), minute + timedelta(seconds=i), change)
                state.apply_change(change)
            self.assertEqual(len(state.history), 3)
            self.assertEqual(state.telemetry.temperature, 10)
            self.assertEqual((await history.page("telemetry")).items, [])
            await history.flush_trends(now=minute + timedelta(seconds=50))
            self.assertEqual((await history.page("telemetry_trends")).items, [])
            await history.flush_trends(final=True, now=minute)
            item = (await history.page("telemetry_trends")).items[0]
            summary = item.data
            self.assertEqual(summary.sample_count, 3)
            self.assertEqual(summary.temperature, 20)
            self.assertEqual(summary.minimum.temperature, 10)
            self.assertEqual(summary.maximum.temperature, 30)
            self.assertEqual(summary.motion_count, 1)
            self.assertEqual(summary.motion_transitions, 2)
            self.assertTrue(summary.motion)
            # Simulate restart / delayed event after the partial minute was saved.
            sample = dict(telemetry(), temperature=40, motion=True)
            change = state.prepare_message(TELEMETRY_TOPIC, json.dumps(sample).encode())
            await history.append("new", minute + timedelta(seconds=55), change)
            await history.flush_trends(now=minute + timedelta(minutes=1))
            items = (await history.page("telemetry_trends")).items
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].id, item.id)
            self.assertEqual(items[0].data.sample_count, 4)
            self.assertEqual(items[0].data.temperature, 25)
            self.assertEqual(items[0].data.maximum.temperature, 40)
            restored = StateService()
            await history.restore(restored)
            self.assertIsNone(restored.telemetry)
        finally:
            await history.close()

    async def test_separate_devices_minutes_and_retry(self):
        history = HistoryStore("sqlite:///:memory:", trends_only=True)
        state = StateService()
        minute = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)
        try:
            await history.initialize()
            for i, (device, offset) in enumerate([("one", 0), ("two", 0), ("one", 60)]):
                change = state.prepare_message(TELEMETRY_TOPIC, json.dumps(dict(telemetry(), device_id=device)).encode())
                await history.append(str(i), minute + timedelta(seconds=offset), change)
            with patch.object(type(history.engine), "begin", side_effect=OperationalError("test", {}, Exception("offline"))):
                with self.assertRaises(OperationalError):
                    await history.flush_trends(final=True)
            self.assertEqual(len(history._minutes), 3)
            await history.flush_trends(final=True)
            await history.flush_trends(final=True)
            self.assertEqual(len((await history.page("telemetry_trends")).items), 3)
            self.assertEqual(len((await history.page("telemetry_trends", device_id="one")).items), 2)
        finally:
            await history.close()


class TrendLiveTests(unittest.TestCase):
    def test_every_sample_reaches_live_state_and_summary_is_exposed(self):
        app = create_app(Settings(database_url="sqlite:///:memory:", telemetry_storage="trends"))
        helpers = history_tests.HistoryAPITests()
        with patch("app.main.MQTTClient", FakeMQTT), TestClient(app) as client:
            for value in (21, 22, 23):
                helpers.enqueue(app, TELEMETRY_TOPIC, dict(telemetry(), temperature=value))
                helpers.wait_state(client, lambda state: state["telemetry"] and state["telemetry"]["temperature"] == value)
            self.assertEqual(client.get("/api/v1/history/telemetry").json()["items"], [])
            with client.websocket_connect("/ws") as socket:
                self.assertEqual(socket.receive_json()["data"]["telemetry"]["temperature"], 23)
            # Starlette TestClient portal runs the coroutine on the app's event loop.
            client.portal.call(lambda: app.state.history.flush_trends(final=True))
            data = client.get("/api/v1/history/telemetry_trends").json()
            self.assertEqual(data["items"][0]["data"]["sample_count"], 3)
            self.assertEqual(data["items"][0]["data"]["temperature"], 22)
            self.assertEqual(data["items"][0]["data"]["maximum"]["temperature"], 23)
