"""PydanticAI adapter for the read-only investigation specialists.

The package intentionally contains no persistence, CLI, or domain orchestration.
"""

from .contracts import (
    EvidenceItem,
    EvidencePack,
    HypothesisDraft,
    HypothesisReview,
    HypothesisReviewContext,
)
from .deps import AgentDeps, AgentPolicy, CriticDeps, ToolObservation
from .factory import build_critic_agent, build_hypothesis_agent, usage_limits_for

__all__ = [
    "AgentDeps",
    "AgentPolicy",
    "CriticDeps",
    "EvidenceItem",
    "EvidencePack",
    "HypothesisDraft",
    "HypothesisReview",
    "HypothesisReviewContext",
    "ToolObservation",
    "build_critic_agent",
    "build_hypothesis_agent",
    "usage_limits_for",
]
