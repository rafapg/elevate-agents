"""Provider-neutral boundary for one bounded coordination specialist.

The coordinator selects evidence *before* crossing this boundary.  An executor
therefore cannot read the task board, discover additional tools, or obtain
configuration/credentials.  It may only interpret the compact packet and
return a typed report for the task that it was given.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aula12_agents.domain.models import CoordinationTask, EvidenceRef, EvidenceReport

BoundedText = Annotated[str, Field(min_length=1, max_length=1_000)]


class CoordinationEvidenceItem(BaseModel):
    """A redacted evidence item already authorized for one specialist."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    reference: EvidenceRef
    summary: BoundedText


class CoordinationEvidencePacket(BaseModel):
    """The smallest attributable input that may be sent to a provider."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    task_id: UUID
    items: tuple[CoordinationEvidenceItem, ...] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def has_unique_references(self) -> CoordinationEvidencePacket:
        ids = [item.reference.evidence_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence packet cannot repeat an evidence reference")
        return self


class CoordinationSpecialistExecutor(Protocol):
    """The only application-facing capability of an external specialist."""

    async def execute(
        self, *, task: CoordinationTask, evidence: CoordinationEvidencePacket
    ) -> EvidenceReport: ...


def validate_execution_request(
    *, task: CoordinationTask, evidence: CoordinationEvidencePacket, now: datetime
) -> None:
    """Reject malformed or expired work before any provider request is made."""

    if evidence.task_id != task.task_id:
        raise ValueError("evidence packet must belong to the coordination task")
    if task.deadline <= now:
        raise TimeoutError("coordination task deadline has already elapsed")
