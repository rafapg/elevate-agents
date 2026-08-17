"""Adapters locais de persistência."""

from .coordination_sqlite import (
    CoordinationRevisionConflict,
    CoordinationRunNotFound,
    SQLiteCoordinationStore,
    StoredCoordinationEvent,
)
from .sqlite import (
    CheckpointNotFound,
    IdempotencyConflict,
    RevisionConflict,
    SQLitePersistence,
)

__all__ = [
    "CheckpointNotFound",
    "CoordinationRevisionConflict",
    "CoordinationRunNotFound",
    "IdempotencyConflict",
    "RevisionConflict",
    "SQLiteCoordinationStore",
    "SQLitePersistence",
    "StoredCoordinationEvent",
]
