import json
import unittest

from app.models.schemas import ANOMALY_TOPIC, VISION_TOPIC, AlertCreate
from app.services.state import StateService
from test_schemas import anomaly, vision


class AlertTests(unittest.TestCase):
    def test_intrusion_only_on_activation_including_first_positive_detection(self):
        store = StateService()
        for detected in (True, True, True, False, True, True):
            store.apply_message(VISION_TOPIC, json.dumps(vision(person_detected=detected)).encode())
        alerts = store.alerts.recent()
        self.assertEqual(len(alerts), 2)
        self.assertTrue(all(alert.type == "INTRUSION" and alert.severity == "critical" for alert in alerts))
        self.assertNotEqual(alerts[0].id, alerts[1].id)

    def test_environment_calibration_and_repeated_positive_results(self):
        store = StateService()
        for _ in range(20):
            store.apply_message(ANOMALY_TOPIC, json.dumps(anomaly(ready=False, anomaly=False, score=None)).encode())
        self.assertEqual(store.alerts.recent(), [])
        for detected in (False, True, True, False, True):
            store.apply_message(ANOMALY_TOPIC, json.dumps(anomaly(anomaly=detected)).encode())
        alerts = store.alerts.recent()
        self.assertEqual(len(alerts), 2)
        self.assertTrue(all(alert.type == "ENVIRONMENTAL_ANOMALY" for alert in alerts))

    def test_invalid_detection_does_not_trigger_alert(self):
        store = StateService()
        with self.assertLogs("MQTT", level="WARNING"):
            self.assertFalse(store.apply_message(VISION_TOPIC, json.dumps(vision(confidence=2)).encode()))
        self.assertEqual(store.alerts.recent(), [])
        self.assertIsNone(store.vision)

    def test_system_alerts_only_for_connection_changes(self):
        store = StateService()
        changes = [store.set_mqtt_connected(connected) for connected in
                   (False, False, True, True, False, False, True)]
        self.assertEqual(changes, [False, False, True, False, True, False, True])
        alerts = store.alerts.recent()
        self.assertEqual([alert.severity for alert in alerts], ["info", "warning", "info"])
        self.assertTrue(all(alert.type == "SYSTEM" for alert in alerts))

    def test_history_keeps_50_newest_alerts_and_mqtt_uses_common_contract(self):
        store = StateService()
        for index in range(55):
            store.add_alert(AlertCreate(ts="2026-10-05T14:30:00Z", type="intrusion",
                                        severity="critical", message=str(index)))
        snapshot = store.snapshot()
        self.assertEqual(len(snapshot.alerts), 50)
        self.assertEqual(snapshot.alerts[0].message, "54")
        self.assertEqual(snapshot.alerts[-1].message, "5")
        self.assertEqual(snapshot.alerts[0].mqtt_payload(), {
            "ts": "2026-10-05T14:30:00Z", "type": "intrusion",
            "severity": "critical", "message": "54"})
        snapshot.alerts.clear()
        self.assertEqual(len(store.alerts.recent()), 50)


if __name__ == "__main__":
    unittest.main()
