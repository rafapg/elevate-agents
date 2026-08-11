from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from aula12_agents.application.coordinator import CoordinatorPolicy, RunCoordinator
from aula12_agents.domain.models import CheckpointState, Incident

NOW = datetime(2026, 8, 8, tzinfo=UTC)


class MemoryStore:
    def __init__(self) -> None:
        self.value = None

    def create(self, checkpoint):
        self.value = checkpoint
        return checkpoint

    def load(self, run_id):
        assert self.value is not None
        assert self.value.run_id == run_id
        return self.value

    def compare_and_swap(self, *, expected_revision, checkpoint):
        assert self.value is not None
        assert self.value.revision == expected_revision
        self.value = checkpoint
        return checkpoint


class TimeoutThenEvidence:
    def __init__(self) -> None:
        self.calls = 0

    async def collect_evidence(self, *, incident):
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("CI timeout")
        return ()


class Escalator:
    async def decide(self, *, run_id, incident, evidence):
        del run_id
        from aula12_agents.domain.models import Decision, HypothesisCard

        return HypothesisCard(
            decision=Decision.ESCALATE, uncertainty="CI unavailable", next_action="Review"
        )


class Scheduler:
    def schedule(self, *, run_id, retry_at):
        self.retry_at = retry_at


class Events:
    def __init__(self) -> None:
        self.types = []

    def append(self, *, run_id, event_type, payload_json, occurred_at):
        self.types.append(event_type)


def test_timeout_retry_resume_escalate() -> None:
    async def scenario():
        store, tools, scheduler, events = (
            MemoryStore(),
            TimeoutThenEvidence(),
            Scheduler(),
            Events(),
        )
        coordinator = RunCoordinator(
            checkpoints=store,
            tools=tools,
            agent=Escalator(),
            scheduler=scheduler,
            events=events,
            policy=CoordinatorPolicy(
                "v1", "a" * 64, max_attempts=2, retry_delay=timedelta(seconds=1)
            ),
            now=lambda: NOW,
        )
        incident = Incident(
            incident_id="i-1",
            title="checkout",
            description="timeout",
            reported_at=NOW,
            service="pay",
            severity="high",
        )
        waiting = await coordinator.start(incident)
        final = await coordinator.resume(waiting.run_id)
        return waiting, final, events

    waiting, final, events = asyncio.run(scenario())
    assert waiting.state is CheckpointState.WAITING_RETRY
    assert final.state is CheckpointState.ESCALATED
    assert events.types == ["checkpoint_created", "retry_scheduled", "retry_resumed", "escalated"]
