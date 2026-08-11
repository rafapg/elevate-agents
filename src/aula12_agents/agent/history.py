"""Safe serialization and bounded compaction of PydanticAI message history."""

from __future__ import annotations

from pydantic_ai import ModelMessagesTypeAdapter
from pydantic_ai.messages import ModelMessage


def serialize_history(messages: list[ModelMessage]) -> bytes:
    """Serialize messages for an audit/replay artifact, never as domain state."""

    return ModelMessagesTypeAdapter.dump_json(messages)


def deserialize_history(payload: bytes | str) -> list[ModelMessage]:
    """Restore a previously serialized history without mutating its messages."""

    return ModelMessagesTypeAdapter.validate_json(payload)


def bounded_history(messages: list[ModelMessage], *, max_messages: int = 12) -> list[ModelMessage]:
    """Keep the latest messages; callers retain the canonical run snapshot elsewhere."""

    if max_messages < 1:
        raise ValueError("max_messages must be positive")
    return list(messages[-max_messages:])
