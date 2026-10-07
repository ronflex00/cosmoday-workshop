import json
import unittest

from app.models.schemas import ANOMALY_TOPIC, TELEMETRY_TOPIC, VISION_TOPIC
from app.services.state import StateService
from test_schemas import anomaly, telemetry, vision


class StateTests(unittest.TestCase):
    def test_all_three_topics_update_state(self):
        store = StateService()
        store.set_mqtt_connected(True)
        for topic, payload in ((TELEMETRY_TOPIC, telemetry()), (VISION_TOPIC, vision()),
                               (ANOMALY_TOPIC, anomaly(ready=False, anomaly=False, score=None))):
            self.assertTrue(store.apply_message(topic, json.dumps(payload).encode()))
        state = store.snapshot().model_dump(mode="json")
        self.assertTrue(state["system"]["mqtt_connected"])
        self.assertEqual(state["vision"]["confidence"], 0.95)
        self.assertIsNone(state["anomaly"]["score"])
        self.assertEqual(len(state["history"]), 1)
        self.assertEqual(len(state["anomaly_history"]), 1)
        self.assertIsNotNone(state["system"]["last_update"])

    def test_anomaly_history_is_bounded_and_snapshotted(self):
        store = StateService(history_limit=3)
        for value in range(5):
            store.apply_message(ANOMALY_TOPIC, json.dumps(anomaly(
                ts=f"2026-10-05T14:30:{value:02d}Z",
                score=-0.1 * value,
                anomaly=value >= 3,
            )).encode())
        snapshot = store.snapshot()
        self.assertEqual(
            [round(result.score, 1) for result in snapshot.anomaly_history],
            [-0.2, -0.3, -0.4],
        )
        snapshot.anomaly_history.clear()
        self.assertEqual(len(store.anomaly_history), 3)

    def test_bad_payload_does_not_replace_valid_state(self):
        store = StateService()
        store.apply_message(TELEMETRY_TOPIC, json.dumps(telemetry()).encode())
        before = store.snapshot()
        for payload in (b"{broken", b"\xff", b"[]", b"null", b"{" * 16385,
                        json.dumps(telemetry(temperature="invalid")).encode()):
            with self.subTest(payload=payload[:20]), self.assertLogs("MQTT", level="WARNING"):
                self.assertFalse(store.apply_message(TELEMETRY_TOPIC, payload))
            self.assertEqual(store.snapshot(), before)

    def test_history_is_bounded_and_snapshot_is_independent(self):
        store = StateService(history_limit=3)
        for value in range(5):
            store.apply_message(TELEMETRY_TOPIC, json.dumps(telemetry(gas=value)).encode())
        snapshot = store.snapshot()
        self.assertEqual([point.gas for point in snapshot.history], [2, 3, 4])
        snapshot.history.clear()
        self.assertEqual(len(store.history), 3)
        store.set_mqtt_connected(False)
        self.assertEqual(store.snapshot().telemetry.gas, 4)
        self.assertFalse(store.snapshot().system.mqtt_connected)


if __name__ == "__main__":
    unittest.main()
