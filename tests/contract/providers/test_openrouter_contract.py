"""Explicit paid-provider contract for OpenRouter's configured primary model."""

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
from aula12_agents.infrastructure.providers import ProviderSettings, build_model
from aula12_agents.settings import load_settings

pytestmark = pytest.mark.provider


class ContractEvidenceReader:
    """Small deterministic source for the paid-provider capability check."""

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


def _openrouter_settings_or_skip() -> ProviderSettings:
    settings = load_settings()
    if settings.model_provider != "openrouter":
        pytest.skip("configure MODEL_PROVIDER=openrouter in the lab .env")
    provider = settings.provider_settings()
    if settings.openrouter_api_key is None or provider.model is None:
        pytest.skip("configure OPENROUTER_API_KEY and OPENROUTER_PRIMARY_MODEL in the lab .env")
    return provider


@pytest.mark.asyncio
async def test_openrouter_primary_supports_read_only_tool_call_and_structured_output() -> None:
    """Opt-in paid test: ``RUN_OPENROUTER_CONTRACT=1 uv run pytest -m provider -k openrouter``."""
    if os.environ.get("RUN_OPENROUTER_CONTRACT") != "1":
        pytest.skip("set RUN_OPENROUTER_CONTRACT=1 to call the configured OpenRouter primary model")
    settings = _openrouter_settings_or_skip()
    observations: list[ToolObservation] = []

    async def observe(event: ToolObservation) -> None:
        observations.append(event)

    policy = AgentPolicy(
        max_evidence_items=3,
        request_limit=4,
        tool_calls_limit=2,
        # This contract bounds requests, tool calls, response size and wall time.
        # Lesson scenarios set their own whole-run token budget.
        total_tokens_limit=None,
    )
    deps = AgentDeps(
        run_id="openrouter-contract",
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
                    "and a short read-only next_action. Do not add explanation outside the "
                    "structured output."
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
