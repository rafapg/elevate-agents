"""Agent-facing contracts.

These are deliberately drafts: the application layer must turn a valid draft
into a domain card only after its deterministic evidence gate has approved it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ReviewText = Annotated[str, Field(min_length=1, max_length=600)]


class EvidenceItem(BaseModel):
    """A compact, attributable piece of read-only evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1, max_length=80)
    artifact_id: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=1_000)


class EvidencePack(BaseModel):
    """The only evidence shape exposed by the agent tools."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: str = Field(min_length=1, max_length=120)
    items: tuple[EvidenceItem, ...] = Field(default_factory=tuple, max_length=12)
    truncated: bool = False


class HypothesisDraft(BaseModel):
    """Structured but unapproved output from a PydanticAI specialist."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["retry", "escalate", "conclude"]
    hypothesis: str | None = Field(default=None, max_length=1_000)
    uncertainty: str = Field(min_length=1, max_length=1_000)
    next_action: str = Field(min_length=1, max_length=600)
    evidence: tuple[EvidenceItem, ...] = Field(default_factory=tuple, max_length=12)


class HypothesisReviewContext(BaseModel):
    """Immutable hand-off from the hypothesis specialist to its critic.

    The application supplies this as prompt context. It is intentionally a
    typed value rather than conversational history, so a future coordinator
    can persist and audit the boundary without treating agent messages as
    workflow state.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    draft: HypothesisDraft
    evidence: EvidencePack


class HypothesisReview(BaseModel):
    """Structured recommendation from the read-only hypothesis critic."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["approve", "retry", "escalate"]
    reasons: tuple[ReviewText, ...] = Field(min_length=1, max_length=6)
    gaps: tuple[ReviewText, ...] = Field(default_factory=tuple, max_length=6)
