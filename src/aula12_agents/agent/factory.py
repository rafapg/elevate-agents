"""Construction of the PydanticAI hypothesis specialist."""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.usage import UsageLimits

from .contracts import HypothesisDraft, HypothesisReview
from .deps import AgentDeps, AgentPolicy, CriticDeps
from .prompts import (
    CRITIC_INSTRUCTIONS,
    CRITIC_PROMPT_VERSION,
    HYPOTHESIS_INSTRUCTIONS,
    PROMPT_VERSION,
)
from .toolsets import build_readonly_toolset
from .validators import validate_hypothesis_draft, validate_hypothesis_review

HYPOTHESIS_AGENT_NAME = "hypothesis-specialist-v2"
CRITIC_AGENT_NAME = "hypothesis-critic-v1"


def usage_limits_for(policy: AgentPolicy) -> UsageLimits:
    """Translate the visible application policy into PydanticAI run limits."""

    return UsageLimits(
        request_limit=policy.request_limit,
        tool_calls_limit=policy.tool_calls_limit,
        total_tokens_limit=policy.total_tokens_limit,
    )


def build_hypothesis_agent(model: Model) -> Agent[AgentDeps, HypothesisDraft]:
    """Create an agent with only read-only tools and bounded model usage.

    Execution remains async: callers use ``await agent.run(...)`` with explicit
    ``UsageLimits`` derived from the same policy in ``usage_limits_for``.
    """
    agent = Agent(
        model=model,
        name=HYPOTHESIS_AGENT_NAME,
        deps_type=AgentDeps,
        output_type=HypothesisDraft,
        instructions=HYPOTHESIS_INSTRUCTIONS,
        toolsets=[build_readonly_toolset()],
        retries={"output": 1, "tools": 1},
        metadata={"prompt_version": PROMPT_VERSION, "tool_policy": "readonly"},
    )
    agent.output_validator(validate_hypothesis_draft)
    return agent


def build_critic_agent(model: Model) -> Agent[CriticDeps, HypothesisReview]:
    """Create a tool-free critic for a typed hypothesis/evidence hand-off."""

    agent = Agent(
        model=model,
        name=CRITIC_AGENT_NAME,
        deps_type=CriticDeps,
        output_type=HypothesisReview,
        instructions=CRITIC_INSTRUCTIONS,
        retries={"output": 1},
        metadata={"prompt_version": CRITIC_PROMPT_VERSION, "tool_policy": "none"},
    )
    agent.output_validator(validate_hypothesis_review)
    return agent
