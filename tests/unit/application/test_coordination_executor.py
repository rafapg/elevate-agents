from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aula12_agents.application.coordination_executor import (
    CoordinationEvidenceItem,
    CoordinationEvidencePacket,
    validate_execution_request,
)
from aula12_agents.domain.models import CoordinationTask, EvidenceRef, SubagentProfile


def _task() -> CoordinationTask:
    return CoordinationTask(
        profile=SubagentProfile.CI_ANALYST,
        read_scope=("read_ci_summary",),
        budget_steps=1,
        deadline=datetime(2030, 1, 1, tzinfo=UTC),
        expected_revision=2,
    )


def _packet(task: CoordinationTask) -> CoordinationEvidencePacket:
    return CoordinationEvidencePacket(
        task_id=task.task_id,
        items=(
            CoordinationEvidenceItem(
                reference=EvidenceRef(
                    source="ci",
                    artifact_id="runs/1842.json",
                    content_sha256="a" * 64,
                    captured_at=datetime(2029, 1, 1, tzinfo=UTC),
                ),
                summary="The selected synthetic CI run timed out.",
            ),
        ),
    )


def test_execution_request_requires_the_packet_for_its_task() -> None:
    task = _task()
    now = datetime(2029, 1, 1, tzinfo=UTC)
    validate_execution_request(task=task, evidence=_packet(task), now=now)

    other = _task()
    with pytest.raises(ValueError, match="belong to the coordination task"):
        validate_execution_request(task=other, evidence=_packet(task), now=now)


def test_execution_request_rejects_an_expired_task_before_provider_execution() -> None:
    task = _task().model_copy(update={"deadline": datetime(2029, 1, 1, tzinfo=UTC)})
    with pytest.raises(TimeoutError, match="deadline"):
        validate_execution_request(
            task=task,
            evidence=_packet(task),
            now=task.deadline + timedelta(seconds=1),
        )
