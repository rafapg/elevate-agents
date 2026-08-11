"""Small deterministic scenarios used directly in the Aula 12 walkthrough.

They deliberately use in-memory adapters: students can inspect every durable
checkpoint and event without an API key, Ollama, SQLite, or Langfuse.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from aula12_agents.application.coordinator import CoordinatorPolicy, RunCoordinator
from aula12_agents.domain.models import (
    CheckpointState,
    CritiqueCard,
    CritiqueOutcome,
    Decision,
    Evidence,
    HypothesisCard,
    Incident,
    RunCheckpoint,
)
from aula12_agents.infrastructure.persistence import RevisionConflict

NOW = datetime(2026, 8, 10, tzinfo=UTC)


class MemoryCheckpoints:
    """A teaching adapter that preserves the durable snapshots in order."""

    def __init__(self) -> None:
        self.current: RunCheckpoint | None = None
        self.snapshots: list[RunCheckpoint] = []

    def create(self, checkpoint: RunCheckpoint) -> RunCheckpoint:
        self.current = checkpoint
        self.snapshots.append(checkpoint)
        return checkpoint

    def load(self, run_id: UUID) -> RunCheckpoint:
        assert self.current is not None
        assert self.current.run_id == run_id
        return self.current

    def compare_and_swap(
        self, *, expected_revision: int, checkpoint: RunCheckpoint
    ) -> RunCheckpoint:
        assert self.current is not None
        if self.current.revision != expected_revision:
            raise RevisionConflict(f"expected revision {expected_revision}")
        self.current = checkpoint
        self.snapshots.append(checkpoint)
        return checkpoint


class LessonEvents:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, object]]] = []

    def append(
        self, *, run_id: UUID, event_type: str, payload_json: str, occurred_at: datetime
    ) -> None:
        del run_id, occurred_at
        self.records.append((event_type, json.loads(payload_json)))


class Scheduler:
    def __init__(self) -> None:
        self.scheduled: list[UUID] = []

    def schedule(self, *, run_id: UUID, retry_at: datetime) -> None:
        del retry_at
        self.scheduled.append(run_id)


class EvidenceFixtures:
    def __init__(self) -> None:
        self.calls = 0
        self.pack = (
            Evidence(
                source="logs",
                artifact_id="BUG-204.jsonl",
                content_sha256="a" * 64,
                captured_at=NOW,
                summary="Checkout timeouts began immediately after the deploy.",
            ),
        )

    async def collect_evidence(self, *, incident: Incident) -> tuple[Evidence, ...]:
        del incident
        self.calls += 1
        return self.pack


class Specialist:
    def __init__(self) -> None:
        self.calls = 0

    async def decide(
        self, *, run_id: UUID, incident: Incident, evidence: tuple[Evidence, ...]
    ) -> HypothesisCard:
        del run_id, incident
        self.calls += 1
        return HypothesisCard(
            decision=Decision.CONCLUDE,
            hypothesis={
                "statement": "The deploy exhausted the connection pool.",
                "rationale": "Timeouts started with the deploy.",
                "uncertainty": "The pool metric is not in this fixture.",
                "evidence": evidence,
            },
            uncertainty="The pool metric is not in this fixture.",
            next_action="Inspect database connection-pool metrics.",
            evidence=evidence,
        )


class ScriptedCritic:
    def __init__(self, *outcomes: CritiqueOutcome | TimeoutError) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    async def review(
        self,
        *,
        run_id: UUID,
        incident: Incident,
        evidence: tuple[Evidence, ...],
        proposal: HypothesisCard,
    ) -> CritiqueCard:
        del run_id, incident, evidence, proposal
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, TimeoutError):
            raise outcome
        return CritiqueCard(
            outcome=outcome,
            rationale="A direct pool metric is still missing.",
            gaps=("Collect the direct pool metric before a write.",),
            next_action="Inspect database connection-pool metrics.",
        )


class BarrierCritic:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def review(
        self,
        *,
        run_id: UUID,
        incident: Incident,
        evidence: tuple[Evidence, ...],
        proposal: HypothesisCard,
    ) -> CritiqueCard:
        del run_id, incident, evidence, proposal
        self.started.set()
        await self.release.wait()
        return CritiqueCard(
            outcome=CritiqueOutcome.APPROVE,
            rationale="The proposal is bounded.",
            next_action="Inspect database connection-pool metrics.",
        )


class LessonObserver:
    """Records only the resilience signal needed by the late-result scenario."""

    def __init__(self) -> None:
        self.stale_rejections: list[tuple[str, int, int]] = []

    def record(self, **_: object) -> None: ...

    def record_stage_started(self, **_: object) -> None: ...

    def record_stage_completed(self, **_: object) -> None: ...

    def record_stage_failed(self, **_: object) -> None: ...

    def record_gate_decision(self, **_: object) -> None: ...

    def record_retry_scheduled(self, **_: object) -> None: ...

    def record_resume_started(self, **_: object) -> None: ...

    def record_stale_result_rejected(
        self, *, stage: str, expected_revision: int, observed_revision: int, **_: object
    ) -> None:
        self.stale_rejections.append((stage, expected_revision, observed_revision))


def _incident() -> Incident:
    return Incident(
        incident_id="BUG-204",
        title="Checkout timeout",
        description="Checkout requests fail after deployment.",
        reported_at=NOW,
        service="checkout",
        severity="high",
    )


def _coordinator(
    store: MemoryCheckpoints,
    tools: EvidenceFixtures,
    agent: Specialist,
    critic: object,
    events: LessonEvents,
    scheduler: Scheduler,
    observer: LessonObserver | None = None,
) -> RunCoordinator:
    return RunCoordinator(
        checkpoints=store,
        tools=tools,
        agent=agent,
        critic=critic,  # type: ignore[arg-type]
        scheduler=scheduler,
        events=events,
        observer=observer,  # type: ignore[arg-type]
        policy=CoordinatorPolicy(
            "lesson-v1", "b" * 64, max_attempts=2, retry_delay=timedelta(seconds=1)
        ),
        now=lambda: NOW,
    )


def test_lesson_approved_conclusion_exposes_handoff_checkpoint_and_artifact() -> None:
    async def scenario() -> tuple[RunCheckpoint, MemoryCheckpoints, LessonEvents]:
        store, tools, agent, events, scheduler = (
            MemoryCheckpoints(),
            EvidenceFixtures(),
            Specialist(),
            LessonEvents(),
            Scheduler(),
        )
        result = await _coordinator(
            store, tools, agent, ScriptedCritic(CritiqueOutcome.APPROVE), events, scheduler
        ).start(_incident())
        return result, store, events

    result, store, events = asyncio.run(scenario())

    assert result.state is CheckpointState.COMPLETED
    assert [snapshot.revision for snapshot in store.snapshots] == [0, 1, 2]
    assert store.snapshots[1].next_step == "review_hypothesis"
    assert store.snapshots[1].hypothesis_card is not None
    assert [kind for kind, _ in events.records] == [
        "checkpoint_created",
        "hypothesis_checkpointed",
        "gate_concluded",
    ]
    final_artifact = events.records[-1][1]
    assert final_artifact["state"] == "completed"
    assert final_artifact["evidence_refs"][0]["artifact_id"] == "BUG-204.jsonl"


def test_lesson_insufficient_evidence_is_escalated_by_the_critic_gate() -> None:
    async def scenario() -> tuple[RunCheckpoint, LessonEvents]:
        store, tools, agent, events, scheduler = (
            MemoryCheckpoints(),
            EvidenceFixtures(),
            Specialist(),
            LessonEvents(),
            Scheduler(),
        )
        result = await _coordinator(
            store, tools, agent, ScriptedCritic(CritiqueOutcome.ESCALATE), events, scheduler
        ).start(_incident())
        return result, events

    result, events = asyncio.run(scenario())

    assert result.state is CheckpointState.ESCALATED
    assert result.next_step == "human_review"
    assert result.critique is not None
    assert result.critique.gaps
    assert [kind for kind, _ in events.records][-1] == "critic_escalated"
    assert events.records[-1][1]["decision"]["decision"] == "escalate"


def test_lesson_critic_timeout_resumes_from_the_persisted_handoff() -> None:
    async def scenario() -> tuple[
        RunCheckpoint,
        RunCheckpoint,
        EvidenceFixtures,
        Specialist,
        ScriptedCritic,
        LessonEvents,
    ]:
        store, tools, agent, events, scheduler = (
            MemoryCheckpoints(),
            EvidenceFixtures(),
            Specialist(),
            LessonEvents(),
            Scheduler(),
        )
        critic = ScriptedCritic(TimeoutError("synthetic timeout"), CritiqueOutcome.APPROVE)
        coordinator = _coordinator(store, tools, agent, critic, events, scheduler)
        waiting = await coordinator.start(_incident())
        resumed = await coordinator.resume(waiting.run_id)
        return waiting, resumed, tools, agent, critic, events

    waiting, resumed, tools, agent, critic, events = asyncio.run(scenario())

    assert waiting.state is CheckpointState.WAITING_RETRY
    assert waiting.next_step == "review_hypothesis"
    assert resumed.state is CheckpointState.COMPLETED
    assert (tools.calls, agent.calls, critic.calls) == (2, 1, 2)
    assert [kind for kind, _ in events.records] == [
        "checkpoint_created",
        "hypothesis_checkpointed",
        "retry_scheduled",
        "retry_resumed",
        "gate_concluded",
    ]


def test_lesson_late_critic_result_is_rejected_without_overwriting_checkpoint() -> None:
    async def scenario() -> tuple[RunCheckpoint, BaseException, LessonObserver]:
        store, tools, agent, events, scheduler, observer = (
            MemoryCheckpoints(),
            EvidenceFixtures(),
            Specialist(),
            LessonEvents(),
            Scheduler(),
            LessonObserver(),
        )
        critic = BarrierCritic()
        coordinator = _coordinator(store, tools, agent, critic, events, scheduler, observer)
        proposal = await agent.decide(run_id=UUID(int=1), incident=_incident(), evidence=tools.pack)
        handoff = store.create(
            RunCheckpoint(
                workflow_version="lesson-v1",
                state=CheckpointState.RUNNING,
                revision=1,
                incident=_incident(),
                input_sha256="b" * 64,
                next_step="review_hypothesis",
                attempts={"investigate": 1, "critic": 1},
                evidence_refs=tools.pack,
                hypothesis_card=proposal,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        first = asyncio.create_task(coordinator._review(handoff, tools.pack))
        await critic.started.wait()
        second = asyncio.create_task(coordinator._review(handoff, tools.pack))
        await asyncio.sleep(0)
        critic.release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        completed = next(item for item in results if isinstance(item, RunCheckpoint))
        rejected = next(item for item in results if isinstance(item, BaseException))
        return completed, rejected, observer

    completed, rejected, observer = asyncio.run(scenario())

    assert completed.state is CheckpointState.COMPLETED
    assert isinstance(rejected, RevisionConflict)
    assert observer.stale_rejections == [("critic", 1, 2)]
