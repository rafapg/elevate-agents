"""Translation from an untrusted agent draft to an evidence-bound domain card."""

from __future__ import annotations

from typing import Protocol

from aula12_agents.domain.models import (
    CritiqueCard,
    CritiqueOutcome,
    Decision,
    Evidence,
    EvidenceRef,
    HypothesisCard,
    HypothesisDraft,
)
from aula12_agents.domain.policies import EvidenceGate, PolicyViolation


class AgentHypothesisDraft(Protocol):
    @property
    def decision(self) -> str: ...

    @property
    def hypothesis(self) -> str | None: ...

    @property
    def uncertainty(self) -> str: ...

    @property
    def next_action(self) -> str: ...

    @property
    def evidence(self) -> tuple[object, ...]: ...


class DraftConversionError(ValueError):
    """The agent cited unavailable or ambiguous evidence."""


class AgentHypothesisReview(Protocol):
    @property
    def decision(self) -> str: ...

    @property
    def reasons(self) -> tuple[str, ...]: ...

    @property
    def gaps(self) -> tuple[str, ...]: ...


def hypothesis_card_from_agent_draft(
    draft: AgentHypothesisDraft,
    evidence: tuple[Evidence, ...],
    *,
    evidence_gate: EvidenceGate | None = None,
) -> HypothesisCard:
    """Make provenance explicit before domain policy can accept a model result."""
    trusted = {(item.source, item.artifact_id): item for item in evidence}
    refs: list[EvidenceRef] = []
    for cited in draft.evidence:
        key = (getattr(cited, "source", None), getattr(cited, "artifact_id", None))
        if key not in trusted:
            raise DraftConversionError("agent cited evidence outside the trusted pack")
        if trusted[key] not in refs:
            refs.append(trusted[key])
    try:
        decision = Decision(draft.decision)
    except ValueError as error:
        raise DraftConversionError("agent returned an unknown decision") from error
    hypothesis = None
    if draft.hypothesis is not None and decision is not Decision.RETRY:
        hypothesis = HypothesisDraft(
            statement=draft.hypothesis,
            rationale="Untrusted agent draft; accepted only through the evidence gate.",
            uncertainty=draft.uncertainty,
            evidence=tuple(refs),
        )
    card = HypothesisCard(
        decision=decision,
        hypothesis=hypothesis,
        uncertainty=draft.uncertainty,
        next_action=draft.next_action,
        evidence=tuple(refs),
    )
    try:
        (evidence_gate or EvidenceGate()).enforce(card)
    except PolicyViolation as error:
        raise DraftConversionError(str(error)) from error
    return card


def critique_card_from_agent_review(
    review: AgentHypothesisReview, proposal: HypothesisCard
) -> CritiqueCard:
    """Translate a critic recommendation into domain data with safe next actions.

    The review model controls only its bounded outcome, reasons and gaps. The
    application fixes the operational next action, keeping this hand-off from
    becoming a second workflow controller.
    """
    try:
        outcome = CritiqueOutcome(review.decision)
    except ValueError as error:
        raise DraftConversionError("critic returned an unknown outcome") from error
    rationale = " ".join(review.reasons)
    next_action = {
        CritiqueOutcome.APPROVE: proposal.next_action,
        CritiqueOutcome.RETRY: "Retry bounded, read-only evidence collection; make no writes.",
        CritiqueOutcome.ESCALATE: "Escalate to a human reviewer; do not perform a write.",
    }[outcome]
    return CritiqueCard(
        outcome=outcome,
        rationale=rationale,
        gaps=review.gaps,
        next_action=next_action,
    )
