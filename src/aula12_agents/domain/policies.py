"""Gates e transições de estado sem I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .models import CheckpointState, Decision, EvidenceRef, HypothesisCard, RunCheckpoint


class PolicyViolation(ValueError):
    """Uma regra de segurança ou continuidade do domínio foi violada."""


@dataclass(frozen=True)
class EvidenceGate:
    """Exige evidência externa antes de uma conclusão automatizada."""

    minimum_evidence: int = 1

    def allows(self, card: HypothesisCard) -> bool:
        if card.decision is not Decision.CONCLUDE:
            return True
        return len(card.evidence) >= self.minimum_evidence

    def enforce(self, card: HypothesisCard) -> None:
        if not self.allows(card):
            raise PolicyViolation("conclusão bloqueada: evidência insuficiente")


class CheckpointPolicy:
    """Transições permitidas; persistência e execução ficam fora desta classe."""

    _allowed: ClassVar[dict[CheckpointState, frozenset[CheckpointState]]] = {
        CheckpointState.RUNNING: frozenset(
            {
                # A durable hand-off between specialists advances revision and
                # next_step while the run remains active.
                CheckpointState.RUNNING,
                CheckpointState.WAITING_RETRY,
                CheckpointState.WAITING_APPROVAL,
                CheckpointState.ESCALATED,
                CheckpointState.COMPLETED,
                CheckpointState.CANCELLED,
                CheckpointState.FAILED,
            }
        ),
        CheckpointState.WAITING_RETRY: frozenset(
            {
                CheckpointState.RUNNING,
                CheckpointState.ESCALATED,
                CheckpointState.CANCELLED,
                CheckpointState.FAILED,
            }
        ),
        CheckpointState.WAITING_APPROVAL: frozenset(
            {CheckpointState.RUNNING, CheckpointState.CANCELLED, CheckpointState.ESCALATED}
        ),
        CheckpointState.ESCALATED: frozenset(),
        CheckpointState.COMPLETED: frozenset(),
        CheckpointState.CANCELLED: frozenset(),
        CheckpointState.FAILED: frozenset(),
    }

    def allows(self, source: CheckpointState, target: CheckpointState) -> bool:
        return target in self._allowed[source]

    def enforce_transition(self, current: RunCheckpoint, proposed: RunCheckpoint) -> None:
        if current.run_id != proposed.run_id:
            raise PolicyViolation("run_id não pode mudar durante uma transição")
        if current.workflow_version != proposed.workflow_version:
            raise PolicyViolation("workflow_version não pode mudar durante uma transição")
        if current.incident != proposed.incident or current.input_sha256 != proposed.input_sha256:
            raise PolicyViolation("a entrada de um run é imutável")
        if proposed.revision != current.revision + 1:
            raise PolicyViolation("cada transição deve avançar exatamente uma revisão")
        if not self.allows(current.state, proposed.state):
            raise PolicyViolation(f"transição inválida: {current.state} -> {proposed.state}")


def merge_evidence(*groups: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
    """Deduplica por id sem interpretar nem alterar a evidência."""

    unique: dict[object, EvidenceRef] = {}
    for evidence in (item for group in groups for item in group):
        unique.setdefault(evidence.evidence_id, evidence)
    return tuple(unique.values())
