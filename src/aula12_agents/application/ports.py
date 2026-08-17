"""Portas hexagonais: contratos que a infraestrutura deve implementar."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from aula12_agents.domain.models import (
    CoordinationRun,
    CritiqueCard,
    EffectRecord,
    Evidence,
    FailureRecord,
    HypothesisCard,
    Incident,
    RunCheckpoint,
)


class CheckpointConflict(RuntimeError):
    """A stale worker attempted to advance a checkpoint revision."""


class CoordinationConflict(RuntimeError):
    """A stale worker attempted to advance a coordination task board."""


class CheckpointStore(Protocol):
    def create(self, checkpoint: RunCheckpoint) -> RunCheckpoint: ...

    def load(self, run_id: UUID) -> RunCheckpoint: ...

    def compare_and_swap(
        self, *, expected_revision: int, checkpoint: RunCheckpoint
    ) -> RunCheckpoint: ...


class CoordinationStore(Protocol):
    """Durable task-board storage, separate from the linear workflow store."""

    def create(self, run: CoordinationRun) -> CoordinationRun: ...

    def load(self, run_id: UUID) -> CoordinationRun: ...

    def compare_and_swap(
        self, *, expected_revision: int, run: CoordinationRun
    ) -> CoordinationRun: ...


class CoordinationEventSink(Protocol):
    """Append-only operational events for a coordination run."""

    def append(
        self, *, run_id: UUID, event_type: str, payload_json: str, occurred_at: datetime
    ) -> None: ...


class RunEventSink(Protocol):
    def append(
        self, *, run_id: UUID, event_type: str, payload_json: str, occurred_at: datetime
    ) -> None: ...


class WorkflowEventObserver(Protocol):
    """Observa transições sem tornar a telemetria parte do domínio."""

    def record(
        self, *, checkpoint: RunCheckpoint, event_type: str, occurred_at: datetime
    ) -> None: ...

    def record_stage_started(
        self,
        *,
        checkpoint: RunCheckpoint,
        stage: Literal["hypothesis", "critic", "gate"],
        occurred_at: datetime,
    ) -> None: ...

    def record_stage_completed(
        self,
        *,
        checkpoint: RunCheckpoint,
        stage: Literal["hypothesis", "critic", "gate"],
        occurred_at: datetime,
    ) -> None: ...

    def record_stage_failed(
        self,
        *,
        checkpoint: RunCheckpoint,
        stage: Literal["hypothesis", "critic", "gate"],
        failure_kind: str,
        occurred_at: datetime,
    ) -> None: ...

    def record_gate_decision(
        self,
        *,
        checkpoint: RunCheckpoint,
        decision: Literal["approve", "retry", "escalate"],
        occurred_at: datetime,
    ) -> None: ...

    def record_retry_scheduled(
        self,
        *,
        checkpoint: RunCheckpoint,
        stage: Literal["hypothesis", "critic", "gate"],
        occurred_at: datetime,
    ) -> None: ...

    def record_resume_started(
        self,
        *,
        checkpoint: RunCheckpoint,
        stage: Literal["hypothesis", "critic", "gate"],
        resumed_from_revision: int,
        occurred_at: datetime,
    ) -> None: ...

    def record_stale_result_rejected(
        self,
        *,
        checkpoint: RunCheckpoint,
        stage: Literal["hypothesis", "critic", "gate"],
        expected_revision: int,
        observed_revision: int,
        kind: Literal["revision_conflict", "superseded_stage"],
        occurred_at: datetime,
    ) -> None: ...


class EffectLedger(Protocol):
    def reserve(self, effect: EffectRecord) -> EffectRecord: ...

    def find(self, *, idempotency_key: str) -> EffectRecord | None: ...

    def confirm(
        self, *, effect_id: UUID, provider_receipt: str, occurred_at: datetime
    ) -> EffectRecord: ...

    def mark_unknown(self, *, effect_id: UUID, failure: FailureRecord) -> EffectRecord: ...


class AgentExecutor(Protocol):
    async def decide(
        self, *, run_id: UUID, incident: Incident, evidence: tuple[Evidence, ...]
    ) -> HypothesisCard: ...


class CriticExecutor(Protocol):
    """Reviews a typed proposal; it cannot change workflow state directly."""

    async def review(
        self,
        *,
        run_id: UUID,
        incident: Incident,
        evidence: tuple[Evidence, ...],
        proposal: HypothesisCard,
    ) -> CritiqueCard: ...


class ReadOnlyToolGateway(Protocol):
    async def collect_evidence(self, *, incident: Incident) -> tuple[Evidence, ...]: ...


class EffectExecutor(Protocol):
    async def execute(self, effect: EffectRecord) -> str:
        """Executa um efeito reservado e retorna o recibo externo."""


class RetryScheduler(Protocol):
    def schedule(self, *, run_id: UUID, retry_at: datetime) -> None: ...
