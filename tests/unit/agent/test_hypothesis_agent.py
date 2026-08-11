from __future__ import annotations

import asyncio

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


class StubEvidenceReader:
    async def read_evidence(self, incident_id: str, *, limit: int) -> EvidencePack:
        return EvidencePack(
            incident_id=incident_id,
            items=(
                EvidenceItem(
                    source="log", artifact_id="request-7", summary="A bounded fixture record."
                ),
            ),
        )


def test_default_agent_is_async_read_only_and_emits_a_sanitized_observation() -> None:
    async def scenario() -> list[ToolObservation]:
        observations: list[ToolObservation] = []

        async def collect(observation: ToolObservation) -> None:
            observations.append(observation)

        policy = AgentPolicy(max_evidence_items=2, request_limit=3, tool_calls_limit=2)
        deps = AgentDeps("run-7", StubEvidenceReader(), policy, collect)
        agent = build_hypothesis_agent(build_model(ProviderSettings()))

        result = await agent.run(
            "Investigate incident demo-incident.",
            deps=deps,
            usage_limits=usage_limits_for(policy),
        )

        assert result.output.decision == "conclude"
        return observations

    observations = asyncio.run(scenario())
    assert len(observations) == 1
    assert observations[0].tool_name == "read_evidence"
    assert observations[0].evidence_count == 1


def test_policy_can_block_evidence_tool_without_performing_a_read() -> None:
    class FailingReader:
        async def read_evidence(self, incident_id: str, *, limit: int) -> EvidencePack:
            raise AssertionError("the policy must prevent this call")

    async def scenario() -> None:
        policy = AgentPolicy(allow_read_evidence=False, request_limit=2, tool_calls_limit=1)
        agent = build_hypothesis_agent(build_model(ProviderSettings()))

        # A ModelRetry returns a correction to the model; the deterministic
        # mock repeats the prohibited call and PydanticAI stops at its retry
        # budget. The reader's AssertionError would prove a policy bypass.
        with pytest.raises(Exception, match="exceeded max retries"):
            await agent.run(
                "Investigate incident demo-incident.",
                deps=AgentDeps("run-8", FailingReader(), policy),
                usage_limits=usage_limits_for(policy),
            )

    asyncio.run(scenario())
