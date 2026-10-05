import json
import unittest
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

from app.config import Settings
from app.models.schemas import INPUT_TOPICS, TELEMETRY_TOPIC, Command
from app.mqtt.client import MQTTClient, MQTTEvent


class MQTTTests(unittest.TestCase):
    def test_reconnection_subscribes_to_all_topics(self):
        events = Queue(maxsize=8)
        client = MQTTClient(Settings(), events)
        transport = Mock()
        transport.subscribe.return_value = (0, 1)
        reason = SimpleNamespace(is_failure=False)
        client._on_connect(transport, None, None, reason, None)
        client._on_disconnect(transport, None, None, reason, None)
        client._on_connect(transport, None, None, reason, None)
        self.assertEqual(transport.subscribe.call_count, 2)
        transport.subscribe.assert_called_with([(topic, 0) for topic in INPUT_TOPICS])
        self.assertEqual([events.get_nowait().payload for _ in range(3)], [True, False, True])

    def test_message_callbacks_enqueue_without_mutating_state(self):
        events = Queue(maxsize=1)
        client = MQTTClient(Settings(), events)
        message = SimpleNamespace(topic=TELEMETRY_TOPIC, payload=b"invalid JSON")
        client._on_message(None, None, message)
        self.assertEqual(events.get_nowait(), MQTTEvent(TELEMETRY_TOPIC, b"invalid JSON"))

    def test_connection_status_survives_a_full_queue(self):
        events = Queue(maxsize=1)
        events.put(MQTTEvent(TELEMETRY_TOPIC, b"data"))
        client = MQTTClient(Settings(), events)
        client._enqueue(MQTTEvent(None, False))
        self.assertEqual(events.get_nowait(), MQTTEvent(None, False))

    def test_command_is_published_without_retain_and_waits_for_delivery(self):
        client = MQTTClient(Settings(), Queue())
        client.client = Mock()
        client.client.is_connected.return_value = True
        info = Mock(rc=0)
        info.is_published.return_value = True
        client.client.publish.return_value = info
        command = Command(buzzer=True, led="red")
        self.assertTrue(client.publish_command(command))
        args, kwargs = client.client.publish.call_args
        self.assertEqual(args[0], "sentinel/commands")
        self.assertEqual(json.loads(args[1]), {"buzzer": True, "led": "red"})
        self.assertEqual(kwargs, {"qos": 0, "retain": False})
        info.wait_for_publish.assert_called_once_with(timeout=2.0)

    def test_command_offline_failed_or_timed_out_is_not_successful(self):
        client = MQTTClient(Settings(), Queue())
        client.client = Mock()
        command = Command(buzzer=False, led="green")
        client.client.is_connected.return_value = False
        self.assertFalse(client.publish_command(command))
        client.client.publish.assert_not_called()
        client.client.is_connected.return_value = True
        client.client.publish.return_value = Mock(rc=4)
        self.assertFalse(client.publish_command(command))
        info = Mock(rc=0)
        info.is_published.return_value = False
        client.client.publish.return_value = info
        self.assertFalse(client.publish_command(command))
        info.wait_for_publish.side_effect = RuntimeError("Disconnected")
        with self.assertLogs("MQTT", level="WARNING"):
            self.assertFalse(client.publish_command(command))


if __name__ == "__main__":
    unittest.main()
