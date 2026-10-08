import os
import unittest
from unittest.mock import patch

from app.config import BACKEND_DIR, Settings


class ConfigTests(unittest.TestCase):
    def test_auto_alarm_defaults_off_and_accepts_only_valid_boolean_values(self):
        with patch.dict(os.environ, {}, clear=True), patch("app.config.load_dotenv"):
            self.assertFalse(Settings.from_env().ai_auto_alarm)
            for value in ("true", "1", "yes"):
                with patch.dict(os.environ, {"AI_AUTO_ALARM": value}):
                    self.assertTrue(Settings.from_env().ai_auto_alarm)
            with patch.dict(os.environ, {"AI_AUTO_ALARM": "perhaps"}), self.assertRaises(ValueError):
                Settings.from_env()

    def test_database_urls_and_password_redaction(self):
        with patch.dict(os.environ, {}, clear=True), patch("app.config.load_dotenv"):
            self.assertEqual(Settings.from_env().database_url, f"sqlite+aiosqlite:///{BACKEND_DIR / 'data/sentinel.db'}")
            os.environ["DATABASE_URL"] = "postgresql://sentinel:private-password@localhost:5432/sentinel"
            settings = Settings.from_env()
            self.assertTrue(settings.database_url.startswith("postgresql+asyncpg://"))
            self.assertNotIn("private-password", repr(settings))
            os.environ["DATABASE_URL"] = "sqlite:///data/other.db"
            self.assertEqual(Settings.from_env().database_url, f"sqlite+aiosqlite:///{BACKEND_DIR / 'data/other.db'}")
            for value in ("bad", "mysql://user:secret@host/db", "sqlite://host/db", "postgresql://host"):
                with self.subTest(value=value), patch.dict(os.environ, {"DATABASE_URL": value}), self.assertRaises(ValueError):
                    Settings.from_env()

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
