"""Application port adapter for the bounded PydanticAI specialist."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from pydantic_ai import Agent

from aula12_agents.agent.contracts import (
    EvidenceItem,
    EvidencePack,
    HypothesisDraft,
    HypothesisReview,
    HypothesisReviewContext,
)
from aula12_agents.agent.deps import AgentDeps, CriticDeps
from aula12_agents.agent.factory import usage_limits_for
from aula12_agents.agent.prompts import format_critic_context
from aula12_agents.application.conversion import (
    critique_card_from_agent_review,
    hypothesis_card_from_agent_draft,
)
from aula12_agents.domain.models import (
    CritiqueCard,
    Evidence,
    EvidenceRef,
    HypothesisCard,
    Incident,
)


class PydanticAIAgentExecutor:
    """Keeps the PydanticAI runtime at the infrastructure edge."""

    def __init__(self, agent: Agent[AgentDeps, HypothesisDraft], deps: AgentDeps) -> None:
        self._agent = agent
        self._deps = deps

    async def decide(
        self, *, run_id: UUID, incident: Incident, evidence: tuple[Evidence, ...]
    ) -> HypothesisCard:
        deps = replace(self._deps, run_id=str(run_id))
        result = await self._agent.run(
            f"Investigate incident {incident.incident_id}: {incident.title}",
            deps=deps,
            usage_limits=usage_limits_for(deps.policy),
            model_settings={"max_tokens": deps.policy.max_output_tokens, "temperature": 0},
        )
        return hypothesis_card_from_agent_draft(result.output, evidence)


class PydanticAICriticExecutor:
    """Adapter for a tool-free PydanticAI critic over a typed hand-off."""

    def __init__(self, agent: Agent[CriticDeps, HypothesisReview], deps: CriticDeps) -> None:
        self._agent = agent
        self._deps = deps

    async def review(
        self,
        *,
        run_id: UUID,
        incident: Incident,
        evidence: tuple[Evidence, ...],
        proposal: HypothesisCard,
    ) -> CritiqueCard:
        deps = replace(self._deps, run_id=str(run_id))
        context = HypothesisReviewContext(
            draft=HypothesisDraft(
                decision=proposal.decision.value,
                hypothesis=proposal.hypothesis.statement if proposal.hypothesis else None,
                uncertainty=proposal.uncertainty,
                next_action=proposal.next_action,
                evidence=tuple(_as_evidence_item(item) for item in proposal.evidence),
            ),
            evidence=EvidencePack(
                incident_id=incident.incident_id,
                items=tuple(_as_evidence_item(item) for item in evidence),
            ),
        )
        result = await self._agent.run(
            format_critic_context(context),
            deps=deps,
            usage_limits=usage_limits_for(deps.policy),
            model_settings={"max_tokens": deps.policy.max_output_tokens, "temperature": 0},
        )
        return critique_card_from_agent_review(result.output, proposal)


def _as_evidence_item(evidence: Evidence | EvidenceRef) -> EvidenceItem:
    return EvidenceItem(
        source=evidence.source,
        artifact_id=evidence.artifact_id,
        summary=(
            evidence.summary
            if isinstance(evidence, Evidence)
            else f"Cited evidence from {evidence.source}: {evidence.artifact_id}."
        ),
    )
