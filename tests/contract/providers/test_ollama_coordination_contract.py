"""Opt-in contract for the tool-free Ollama coordination specialist."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from aula12_agents.application.coordination_executor import (
    CoordinationEvidenceItem,
    CoordinationEvidencePacket,
)
from aula12_agents.domain.models import CoordinationTask, EvidenceRef, SubagentProfile
from aula12_agents.infrastructure.coordination_ollama import OllamaCoordinationExecutor
from aula12_agents.infrastructure.providers import build_model
from aula12_agents.settings import load_settings

pytestmark = pytest.mark.provider


@pytest.mark.asyncio
async def test_ollama_returns_a_bounded_typed_coordination_report() -> None:
    """Run only with ``RUN_OLLAMA_COORDINATION_CONTRACT=1`` and a local Ollama model."""
    if os.environ.get("RUN_OLLAMA_COORDINATION_CONTRACT") != "1":
        pytest.skip("set RUN_OLLAMA_COORDINATION_CONTRACT=1 to call the local Ollama model")
    settings = load_settings()
    if settings.model_provider != "ollama" or not settings.ollama_model:
        pytest.skip("configure MODEL_PROVIDER=ollama and OLLAMA_MODEL in the lab .env")
    now = datetime.now(UTC)
    task = CoordinationTask(
        profile=SubagentProfile.CI_ANALYST,
        read_scope=("read_ci_summary",),
        budget_steps=1,
        deadline=now + timedelta(seconds=90),
        expected_revision=3,
    )
    item = CoordinationEvidenceItem(
        reference=EvidenceRef(
            source="ci",
            artifact_id="fixtures/ci/run-1842.json",
            content_sha256="a" * 64,
            captured_at=now,
        ),
        summary="The synthetic CI run timed out after the checkout deployment.",
    )
    executor = OllamaCoordinationExecutor(model=build_model(settings.provider_settings()))
    report = await executor.execute(
        task=task,
        evidence=CoordinationEvidencePacket(task_id=task.task_id, items=(item,)),
    )
    assert report.task_id == task.task_id
    assert report.expected_revision == task.expected_revision
    assert report.evidence == (item.reference,)
    assert report.coverage == ("ci",)
    assert report.limitation
