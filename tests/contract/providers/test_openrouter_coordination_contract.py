"""Opt-in paid contract for the tool-free OpenRouter coordination specialist."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from aula12_agents.application.coordination_executor import (
    CoordinationEvidenceItem,
    CoordinationEvidencePacket,
)
from aula12_agents.domain.models import CoordinationTask, EvidenceRef, SubagentProfile
from aula12_agents.infrastructure.coordination_openrouter import OpenRouterCoordinationExecutor
from aula12_agents.infrastructure.providers import build_model
from aula12_agents.settings import load_settings

pytestmark = pytest.mark.provider


@pytest.mark.asyncio
async def test_openrouter_returns_a_bounded_typed_coordination_report() -> None:
    """Run only with ``RUN_OPENROUTER_COORDINATION_CONTRACT=1`` and configured credits."""
    if os.environ.get("RUN_OPENROUTER_COORDINATION_CONTRACT") != "1":
        pytest.skip("set RUN_OPENROUTER_COORDINATION_CONTRACT=1 to call OpenRouter")
    settings = load_settings()
    if (
        settings.model_provider != "openrouter"
        or settings.openrouter_api_key is None
        or not settings.openrouter_primary_model
    ):
        pytest.skip(
            "configure MODEL_PROVIDER=openrouter, OPENROUTER_API_KEY, and "
            "OPENROUTER_PRIMARY_MODEL in the lab .env"
        )
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
    report = await OpenRouterCoordinationExecutor(
        model=build_model(settings.provider_settings())
    ).execute(
        task=task,
        evidence=CoordinationEvidencePacket(task_id=task.task_id, items=(item,)),
    )
    assert report.task_id == task.task_id
    assert report.expected_revision == task.expected_revision
    assert report.evidence == (item.reference,)
    assert report.coverage == ("ci",)
    assert report.limitation
