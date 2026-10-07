"""Offline, transactional import of existing SQLite history into PostgreSQL."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from sqlalchemy import func, insert, select, text

from .config import Settings
from .services.history import HistoryStore, events, utc


def snapshot(source: Path) -> Path:
    if not source.is_file():
        raise ValueError("SQLite source does not exist; no migration performed")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = source.with_name(f"sentinel-backup-{stamp}.db")
    with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as reader:
        with sqlite3.connect(backup) as writer:
            reader.backup(writer)
    return backup


async def import_history(backup: Path, connection) -> int:
    if await connection.scalar(select(func.count()).select_from(events)):
        raise ValueError("Destination history is not empty; import refused")
    if connection.dialect.name == "postgresql":
        # Prevent concurrent writers until commit, including accidental API startup.
        await connection.execute(text("LOCK TABLE sentinel_history IN ACCESS EXCLUSIVE MODE"))
        if await connection.scalar(select(func.count()).select_from(events)):
            raise ValueError("Destination history is not empty; import refused")
    count = 0
    with sqlite3.connect(backup.resolve().as_uri() + "?mode=ro", uri=True) as reader:
        reader.row_factory = sqlite3.Row
        cursor = reader.execute("SELECT * FROM sentinel_history ORDER BY id")
        while batch := cursor.fetchmany(250):
            rows = []
            for row in batch:
                item = dict(row)
                item["data"] = json.loads(item["data"])
                for key in ("ts", "received_at"):
                    item[key] = utc(datetime.fromisoformat(item[key]))
                rows.append(item)
            await connection.execute(insert(events), rows)
            count += len(rows)
    if await connection.scalar(select(func.count()).select_from(events)) != count:
        raise ValueError("Imported row count does not match")
    if connection.dialect.name == "postgresql":
        await connection.execute(text(
            "SELECT setval(pg_get_serial_sequence('sentinel_history', 'id'), "
            "COALESCE((SELECT max(id) FROM sentinel_history), 1), "
            "EXISTS(SELECT 1 FROM sentinel_history))"
        ))
    return count


async def migrate(source: Path) -> None:
    store = HistoryStore(Settings.from_env().database_url)
    try:
        if store.engine.dialect.name != "postgresql":
            raise ValueError("Migration destination must be PostgreSQL")
        backup = snapshot(source)
        print(f"SQLite backup preserved: {backup}", flush=True)
        await store.initialize()
        async with store.engine.begin() as connection:
            count = await import_history(backup, connection)
        print(f"Migration committed: {count} rows; IDs and timestamps preserved")
    finally:
        await store.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/app/data/sentinel.db"))
    args = parser.parse_args()
    try:
        asyncio.run(migrate(args.source))
    except ValueError as exc:
        parser.exit(1, f"Migration refused: {exc}\n")
    except Exception:
        parser.exit(1, "Migration failed; transaction rolled back. Check DB availability and schema.\n")


if __name__ == "__main__":
    main()
