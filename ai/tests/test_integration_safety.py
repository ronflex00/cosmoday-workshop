"""Critical deployment configuration and cleanup; no hardware or broker required."""

import os
import ssl
import unittest
from unittest.mock import Mock, patch

from src.common.mqtt_client import MQTTClient
from src.config import Config
from src.main import main


class IntegrationSafetyTests(unittest.TestCase):
    def test_environment_defaults_and_tls_port_override(self):
        with patch.dict(os.environ, {}, clear=True), patch("src.config.load_dotenv"):
            config = Config.from_env()
            self.assertEqual((config.mqtt_port, config.training_samples, config.log_level), (1883, 20, "INFO"))
            os.environ.update(MQTT_TLS="true", MQTT_TLS_PORT="9999")
            self.assertEqual(Config.from_env().mqtt_port, 8883)
            os.environ.update(MQTT_PORT="8884", AI_LOG_LEVEL="debug")
            config = Config.from_env()
            self.assertTrue(config.mqtt_tls)
            self.assertEqual(config.mqtt_port, 8884)
            self.assertEqual(config.log_level, "DEBUG")
            for change in ({"AI_CONTAMINATION": "nan"}, {"AI_TRAINING_SAMPLES": "1"},
                           {"MQTT_TLS_CERT": "client.crt"}, {"AI_LOG_LEVEL": "unknown"}):
                with self.subTest(change=change), patch.dict(os.environ, change), self.assertRaises(ValueError):
                    Config.from_env()

    def test_real_tls_context_verifies_server_and_hostname(self):
        client = MQTTClient(Config(mqtt_tls=True, mqtt_port=8883))
        context = client.client._ssl_context
        self.assertIsNotNone(context)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_tls_certificate_paths_are_passed_to_paho(self):
        config = Config(mqtt_tls=True, mqtt_tls_ca="ca.crt",
                        mqtt_tls_cert="client.crt", mqtt_tls_key="client.key")
        with patch("src.common.mqtt_client.mqtt.Client") as constructor:
            MQTTClient(config)
        constructor.return_value.tls_set.assert_called_once_with(
            ca_certs="ca.crt", certfile="client.crt", keyfile="client.key")
        constructor.return_value.tls_insecure_set.assert_not_called()

    def test_network_loop_stops_even_when_disconnect_fails(self):
        client = MQTTClient(Config())
        client.client = Mock()
        client.client.disconnect.side_effect = OSError("disconnect failed")
        client.connected.set()
        client.subscribed.set()
        with self.assertRaises(OSError):
            client.stop()
        client.client.loop_stop.assert_called_once()
        self.assertFalse(client.connected.is_set())
        self.assertFalse(client.subscribed.is_set())

    def test_camera_failure_still_stops_worker_and_mqtt(self):
        with patch("src.main.Config.from_env", return_value=Config()), \
                patch("src.main.MQTTClient") as client, \
                patch("src.main.PersonDetector"), patch("src.main.Camera") as camera:
            camera.return_value.open.side_effect = RuntimeError("camera missing")
            camera.return_value.close.side_effect = RuntimeError("release failed")
            with self.assertLogs(level="ERROR"):
                self.assertEqual(main(), 1)
            client.return_value.stop.assert_called_once()

    def test_worker_start_failure_does_not_join_unstarted_thread(self):
        worker = Mock(ident=None)
        worker.start.side_effect = RuntimeError("worker failed to start")
        with patch("src.main.Config.from_env", return_value=Config()), \
                patch("src.main.MQTTClient") as client, patch("src.main.Thread", return_value=worker):
            with self.assertLogs("AI", level="ERROR"):
                self.assertEqual(main(), 1)
            worker.join.assert_not_called()
            client.return_value.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
