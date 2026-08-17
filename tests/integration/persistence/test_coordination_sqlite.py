from datetime import UTC, datetime, timedelta

import pytest

from aula12_agents.domain.models import CoordinationRun, CoordinationRunState, CoordinationScenario
from aula12_agents.infrastructure.persistence import (
    CoordinationRevisionConflict,
    CoordinationRunNotFound,
    SQLiteCoordinationStore,
)

NOW = datetime(2026, 8, 11, tzinfo=UTC)


def coordination_run() -> CoordinationRun:
    return CoordinationRun(
        scenario=CoordinationScenario.SUPERVISOR,
        deadline=NOW + timedelta(seconds=45),
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
def store(tmp_path) -> SQLiteCoordinationStore:
    return SQLiteCoordinationStore(tmp_path / "runs.sqlite3")


def test_coordination_run_cas_is_durable_and_rejects_stale_update(
    store: SQLiteCoordinationStore,
) -> None:
    initial = store.create(coordination_run())
    updated = initial.model_copy(
        update={
            "revision": 1,
            "spent_steps": 2,
            "updated_at": NOW + timedelta(seconds=1),
        }
    )

    assert store.compare_and_swap(expected_revision=0, run=updated) == updated
    assert store.load(initial.run_id) == updated

    with pytest.raises(CoordinationRevisionConflict):
        store.compare_and_swap(expected_revision=0, run=updated)


def test_coordination_events_are_append_only_and_read_in_order(
    store: SQLiteCoordinationStore,
) -> None:
    run = store.create(coordination_run())
    store.append(
        run_id=run.run_id,
        event_type="coordination.run.started",
        payload_json='{"safe":true}',
        occurred_at=NOW,
    )
    store.append(
        run_id=run.run_id,
        event_type="coordination.aggregate.decided",
        payload_json='{"decision":"aggregate"}',
        occurred_at=NOW + timedelta(seconds=1),
    )

    events = store.list_events(run.run_id)

    assert [event.event_type for event in events] == [
        "coordination.run.started",
        "coordination.aggregate.decided",
    ]
    assert events[0].event_id < events[1].event_id
    assert events[0].payload_json == '{"safe":true}'


def test_coordination_events_require_a_persisted_run(store: SQLiteCoordinationStore) -> None:
    run = coordination_run()

    with pytest.raises(CoordinationRunNotFound):
        store.append(
            run_id=run.run_id,
            event_type="coordination.run.started",
            payload_json="{}",
            occurred_at=NOW,
        )

    with pytest.raises(CoordinationRunNotFound):
        store.list_events(run.run_id)


def test_coordination_runs_use_separate_tables_from_existing_checkpoint_store(tmp_path) -> None:
    """A coordination run id is not coupled to the linear workflow's table."""

    store = SQLiteCoordinationStore(tmp_path / "runs.sqlite3")
    initial = store.create(coordination_run())
    cancelled = initial.model_copy(
        update={
            "revision": 1,
            "state": CoordinationRunState.CANCELLED,
            "updated_at": NOW + timedelta(seconds=1),
        }
    )

    assert store.compare_and_swap(expected_revision=0, run=cancelled) == cancelled
