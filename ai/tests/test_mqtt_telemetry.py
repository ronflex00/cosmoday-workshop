import json
import unittest
from queue import Queue
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock

from src.anomaly.detector import AnomalyDetector
from src.anomaly.service import process_telemetry
from src.common.mqtt_client import MQTTClient
from src.common.schemas import TELEMETRY_TOPIC
from src.config import Config
from test_schemas import payload


class MQTTTelemetryTests(unittest.TestCase):
    def test_invalid_message_does_not_prevent_next_valid_message(self):
        queue = Queue(maxsize=2)
        client = MQTTClient(Config(), queue)
        with self.assertLogs("MQTT", level="WARNING"):
            client._on_message(None, None, SimpleNamespace(topic=TELEMETRY_TOPIC, payload=b"bad JSON"))
        self.assertTrue(queue.empty())
        client._on_message(None, None, SimpleNamespace(topic=TELEMETRY_TOPIC, payload=json.dumps(payload()).encode()))
        self.assertEqual(queue.get_nowait().temperature, 24.3)

    def test_queue_is_nonblocking_when_full(self):
        queue = Queue(maxsize=1)
        client = MQTTClient(Config(), queue)
        message = SimpleNamespace(topic=TELEMETRY_TOPIC, payload=json.dumps(payload()).encode())
        client._on_message(None, None, message)
        with self.assertLogs("MQTT", level="WARNING"):
            client._on_message(None, None, message)
        self.assertEqual(queue.qsize(), 1)

    def test_resubscribe_after_each_connection(self):
        client = MQTTClient(Config(), Queue(maxsize=1))
        connection = Mock()
        connection.subscribe.return_value = (0, 1)
        reason = SimpleNamespace(is_failure=False)
        client._on_connect(connection, None, None, reason, None)
        client._on_disconnect(connection, None, None, reason, None)
        client._on_connect(connection, None, None, reason, None)
        self.assertEqual(connection.subscribe.call_count, 2)
        connection.subscribe.assert_called_with(TELEMETRY_TOPIC, qos=0)

    def test_worker_recovers_and_stops(self):
        queue = Queue(maxsize=2)
        stop = Event()
        published = Event()
        detector = Mock(spec=AnomalyDetector)
        detector.analyze.side_effect = [RuntimeError("test failure"), SimpleNamespace(to_dict=lambda: {"ready": False})]
        client = Mock()
        client.publish_json.side_effect = lambda *args: published.set() or True
        queue.put(object())
        queue.put(object())
        worker = Thread(target=process_telemetry, args=(queue, detector, client, stop))
        try:
            with self.assertLogs("ANOMALY", level="ERROR"):
                worker.start()
                self.assertTrue(published.wait(5))
        finally:
            stop.set()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(detector.analyze.call_count, 2)


if __name__ == "__main__":
    unittest.main()
