"""SQLite persistence store: write-through mirror + startup restore.

Every mutating component (registries, runtime, approval manager) keeps its
in-memory dict as the read-side source of truth and additionally saves each
change here, so reads stay dict-fast and never touch the database. On process
start the facts are loaded back out of these tables: a restart then loses
live executions (graph state and in-process wakeups cannot be serialized) but
never the records themselves.

All payloads are stored as JSON produced by pydantic ``model_dump_json`` —
the same roundtrip convention as ``eval/baseline.py``.

Threading: FastAPI runs sync route handlers in a worker threadpool while the
connection is created on the main thread, so the connection opts into
cross-thread use and a lock serializes writes (WAL keeps readers free). The
LangGraph checkpointer holds a second connection to this file; a generous
busy timeout plus write retries absorb the overlap.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from agent_core.errors.exceptions import ConfigurationError

_SQLITE_PREFIX = "sqlite:///"
_SCHEMA_VERSION = 2
_BUSY_TIMEOUT_MS = 15000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS registry_items (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trace_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trace_events_run ON trace_events (run_id);
"""

# Incremental migrations run in order for databases below _SCHEMA_VERSION.
_MIGRATIONS: dict[int, str] = {
    2: """
CREATE TABLE IF NOT EXISTS schedules (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
""",
}


def parse_sqlite_url(url: str) -> Path | str:
    """Extract the database path from a ``sqlite:///`` URL.

    ``sqlite:///relative.db`` → relative path, ``sqlite:////abs.db`` → absolute
    path, ``sqlite:///:memory:`` → the literal ``:memory:``. Anything else is a
    configuration error (Phase 16 ships SQLite only).
    """
    if not url.startswith(_SQLITE_PREFIX):
        raise ConfigurationError(
            f"Unsupported database_url '{url}': only 'sqlite:///' URLs are supported",
            details={"database_url": url},
        )
    path = url[len(_SQLITE_PREFIX) :]
    if not path:
        raise ConfigurationError(
            f"database_url '{url}' has no database path",
            details={"database_url": url},
        )
    if path == ":memory:":
        return path
    return Path(path)


def open_store(database_url: str | None) -> SqliteStore | None:
    """Return a store for ``database_url``, or None when persistence is off."""
    if database_url is None:
        return None
    return SqliteStore(database_url)


class SqliteStore:
    """The one place that knows the SQLite schema; callers only pass JSON."""

    def __init__(self, database_url: str) -> None:
        # FastAPI runs sync route handlers in a worker threadpool while the
        # connection is created on the main thread — cross-thread use must be
        # opted into, and a lock serializes writes across those threads.
        self._conn = sqlite3.connect(
            parse_sqlite_url(database_url), check_same_thread=False, timeout=20.0
        )
        self._lock = threading.Lock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        self._migrate()

    # ------------------------------------------------------------- lifecycle

    def _migrate(self) -> None:
        """Create the schema when missing; apply incremental migrations in order."""
        (version,) = self._conn.execute("PRAGMA user_version").fetchone()
        if version > _SCHEMA_VERSION:
            raise ConfigurationError(
                f"Database schema v{version} is newer than this build (v{_SCHEMA_VERSION})",
                details={"database_version": version, "code_version": _SCHEMA_VERSION},
            )
        if version < 1:
            self._conn.executescript(_SCHEMA)
        for target in range(version + 1, _SCHEMA_VERSION + 1):
            script = _MIGRATIONS.get(target)
            if script:
                self._conn.executescript(script)
        if version < _SCHEMA_VERSION:
            self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ---------------------------------------------------------------- writes

    def _write(self, sql: str, params: tuple[Any, ...]) -> None:
        """Serialized write; transient lock contention is retried, not fatal."""
        for attempt in range(4):
            try:
                with self._lock:
                    self._conn.execute(sql, params)
                    self._conn.commit()
                return
            except sqlite3.OperationalError as exc:
                message = str(exc)
                if "locked" not in message and "busy" not in message:
                    raise
                time.sleep(0.25 * (attempt + 1))
        raise sqlite3.OperationalError(
            f"database is locked (retries exhausted): {sql[:80]}"
        )

    # ------------------------------------------------------------- registries

    def save_item(self, kind: str, key: str, data: str) -> None:
        self._write(
            "INSERT INTO registry_items (kind, key, data) VALUES (?, ?, ?) "
            "ON CONFLICT(kind, key) DO UPDATE SET data = excluded.data",
            (kind, key, data),
        )

    def delete_item(self, kind: str, key: str) -> None:
        self._write("DELETE FROM registry_items WHERE kind = ? AND key = ?", (kind, key))

    def load_items(self, kind: str) -> list[tuple[str, str]]:
        """(key, data) pairs in registration order."""
        rows = self._conn.execute(
            "SELECT key, data FROM registry_items WHERE kind = ? ORDER BY rowid", (kind,)
        ).fetchall()
        return [(key, data) for key, data in rows]

    # ----------------------------------------------------------- runs / tasks

    def save_task(self, task_id: str, data: str) -> None:
        self._write(
            "INSERT INTO tasks (id, data) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (task_id, data),
        )

    def load_tasks(self) -> list[str]:
        rows = self._conn.execute("SELECT data FROM tasks ORDER BY rowid").fetchall()
        return [data for (data,) in rows]

    def save_run(self, run_id: str, status: str, data: str) -> None:
        self._write(
            "INSERT INTO runs (id, status, data) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET status = excluded.status, data = excluded.data",
            (run_id, status, data),
        )

    def load_runs(self) -> list[str]:
        rows = self._conn.execute("SELECT data FROM runs ORDER BY rowid").fetchall()
        return [data for (data,) in rows]

    # -------------------------------------------------------------- approvals

    def save_approval(self, approval_id: str, status: str, data: str) -> None:
        self._write(
            "INSERT INTO approvals (id, status, data) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET status = excluded.status, data = excluded.data",
            (approval_id, status, data),
        )

    def load_approvals(self) -> list[str]:
        rows = self._conn.execute("SELECT data FROM approvals ORDER BY rowid").fetchall()
        return [data for (data,) in rows]

    # -------------------------------------------------------------- schedules

    def save_schedule(self, schedule_id: str, data: str) -> None:
        self._write(
            "INSERT INTO schedules (id, data) VALUES (?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (schedule_id, data),
        )

    def load_schedules(self) -> list[str]:
        rows = self._conn.execute("SELECT data FROM schedules ORDER BY rowid").fetchall()
        return [data for (data,) in rows]

    def delete_schedule(self, schedule_id: str) -> None:
        self._write("DELETE FROM schedules WHERE id = ?", (schedule_id,))

    # ----------------------------------------------------------- trace events

    def append_event(self, run_id: str, data: str) -> None:
        self._write(
            "INSERT INTO trace_events (run_id, data) VALUES (?, ?)", (run_id, data)
        )

    def load_events(self) -> list[tuple[str, str]]:
        """(run_id, data) pairs in emission order across all runs."""
        rows = self._conn.execute(
            "SELECT run_id, data FROM trace_events ORDER BY seq"
        ).fetchall()
        return [(run_id, data) for run_id, data in rows]
