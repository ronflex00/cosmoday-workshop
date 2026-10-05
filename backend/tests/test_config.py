import os
import unittest
from unittest.mock import patch

from app.config import Settings


class ConfigTests(unittest.TestCase):
    def test_defaults_overrides_and_invalid_config(self):
        with patch.dict(os.environ, {}, clear=True), patch("app.config.load_dotenv"):
            settings = Settings.from_env()
            self.assertEqual(settings.mqtt_port, 1883)
            self.assertEqual(settings.cors_origins, ("http://localhost:5173",))
            os.environ.update(MQTT_PORT="18883", API_PORT="8010", CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173")
            settings = Settings.from_env()
            self.assertEqual((settings.mqtt_port, settings.api_port), (18883, 8010))
            self.assertEqual(len(settings.cors_origins), 2)
            for change in ({"MQTT_PORT": "0"}, {"MQTT_TLS": "maybe"}, {"CORS_ORIGINS": "*"},
                           {"API_HISTORY_LIMIT": "121"}, {"MQTT_TLS_CERT": "client.crt"}):
                with self.subTest(change=change), patch.dict(os.environ, change), self.assertRaises(ValueError):
                    Settings.from_env()


if __name__ == "__main__":
    unittest.main()
