"""Opt-in contract test for a local Ollama model with tools and JSON schema output."""

from __future__ import annotations

import asyncio
import os

import pytest

from aula12_agents.agent import (
    AgentDeps,
    AgentPolicy,
    EvidenceItem,
    EvidencePack,
    ToolObservation,
    build_hypothesis_agent,
    usage_limits_for,
)
from aula12_agents.infrastructure.fixtures.gateway import FixtureGateway
from aula12_agents.infrastructure.fixtures.reader import FixtureReader
from aula12_agents.infrastructure.providers import ProviderSettings, build_model
from aula12_agents.settings import load_settings

pytestmark = pytest.mark.provider


class ContractEvidenceReader:
    """Small read-only payload: provider capability is independent of fixture size."""

    async def read_evidence(self, incident_id: str, *, limit: int) -> EvidencePack:
        del limit
        return EvidencePack(
            incident_id=incident_id,
            items=(
                EvidenceItem(
                    source="contract_fixture",
                    artifact_id="BUG-204-summary",
                    summary="A checkout error was observed after the synthetic deployment.",
                ),
            ),
        )


def _ollama_settings_or_skip() -> ProviderSettings:
    settings = load_settings()
    if settings.model_provider != "ollama" or not settings.ollama_model:
        pytest.skip("configure MODEL_PROVIDER=ollama and OLLAMA_MODEL in the lab .env")
    return settings.provider_settings()


@pytest.mark.asyncio
async def test_ollama_supports_read_only_tool_call_and_hypothesis_draft() -> None:
    """Opt-in: ``RUN_OLLAMA_CONTRACT=1 uv run pytest -m provider``."""
    if os.environ.get("RUN_OLLAMA_CONTRACT") != "1":
        pytest.skip("set RUN_OLLAMA_CONTRACT=1 to call the local Ollama model")
    settings = _ollama_settings_or_skip()
    observations: list[ToolObservation] = []

    async def observe(event: ToolObservation) -> None:
        observations.append(event)

    policy = AgentPolicy(
        max_evidence_items=3,
        request_limit=4,
        tool_calls_limit=2,
        # Token accounting varies by local model and includes the accumulated
        # tool/schema context. This provider *capability* contract instead
        # bounds requests, tool calls and wall time; lesson scenarios define
        # their own explicit token budget.
        total_tokens_limit=None,
    )
    deps = AgentDeps(
        run_id="ollama-contract",
        evidence_reader=ContractEvidenceReader(),
        policy=policy,
        observation_sink=observe,
    )
    agent = build_hypothesis_agent(build_model(settings))

    try:
        result = await asyncio.wait_for(
            agent.run(
                (
                    "For incident BUG-204, call read_evidence exactly once. Then return "
                    "the required structured output with decision='escalate', a short uncertainty, "
                    "and a short "
                    "read-only next_action. Do not add explanation outside the structured output."
                ),
                deps=deps,
                usage_limits=usage_limits_for(policy),
                model_settings={"max_tokens": 256, "temperature": 0},
            ),
            timeout=90,
        )
    except TimeoutError:
        pytest.fail(f"timed out after 90s; observations={observations!r}")

    observed_tools = [event.tool_name for event in observations]
    output = result.output.model_dump(mode="json")
    usage = result.usage
    assert observations, f"the provider did not call read_evidence; observed={observed_tools}"
    assert all(tool_name == "read_evidence" for tool_name in observed_tools), (
        f"unexpected tool call; observed={observed_tools}"
    )
    assert result.output.decision in {"retry", "escalate", "conclude"}, output
    assert result.output.uncertainty, output
    assert result.output.next_action, output
    assert usage.requests <= policy.request_limit, usage
    assert usage.tool_calls <= policy.tool_calls_limit, usage


@pytest.mark.asyncio
async def test_ollama_handles_the_full_fixture_context_after_model_warmup() -> None:
    """Opt-in integration contract for the realistic fixture payload."""
    if os.environ.get("RUN_OLLAMA_LARGE_CONTRACT") != "1":
        pytest.skip("set RUN_OLLAMA_LARGE_CONTRACT=1 to run the full fixture contract")
    settings = _ollama_settings_or_skip()
    observations: list[ToolObservation] = []

    async def observe(event: ToolObservation) -> None:
        observations.append(event)

    policy = AgentPolicy(
        max_evidence_items=3,
        request_limit=4,
        tool_calls_limit=2,
        total_tokens_limit=None,
    )
    agent = build_hypothesis_agent(build_model(settings))
    deps = AgentDeps(
        run_id="ollama-large-contract",
        evidence_reader=FixtureGateway(FixtureReader()),
        policy=policy,
        observation_sink=observe,
    )

    try:
        result = await asyncio.wait_for(
            agent.run(
                "Investigate incident BUG-204. You must read evidence before returning a safe "
                "hypothesis draft.",
                deps=deps,
                usage_limits=usage_limits_for(policy),
                model_settings={"max_tokens": 512, "temperature": 0},
            ),
            timeout=180,
        )
    except TimeoutError:
        pytest.fail(f"timed out after 180s; observations={observations!r}")

    usage = result.usage
    output = result.output.model_dump(mode="json")
    assert observations, f"the provider did not call read_evidence; output={output}"
    assert result.output.decision in {"retry", "escalate", "conclude"}, output
    assert result.output.uncertainty, output
    assert result.output.next_action, output
    assert usage.requests <= policy.request_limit, usage
    assert usage.tool_calls <= policy.tool_calls_limit, usage
