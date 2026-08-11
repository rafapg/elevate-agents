"""Adapters locais de persistência."""

from .sqlite import (
    CheckpointNotFound,
    IdempotencyConflict,
    RevisionConflict,
    SQLitePersistence,
)

__all__ = [
    "CheckpointNotFound",
    "IdempotencyConflict",
    "RevisionConflict",
    "SQLitePersistence",
]
