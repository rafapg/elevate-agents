from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from aula12_agents.domain import (
    CheckpointState,
    Decision,
    EvidenceRef,
    HypothesisCard,
    Incident,
    RunCheckpoint,
)

NOW = datetime(2026, 8, 8, tzinfo=UTC)
HASH = "a" * 64


def incident() -> Incident:
    return Incident(
        incident_id="inc-1",
        title="Checkout falha",
        description="Erros 500",
        reported_at=NOW,
        service="checkout",
        severity="high",
    )


def evidence() -> EvidenceRef:
    return EvidenceRef(
        source="logs", artifact_id="checkout.jsonl", content_sha256=HASH, captured_at=NOW
    )


def test_conclusion_requires_evidence():
    with pytest.raises(ValidationError, match="conclusão exige"):
        HypothesisCard(decision=Decision.CONCLUDE, uncertainty="baixa", next_action="Encerrar")


def test_retry_cannot_claim_hypothesis():
    with pytest.raises(ValidationError, match="retry não deve"):
        HypothesisCard(
            decision=Decision.RETRY,
            uncertainty="CI indisponível",
            next_action="Tentar novamente",
            hypothesis={"statement": "x", "rationale": "y", "uncertainty": "z"},
        )


def test_checkpoint_waiting_retry_requires_retry_at():
    retry_card = HypothesisCard(
        decision=Decision.RETRY, uncertainty="CI indisponível", next_action="Tentar novamente"
    )
    with pytest.raises(ValidationError, match="waiting_retry exige retry_at"):
        RunCheckpoint(
            workflow_version="1",
            state=CheckpointState.WAITING_RETRY,
            incident=incident(),
            input_sha256=HASH,
            next_step="retry_ci",
            decision=retry_card,
            created_at=NOW,
            updated_at=NOW,
        )


def test_valid_checkpoint_is_frozen():
    card = HypothesisCard(
        decision=Decision.CONCLUDE,
        uncertainty="baixa",
        next_action="Encerrar",
        evidence=(evidence(),),
    )
    checkpoint = RunCheckpoint(
        workflow_version="1",
        state=CheckpointState.COMPLETED,
        incident=incident(),
        input_sha256=HASH,
        next_step="done",
        decision=card,
        created_at=NOW,
        updated_at=NOW + timedelta(seconds=1),
    )
    with pytest.raises(ValidationError):
        checkpoint.state = CheckpointState.RUNNING
