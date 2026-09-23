"""
PostgreSQL access.

The application talks to the database in two ways:

- Hand-written SQL through fetch / fetchrow / fetchval / execute, for anything
  that joins or aggregates (the analytics, mostly).
- Small helpers -- find_one, find, insert, update, upsert, delete, take -- for
  the plain "row by key" reads and writes that make up most of the app. They
  take a table name and dicts of column values, check every column name
  against the live schema, and always bind values as parameters.

Rows come back as dicts with dates and timestamps as ISO strings, which is the
shape the API has always returned, so routes and the frontend are unchanged.

`async with db.transaction():` makes every call inside it, from any function,
run on one connection in one transaction.
"""
import contextvars
import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

SCHEMA_PATH = ROOT_DIR / "schema.sql"

# Marks a "column IS NOT NULL" condition in a where dict.
NOT_NULL = object()


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _to_python(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _row(record) -> dict | None:
    if record is None:
        return None
    return {key: _to_python(value) for key, value in record.items()}


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class Database:
    def __init__(self):
        self.pool: asyncpg.Pool | None = None
        self.columns: dict[str, dict[str, str]] = {}
        self._tx: contextvars.ContextVar = contextvars.ContextVar("db_tx", default=None)

    # ---------- lifecycle ----------

    async def connect(self, url: str | None = None, *, min_size: int = 1, max_size: int = 10):
        async def init(conn):
            await conn.set_type_codec(
                "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
            )

        self.pool = await asyncpg.create_pool(
            url or database_url(), min_size=min_size, max_size=max_size, init=init
        )
        await self.apply_schema()

    async def apply_schema(self):
        async with self.pool.acquire() as conn:
            # Serialise concurrent start-ups; CREATE ... IF NOT EXISTS is not
            # safe to race.
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(7212026)")
                await conn.execute(SCHEMA_PATH.read_text())
        await self._load_columns()

    async def _load_columns(self):
        rows = await self.pool.fetch(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
            """
        )
        columns: dict[str, dict[str, str]] = {}
        for r in rows:
            columns.setdefault(r["table_name"], {})[r["column_name"]] = r["data_type"]
        self.columns = columns

    async def close(self):
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    # ---------- raw SQL ----------

    @asynccontextmanager
    async def _connection(self):
        conn = self._tx.get()
        if conn is not None:
            yield conn
            return
        if self.pool is None:
            raise RuntimeError("Database is not connected")
        async with self.pool.acquire() as conn:
            yield conn

    @asynccontextmanager
    async def transaction(self):
        if self._tx.get() is not None:
            # Already inside one: join it.
            yield
            return
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                token = self._tx.set(conn)
                try:
                    yield
                finally:
                    self._tx.reset(token)

    async def fetch(self, sql: str, *args) -> list[dict]:
        async with self._connection() as conn:
            return [_row(r) for r in await conn.fetch(sql, *args)]

    async def fetchrow(self, sql: str, *args) -> dict | None:
        async with self._connection() as conn:
            return _row(await conn.fetchrow(sql, *args))

    async def fetchval(self, sql: str, *args):
        async with self._connection() as conn:
            return _to_python(await conn.fetchval(sql, *args))

    async def execute(self, sql: str, *args) -> str:
        async with self._connection() as conn:
            return await conn.execute(sql, *args)

    async def executemany(self, sql: str, args) -> None:
        async with self._connection() as conn:
            await conn.executemany(sql, args)

    # ---------- helpers ----------

    def _table(self, table: str) -> dict[str, str]:
        cols = self.columns.get(table)
        if cols is None:
            raise ValueError(f"Unknown table: {table}")
        return cols

    def _column(self, table: str, column: str) -> str:
        if column not in self._table(table):
            raise ValueError(f"Unknown column {table}.{column}")
        return f'"{column}"'

    def _coerce(self, table: str, column: str, value):
        if value is None:
            return None
        kind = self._table(table)[column]
        if kind == "date":
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, str):
                return date.fromisoformat(value.strip()[:10])
        elif kind == "timestamp with time zone":
            if isinstance(value, str):
                return _parse_timestamp(value)
            if isinstance(value, datetime) and value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
        elif kind in ("integer", "bigint"):
            if isinstance(value, float):
                return int(value)
        elif kind == "ARRAY":
            if isinstance(value, str):
                return value.split()
            if isinstance(value, (set, tuple)):
                return list(value)
        return value

    def _where(self, table: str, where: dict, args: list) -> str:
        if not where:
            return "TRUE"
        parts = []
        for column, value in where.items():
            name = self._column(table, column)
            if value is None:
                parts.append(f"{name} IS NULL")
            elif value is NOT_NULL:
                parts.append(f"{name} IS NOT NULL")
            elif isinstance(value, (list, tuple, set)):
                args.append([self._coerce(table, column, v) for v in value])
                parts.append(f"{name} = ANY(${len(args)})")
            else:
                args.append(self._coerce(table, column, value))
                parts.append(f"{name} = ${len(args)}")
        return " AND ".join(parts)

    async def find_one(self, table: str, where: dict) -> dict | None:
        args: list = []
        sql = f'SELECT * FROM "{table}" WHERE {self._where(table, where, args)} LIMIT 1'
        return await self.fetchrow(sql, *args)

    async def find(self, table: str, where: dict, *, order_by: str | None = None,
                   limit: int | None = None) -> list[dict]:
        args: list = []
        sql = f'SELECT * FROM "{table}" WHERE {self._where(table, where, args)}'
        if order_by:
            column, _, direction = order_by.partition(" ")
            direction = direction.strip().upper() or "ASC"
            if direction not in ("ASC", "DESC"):
                raise ValueError(f"Bad sort direction: {direction}")
            sql += f" ORDER BY {self._column(table, column)} {direction}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return await self.fetch(sql, *args)

    async def count(self, table: str, where: dict) -> int:
        args: list = []
        sql = f'SELECT count(*) FROM "{table}" WHERE {self._where(table, where, args)}'
        return int(await self.fetchval(sql, *args))

    def _values(self, table: str, row: dict) -> tuple[list[str], list]:
        names = [self._column(table, c) for c in row]
        values = [self._coerce(table, c, v) for c, v in row.items()]
        return names, values

    async def insert(self, table: str, row: dict) -> None:
        names, values = self._values(table, row)
        marks = ", ".join(f"${i}" for i in range(1, len(values) + 1))
        await self.execute(f'INSERT INTO "{table}" ({", ".join(names)}) VALUES ({marks})', *values)

    async def insert_many(self, table: str, rows: list[dict]) -> None:
        if not rows:
            return
        columns = list(rows[0])
        names = [self._column(table, c) for c in columns]
        marks = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
        sql = f'INSERT INTO "{table}" ({", ".join(names)}) VALUES ({marks})'
        await self.executemany(
            sql, [[self._coerce(table, c, row.get(c)) for c in columns] for row in rows]
        )

    async def update(self, table: str, where: dict, values: dict) -> int:
        if not values:
            return 0
        args: list = []
        sets = []
        for column, value in values.items():
            args.append(self._coerce(table, column, value))
            sets.append(f"{self._column(table, column)} = ${len(args)}")
        sql = f'UPDATE "{table}" SET {", ".join(sets)} WHERE {self._where(table, where, args)}'
        status = await self.execute(sql, *args)
        return int(status.split()[-1])

    async def upsert(self, table: str, row: dict, conflict: tuple[str, ...],
                     keep: tuple[str, ...] = ()) -> bool:
        """Insert, or update the existing row with the same `conflict` key.

        Columns in `keep` are written on insert but never overwritten (the row
        id, creation time). Returns True when a new row was inserted.
        """
        names, values = self._values(table, row)
        marks = ", ".join(f"${i}" for i in range(1, len(values) + 1))
        target = ", ".join(self._column(table, c) for c in conflict)
        updates = [
            f"{self._column(table, c)} = EXCLUDED.{self._column(table, c)}"
            for c in row if c not in conflict and c not in keep
        ]
        action = f"DO UPDATE SET {', '.join(updates)}" if updates else "DO NOTHING"
        sql = (
            f'INSERT INTO "{table}" ({", ".join(names)}) VALUES ({marks}) '
            f"ON CONFLICT ({target}) {action} RETURNING (xmax = 0) AS inserted"
        )
        inserted = await self.fetchval(sql, *values)
        return bool(inserted)

    async def upsert_many(self, table: str, rows: list[dict], conflict: tuple[str, ...],
                          keep: tuple[str, ...] = ()) -> None:
        """upsert() for many rows with the same columns, in one round trip."""
        if not rows:
            return
        columns = list(rows[0])
        names = [self._column(table, c) for c in columns]
        marks = ", ".join(f"${i}" for i in range(1, len(columns) + 1))
        target = ", ".join(self._column(table, c) for c in conflict)
        updates = ", ".join(
            f"{self._column(table, c)} = EXCLUDED.{self._column(table, c)}"
            for c in columns if c not in conflict and c not in keep
        )
        sql = (
            f'INSERT INTO "{table}" ({", ".join(names)}) VALUES ({marks}) '
            f"ON CONFLICT ({target}) DO UPDATE SET {updates}"
        )
        await self.executemany(
            sql, [[self._coerce(table, c, row.get(c)) for c in columns] for row in rows]
        )

    async def delete(self, table: str, where: dict) -> int:
        args: list = []
        status = await self.execute(
            f'DELETE FROM "{table}" WHERE {self._where(table, where, args)}', *args
        )
        return int(status.split()[-1])

    async def take(self, table: str, where: dict) -> dict | None:
        """Delete and return one matching row -- for single-use tokens."""
        args: list = []
        sql = f'DELETE FROM "{table}" WHERE {self._where(table, where, args)} RETURNING *'
        rows = await self.fetch(sql, *args)
        return rows[0] if rows else None


db = Database()
