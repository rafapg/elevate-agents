"""Resilience contracts at the durable specialist-to-critic boundary."""

from __future__ import annotations

import asyncio
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


class CompareAndSwapMemoryStore:
    def __init__(self) -> None:
        self.value: RunCheckpoint | None = None
        self.history: list[RunCheckpoint] = []

    def create(self, checkpoint: RunCheckpoint) -> RunCheckpoint:
        self.value = checkpoint
        self.history.append(checkpoint)
        return checkpoint

    def load(self, run_id: UUID) -> RunCheckpoint:
        assert self.value is not None
        assert self.value.run_id == run_id
        return self.value

    def compare_and_swap(
        self, *, expected_revision: int, checkpoint: RunCheckpoint
    ) -> RunCheckpoint:
        assert self.value is not None
        if self.value.revision != expected_revision:
            raise RevisionConflict(f"stale revision: {expected_revision}")
        self.value = checkpoint
        self.history.append(checkpoint)
        return checkpoint


class EvidenceTool:
    def __init__(self) -> None:
        self.calls = 0
        self.evidence = (
            Evidence(
                source="logs",
                artifact_id="BUG-204.jsonl",
                content_sha256="a" * 64,
                captured_at=NOW,
                summary="Checkout requests timed out after a deploy.",
            ),
        )

    async def collect_evidence(self, *, incident: Incident) -> tuple[Evidence, ...]:
        del incident
        self.calls += 1
        return self.evidence


class HypothesisSpecialist:
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
                "rationale": "Timeouts began immediately after deployment.",
                "uncertainty": "Pool metrics have not yet been inspected.",
                "evidence": evidence,
            },
            uncertainty="Pool metrics have not yet been inspected.",
            next_action="Inspect database connection-pool metrics.",
            evidence=evidence,
        )


class TimeoutThenApproveCritic:
    def __init__(self) -> None:
        self.calls = 0
        self.evidence_packs: list[tuple[Evidence, ...]] = []

    async def review(
        self,
        *,
        run_id: UUID,
        incident: Incident,
        evidence: tuple[Evidence, ...],
        proposal: HypothesisCard,
    ) -> CritiqueCard:
        del run_id, incident, proposal
        self.calls += 1
        self.evidence_packs.append(evidence)
        if self.calls == 1:
            raise TimeoutError("critic provider timed out")
        return CritiqueCard(
            outcome=CritiqueOutcome.APPROVE,
            rationale="The proposal is bounded by the evidence.",
            next_action="Inspect database connection-pool metrics.",
        )


class BarrierApproveCritic:
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
            rationale="The proposal is bounded by the evidence.",
            next_action="Inspect database connection-pool metrics.",
        )


class Scheduler:
    def __init__(self) -> None:
        self.scheduled: list[UUID] = []

    def schedule(self, *, run_id: UUID, retry_at: datetime) -> None:
        del retry_at
        self.scheduled.append(run_id)


class Events:
    def __init__(self) -> None:
        self.types: list[str] = []

    def append(
        self, *, run_id: UUID, event_type: str, payload_json: str, occurred_at: datetime
    ) -> None:
        del run_id, payload_json, occurred_at
        self.types.append(event_type)


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
    *,
    store: CompareAndSwapMemoryStore,
    tools: EvidenceTool,
    agent: HypothesisSpecialist,
    critic: object,
    scheduler: Scheduler,
    events: Events,
) -> RunCoordinator:
    return RunCoordinator(
        checkpoints=store,
        tools=tools,
        agent=agent,
        critic=critic,  # type: ignore[arg-type]
        scheduler=scheduler,
        events=events,
        policy=CoordinatorPolicy(
            "multi-agent-v1", "b" * 64, max_attempts=2, retry_delay=timedelta(seconds=1)
        ),
        now=lambda: NOW,
    )


def test_critic_timeout_resumes_from_durable_review_handoff() -> None:
    """A critic retry must not repeat the already-persisted hypothesis stage."""

    async def scenario() -> tuple[
        RunCheckpoint,
        RunCheckpoint,
        EvidenceTool,
        HypothesisSpecialist,
        TimeoutThenApproveCritic,
        Events,
    ]:
        store, tools, agent, critic, scheduler, events = (
            CompareAndSwapMemoryStore(),
            EvidenceTool(),
            HypothesisSpecialist(),
            TimeoutThenApproveCritic(),
            Scheduler(),
            Events(),
        )
        coordinator = _coordinator(
            store=store,
            tools=tools,
            agent=agent,
            critic=critic,
            scheduler=scheduler,
            events=events,
        )
        waiting = await coordinator.start(_incident())
        resumed = await coordinator.resume(waiting.run_id)
        return waiting, resumed, tools, agent, critic, events

    waiting, resumed, tools, agent, critic, events = asyncio.run(scenario())

    assert waiting.state is CheckpointState.WAITING_RETRY
    assert waiting.next_step == "review_hypothesis"
    assert waiting.hypothesis_card is not None
    assert waiting.last_failure is not None
    assert waiting.last_failure.step == "review_hypothesis"
    assert resumed.state is CheckpointState.COMPLETED
    # Rehydration is a separate, read-only lookup; the costly hypothesis call is not repeated.
    assert tools.calls == 2
    assert agent.calls == 1
    assert critic.calls == 2
    assert critic.evidence_packs[0] == critic.evidence_packs[1]
    assert events.types == [
        "checkpoint_created",
        "hypothesis_checkpointed",
        "retry_scheduled",
        "retry_resumed",
        "gate_concluded",
    ]


def test_late_critic_result_cannot_overwrite_newer_checkpoint() -> None:
    """Two workers completing the same critic invocation race through the CAS boundary."""

    async def scenario() -> tuple[RunCheckpoint, BaseException]:
        store, tools, agent, critic, scheduler, events = (
            CompareAndSwapMemoryStore(),
            EvidenceTool(),
            HypothesisSpecialist(),
            BarrierApproveCritic(),
            Scheduler(),
            Events(),
        )
        coordinator = _coordinator(
            store=store,
            tools=tools,
            agent=agent,
            critic=critic,
            scheduler=scheduler,
            events=events,
        )
        handoff = store.create(
            RunCheckpoint(
                workflow_version="multi-agent-v1",
                state=CheckpointState.RUNNING,
                revision=1,
                incident=_incident(),
                input_sha256="b" * 64,
                next_step="review_hypothesis",
                evidence_refs=tools.evidence,
                hypothesis_card=await agent.decide(
                    run_id=UUID(int=1), incident=_incident(), evidence=tools.evidence
                ),
                created_at=NOW,
                updated_at=NOW,
            )
        )
        first = asyncio.create_task(coordinator._review(handoff, tools.evidence))
        await critic.started.wait()
        second = asyncio.create_task(coordinator._review(handoff, tools.evidence))
        await asyncio.sleep(0)
        critic.release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        completed = next(result for result in results if isinstance(result, RunCheckpoint))
        rejected = next(result for result in results if isinstance(result, BaseException))
        return completed, rejected

    completed, rejected = asyncio.run(scenario())

    assert completed.state is CheckpointState.COMPLETED
    assert isinstance(rejected, RevisionConflict)
