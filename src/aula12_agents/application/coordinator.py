"""Async workflow coordination over ports, with explicit retry and escalation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from aula12_agents.domain.models import (
    CheckpointState,
    CritiqueCard,
    CritiqueOutcome,
    Decision,
    Evidence,
    EvidenceRef,
    FailureKind,
    FailureRecord,
    HypothesisCard,
    Incident,
    RunCheckpoint,
)
from aula12_agents.domain.policies import (
    CheckpointPolicy,
    EvidenceGate,
    PolicyViolation,
    merge_evidence,
)

from .ports import (
    AgentExecutor,
    CheckpointConflict,
    CheckpointStore,
    CriticExecutor,
    ReadOnlyToolGateway,
    RetryScheduler,
    RunEventSink,
    WorkflowEventObserver,
)


class ResumeNotAllowed(ValueError):
    """A run can only resume from a durable retry checkpoint."""


@dataclass(frozen=True, slots=True)
class CoordinatorPolicy:
    workflow_version: str
    input_sha256: str
    max_attempts: int = 2
    retry_delay: timedelta = timedelta(minutes=1)


class RunCoordinator:
    """Coordinates I/O through ports; it never assumes a persistence backend."""

    def __init__(
        self,
        *,
        checkpoints: CheckpointStore,
        tools: ReadOnlyToolGateway,
        agent: AgentExecutor,
        critic: CriticExecutor | None = None,
        scheduler: RetryScheduler,
        events: RunEventSink,
        policy: CoordinatorPolicy,
        now: Callable[[], datetime],
        observer: WorkflowEventObserver | None = None,
    ) -> None:
        if policy.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.checkpoints, self.tools, self.agent, self.critic = checkpoints, tools, agent, critic
        self.scheduler, self.events, self.policy, self.now = scheduler, events, policy, now
        self.observer = observer

    async def start(self, incident: Incident) -> RunCheckpoint:
        current_time = self.now()
        checkpoint = RunCheckpoint(
            workflow_version=self.policy.workflow_version,
            state=CheckpointState.RUNNING,
            incident=incident,
            input_sha256=self.policy.input_sha256,
            next_step="collect_evidence",
            attempts={"investigate": 1},
            created_at=current_time,
            updated_at=current_time,
        )
        stored = self.checkpoints.create(checkpoint)
        self._emit(stored, "checkpoint_created")
        return await self._investigate(stored)

    async def resume(self, run_id: UUID) -> RunCheckpoint:
        current = self.checkpoints.load(run_id)
        attempt_key = self._attempt_key_for(current)
        attempt = current.attempts.get(attempt_key, 0)
        if (
            current.state is not CheckpointState.WAITING_RETRY
            or attempt >= self.policy.max_attempts
        ):
            raise ResumeNotAllowed("run is not eligible for another bounded retry")
        running = current.model_copy(
            update={
                "state": CheckpointState.RUNNING,
                "revision": current.revision + 1,
                "attempts": {**current.attempts, attempt_key: attempt + 1},
                "retry_at": None,
                "updated_at": self.now(),
            }
        )
        stored = self._transition(current, running)
        self._emit(stored, "retry_resumed")
        self._resume_started(stored, current.revision)
        if stored.next_step == "review_hypothesis":
            return await self._resume_review(stored)
        return await self._investigate(stored)

    async def _investigate(self, current: RunCheckpoint) -> RunCheckpoint:
        try:
            evidence = await self.tools.collect_evidence(incident=current.incident)
        except TimeoutError as error:
            return self._timeout(current, error)
        self._stage_started(current, "hypothesis")
        try:
            card = await self.agent.decide(
                run_id=current.run_id,
                incident=current.incident,
                evidence=evidence,
            )
            self._enforce_provenance(card, evidence)
            EvidenceGate().enforce(card)
        except PolicyViolation as error:
            self._stage_failed(current, "hypothesis", error)
            return self._escalate(current, str(error), evidence)
        except Exception as error:
            self._stage_failed(current, "hypothesis", error)
            raise
        if self.critic is not None:
            handoff = self._checkpoint_hypothesis(current, card, evidence)
            self._stage_completed(handoff, "hypothesis")
            return await self._review(handoff, evidence)
        self._stage_completed(current, "hypothesis")
        return self._apply_proposal(current, card, evidence)

    def _checkpoint_hypothesis(
        self,
        current: RunCheckpoint,
        card: HypothesisCard,
        evidence: tuple[object, ...],
    ) -> RunCheckpoint:
        """Persist the typed inter-agent hand-off before invoking the critic."""
        refs = tuple(item for item in evidence if isinstance(item, EvidenceRef))
        proposed = current.model_copy(
            update={
                "revision": current.revision + 1,
                "next_step": "review_hypothesis",
                "evidence_refs": merge_evidence(current.evidence_refs, refs),
                "hypothesis_card": card,
                "attempts": {**current.attempts, "critic": 1},
                "updated_at": self.now(),
            }
        )
        stored = self._transition(current, proposed)
        self._emit(stored, "hypothesis_checkpointed")
        return stored

    async def _resume_review(self, current: RunCheckpoint) -> RunCheckpoint:
        """Rehydrate read-only evidence and reuse the durable hypothesis hand-off.

        Checkpoints retain only references, never evidence excerpts or prompts.  A
        resumed critic step therefore fetches a fresh read-only pack and verifies
        that the persisted proposal still cites that pack before it is reviewed.
        """
        if current.hypothesis_card is None:
            raise ResumeNotAllowed("review retry requires a persisted hypothesis hand-off")
        try:
            evidence = await self.tools.collect_evidence(incident=current.incident)
            self._enforce_provenance(current.hypothesis_card, evidence)
        except TimeoutError as error:
            return self._critic_timeout(current, error)
        except PolicyViolation as error:
            self._stage_failed(current, "critic", error)
            return self._escalate(current, str(error), ())
        return await self._review(current, evidence)

    async def _review(
        self, current: RunCheckpoint, evidence: tuple[Evidence, ...]
    ) -> RunCheckpoint:
        assert self.critic is not None
        assert current.hypothesis_card is not None
        self._stage_started(current, "critic")
        try:
            critique = await self.critic.review(
                run_id=current.run_id,
                incident=current.incident,
                evidence=evidence,
                proposal=current.hypothesis_card,
            )
        except (TimeoutError, ConnectionError) as error:
            self._stage_failed(current, "critic", error)
            return self._critic_timeout(current, error)
        except PolicyViolation as error:
            self._stage_failed(current, "critic", error)
            return self._escalate(current, str(error), evidence)
        except Exception as error:
            self._stage_failed(current, "critic", error)
            raise
        self._stage_completed(current, "critic")
        self._stage_started(current, "gate")
        if critique.outcome is CritiqueOutcome.RETRY:
            card = HypothesisCard(
                decision=Decision.RETRY,
                uncertainty=critique.rationale,
                next_action=critique.next_action,
            )
            stored = self._retry(current, card, evidence, "critic_retry", critique=critique)
            self._gate_decided(stored, "retry")
            self._stage_completed(stored, "gate")
            return stored
        if critique.outcome is CritiqueOutcome.ESCALATE:
            stored = self._escalate(
                current,
                critique.rationale,
                evidence,
                critique=critique,
            )
            self._gate_decided(stored, "escalate")
            self._stage_completed(stored, "gate")
            return stored
        stored = self._apply_proposal(current, current.hypothesis_card, evidence, critique)
        if stored.state is CheckpointState.COMPLETED:
            decision: Literal["approve", "retry", "escalate"] = "approve"
        elif stored.state is CheckpointState.WAITING_RETRY:
            decision = "retry"
        else:
            decision = "escalate"
        self._gate_decided(stored, decision)
        self._stage_completed(stored, "gate")
        return stored

    def _apply_proposal(
        self,
        current: RunCheckpoint,
        card: HypothesisCard,
        evidence: tuple[Evidence, ...],
        critique: CritiqueCard | None = None,
    ) -> RunCheckpoint:
        if card.decision is Decision.CONCLUDE:
            proposed = current.model_copy(
                update={
                    "state": CheckpointState.COMPLETED,
                    "revision": current.revision + 1,
                    "next_step": "done",
                    "evidence_refs": merge_evidence(current.evidence_refs, tuple(evidence)),
                    "critique": critique,
                    "decision": card,
                    "updated_at": self.now(),
                }
            )
            stored = self._transition(current, proposed)
            self._emit(stored, "gate_concluded" if critique else "concluded")
            return stored
        if card.decision is Decision.ESCALATE:
            return self._escalate(current, card.uncertainty, evidence, card, critique)
        return self._retry(current, card, evidence, "agent_retry", critique=critique)

    def _timeout(self, current: RunCheckpoint, error: TimeoutError) -> RunCheckpoint:
        failure = FailureRecord(
            kind=FailureKind.TRANSIENT,
            code="read_only_timeout",
            message=str(error) or "read-only evidence collection timed out",
            occurred_at=self.now(),
            retryable=True,
            step="collect_evidence",
        )
        card = HypothesisCard(
            decision=Decision.RETRY,
            uncertainty="Evidence collection timed out; no conclusion is safe.",
            next_action="Retry the read-only evidence collection once.",
        )
        return self._retry(current, card, (), failure.code, failure)

    def _critic_timeout(self, current: RunCheckpoint, error: Exception) -> RunCheckpoint:
        """Schedule a bounded retry at the critic boundary, not at investigation."""
        failure = FailureRecord(
            kind=FailureKind.TRANSIENT,
            code="critic_transient_failure",
            message=str(error) or "hypothesis review did not complete",
            occurred_at=self.now(),
            retryable=True,
            step="review_hypothesis",
        )
        card = HypothesisCard(
            decision=Decision.RETRY,
            uncertainty="Hypothesis review did not complete; no conclusion is safe.",
            next_action="Retry the bounded hypothesis review without performing a write.",
        )
        return self._retry(
            current,
            card,
            (),
            failure.code,
            failure,
            retry_step="review_hypothesis",
            attempt_key="critic",
        )

    def _retry(
        self,
        current: RunCheckpoint,
        card: HypothesisCard,
        evidence: tuple[object, ...],
        code: str,
        failure: FailureRecord | None = None,
        critique: CritiqueCard | None = None,
        retry_step: Literal["collect_evidence", "review_hypothesis"] = "collect_evidence",
        attempt_key: Literal["investigate", "critic"] = "investigate",
    ) -> RunCheckpoint:
        if current.attempts.get(attempt_key, 0) >= self.policy.max_attempts:
            return self._escalate(
                current,
                f"Retry budget exhausted ({code}).",
                evidence,
                critique=critique,
            )
        retry_at = self.now() + self.policy.retry_delay
        refs = tuple(item for item in evidence if isinstance(item, EvidenceRef))
        proposed = current.model_copy(
            update={
                "state": CheckpointState.WAITING_RETRY,
                "revision": current.revision + 1,
                "next_step": retry_step,
                "retry_at": retry_at,
                "evidence_refs": merge_evidence(current.evidence_refs, refs),
                "decision": card,
                "critique": critique,
                "last_failure": failure,
                "updated_at": self.now(),
            }
        )
        stored = self._transition(current, proposed)
        self.scheduler.schedule(run_id=stored.run_id, retry_at=retry_at)
        self._emit(stored, "retry_scheduled")
        self._retry_scheduled(stored)
        return stored

    @staticmethod
    def _attempt_key_for(current: RunCheckpoint) -> Literal["investigate", "critic"]:
        if current.next_step == "review_hypothesis":
            return "critic"
        if current.next_step == "collect_evidence":
            return "investigate"
        raise ResumeNotAllowed(f"retry has no resumable step: {current.next_step}")

    def _escalate(
        self,
        current: RunCheckpoint,
        reason: str,
        evidence: tuple[object, ...],
        card: HypothesisCard | None = None,
        critique: CritiqueCard | None = None,
    ) -> RunCheckpoint:
        refs = tuple(item for item in evidence if isinstance(item, EvidenceRef))
        escalation = (
            card
            if card and card.decision is Decision.ESCALATE
            else HypothesisCard(
                decision=Decision.ESCALATE,
                uncertainty=reason,
                next_action="Escalate to a human reviewer; do not perform a write.",
                evidence=refs,
            )
        )
        proposed = current.model_copy(
            update={
                "state": CheckpointState.ESCALATED,
                "revision": current.revision + 1,
                "next_step": "human_review",
                "evidence_refs": merge_evidence(current.evidence_refs, refs),
                "decision": escalation,
                "critique": critique,
                "updated_at": self.now(),
            }
        )
        stored = self._transition(current, proposed)
        self._emit(stored, "critic_escalated" if critique else "escalated")
        return stored

    @staticmethod
    def _enforce_provenance(card: HypothesisCard, evidence: tuple[object, ...]) -> None:
        trusted = {getattr(item, "evidence_id", None) for item in evidence}
        if any(ref.evidence_id not in trusted for ref in card.evidence):
            raise PolicyViolation("agent cited evidence outside the read-only evidence pack")

    def _transition(self, current: RunCheckpoint, proposed: RunCheckpoint) -> RunCheckpoint:
        CheckpointPolicy().enforce_transition(current, proposed)
        try:
            return self.checkpoints.compare_and_swap(
                expected_revision=current.revision, checkpoint=proposed
            )
        except CheckpointConflict:
            self._stale_result_rejected(current)
            raise

    def _emit(self, checkpoint: RunCheckpoint, event_type: str) -> None:
        occurred_at = self.now()
        self.events.append(
            run_id=checkpoint.run_id,
            event_type=event_type,
            payload_json=checkpoint.model_dump_json(),
            occurred_at=occurred_at,
        )
        if self.observer is not None:
            self.observer.record(
                checkpoint=checkpoint,
                event_type=event_type,
                occurred_at=occurred_at,
            )

    def _stage_started(
        self, checkpoint: RunCheckpoint, stage: Literal["hypothesis", "critic", "gate"]
    ) -> None:
        if self.observer is not None:
            self.observer.record_stage_started(
                checkpoint=checkpoint, stage=stage, occurred_at=self.now()
            )

    def _stage_completed(
        self, checkpoint: RunCheckpoint, stage: Literal["hypothesis", "critic", "gate"]
    ) -> None:
        if self.observer is not None:
            self.observer.record_stage_completed(
                checkpoint=checkpoint, stage=stage, occurred_at=self.now()
            )

    def _stage_failed(
        self,
        checkpoint: RunCheckpoint,
        stage: Literal["hypothesis", "critic", "gate"],
        error: Exception,
    ) -> None:
        if self.observer is not None:
            self.observer.record_stage_failed(
                checkpoint=checkpoint,
                stage=stage,
                failure_kind=type(error).__name__,
                occurred_at=self.now(),
            )

    def _gate_decided(
        self,
        checkpoint: RunCheckpoint,
        decision: Literal["approve", "retry", "escalate"],
    ) -> None:
        if self.observer is not None:
            self.observer.record_gate_decision(
                checkpoint=checkpoint, decision=decision, occurred_at=self.now()
            )

    def _retry_scheduled(self, checkpoint: RunCheckpoint) -> None:
        if self.observer is not None:
            self.observer.record_retry_scheduled(
                checkpoint=checkpoint,
                stage=self._stage_for(checkpoint),
                occurred_at=self.now(),
            )

    def _resume_started(self, checkpoint: RunCheckpoint, resumed_from_revision: int) -> None:
        if self.observer is not None:
            self.observer.record_resume_started(
                checkpoint=checkpoint,
                stage=self._stage_for(checkpoint),
                resumed_from_revision=resumed_from_revision,
                occurred_at=self.now(),
            )

    def _stale_result_rejected(self, checkpoint: RunCheckpoint) -> None:
        if self.observer is not None:
            self.observer.record_stale_result_rejected(
                checkpoint=checkpoint,
                stage=self._stage_for(checkpoint),
                expected_revision=checkpoint.revision,
                observed_revision=checkpoint.revision + 1,
                kind="revision_conflict",
                occurred_at=self.now(),
            )

    @staticmethod
    def _stage_for(checkpoint: RunCheckpoint) -> Literal["hypothesis", "critic", "gate"]:
        if checkpoint.next_step == "review_hypothesis":
            return "critic"
        return "hypothesis"
