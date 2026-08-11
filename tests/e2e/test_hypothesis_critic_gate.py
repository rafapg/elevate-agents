"""The application owns multi-agent control flow, independent of PydanticAI."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

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

NOW = datetime(2026, 8, 10, tzinfo=UTC)


class MemoryStore:
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
        assert self.value.revision == expected_revision
        self.value = checkpoint
        self.history.append(checkpoint)
        return checkpoint


class Fixtures:
    async def collect_evidence(self, *, incident: Incident) -> tuple[Evidence, ...]:
        del incident
        return (
            Evidence(
                source="logs",
                artifact_id="BUG-204.jsonl",
                content_sha256="a" * 64,
                captured_at=NOW,
                summary="Checkout requests timed out after a deploy.",
            ),
        )


class HypothesisSpecialist:
    async def decide(
        self, *, run_id: UUID, incident: Incident, evidence: tuple[Evidence, ...]
    ) -> HypothesisCard:
        del run_id, incident
        return HypothesisCard(
            decision=Decision.CONCLUDE,
            hypothesis={
                "statement": "The deploy exhausted the connection pool.",
                "rationale": "Timeouts began immediately after deployment.",
                "uncertainty": "Pool metrics have not yet been inspected.",
                "evidence": (evidence[0],),
            },
            uncertainty="Pool metrics have not yet been inspected.",
            next_action="Inspect database connection-pool metrics.",
            evidence=(evidence[0],),
        )


class Critic:
    def __init__(self, outcome: CritiqueOutcome) -> None:
        self.outcome = outcome
        self.proposals: list[HypothesisCard] = []

    async def review(
        self,
        *,
        run_id: UUID,
        incident: Incident,
        evidence: tuple[Evidence, ...],
        proposal: HypothesisCard,
    ) -> CritiqueCard:
        del run_id, incident, evidence
        self.proposals.append(proposal)
        return CritiqueCard(
            outcome=self.outcome,
            rationale="The evidence supports a bounded operational decision.",
            gaps=("No direct connection-pool metric yet.",),
            next_action="Inspect the relevant metric before any write.",
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


@pytest.mark.parametrize(
    ("outcome", "expected_state", "expected_event"),
    [
        (CritiqueOutcome.APPROVE, CheckpointState.COMPLETED, "gate_concluded"),
        (CritiqueOutcome.RETRY, CheckpointState.WAITING_RETRY, "retry_scheduled"),
        (CritiqueOutcome.ESCALATE, CheckpointState.ESCALATED, "critic_escalated"),
    ],
)
def test_hypothesis_critic_gate_persists_each_handoff(
    outcome: CritiqueOutcome, expected_state: CheckpointState, expected_event: str
) -> None:
    async def scenario() -> tuple[RunCheckpoint, MemoryStore, Critic, Scheduler, Events]:
        store, critic, scheduler, events = MemoryStore(), Critic(outcome), Scheduler(), Events()
        coordinator = RunCoordinator(
            checkpoints=store,
            tools=Fixtures(),
            agent=HypothesisSpecialist(),
            critic=critic,
            scheduler=scheduler,
            events=events,
            policy=CoordinatorPolicy("multi-agent-v1", "b" * 64, retry_delay=timedelta(seconds=1)),
            now=lambda: NOW,
        )
        result = await coordinator.start(_incident())
        return result, store, critic, scheduler, events

    result, store, critic, scheduler, events = asyncio.run(scenario())

    assert result.state is expected_state
    assert result.critique is not None
    assert result.critique.outcome is outcome
    assert len(critic.proposals) == 1
    # initial checkpoint -> persisted proposal -> persisted critic/gate outcome
    assert [checkpoint.revision for checkpoint in store.history] == [0, 1, 2]
    handoff = store.history[1]
    assert handoff.state is CheckpointState.RUNNING
    assert handoff.next_step == "review_hypothesis"
    assert handoff.hypothesis_card == critic.proposals[0]
    assert events.types == ["checkpoint_created", "hypothesis_checkpointed", expected_event]
    assert bool(scheduler.scheduled) is (outcome is CritiqueOutcome.RETRY)
