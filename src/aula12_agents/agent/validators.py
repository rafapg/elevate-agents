"""Validation that belongs at the model-output boundary."""

from __future__ import annotations

from pydantic_ai import ModelRetry, RunContext

from .contracts import HypothesisDraft, HypothesisReview
from .deps import AgentDeps, CriticDeps


async def validate_hypothesis_draft(
    ctx: RunContext[AgentDeps], draft: HypothesisDraft
) -> HypothesisDraft:
    """Reject internally inconsistent output so the model may correct itself once."""

    if draft.decision == "conclude" and not draft.evidence:
        raise ModelRetry("A conclusion requires at least one cited evidence item.")
    if draft.decision == "conclude" and draft.hypothesis is None:
        raise ModelRetry("A conclusion requires a concrete hypothesis.")
    if len(draft.evidence) > ctx.deps.policy.max_evidence_items:
        raise ModelRetry("The evidence list exceeds the explicit context budget.")
    return draft


async def validate_hypothesis_review(
    _: RunContext[CriticDeps], review: HypothesisReview
) -> HypothesisReview:
    """Reject reviews whose decision is inconsistent with their stated gaps."""

    if review.decision == "approve" and review.gaps:
        raise ModelRetry("An approval cannot retain blocking gaps.")
    if review.decision in {"retry", "escalate"} and not review.gaps:
        raise ModelRetry("A retry or escalation must identify at least one gap.")
    return review
