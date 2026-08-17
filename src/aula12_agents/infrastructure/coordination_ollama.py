"""Optional Ollama adapter for the provider-neutral coordination boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from aula12_agents.application.coordination_executor import (
    CoordinationEvidencePacket,
    CoordinationSpecialistExecutor,
    validate_execution_request,
)
from aula12_agents.domain.models import CoordinationTask, EvidenceReport

AssessmentText = Annotated[str, Field(min_length=1, max_length=600)]


class CoordinationAssessment(BaseModel):
    """Untrusted structured provider output; references are checked below."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cited_evidence_ids: tuple[UUID, ...] = Field(min_length=1, max_length=6)
    limitation: AssessmentText


class OllamaCoordinationExecutor(CoordinationSpecialistExecutor):
    """Runs one tool-free, bounded specialist against a local Ollama model.

    This adapter deliberately has no dependencies object and no toolset.  The
    model sees only the packet supplied by the application, not the fixture
    reader, SQLite board, policy objects, environment, or credentials.
    """

    def __init__(
        self,
        *,
        model: Model,
        now: Callable[[], datetime] | None = None,
        max_output_tokens: int = 512,
        maximum_timeout_seconds: float = 90.0,
    ) -> None:
        if max_output_tokens < 64:
            raise ValueError("max_output_tokens must be at least 64")
        if maximum_timeout_seconds <= 0:
            raise ValueError("maximum_timeout_seconds must be positive")
        self._agent: Agent[None, CoordinationAssessment] = Agent(
            model,
            name="coordination-ollama-specialist-v1",
            output_type=CoordinationAssessment,
            instructions=(
                "You are a read-only coordination specialist in a teaching lab. "
                "Use only the supplied evidence packet. Return a structured assessment "
                "that cites one or more evidence IDs from that packet. Do not invent "
                "sources, request tools, or propose changes. State one concrete limitation."
            ),
            retries={"output": 1},
            metadata={"tool_policy": "none", "prompt_version": "coordination-ollama-v1"},
        )
        self._now = now or (lambda: datetime.now(UTC))
        self._max_output_tokens = max_output_tokens
        self._maximum_timeout_seconds = maximum_timeout_seconds

    async def execute(
        self, *, task: CoordinationTask, evidence: CoordinationEvidencePacket
    ) -> EvidenceReport:
        now = self._now()
        validate_execution_request(task=task, evidence=evidence, now=now)
        timeout = min((task.deadline - now).total_seconds(), self._maximum_timeout_seconds)
        prompt = _format_prompt(task=task, evidence=evidence)
        try:
            result = await asyncio.wait_for(
                self._agent.run(
                    prompt,
                    usage_limits=UsageLimits(
                        request_limit=min(task.budget_steps, 2),
                        tool_calls_limit=0,
                    ),
                    model_settings={"max_tokens": self._max_output_tokens, "temperature": 0},
                ),
                timeout=timeout,
            )
        except TimeoutError as error:
            raise TimeoutError(
                f"coordination specialist exceeded its {timeout:.1f}s deadline"
            ) from error

        selected = {item.reference.evidence_id: item.reference for item in evidence.items}
        cited_ids = result.output.cited_evidence_ids
        if len(cited_ids) != len(set(cited_ids)):
            raise ValueError("provider assessment repeated an evidence ID")
        if not set(cited_ids).issubset(selected):
            raise ValueError("provider assessment cited evidence outside its packet")
        references = tuple(selected[item_id] for item_id in cited_ids)
        return EvidenceReport(
            task_id=task.task_id,
            expected_revision=task.expected_revision,
            evidence=references,
            provenance="ollama coordination specialist; selected evidence packet only",
            limitation=result.output.limitation,
            coverage=tuple(sorted({item.source for item in references})),
            completed_at=self._now(),
        )


def _format_prompt(*, task: CoordinationTask, evidence: CoordinationEvidencePacket) -> str:
    """Render an explicit, compact and non-secret packet for structured output."""

    lines = [
        f"Task profile: {task.profile.value}",
        f"Allowed read scope (already enforced): {', '.join(task.read_scope)}",
        f"Work budget: at most {task.budget_steps} bounded steps.",
        "Selected evidence:",
    ]
    lines.extend(
        f"- id={item.reference.evidence_id}; source={item.reference.source}; "
        f"artifact={item.reference.artifact_id}; summary={item.summary}"
        for item in evidence.items
    )
    return "\n".join(lines)
