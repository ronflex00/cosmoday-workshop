import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from app.models.schemas import ANOMALY_TOPIC, TELEMETRY_TOPIC, VISION_TOPIC
from app.services.history import HistoryStore
from app.services.state import StateService
from test_schemas import anomaly, telemetry, vision


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.url = f"sqlite+aiosqlite:///{Path(self.directory.name) / 'history.db'}"
        self.history = HistoryStore(self.url)
        await self.history.initialize()
        self.store = StateService(history_limit=2)

    async def asyncTearDown(self):
        await self.history.close()
        self.directory.cleanup()

    async def ingest(self, topic, payload, event_id=None):
        change = self.store.prepare_message(topic, json.dumps(payload).encode())
        self.assertIsNotNone(change)
        await self.history.append(event_id or str(uuid4()), datetime.now(timezone.utc), change)
        self.store.apply_change(change)
        return change

    async def test_all_payloads_and_generated_alerts_round_trip(self):
        await self.ingest(TELEMETRY_TOPIC, telemetry())
        await self.ingest(VISION_TOPIC, vision())
        await self.ingest(ANOMALY_TOPIC, anomaly(ready=False, anomaly=False, score=None))
        await self.ingest(ANOMALY_TOPIC, anomaly())
        samples = (await self.history.page("telemetry")).items
        self.assertEqual(samples[0].data.device_id, "sentinel-01")
        self.assertEqual(samples[0].received_at.utcoffset().total_seconds(), 0)
        results = (await self.history.page("anomalies")).items
        self.assertTrue(results[0].data.anomaly)
        self.assertIsNone(results[1].data.score)
        self.assertFalse(results[1].data.ready)
        alerts = (await self.history.page("alerts")).items
        self.assertEqual([entry.data.type for entry in alerts], ["ENVIRONMENTAL_ANOMALY", "INTRUSION"])
        self.assertEqual(alerts[-1].data.id, self.store.alerts.recent()[-1].id)

    async def test_retry_is_idempotent_but_distinct_received_messages_are_saved(self):
        change = self.store.prepare_message(VISION_TOPIC, json.dumps(vision()).encode())
        key, received = str(uuid4()), datetime.now(timezone.utc)
        for _ in range(2):
            await self.history.append(key, received, change)
        self.assertEqual(len((await self.history.page("vision")).items), 1)
        self.assertEqual(len((await self.history.page("alerts")).items), 1)
        self.store.apply_change(change)
        await self.ingest(VISION_TOPIC, vision())
        self.assertEqual(len((await self.history.page("vision")).items), 2)
        self.assertEqual(len((await self.history.page("alerts")).items), 1)

    async def test_cursor_does_not_skip_or_repeat_data_during_new_insertions(self):
        for gas in range(5):
            await self.ingest(TELEMETRY_TOPIC, telemetry(gas=gas))
        first = await self.history.page("telemetry", limit=2)
        self.assertEqual([entry.data.gas for entry in first.items], [4, 3])
        await self.ingest(TELEMETRY_TOPIC, telemetry(gas=99))
        second = await self.history.page("telemetry", limit=2, before_id=first.next_before_id)
        third = await self.history.page("telemetry", limit=2, before_id=second.next_before_id)
        self.assertEqual([entry.data.gas for entry in second.items + third.items], [2, 1, 0])
        self.assertIsNone(third.next_before_id)

    async def test_time_and_device_filters_are_inclusive_and_parameterized(self):
        strange_id = "node' OR 1=1 --"
        for number in range(3):
            await self.ingest(TELEMETRY_TOPIC, telemetry(
                device_id=strange_id if number == 1 else "other",
                ts=f"2026-10-05T14:30:0{number}Z", gas=number))
        page = await self.history.page("telemetry", device_id=strange_id,
                                       start=datetime.fromisoformat("2026-10-05T16:30:01+02:00"),
                                       end=datetime.fromisoformat("2026-10-05T14:30:01+00:00"))
        self.assertEqual([entry.data.gas for entry in page.items], [1])

    async def test_close_and_reopen_restore_recent_cache_without_truncating_database(self):
        for gas in range(5):
            await self.ingest(TELEMETRY_TOPIC, telemetry(gas=gas))
            await self.ingest(ANOMALY_TOPIC, anomaly(score=gas / 10, anomaly=False))
        await self.ingest(VISION_TOPIC, vision())
        original_alert_id = self.store.alerts.latest.id
        await self.history.close()
        self.history = HistoryStore(self.url)
        await self.history.initialize()
        restored = StateService(history_limit=2)
        await self.history.restore(restored)
        self.assertEqual([entry.gas for entry in restored.history], [3, 4])
        self.assertEqual([entry.score for entry in restored.anomaly_history], [0.3, 0.4])
        self.assertTrue(restored.vision.person_detected)
        self.assertEqual(restored.alerts.latest.id, original_alert_id)
        self.assertFalse(restored.system.mqtt_connected)
        self.assertEqual(len((await self.history.page("telemetry")).items), 5)
        # Restarting does not turn an unchanged positive detection into a new intrusion.
        change = restored.prepare_message(VISION_TOPIC, json.dumps(vision()).encode())
        self.assertIsNone(change.alert)

    async def test_invalid_json_never_changes_live_state_or_database(self):
        for data in (b"{invalid", b"null", json.dumps(telemetry(gas=-1)).encode()):
            with self.assertLogs("MQTT", level="WARNING"):
                self.assertIsNone(self.store.prepare_message(TELEMETRY_TOPIC, data))
        self.assertEqual((await self.history.page("telemetry")).items, [])
        self.assertIsNone(self.store.telemetry)


if __name__ == "__main__":
    unittest.main()
