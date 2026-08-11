"""Contratos persistíveis e independentes de framework para a aula."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

NonEmptyText = Annotated[str, Field(min_length=1)]


class DomainModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class Decision(StrEnum):
    RETRY = "retry"
    ESCALATE = "escalate"
    CONCLUDE = "conclude"


class CritiqueOutcome(StrEnum):
    """A bounded review outcome; it is not a second workflow controller."""

    APPROVE = "approve"
    RETRY = "retry"
    ESCALATE = "escalate"


class CheckpointState(StrEnum):
    RUNNING = "running"
    WAITING_RETRY = "waiting_retry"
    WAITING_APPROVAL = "waiting_approval"
    ESCALATED = "escalated"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class FailureKind(StrEnum):
    TRANSIENT = "transient"
    INVALID_RESULT = "invalid_result"
    POLICY = "policy"
    CONFIGURATION = "configuration"
    BUDGET = "budget"
    CANCELLED = "cancelled"
    UNKNOWN_EFFECT = "unknown_effect"
    CONCURRENCY = "concurrency"


class EffectStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
    FAILED = "failed"


class Incident(DomainModel):
    incident_id: NonEmptyText
    title: NonEmptyText
    description: NonEmptyText
    reported_at: datetime
    service: NonEmptyText
    severity: Literal["low", "medium", "high", "critical"]


class EvidenceRef(DomainModel):
    evidence_id: UUID = Field(default_factory=uuid4)
    source: NonEmptyText
    artifact_id: NonEmptyText
    content_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    captured_at: datetime


class Evidence(EvidenceRef):
    summary: NonEmptyText
    excerpt: str | None = Field(default=None, max_length=2_000)
    trust: Literal["observed", "reported", "derived"] = "observed"


class HypothesisDraft(DomainModel):
    statement: NonEmptyText
    rationale: NonEmptyText
    uncertainty: NonEmptyText
    evidence: tuple[EvidenceRef, ...] = ()


class HypothesisCard(DomainModel):
    decision: Decision
    hypothesis: HypothesisDraft | None = None
    uncertainty: NonEmptyText
    next_action: NonEmptyText
    evidence: tuple[EvidenceRef, ...] = ()

    @model_validator(mode="after")
    def decision_has_the_required_evidence(self) -> HypothesisCard:
        if self.decision is Decision.CONCLUDE and not self.evidence:
            raise ValueError("a conclusão exige ao menos uma evidência referenciada")
        if self.decision is Decision.RETRY and self.hypothesis is not None:
            raise ValueError("um retry não deve afirmar uma hipótese")
        return self


class CritiqueCard(DomainModel):
    """A critic's typed assessment of a hypothesis proposal.

    The application, rather than the critic, translates this assessment into a
    durable workflow state. Keeping it as data makes the hand-off auditable
    and avoids a free-form conversation between specialists.
    """

    outcome: CritiqueOutcome
    rationale: NonEmptyText
    gaps: tuple[NonEmptyText, ...] = ()
    next_action: NonEmptyText


class FailureRecord(DomainModel):
    kind: FailureKind
    code: NonEmptyText
    message: NonEmptyText
    occurred_at: datetime
    retryable: bool
    step: NonEmptyText

    @model_validator(mode="after")
    def retryability_matches_failure_kind(self) -> FailureRecord:
        retryable_kinds = {
            FailureKind.TRANSIENT,
            FailureKind.INVALID_RESULT,
            FailureKind.CONCURRENCY,
        }
        if self.retryable != (self.kind in retryable_kinds):
            raise ValueError("retryable deve ser coerente com a classe da falha")
        return self


class EffectRecord(DomainModel):
    effect_id: UUID = Field(default_factory=uuid4)
    idempotency_key: NonEmptyText
    kind: NonEmptyText
    payload_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    status: EffectStatus = EffectStatus.PENDING
    provider_receipt: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def receipt_matches_status(self) -> EffectRecord:
        if self.status is EffectStatus.CONFIRMED and not self.provider_receipt:
            raise ValueError("efeito confirmado exige um recibo do provedor")
        if self.status is EffectStatus.PENDING and self.provider_receipt is not None:
            raise ValueError("efeito pendente não pode possuir recibo")
        return self


class RunCheckpoint(DomainModel):
    schema_version: Literal[1] = 1
    run_id: UUID = Field(default_factory=uuid4)
    workflow_version: NonEmptyText
    state: CheckpointState
    revision: Annotated[int, Field(ge=0)] = 0
    incident: Incident
    input_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    next_step: NonEmptyText
    attempts: dict[NonEmptyText, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    retry_at: datetime | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()
    hypothesis_card: HypothesisCard | None = None
    critique: CritiqueCard | None = None
    decision: HypothesisCard | None = None
    last_failure: FailureRecord | None = None
    effects: tuple[EffectRecord, ...] = ()
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def is_a_coherent_durable_state(self) -> RunCheckpoint:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at não pode anteceder created_at")
        if self.state is CheckpointState.WAITING_RETRY and self.retry_at is None:
            raise ValueError("waiting_retry exige retry_at")
        if self.state is not CheckpointState.WAITING_RETRY and self.retry_at is not None:
            raise ValueError("retry_at só é válido em waiting_retry")
        if self.state is CheckpointState.COMPLETED and (
            self.decision is None or self.decision.decision is not Decision.CONCLUDE
        ):
            raise ValueError("completed exige uma decisão conclude")
        if self.state is CheckpointState.ESCALATED and (
            self.decision is None or self.decision.decision is not Decision.ESCALATE
        ):
            raise ValueError("escalated exige uma decisão escalate")
        if self.state is CheckpointState.WAITING_RETRY and (
            self.decision is None or self.decision.decision is not Decision.RETRY
        ):
            raise ValueError("waiting_retry exige uma decisão retry")
        if self.next_step == "review_hypothesis":
            if self.hypothesis_card is None:
                raise ValueError("review_hypothesis exige uma hipótese persistida")
            if self.state not in {CheckpointState.RUNNING, CheckpointState.WAITING_RETRY}:
                raise ValueError("review_hypothesis só é válido durante uma execução ou retry")
        keys = [effect.idempotency_key for effect in self.effects]
        if len(keys) != len(set(keys)):
            raise ValueError("idempotency_key deve ser única por run")
        return self
