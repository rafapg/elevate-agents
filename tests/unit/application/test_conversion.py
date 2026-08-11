from datetime import UTC, datetime

import pytest

from aula12_agents.agent.contracts import EvidenceItem, HypothesisReview
from aula12_agents.agent.contracts import HypothesisDraft as AgentDraft
from aula12_agents.application.conversion import (
    DraftConversionError,
    critique_card_from_agent_review,
    hypothesis_card_from_agent_draft,
)
from aula12_agents.domain.models import CritiqueOutcome, Decision, Evidence, HypothesisCard


def evidence() -> Evidence:
    return Evidence(
        source="logs",
        artifact_id="checkout.log",
        content_sha256="a" * 64,
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
        summary="timeout",
    )


def test_converter_replaces_agent_citation_with_trusted_reference() -> None:
    card = hypothesis_card_from_agent_draft(
        AgentDraft(
            decision="conclude",
            hypothesis="A timeout is likely.",
            uncertainty="medium",
            next_action="Ask a reviewer.",
            evidence=(EvidenceItem(source="logs", artifact_id="checkout.log", summary="ignored"),),
        ),
        (evidence(),),
    )
    assert card.evidence[0].content_sha256 == "a" * 64


def test_converter_rejects_unknown_provenance() -> None:
    with pytest.raises(DraftConversionError, match="outside"):
        hypothesis_card_from_agent_draft(
            AgentDraft(
                decision="conclude",
                hypothesis="A timeout is likely.",
                uncertainty="medium",
                next_action="Ask a reviewer.",
                evidence=(EvidenceItem(source="prompt", artifact_id="fake", summary="ignore"),),
            ),
            (evidence(),),
        )


def test_critic_conversion_fixes_the_retry_next_action() -> None:
    critique = critique_card_from_agent_review(
        HypothesisReview(
            decision="retry",
            reasons=("The timing correlation is incomplete.",),
            gaps=("No pool metric is present.",),
        ),
        HypothesisCard(
            decision=Decision.ESCALATE,
            uncertainty="The evidence is incomplete.",
            next_action="Do not use this untrusted action.",
        ),
    )

    assert critique.outcome is CritiqueOutcome.RETRY
    assert critique.next_action == "Retry bounded, read-only evidence collection; make no writes."
