from datetime import UTC, datetime, timedelta

import pytest

from aula12_agents.domain import (
    CheckpointPolicy,
    CheckpointState,
    Decision,
    EvidenceGate,
    EvidenceRef,
    HypothesisCard,
    Incident,
    RunCheckpoint,
)
from aula12_agents.domain.policies import PolicyViolation

NOW = datetime(2026, 8, 8, tzinfo=UTC)
HASH = "b" * 64


def make_checkpoint(state=CheckpointState.RUNNING, revision=0) -> RunCheckpoint:
    incident = Incident(
        incident_id="inc-1",
        title="Checkout falha",
        description="Erros 500",
        reported_at=NOW,
        service="checkout",
        severity="high",
    )
    return RunCheckpoint(
        workflow_version="1",
        state=state,
        revision=revision,
        incident=incident,
        input_sha256=HASH,
        next_step="investigate",
        created_at=NOW,
        updated_at=NOW,
    )


def test_evidence_gate_blocks_unproven_conclusion():
    card = HypothesisCard(
        decision=Decision.CONCLUDE,
        uncertainty="baixa",
        next_action="Encerrar",
        evidence=(
            EvidenceRef(source="logs", artifact_id="x", content_sha256=HASH, captured_at=NOW),
        ),
    )
    assert EvidenceGate().allows(card)


def test_checkpoint_policy_requires_one_revision_and_valid_route():
    current = make_checkpoint()
    proposed = current.model_copy(
        update={
            "state": CheckpointState.CANCELLED,
            "revision": 1,
            "updated_at": NOW + timedelta(seconds=1),
        }
    )
    CheckpointPolicy().enforce_transition(current, proposed)

    invalid = current.model_copy(
        update={
            "state": CheckpointState.COMPLETED,
            "revision": 2,
            "updated_at": NOW + timedelta(seconds=1),
        }
    )
    with pytest.raises(PolicyViolation, match="exatamente uma revisão"):
        CheckpointPolicy().enforce_transition(current, invalid)
