"""Read-only projections used by the local teaching CLI.

The workflow owns writes through the persistence adapter.  These projections
intentionally query SQLite and JSONL without constructing a coordinator, so a
student can inspect a previous run while offline and without a model provider.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from aula12_agents.infrastructure.persistence import CheckpointNotFound
from aula12_agents.infrastructure.trace.models import TraceEvent
from aula12_agents.infrastructure.trace.sinks import TraceRedactor


class LocalRunInspector:
    """Read only, redacted projections over the local SQLite and JSONL stores."""

    def __init__(self, *, database_path: Path, trace_dir: Path) -> None:
        self._database_path = database_path
        self._trace_dir = trace_dir

    def list_runs(self) -> list[dict[str, object]]:
        """Return a compact run index; it deliberately excludes incident content."""
        if not self._database_path.exists():
            return []
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT run_id, revision, state, created_at, updated_at
                FROM runs
                ORDER BY updated_at DESC, run_id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def events_for(self, run_id: UUID) -> list[dict[str, object]]:
        """Return event metadata plus a safe checkpoint projection, never raw JSON."""
        self._require_run(run_id)
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT event_id, event_type, payload_json, occurred_at
                FROM events
                WHERE run_id = ?
                ORDER BY event_id ASC
                """,
                (str(run_id),),
            ).fetchall()
        return [self._event_projection(row) for row in rows]

    def trace_for(self, run_id: UUID) -> list[dict[str, object]]:
        """Read matching JSONL events and redact again for terminal display.

        A trace can have been written with content capture enabled.  Inspection
        is intentionally stricter: it always applies the no-content redactor.
        Corrupt or unrelated lines are ignored so an inspection command remains
        useful after an interrupted local write.
        """
        self._require_run(run_id)
        if not self._trace_dir.exists():
            return []
        redactor = TraceRedactor(capture_content=False)
        events: list[dict[str, object]] = []
        for path in sorted(self._trace_dir.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    event = TraceEvent.model_validate_json(line)
                except (ValidationError, ValueError, json.JSONDecodeError):
                    continue
                if event.run_id != run_id:
                    continue
                events.append(redactor.redact_event(event).model_dump(mode="json"))
        return sorted(events, key=lambda event: (str(event["occurred_at"]), str(event["event_id"])))

    def _require_run(self, run_id: UUID) -> None:
        if not self._database_path.exists():
            raise CheckpointNotFound(f"run não encontrado: {run_id}")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM runs WHERE run_id = ?", (str(run_id),)
            ).fetchone()
        if row is None:
            raise CheckpointNotFound(f"run não encontrado: {run_id}")

    @staticmethod
    def _event_projection(row: sqlite3.Row) -> dict[str, object]:
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError:
            checkpoint: dict[str, object] = {"available": False}
        else:
            checkpoint = LocalRunInspector._checkpoint_projection(payload)
        return {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "occurred_at": row["occurred_at"],
            "checkpoint": checkpoint,
        }

    @staticmethod
    def _checkpoint_projection(payload: Any) -> dict[str, object]:
        if not isinstance(payload, dict):
            return {"available": False}
        evidence_refs = payload.get("evidence_refs")
        failure = payload.get("last_failure")
        safe_failure: dict[str, object] | None = None
        if isinstance(failure, dict):
            safe_failure = {
                key: failure[key]
                for key in ("kind", "code", "retryable", "step", "occurred_at")
                if key in failure
            }
        return {
            "available": True,
            "revision": payload.get("revision"),
            "state": payload.get("state"),
            "next_step": payload.get("next_step"),
            "attempts": payload.get("attempts", {}),
            "evidence_count": len(evidence_refs) if isinstance(evidence_refs, list) else 0,
            "has_hypothesis": payload.get("hypothesis_card") is not None,
            "has_critique": payload.get("critique") is not None,
            "has_decision": payload.get("decision") is not None,
            "last_failure": safe_failure,
        }

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()
