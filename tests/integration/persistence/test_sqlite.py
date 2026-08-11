from datetime import UTC, datetime, timedelta

import pytest

from aula12_agents.domain import (
    CheckpointState,
    EffectRecord,
    EffectStatus,
    Incident,
    RunCheckpoint,
)
from aula12_agents.infrastructure.persistence import (
    IdempotencyConflict,
    RevisionConflict,
    SQLitePersistence,
)

NOW = datetime(2026, 8, 8, tzinfo=UTC)
HASH = "c" * 64


def checkpoint() -> RunCheckpoint:
    return RunCheckpoint(
        workflow_version="1",
        state=CheckpointState.RUNNING,
        incident=Incident(
            incident_id="inc-1",
            title="Falha no checkout",
            description="Erro 500",
            reported_at=NOW,
            service="checkout",
            severity="high",
        ),
        input_sha256=HASH,
        next_step="investigate",
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
def store(tmp_path) -> SQLitePersistence:
    return SQLitePersistence(tmp_path / "runs.sqlite3")


def test_checkpoint_cas_and_event_are_durable(store: SQLitePersistence):
    initial = store.create(checkpoint())
    store.append(run_id=initial.run_id, event_type="started", payload_json="{}", occurred_at=NOW)
    updated = initial.model_copy(
        update={
            "revision": 1,
            "state": CheckpointState.CANCELLED,
            "updated_at": NOW + timedelta(seconds=1),
        }
    )
    assert store.compare_and_swap(expected_revision=0, checkpoint=updated) == updated
    assert store.load(initial.run_id) == updated

    with pytest.raises(RevisionConflict):
        store.compare_and_swap(expected_revision=0, checkpoint=updated)


def test_effect_ledger_deduplicates_and_records_confirmation(store: SQLitePersistence):
    effect = EffectRecord(
        idempotency_key="issue:inc-1",
        kind="draft_issue",
        payload_sha256=HASH,
        created_at=NOW,
        updated_at=NOW,
    )
    assert store.reserve(effect) == effect
    assert store.reserve(effect) == effect
    confirmed = store.confirm(
        effect_id=effect.effect_id,
        provider_receipt="issue-42",
        occurred_at=NOW + timedelta(seconds=1),
    )
    assert confirmed.status is EffectStatus.CONFIRMED
    assert store.find(idempotency_key="issue:inc-1") == confirmed


def test_effect_ledger_rejects_key_reused_for_another_payload(store: SQLitePersistence):
    effect = EffectRecord(
        idempotency_key="issue:inc-1",
        kind="draft_issue",
        payload_sha256=HASH,
        created_at=NOW,
        updated_at=NOW,
    )
    store.reserve(effect)
    other = effect.model_copy(update={"payload_sha256": "d" * 64})
    with pytest.raises(IdempotencyConflict):
        store.reserve(other)
