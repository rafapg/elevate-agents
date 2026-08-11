from __future__ import annotations

import asyncio

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from aula12_agents.agent import (
    AgentPolicy,
    CriticDeps,
    EvidenceItem,
    EvidencePack,
    HypothesisDraft,
    HypothesisReviewContext,
    build_critic_agent,
    usage_limits_for,
)
from aula12_agents.agent.prompts import format_critic_context


def _context() -> HypothesisReviewContext:
    return HypothesisReviewContext(
        draft=HypothesisDraft(
            decision="conclude",
            hypothesis="A recent regression likely increased error rates.",
            uncertainty="The fixture has only one bounded record.",
            next_action="Ask a human to review the bounded evidence card.",
            evidence=(
                EvidenceItem(
                    source="fixture",
                    artifact_id="record-1",
                    summary="Error rate rose after a deploy.",
                ),
            ),
        ),
        evidence=EvidencePack(
            incident_id="BUG-204",
            items=(
                EvidenceItem(
                    source="fixture",
                    artifact_id="record-1",
                    summary="Error rate rose after a deploy.",
                ),
            ),
        ),
    )


def test_critic_is_tool_free_and_approves_a_typed_hand_off() -> None:
    def response(_: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        assert not info.function_tools
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "decision": "approve",
                        "reasons": ["The cited evidence supports the bounded conclusion."],
                        "gaps": [],
                    },
                )
            ]
        )

    async def scenario() -> None:
        policy = AgentPolicy(request_limit=2, tool_calls_limit=1)
        result = await build_critic_agent(FunctionModel(response)).run(
            format_critic_context(_context()),
            deps=CriticDeps(run_id="run-critic-1", policy=policy),
            usage_limits=usage_limits_for(policy),
        )
        assert result.output.decision == "approve"
        assert result.output.gaps == ()

    asyncio.run(scenario())


def test_critic_rejects_an_approval_that_retains_blocking_gaps() -> None:
    def invalid_response(_: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name,
                    {
                        "decision": "approve",
                        "reasons": ["The draft looks plausible."],
                        "gaps": ["The deployment correlation is unverified."],
                    },
                )
            ]
        )

    async def scenario() -> None:
        policy = AgentPolicy(request_limit=2, tool_calls_limit=1)
        with pytest.raises(Exception, match="Exceeded maximum output retries"):
            await build_critic_agent(FunctionModel(invalid_response)).run(
                format_critic_context(_context()),
                deps=CriticDeps(run_id="run-critic-2", policy=policy),
                usage_limits=usage_limits_for(policy),
            )

    asyncio.run(scenario())


def test_critic_context_serializes_the_structured_handoff_as_data() -> None:
    prompt = format_critic_context(_context())

    assert prompt.startswith("Review this typed hand-off.")
    assert '"incident_id":"BUG-204"' in prompt
    assert '"decision":"conclude"' in prompt
