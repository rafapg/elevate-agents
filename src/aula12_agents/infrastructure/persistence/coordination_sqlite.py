"""SQLite adapter for the durable coordination task board.

This adapter intentionally uses tables separate from ``SQLitePersistence``.
The lesson can therefore run the linear workflow and a coordination scenario in
the same local database without their revisions or event streams interacting.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from aula12_agents.application.ports import (
    CoordinationConflict,
    CoordinationEventSink,
    CoordinationStore,
)
from aula12_agents.domain.models import CoordinationRun

from .sqlite import PersistenceError


class CoordinationRunNotFound(PersistenceError):
    """The requested coordination run has not been persisted."""


class CoordinationRevisionConflict(PersistenceError, CoordinationConflict):
    """Another executor advanced the coordination board first."""


@dataclass(frozen=True, slots=True)
class StoredCoordinationEvent:
    """Read-only projection of an append-only coordination event."""

    event_id: int
    run_id: UUID
    event_type: str
    payload_json: str
    occurred_at: datetime


class SQLiteCoordinationStore(CoordinationStore, CoordinationEventSink):
    """Local task-board store with optimistic concurrency and append-only events."""

    def __init__(self, database_path: Path | str, *, busy_timeout_ms: int = 5_000) -> None:
        self._database_path = str(database_path)
        self._busy_timeout_ms = busy_timeout_ms
        self._initialize()

    def create(self, run: CoordinationRun) -> CoordinationRun:
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO coordination_runs
                        (run_id, scenario, revision, state, run_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(run.run_id),
                        run.scenario.value,
                        run.revision,
                        run.state.value,
                        run.model_dump_json(),
                        run.created_at.isoformat(),
                        run.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise CoordinationRevisionConflict(
                    f"coordination run já existe: {run.run_id}"
                ) from exc
        return run

    def load(self, run_id: UUID) -> CoordinationRun:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT run_json FROM coordination_runs WHERE run_id = ?", (str(run_id),)
            ).fetchone()
        if row is None:
            raise CoordinationRunNotFound(f"coordination run não encontrado: {run_id}")
        return CoordinationRun.model_validate_json(str(row["run_json"]))

    def compare_and_swap(self, *, expected_revision: int, run: CoordinationRun) -> CoordinationRun:
        if run.revision != expected_revision + 1:
            raise ValueError("run.revision deve avançar exatamente uma revisão")
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE coordination_runs
                SET revision = ?, state = ?, run_json = ?, updated_at = ?
                WHERE run_id = ? AND revision = ?
                """,
                (
                    run.revision,
                    run.state.value,
                    run.model_dump_json(),
                    run.updated_at.isoformat(),
                    str(run.run_id),
                    expected_revision,
                ),
            )
            if cursor.rowcount == 1:
                return run
            exists = connection.execute(
                "SELECT 1 FROM coordination_runs WHERE run_id = ?", (str(run.run_id),)
            ).fetchone()
            if exists is None:
                raise CoordinationRunNotFound(f"coordination run não encontrado: {run.run_id}")
            raise CoordinationRevisionConflict(
                f"revisão obsoleta para coordination run: {run.run_id}"
            )

    def append(
        self, *, run_id: UUID, event_type: str, payload_json: str, occurred_at: datetime
    ) -> None:
        """Append an immutable event; callers cannot update or delete it through this API."""

        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO coordination_events (run_id, event_type, payload_json, occurred_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (str(run_id), event_type, payload_json, occurred_at.isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise CoordinationRunNotFound(f"coordination run não encontrado: {run_id}") from exc

    def list_events(self, run_id: UUID) -> tuple[StoredCoordinationEvent, ...]:
        """Return chronological events without providing a mutation operation."""

        with self._connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM coordination_runs WHERE run_id = ?", (str(run_id),)
            ).fetchone()
            if exists is None:
                raise CoordinationRunNotFound(f"coordination run não encontrado: {run_id}")
            rows = connection.execute(
                """
                SELECT event_id, run_id, event_type, payload_json, occurred_at
                FROM coordination_events WHERE run_id = ? ORDER BY event_id
                """,
                (str(run_id),),
            ).fetchall()
        return tuple(
            StoredCoordinationEvent(
                event_id=int(row["event_id"]),
                run_id=UUID(str(row["run_id"])),
                event_type=str(row["event_type"]),
                payload_json=str(row["payload_json"]),
                occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
            )
            for row in rows
        )

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS coordination_runs (
                    run_id TEXT PRIMARY KEY,
                    scenario TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (revision >= 0),
                    state TEXT NOT NULL,
                    run_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS coordination_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES coordination_runs(run_id),
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS coordination_events_by_run
                    ON coordination_events(run_id, event_id);
                """
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path, timeout=self._busy_timeout_ms / 1_000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()
