"""Gates e transições de estado sem I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .models import (
    CheckpointState,
    CoordinationDecision,
    CoordinationDecisionKind,
    CoordinationRun,
    CoordinationRunState,
    CoordinationTask,
    CoordinationTaskState,
    Decision,
    EvidenceRef,
    EvidenceReport,
    HypothesisCard,
    RunCheckpoint,
)


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


def coverage_sources(reports: tuple[EvidenceReport, ...]) -> frozenset[str]:
    """Return independent evidence sources represented by accepted reports."""

    return frozenset(reference.source for report in reports for reference in report.evidence)


def accepted_reports(run: CoordinationRun) -> tuple[EvidenceReport, ...]:
    """Return only reports already accepted into completed task records."""

    return tuple(
        task.result
        for task in run.tasks
        if task.status is CoordinationTaskState.COMPLETED and task.result is not None
    )


class CoordinationPolicy:
    """Pure rules for the task board; scheduling and I/O remain in application code."""

    _allowed_task_transitions: ClassVar[
        dict[CoordinationTaskState, frozenset[CoordinationTaskState]]
    ] = {
        CoordinationTaskState.PENDING: frozenset(
            {CoordinationTaskState.RUNNING, CoordinationTaskState.CANCELLED}
        ),
        CoordinationTaskState.RUNNING: frozenset(
            {
                CoordinationTaskState.COMPLETED,
                CoordinationTaskState.CANCELLED,
                CoordinationTaskState.REJECTED,
            }
        ),
        CoordinationTaskState.COMPLETED: frozenset(),
        CoordinationTaskState.CANCELLED: frozenset(),
        CoordinationTaskState.REJECTED: frozenset(),
    }

    def coverage_is_sufficient(self, run: CoordinationRun) -> bool:
        """Coverage means independent sources from completed, valid reports."""

        return len(coverage_sources(accepted_reports(run))) >= run.coverage_target

    def decide_spawn(self, run: CoordinationRun, *, gap: str) -> CoordinationDecision:
        """Allow an extra task only while a named coverage gap still exists."""

        if not gap.strip():
            raise PolicyViolation("spawn exige uma lacuna de cobertura explícita")
        if self.coverage_is_sufficient(run):
            return CoordinationDecision(
                kind=CoordinationDecisionKind.NO_SPAWN,
                reason="cobertura mínima já foi alcançada; nenhuma tarefa adicional será criada",
            )
        if run.spent_steps + run.reserved_steps >= run.budget_steps:
            return CoordinationDecision(
                kind=CoordinationDecisionKind.NO_SPAWN,
                reason="orçamento de passos esgotado; nenhuma tarefa adicional será criada",
            )
        return CoordinationDecision(
            kind=CoordinationDecisionKind.SPAWN,
            reason=f"lacuna de cobertura: {gap}",
        )

    def decide_supervision(self, run: CoordinationRun) -> CoordinationDecision:
        if run.tasks:
            raise PolicyViolation("supervisor fixo só planeja um quadro de tarefas vazio")
        return CoordinationDecision(
            kind=CoordinationDecisionKind.SUPERVISE,
            reason="delegar investigação independente a perfis read-only fixos",
        )

    def decide_aggregation(self, run: CoordinationRun) -> CoordinationDecision:
        if not self.coverage_is_sufficient(run):
            raise PolicyViolation("agregação bloqueada: cobertura de evidência insuficiente")
        return CoordinationDecision(
            kind=CoordinationDecisionKind.AGGREGATE,
            reason="fontes independentes e limitações explícitas atingiram a cobertura mínima",
        )

    def decide_cancellation(self, task: CoordinationTask, *, reason: str) -> CoordinationDecision:
        if not reason.strip():
            raise PolicyViolation("cancelamento exige uma razão explícita")
        if task.status not in {CoordinationTaskState.PENDING, CoordinationTaskState.RUNNING}:
            raise PolicyViolation("somente tarefa pendente ou em execução pode ser cancelada")
        return CoordinationDecision(
            kind=CoordinationDecisionKind.CANCEL,
            task_id=task.task_id,
            reason=reason,
        )

    def decide_report_acceptance(
        self, run: CoordinationRun, task: CoordinationTask, report: EvidenceReport
    ) -> CoordinationDecision | None:
        """Return a rejection decision when a report is stale; otherwise accept it.

        Returning ``None`` means the coordinator may atomically mark the task
        completed.  The caller must persist that update with a compare-and-swap.
        """

        if report.task_id != task.task_id:
            return self._reject(task, "resultado pertence a outra tarefa")
        if task.status is not CoordinationTaskState.RUNNING:
            return self._reject(task, f"tarefa está {task.status}, não running")
        if report.expected_revision != task.expected_revision:
            return self._reject(task, "revisão declarada pelo resultado está obsoleta")
        return None

    def enforce_task_transition(
        self, current: CoordinationTask, proposed: CoordinationTask
    ) -> None:
        """Guard immutable task authority and its small state machine."""

        if current.task_id != proposed.task_id:
            raise PolicyViolation("task_id não pode mudar durante uma transição")
        immutable_fields = (
            "profile",
            "read_scope",
            "budget_steps",
            "deadline",
            "depends_on",
        )
        if any(getattr(current, name) != getattr(proposed, name) for name in immutable_fields):
            raise PolicyViolation("perfil, escopo, orçamento, prazo e dependências são imutáveis")
        changes_dispatch_token = current.expected_revision != proposed.expected_revision
        is_dispatch = (
            current.status is CoordinationTaskState.PENDING
            and proposed.status is CoordinationTaskState.RUNNING
        )
        if changes_dispatch_token and not is_dispatch:
            raise PolicyViolation("token de despacho só pode ser definido ao iniciar a tarefa")
        if is_dispatch and not changes_dispatch_token:
            raise PolicyViolation("despacho exige um novo token imutável")
        if proposed.status not in self._allowed_task_transitions[current.status]:
            raise PolicyViolation(f"transição inválida: {current.status} -> {proposed.status}")
        if proposed.revision != current.revision + 1:
            raise PolicyViolation("cada transição da tarefa deve avançar exatamente uma revisão")

    def enforce_task_board_transition(
        self, current: CoordinationRun, proposed: CoordinationRun
    ) -> None:
        """Ensure every existing task uses its own state machine.

        New work always enters as PENDING.  This makes a task's authority and
        budget reservation visible before a worker is allowed to run it.
        """

        previous = {task.task_id: task for task in current.tasks}
        for candidate in proposed.tasks:
            before = previous.pop(candidate.task_id, None)
            if before is None:
                if candidate.status is not CoordinationTaskState.PENDING or candidate.revision != 0:
                    raise PolicyViolation("nova tarefa deve começar pending na revisão 0")
            else:
                if candidate != before:
                    self.enforce_task_transition(before, candidate)
                    if (
                        before.status is CoordinationTaskState.PENDING
                        and candidate.status is CoordinationTaskState.RUNNING
                    ):
                        parents = {task.task_id: task for task in current.tasks}
                        if any(
                            parents[parent_id].status is not CoordinationTaskState.COMPLETED
                            for parent_id in candidate.depends_on
                        ):
                            raise PolicyViolation(
                                "tarefa dependente só pode iniciar após seus "
                                "pré-requisitos completed"
                            )
        if previous:
            raise PolicyViolation("tarefas existentes não podem desaparecer do quadro")

    def cancellation_targets(
        self, run: CoordinationRun, *, task_id: object
    ) -> tuple[CoordinationTask, ...]:
        """Return an active parent and every active task that depends on it."""

        targets: set[object] = {task_id}
        changed = True
        while changed:
            changed = False
            for task in run.tasks:
                is_active_dependent = task.status in {
                    CoordinationTaskState.PENDING,
                    CoordinationTaskState.RUNNING,
                } and (
                    task.task_id in targets or any(parent in targets for parent in task.depends_on)
                )
                if is_active_dependent and task.task_id not in targets:
                    targets.add(task.task_id)
                    changed = True
        return tuple(task for task in run.tasks if task.task_id in targets)

    @staticmethod
    def _reject(task: CoordinationTask, reason: str) -> CoordinationDecision:
        return CoordinationDecision(
            kind=CoordinationDecisionKind.REJECT_LATE_RESULT,
            task_id=task.task_id,
            reason=reason,
        )


class CoordinationRunPolicy:
    """Validate durable task-board changes before the store applies CAS."""

    _allowed: ClassVar[dict[CoordinationRunState, frozenset[CoordinationRunState]]] = {
        CoordinationRunState.RUNNING: frozenset(
            {
                CoordinationRunState.RUNNING,
                CoordinationRunState.COMPLETED,
                CoordinationRunState.CANCELLED,
                CoordinationRunState.FAILED,
            }
        ),
        CoordinationRunState.COMPLETED: frozenset(),
        CoordinationRunState.CANCELLED: frozenset(),
        CoordinationRunState.FAILED: frozenset(),
    }

    def enforce_transition(self, current: CoordinationRun, proposed: CoordinationRun) -> None:
        if current.run_id != proposed.run_id:
            raise PolicyViolation("run_id não pode mudar durante uma transição")
        if current.scenario != proposed.scenario:
            raise PolicyViolation("scenario não pode mudar durante uma transição")
        if current.created_at != proposed.created_at:
            raise PolicyViolation("created_at não pode mudar durante uma transição")
        if proposed.revision != current.revision + 1:
            raise PolicyViolation("cada transição deve avançar exatamente uma revisão")
        if proposed.updated_at < current.updated_at:
            raise PolicyViolation("updated_at não pode retroceder")
        if proposed.state not in self._allowed[current.state]:
            raise PolicyViolation(f"transição inválida: {current.state} -> {proposed.state}")
