import json
from datetime import datetime
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from app.config import configured_database_url
from app.migrate_sqlite import import_history, snapshot
from app.services.history import HistoryStore, events


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_copy_preserves_ids_and_refuses_nonempty_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "old.db"
            old = HistoryStore(f"sqlite:///{source.as_posix()}")
            await old.initialize()
            row = dict(id=42, event_id="event-42", kind="telemetry", topic="sentinel/telemetry",
                       ts=datetime(2026, 10, 7),
                       received_at=datetime(2026, 10, 7),
                       device_id="sentinel-01", device_key="abc", data={"motion": True})
            async with old.engine.begin() as connection:
                await connection.execute(events.insert(), row)
            backup = snapshot(source)
            await old.close()
            target = HistoryStore("sqlite:///:memory:")
            try:
                await target.initialize()
                async with target.engine.begin() as connection:
                    self.assertEqual(await import_history(backup, connection), 1)
                    imported = (await connection.execute(select(events))).mappings().one()
                    self.assertEqual(imported["id"], 42)
                    self.assertEqual(imported["data"], {"motion": True})
                with self.assertRaises(ValueError):
                    async with target.engine.begin() as connection:
                        await import_history(backup, connection)
                self.assertTrue(source.is_file())
                self.assertTrue(backup.is_file())
            finally:
                await target.close()

    async def test_failed_import_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "broken.db"
            with closing(sqlite3.connect(source)) as connection, connection:
                connection.execute("CREATE TABLE sentinel_history (id INTEGER, event_id TEXT, kind TEXT, topic TEXT, data TEXT, ts TEXT, received_at TEXT)")
                connection.executemany("INSERT INTO sentinel_history VALUES (?, ?, 'telemetry', 'sentinel/telemetry', ?, ?, ?)",
                                       [(i, f"event-{i}", json.dumps({}), "2026-10-07", "2026-10-07") for i in range(1, 251)])
                connection.execute("INSERT INTO sentinel_history VALUES (251, 'broken', 'telemetry', 'sentinel/telemetry', ?, 'invalid', 'invalid')", (json.dumps({}),))
            target = HistoryStore("sqlite:///:memory:")
            try:
                await target.initialize()
                with self.assertRaises(ValueError):
                    async with target.engine.begin() as connection:
                        await import_history(source, connection)
                async with target.engine.connect() as connection:
                    self.assertEqual(await connection.scalar(select(func.count()).select_from(events)), 0)
            finally:
                await target.close()

    def test_secret_password_escaping_and_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            secret = Path(directory) / "password"
            secret.write_text("a@:/?#% password\n", encoding="utf-8")
            with patch.dict(os.environ, {"DATABASE_PASSWORD_FILE": str(secret)}, clear=True):
                url = make_url(configured_database_url())
                self.assertEqual(url.password, "a@:/?#% password")
                self.assertEqual(url.host, "db")
                os.environ["DATABASE_URL"] = "sqlite:///:memory:"
                with self.assertRaises(ValueError):
                    configured_database_url()

    def test_missing_source_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "missing.db"
            with self.assertRaises(ValueError):
                snapshot(source)
            self.assertFalse(source.exists())
