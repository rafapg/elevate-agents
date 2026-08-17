"""Contracts and pure policy decisions for reference coordination."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from aula12_agents.application.coordination import CoordinationCoordinator
from aula12_agents.domain import (
    CoordinationDecisionKind,
    CoordinationPolicy,
    CoordinationRun,
    CoordinationRunPolicy,
    CoordinationScenario,
    CoordinationTask,
    CoordinationTaskState,
    EvidenceRef,
    EvidenceReport,
    SubagentProfile,
)
from aula12_agents.domain.policies import PolicyViolation

NOW = datetime(2026, 8, 11, tzinfo=UTC)
HASH = "c" * 64


def evidence(source: str) -> EvidenceRef:
    return EvidenceRef(
        source=source,
        artifact_id=f"{source}.fixture",
        content_sha256=HASH,
        captured_at=NOW,
    )


def task(*, state: CoordinationTaskState = CoordinationTaskState.RUNNING) -> CoordinationTask:
    return CoordinationTask(
        profile=SubagentProfile.CI_ANALYST,
        read_scope=("ci/run-1842.json",),
        budget_steps=1,
        deadline=NOW + timedelta(seconds=45),
        expected_revision=0,
        revision=0 if state is CoordinationTaskState.PENDING else 1,
        status=state,
    )


def report(for_task: CoordinationTask, source: str = "ci") -> EvidenceReport:
    return EvidenceReport(
        task_id=for_task.task_id,
        expected_revision=for_task.expected_revision,
        evidence=(evidence(source),),
        provenance="fixture local read-only",
        limitation="não cobre logs segmentados",
        coverage=(f"cobertura de {source}",),
        completed_at=NOW,
    )


def complete(original: CoordinationTask, source: str) -> CoordinationTask:
    values = original.model_dump()
    values.update(
        {
            "status": CoordinationTaskState.COMPLETED,
            "result": report(original, source),
        }
    )
    return CoordinationTask.model_validate(values)


def run(*, tasks: tuple[CoordinationTask, ...] = (), revision: int = 0) -> CoordinationRun:
    return CoordinationRun(
        scenario=CoordinationScenario.SUPERVISOR,
        revision=revision,
        deadline=NOW + timedelta(seconds=45),
        tasks=tasks,
        created_at=NOW,
        updated_at=NOW,
    )


def test_completed_task_requires_its_matching_report() -> None:
    with pytest.raises(ValidationError, match="completed exige"):
        task(state=CoordinationTaskState.COMPLETED)

    original = task()
    other = task()
    with pytest.raises(ValidationError, match="pertencer à própria tarefa"):
        CoordinationTask(
            task_id=original.task_id,
            profile=original.profile,
            read_scope=original.read_scope,
            budget_steps=original.budget_steps,
            deadline=original.deadline,
            expected_revision=original.expected_revision,
            status=CoordinationTaskState.COMPLETED,
            result=report(other),
        )


def test_run_rejects_unknown_dependency_and_deadline() -> None:
    dependent = task().model_copy(update={"depends_on": (task().task_id,)})
    with pytest.raises(ValidationError, match="mesmo run"):
        run(tasks=(dependent,))

    late_task = task().model_copy(update={"deadline": NOW + timedelta(seconds=46)})
    with pytest.raises(ValidationError, match="não pode exceder"):
        run(tasks=(late_task,))


def test_spawn_is_allowed_only_for_an_explicit_unfilled_gap() -> None:
    policy = CoordinationPolicy()
    decision = policy.decide_spawn(run(), gap="correlação por feature flag")
    assert decision.kind is CoordinationDecisionKind.SPAWN

    with pytest.raises(PolicyViolation, match="lacuna"):
        policy.decide_spawn(run(), gap=" ")

    first = task()
    completed_first = complete(first, "ci")
    second = task().model_copy(update={"profile": SubagentProfile.CHANGE_ANALYST})
    completed_second = complete(second, "commit")
    sufficient = run(tasks=(completed_first, completed_second))
    spawn_decision = policy.decide_spawn(sufficient, gap="qualquer lacuna")
    assert spawn_decision.kind is CoordinationDecisionKind.NO_SPAWN
    assert policy.decide_aggregation(sufficient).kind is CoordinationDecisionKind.AGGREGATE


def test_cancelled_or_stale_task_result_is_rejected() -> None:
    policy = CoordinationPolicy()
    running = task()
    cancellation = policy.decide_cancellation(running, reason="hipótese-pai invalidada")
    assert cancellation.kind is CoordinationDecisionKind.CANCEL

    cancelled = running.model_copy(
        update={"status": CoordinationTaskState.CANCELLED, "revision": 2}
    )
    decision = policy.decide_report_acceptance(run(revision=1), cancelled, report(running))
    assert decision is not None
    assert decision.kind is CoordinationDecisionKind.REJECT_LATE_RESULT
    assert "cancelled" in decision.reason

    stale_report = report(running)
    newer_running = running.model_copy(update={"expected_revision": 2, "revision": 2})
    stale = policy.decide_report_acceptance(run(revision=1), newer_running, stale_report)
    assert stale is not None
    assert stale.kind is CoordinationDecisionKind.REJECT_LATE_RESULT
    assert "obsoleta" in stale.reason


def test_task_and_run_transition_guards() -> None:
    policy = CoordinationPolicy()
    current_task = task(state=CoordinationTaskState.PENDING)
    running_task = current_task.model_copy(
        update={"status": CoordinationTaskState.RUNNING, "expected_revision": 1, "revision": 1}
    )
    policy.enforce_task_transition(current_task, running_task)
    with pytest.raises(PolicyViolation, match="transição inválida"):
        policy.enforce_task_transition(current_task, current_task)

    current_run = run()
    proposed = current_run.model_copy(
        update={"revision": 1, "updated_at": NOW + timedelta(seconds=1)}
    )
    CoordinationRunPolicy().enforce_transition(current_run, proposed)
    with pytest.raises(PolicyViolation, match="exatamente uma revisão"):
        CoordinationRunPolicy().enforce_transition(current_run, current_run)


def test_report_cas_uses_the_immutable_dispatch_token_not_board_revision() -> None:
    running = task()
    report_from_running_task = report(running)
    # Another worker may have advanced the board many times.  That must not
    # invalidate this task's own dispatch token.
    advanced_board = run(tasks=(running,), revision=7)
    assert (
        CoordinationPolicy().decide_report_acceptance(
            advanced_board, running, report_from_running_task
        )
        is None
    )


def test_budget_is_reserved_before_dispatch_and_cannot_be_overcommitted() -> None:
    with pytest.raises(ValidationError, match="gastos e reservados"):
        CoordinationRun(
            scenario=CoordinationScenario.SUPERVISOR,
            budget_steps=2,
            reserved_steps=3,
            deadline=NOW + timedelta(seconds=45),
            created_at=NOW,
            updated_at=NOW,
        )
    reserved = run().model_copy(update={"reserved_steps": 6})
    assert (
        CoordinationPolicy().decide_spawn(reserved, gap="logs").kind
        is CoordinationDecisionKind.NO_SPAWN
    )


def test_read_scope_blocks_an_operation_not_granted_to_the_task() -> None:
    with pytest.raises(PermissionError, match="query_error_logs"):
        CoordinationCoordinator._require_scope(task(), "query_error_logs")


def test_cancellation_includes_the_real_dependent_task() -> None:
    parent = task()
    child = task().model_copy(update={"depends_on": (parent.task_id,)})
    targets = CoordinationPolicy().cancellation_targets(
        run(tasks=(parent, child)), task_id=parent.task_id
    )
    assert {item.task_id for item in targets} == {parent.task_id, child.task_id}


def test_dependent_task_cannot_be_dispatched_before_parent_is_completed() -> None:
    parent = task(state=CoordinationTaskState.PENDING)
    child = task(state=CoordinationTaskState.PENDING).model_copy(
        update={"depends_on": (parent.task_id,)}
    )
    current = run(tasks=(parent, child))
    started_child = child.model_copy(
        update={"status": CoordinationTaskState.RUNNING, "expected_revision": 1, "revision": 1}
    )
    proposed = current.model_copy(
        update={
            "revision": 1,
            "tasks": (parent, started_child),
            "updated_at": NOW + timedelta(seconds=1),
        }
    )
    with pytest.raises(PolicyViolation, match="pré-requisitos"):
        CoordinationPolicy().enforce_task_board_transition(current, proposed)
