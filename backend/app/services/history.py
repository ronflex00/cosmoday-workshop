"""Durable validated events, shared by PostgreSQL and local SQLite storage."""

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from sqlalchemy import (JSON, BigInteger, Column, DateTime, Index, Integer, MetaData,
                        String, Table, Text, UniqueConstraint, select)
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.exc import SQLAlchemyError

from ..config import database_url
from ..models.schemas import (ALERTS_TOPIC, ANOMALY_TOPIC, TELEMETRY_TOPIC, VISION_TOPIC,
                              Alert, AnomalyResult, HistoryEntry, HistoryKind, HistoryPage,
                              SensorTelemetry, TelemetryTrend, VisionResult)
from .state import StateChange, StateService
from .trends import Minute

metadata = MetaData()
events = Table(
    "sentinel_history", metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True),
    Column("event_id", String(36), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("topic", String(128), nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
    Column("device_id", Text),
    Column("device_key", String(64)),
    Column("data", JSON, nullable=False),
    UniqueConstraint("event_id", "kind", name="uq_sentinel_history_event_kind"),
    Index("ix_sentinel_history_kind_id", "kind", "id"),
    Index("ix_sentinel_history_kind_ts", "kind", "ts"),
    Index("ix_sentinel_history_device_key", "kind", "device_key", "id"),
)
intelligence_state = Table(
    "sentinel_environment_state", metadata,
    Column("key", String(32), primary_key=True),
    Column("data", JSON, nullable=False),
)
KINDS = {TELEMETRY_TOPIC: "telemetry", VISION_TOPIC: "vision", ANOMALY_TOPIC: "anomalies"}
SCHEMAS = {"telemetry": SensorTelemetry, "vision": VisionResult,
           "anomalies": AnomalyResult, "alerts": Alert, "telemetry_trends": TelemetryTrend}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class HistoryStore:
    def __init__(self, url: str, *, trends_only: bool = False):
        url = database_url(url)
        parsed = make_url(url)
        if parsed.drivername == "sqlite+aiosqlite" and parsed.database != ":memory:":
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        options = {"timeout": 5, "command_timeout": 5} if parsed.drivername == "postgresql+asyncpg" else {"timeout": 5}
        self.engine = create_async_engine(url, pool_pre_ping=True, hide_parameters=True, connect_args=options)
        self.available = False
        # Protects SQLite's shared in-memory connection in isolated tests too.
        self._lock = asyncio.Lock()
        self.trends_only = trends_only
        self._minutes: dict[tuple[str, datetime], Minute] = {}

    async def initialize(self) -> None:
        async with self.engine.begin() as connection:
            if self.engine.dialect.name == "sqlite":
                await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            await connection.run_sync(metadata.create_all)
        self.available = True

    @staticmethod
    def _record(event_id: str, kind: str, topic: str, received_at: datetime, payload) -> dict:
        device_id = getattr(payload, "device_id", None)
        return {"event_id": event_id, "kind": kind, "topic": topic, "ts": payload.ts,
                "received_at": received_at, "device_id": device_id,
                "device_key": sha256(device_id.encode()).hexdigest() if device_id is not None else None,
                "data": payload.model_dump(mode="json")}

    async def _write(self, rows: list[dict], environment_state: dict | None = None) -> None:
        insert = postgres_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
        async with self._lock, self.engine.begin() as connection:
            if rows:
                statement = insert(events).values(rows).on_conflict_do_nothing(index_elements=["event_id", "kind"])
                await connection.execute(statement)
            if environment_state is not None:
                statement = insert(intelligence_state).values(key="episode", data=environment_state)
                await connection.execute(statement.on_conflict_do_update(
                    index_elements=["key"], set_={"data": statement.excluded.data}))
        self.available = True

    async def append(self, event_id: str, received_at: datetime, change: StateChange) -> None:
        rows = []
        aggregate = self.trends_only and change.topic == TELEMETRY_TOPIC
        if change.topic in KINDS and not aggregate:
            rows.append(self._record(event_id, KINDS[change.topic], change.topic, received_at, change.message))
        if change.alert is not None:
            alert_event_id = change.alert.id if change.topic == ALERTS_TOPIC else event_id
            rows.append(self._record(alert_event_id, "alerts", ALERTS_TOPIC, received_at, change.alert))
        for alert in change.additional_alerts:
            rows.append(self._record(alert.id, "alerts", ALERTS_TOPIC, received_at, alert))
        if rows or change.environment_state is not None:
            await self._write(rows, change.environment_state)

    async def environment_state(self, key: str) -> dict | None:
        async with self._lock, self.engine.connect() as connection:
            result = (await connection.execute(select(intelligence_state.c.data).where(
                intelligence_state.c.key == key))).scalar_one_or_none()
        return result

    async def save_alarm_state(self, state: dict) -> None:
        insert = postgres_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
        statement = insert(intelligence_state).values(key="manual", data=state)
        try:
            async with self._lock, self.engine.begin() as connection:
                await connection.execute(statement.on_conflict_do_update(
                    index_elements=["key"], set_={"data": statement.excluded.data}))
        except (SQLAlchemyError, OSError, TimeoutError):
            self.available = False
            raise
        self.available = True
        if aggregate:
            # After durable alert writes: retries cannot double-count a sample.
            start = utc(received_at).replace(second=0, microsecond=0)
            key = (change.message.device_id, start)
            if key not in self._minutes:
                minute = Minute(change.message.device_id, start)
                async with self._lock, self.engine.connect() as connection:
                    existing = await connection.scalar(select(events.c.data).where(
                        events.c.event_id == minute.event_id, events.c.kind == "telemetry_trends"))
                if existing is not None:
                    minute.resume(TelemetryTrend.model_validate(existing))
                self._minutes[key] = minute
            self._minutes[key].add(change.message)

    async def flush_trends(self, *, now: datetime | None = None, final: bool = False) -> None:
        cutoff = utc(now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
        pending = [(key, minute, minute.count) for key, minute in self._minutes.items()
                   if final or minute.start < cutoff]
        if not pending:
            return
        rows = [self._record(minute.event_id, "telemetry_trends", TELEMETRY_TOPIC,
                             cutoff, minute.summary()) for _, minute, _ in pending]
        insert = postgres_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
        statement = insert(events).values(rows)
        statement = statement.on_conflict_do_update(
            index_elements=["event_id", "kind"],
            set_={"data": statement.excluded.data, "received_at": statement.excluded.received_at},
        )
        async with self._lock, self.engine.begin() as connection:
            await connection.execute(statement)
        for key, minute, count in pending:
            if minute.count == count:
                self._minutes.pop(key, None)
        self.available = True

    async def append_alert(self, alert: Alert) -> None:
        await self._write([self._record(alert.id, "alerts", ALERTS_TOPIC, datetime.now(timezone.utc), alert)])

    async def page(self, kind: HistoryKind, *, limit: int = 100, before_id: int | None = None,
                   start: datetime | None = None, end: datetime | None = None,
                   device_id: str | None = None) -> HistoryPage:
        query = select(events).where(events.c.kind == kind)
        if before_id is not None:
            query = query.where(events.c.id < before_id)
        if start is not None:
            query = query.where(events.c.ts >= utc(start))
        if end is not None:
            query = query.where(events.c.ts <= utc(end))
        if device_id is not None:
            # Fixed-width index keeps every valid device ID compatible with PostgreSQL.
            query = query.where(events.c.device_key == sha256(device_id.encode()).hexdigest(),
                                events.c.device_id == device_id)
        query = query.order_by(events.c.id.desc()).limit(limit + 1)
        async with self._lock, self.engine.connect() as connection:
            rows = (await connection.execute(query)).mappings().all()
        self.available = True
        items = [HistoryEntry(id=row["id"], ts=utc(row["ts"]), received_at=utc(row["received_at"]),
                              topic=row["topic"], data=SCHEMAS[kind].model_validate(row["data"]))
                 for row in rows[:limit]]
        return HistoryPage(items=items, limit=limit,
                           next_before_id=items[-1].id if len(rows) > limit else None)

    async def restore(self, store: StateService) -> None:
        # A minute average must never be presented as a live sensor reading.
        telemetry = [] if self.trends_only else (await self.page("telemetry", limit=store.history.maxlen)).items
        vision = (await self.page("vision", limit=1)).items
        anomalies = (await self.page("anomalies", limit=store.anomaly_history.maxlen)).items
        alerts = (await self.page("alerts", limit=50)).items
        recent = [entry for group in (telemetry, vision, anomalies, alerts) for entry in group]
        last_update = max((entry.received_at for entry in recent), default=None)
        store.restore([entry.data for entry in reversed(telemetry)], vision[0].data if vision else None,
                      [entry.data for entry in reversed(anomalies)],
                      [entry.data for entry in reversed(alerts)], last_update)

    async def close(self) -> None:
        await self.engine.dispose()
