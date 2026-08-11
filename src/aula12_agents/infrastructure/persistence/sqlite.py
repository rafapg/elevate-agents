"""Persistência SQLite transacional para checkpoints, eventos e efeitos."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID

from aula12_agents.application.ports import (
    CheckpointConflict,
    CheckpointStore,
    EffectLedger,
    RunEventSink,
)
from aula12_agents.domain.models import EffectRecord, EffectStatus, FailureRecord, RunCheckpoint


class PersistenceError(RuntimeError):
    """Erro base de persistência local."""


class CheckpointNotFound(PersistenceError):
    """O run solicitado não foi persistido."""


class RevisionConflict(PersistenceError, CheckpointConflict):
    """Outro executor já avançou a revisão do checkpoint."""


class IdempotencyConflict(PersistenceError):
    """Uma chave de idempotência foi reutilizada para outro efeito."""


class SQLitePersistence(CheckpointStore, RunEventSink, EffectLedger):
    """Store local com uma conexão curta por operação e escrita serializada."""

    def __init__(self, database_path: Path | str, *, busy_timeout_ms: int = 5_000) -> None:
        self._database_path = str(database_path)
        self._busy_timeout_ms = busy_timeout_ms
        self._initialize()

    def create(self, checkpoint: RunCheckpoint) -> RunCheckpoint:
        payload = checkpoint.model_dump_json()
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO runs
                        (run_id, revision, state, checkpoint_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(checkpoint.run_id),
                        checkpoint.revision,
                        checkpoint.state.value,
                        payload,
                        checkpoint.created_at.isoformat(),
                        checkpoint.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise RevisionConflict(f"run já existe: {checkpoint.run_id}") from exc
        return checkpoint

    def load(self, run_id: UUID) -> RunCheckpoint:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT checkpoint_json FROM runs WHERE run_id = ?", (str(run_id),)
            ).fetchone()
        if row is None:
            raise CheckpointNotFound(f"run não encontrado: {run_id}")
        return RunCheckpoint.model_validate_json(str(row["checkpoint_json"]))

    def compare_and_swap(
        self, *, expected_revision: int, checkpoint: RunCheckpoint
    ) -> RunCheckpoint:
        if checkpoint.revision != expected_revision + 1:
            raise ValueError("checkpoint.revision deve avançar exatamente uma revisão")
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET revision = ?, state = ?, checkpoint_json = ?, updated_at = ?
                WHERE run_id = ? AND revision = ?
                """,
                (
                    checkpoint.revision,
                    checkpoint.state.value,
                    checkpoint.model_dump_json(),
                    checkpoint.updated_at.isoformat(),
                    str(checkpoint.run_id),
                    expected_revision,
                ),
            )
            if cursor.rowcount == 1:
                return checkpoint
            exists = connection.execute(
                "SELECT 1 FROM runs WHERE run_id = ?", (str(checkpoint.run_id),)
            ).fetchone()
            if exists is None:
                raise CheckpointNotFound(f"run não encontrado: {checkpoint.run_id}")
            raise RevisionConflict(f"revisão obsoleta para run: {checkpoint.run_id}")

    def append(
        self, *, run_id: UUID, event_type: str, payload_json: str, occurred_at: datetime
    ) -> None:
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO events (run_id, event_type, payload_json, occurred_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (str(run_id), event_type, payload_json, occurred_at.isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise CheckpointNotFound(f"run não encontrado: {run_id}") from exc

    def reserve(self, effect: EffectRecord) -> EffectRecord:
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO effects
                        (effect_id, idempotency_key, kind, payload_sha256, status, record_json,
                         failure_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        str(effect.effect_id),
                        effect.idempotency_key,
                        effect.kind,
                        effect.payload_sha256,
                        effect.status.value,
                        effect.model_dump_json(),
                        effect.created_at.isoformat(),
                        effect.updated_at.isoformat(),
                    ),
                )
                return effect
            except sqlite3.IntegrityError as exc:
                row = connection.execute(
                    """
                    SELECT record_json, kind, payload_sha256
                    FROM effects WHERE idempotency_key = ?
                    """,
                    (effect.idempotency_key,),
                ).fetchone()
                if row is None:
                    raise
                if row["kind"] != effect.kind or row["payload_sha256"] != effect.payload_sha256:
                    raise IdempotencyConflict(
                        f"chave reutilizada para efeito diferente: {effect.idempotency_key}"
                    ) from exc
                return EffectRecord.model_validate_json(str(row["record_json"]))

    def find(self, *, idempotency_key: str) -> EffectRecord | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT record_json FROM effects WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
        return None if row is None else EffectRecord.model_validate_json(str(row["record_json"]))

    def confirm(
        self, *, effect_id: UUID, provider_receipt: str, occurred_at: datetime
    ) -> EffectRecord:
        effect = self._load_effect(effect_id)
        confirmed = effect.model_copy(
            update={
                "status": EffectStatus.CONFIRMED,
                "provider_receipt": provider_receipt,
                "updated_at": occurred_at,
            }
        )
        self._write_effect(confirmed, failure=None)
        return confirmed

    def mark_unknown(self, *, effect_id: UUID, failure: FailureRecord) -> EffectRecord:
        effect = self._load_effect(effect_id)
        unknown = effect.model_copy(
            update={"status": EffectStatus.UNKNOWN, "updated_at": failure.occurred_at}
        )
        self._write_effect(unknown, failure=failure)
        return unknown

    def export_checkpoint_json(self, run_id: UUID, destination: Path) -> None:
        """Exporta um checkpoint para inspeção/replay sem expor a base SQLite."""

        checkpoint = self.load(run_id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(checkpoint.model_dump_json(indent=2), encoding="utf-8")

    def _load_effect(self, effect_id: UUID) -> EffectRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT record_json FROM effects WHERE effect_id = ?", (str(effect_id),)
            ).fetchone()
        if row is None:
            raise CheckpointNotFound(f"efeito não encontrado: {effect_id}")
        return EffectRecord.model_validate_json(str(row["record_json"]))

    def _write_effect(self, effect: EffectRecord, *, failure: FailureRecord | None) -> None:
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE effects
                SET status = ?, record_json = ?, failure_json = ?, updated_at = ?
                WHERE effect_id = ?
                """,
                (
                    effect.status.value,
                    effect.model_dump_json(),
                    None if failure is None else failure.model_dump_json(),
                    effect.updated_at.isoformat(),
                    str(effect.effect_id),
                ),
            )
            if cursor.rowcount != 1:
                raise CheckpointNotFound(f"efeito não encontrado: {effect.effect_id}")

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    revision INTEGER NOT NULL CHECK (revision >= 0),
                    state TEXT NOT NULL,
                    checkpoint_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_by_run ON events(run_id, event_id);
                CREATE TABLE IF NOT EXISTS effects (
                    effect_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    failure_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
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
