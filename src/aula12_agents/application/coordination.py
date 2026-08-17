"""Offline reference implementation of bounded subagent coordination.

The coordinator owns task-board state, permissions, budget, cancellation and
optimistic concurrency.  The deterministic fixture readers stand in for
specialists so the lesson remains reproducible without a model provider.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from aula12_agents.application.coordination_executor import (
    CoordinationEvidenceItem,
    CoordinationEvidencePacket,
    CoordinationSpecialistExecutor,
)
from aula12_agents.application.ports import CoordinationEventSink, CoordinationStore
from aula12_agents.domain.models import (
    CoordinationDecision,
    CoordinationRun,
    CoordinationRunState,
    CoordinationScenario,
    CoordinationTask,
    CoordinationTaskState,
    EvidenceRef,
    EvidenceReport,
    SubagentProfile,
)
from aula12_agents.domain.policies import CoordinationPolicy, CoordinationRunPolicy


class FixtureEvidenceView(Protocol):
    evidence_id: str
    source_kind: str
    source_uri: str
    retrieved_at: datetime
    content_sha256: str
    content: str


class CoordinationFixtureReader(Protocol):
    def read_ci_summary(self, run_id: str) -> FixtureEvidenceView: ...

    def search_commits(self, query: str) -> Sequence[FixtureEvidenceView]: ...

    def query_error_logs(
        self,
        *,
        status_code: int | None = None,
        browser_family: str | None = None,
        feature_flag: str | None = None,
    ) -> Sequence[FixtureEvidenceView]: ...


class CoordinationObserver(Protocol):
    def record_run_started(self, *, run: CoordinationRun, occurred_at: datetime) -> None: ...

    def record_task_dispatched(
        self, *, run: CoordinationRun, task: CoordinationTask, occurred_at: datetime
    ) -> None: ...

    def record_task_completed(
        self,
        *,
        run: CoordinationRun,
        task: CoordinationTask,
        report: EvidenceReport,
        occurred_at: datetime,
    ) -> None: ...

    def record_task_cancelled(
        self, *, run: CoordinationRun, task: CoordinationTask, reason: str, occurred_at: datetime
    ) -> None: ...

    def record_result_rejected(
        self,
        *,
        run: CoordinationRun,
        task: CoordinationTask,
        report: EvidenceReport,
        observed_revision: int,
        reason: str,
        occurred_at: datetime,
    ) -> None: ...

    def record_decision(
        self, *, run: CoordinationRun, decision: CoordinationDecision, occurred_at: datetime
    ) -> None: ...


class CoordinationCoordinator:
    """Run the four teaching scenarios over a real durable task board."""

    def __init__(
        self,
        *,
        store: CoordinationStore,
        events: CoordinationEventSink,
        reader: CoordinationFixtureReader,
        observer: CoordinationObserver,
        specialist: CoordinationSpecialistExecutor | None = None,
        run_timeout_seconds: int = 300,
        now: Callable[[], datetime],
    ) -> None:
        if run_timeout_seconds < 60:
            raise ValueError("run_timeout_seconds must be at least 60")
        self._store = store
        self._events = events
        self._reader = reader
        self._observer = observer
        self._specialist = specialist
        self._run_timeout_seconds = run_timeout_seconds
        self._now = now
        self._policy = CoordinationPolicy()
        self._run_policy = CoordinationRunPolicy()

    async def run(self, scenario: CoordinationScenario) -> CoordinationRun:
        current = self._new_run(scenario)
        self._store.create(current)
        self._event(current, "coordination_run_created")
        self._observer.record_run_started(run=current, occurred_at=self._now())

        if scenario is CoordinationScenario.SUPERVISOR:
            return await self._run_supervisor(current)
        if scenario is CoordinationScenario.SPAWN:
            return await self._run_spawn(current)
        if scenario is CoordinationScenario.NO_SPAWN:
            return await self._run_no_spawn(current)
        return await self._run_cancellation(current)

    async def _run_supervisor(self, current: CoordinationRun) -> CoordinationRun:
        decision = self._policy.decide_supervision(current)
        tasks = (
            self._task(current, SubagentProfile.CI_ANALYST, ("read_ci_summary",), 2),
            self._task(current, SubagentProfile.CHANGE_ANALYST, ("search_commits",), 2),
        )
        planned = self._advance(current, tasks=tasks, reserved_steps=4, decision=decision)
        self._record_decision(planned, decision)
        running = self._start_all(planned)
        for task in running.tasks:
            self._observer.record_task_dispatched(run=running, task=task, occurred_at=self._now())

        reports = await asyncio.gather(*(self._execute(task) for task in running.tasks))
        # Accept individually: the second report remains valid even though the
        # first one already advanced the board revision.
        accepted = running
        for report in reports:
            accepted = self._accept_report(accepted, report)
        decision = self._policy.decide_aggregation(accepted)
        completed = self._advance(
            accepted,
            state=CoordinationRunState.COMPLETED,
            decision=decision,
        )
        self._record_decision(completed, decision)
        return completed

    async def _run_spawn(self, current: CoordinationRun) -> CoordinationRun:
        baseline = self._task(current, SubagentProfile.CHANGE_ANALYST, ("search_commits",), 2)
        planned = self._advance(current, tasks=(baseline,), reserved_steps=2)
        running = self._start_all(planned)
        self._observer.record_task_dispatched(run=running, task=baseline, occurred_at=self._now())
        report = await self._execute(running.tasks[0])
        partial = self._accept_report(running, report)

        decision = self._policy.decide_spawn(partial, gap="correlação por feature flag")
        self._record_decision(partial, decision)
        spawned = self._task(partial, SubagentProfile.LOG_ANALYST, ("query_error_logs",), 2)
        planned = self._advance(
            partial, tasks=(*partial.tasks, spawned), reserved_steps=2, decision=decision
        )
        running = self._start_all(planned)
        self._observer.record_task_dispatched(run=running, task=spawned, occurred_at=self._now())
        started_spawned = next(task for task in running.tasks if task.task_id == spawned.task_id)
        report = await self._execute(started_spawned)
        accepted = self._accept_report(running, report)
        decision = self._policy.decide_aggregation(accepted)
        completed = self._advance(
            accepted,
            state=CoordinationRunState.COMPLETED,
            decision=decision,
        )
        self._record_decision(completed, decision)
        return completed

    async def _run_no_spawn(self, current: CoordinationRun) -> CoordinationRun:
        baseline = self._task(
            current, SubagentProfile.SINGLE_INVESTIGATOR, ("search_commits", "query_error_logs"), 4
        )
        planned = self._advance(current, tasks=(baseline,), reserved_steps=4)
        running = self._start_all(planned)
        self._observer.record_task_dispatched(run=running, task=baseline, occurred_at=self._now())
        report = await self._execute(running.tasks[0])
        evidenced = self._accept_report(running, report)
        decision = self._policy.decide_spawn(evidenced, gap="especialista adicional")
        completed = self._advance(
            evidenced, state=CoordinationRunState.COMPLETED, decision=decision
        )
        self._record_decision(completed, decision)
        return completed

    async def _run_cancellation(self, current: CoordinationRun) -> CoordinationRun:
        parent = self._task(current, SubagentProfile.CHANGE_ANALYST, ("search_commits",), 1)
        dependent = self._task(
            current,
            SubagentProfile.LOG_ANALYST,
            ("query_error_logs",),
            2,
            depends_on=(parent.task_id,),
        )
        planned = self._advance(current, tasks=(parent, dependent), reserved_steps=3)
        running = self._start_all(planned)
        started_parent = running.tasks[0]
        self._observer.record_task_dispatched(
            run=running, task=started_parent, occurred_at=self._now()
        )
        parent_report = await self._execute(started_parent)
        parent_completed = self._accept_report(running, parent_report)
        # The dependent has a real prerequisite: it cannot be dispatched until
        # the parent result is durably completed.
        running = self._start_all(parent_completed)
        started_dependent = next(
            task for task in running.tasks if task.task_id == dependent.task_id
        )
        self._observer.record_task_dispatched(
            run=running, task=started_dependent, occurred_at=self._now()
        )

        cancellation = self._policy.decide_cancellation(
            started_dependent, reason="evidência posterior invalidou o resultado da tarefa-pai"
        )
        targets = self._policy.cancellation_targets(running, task_id=started_dependent.task_id)
        cancelled_tasks = tuple(
            task.model_copy(
                update={"status": CoordinationTaskState.CANCELLED, "revision": task.revision + 1}
            )
            if task in targets
            else task
            for task in running.tasks
        )
        cancelled = self._advance(
            running, tasks=cancelled_tasks, reserved_steps=0, decision=cancellation
        )
        for cancelled_task in cancelled.tasks:
            if cancelled_task.status is not CoordinationTaskState.CANCELLED:
                continue
            self._observer.record_task_cancelled(
                run=cancelled,
                task=cancelled_task,
                reason=cancellation.reason,
                occurred_at=self._now(),
            )
        self._record_decision(cancelled, cancellation)

        late_report = await self._execute(started_dependent)
        cancelled_dependent = next(
            task for task in cancelled.tasks if task.task_id == dependent.task_id
        )
        rejection = self._policy.decide_report_acceptance(
            cancelled, cancelled_dependent, late_report
        )
        assert rejection is not None
        completed = self._advance(
            cancelled, state=CoordinationRunState.COMPLETED, decision=rejection
        )
        self._observer.record_result_rejected(
            run=completed,
            task=cancelled_dependent,
            report=late_report,
            observed_revision=cancelled.revision,
            reason=rejection.reason,
            occurred_at=self._now(),
        )
        self._record_decision(completed, rejection)
        return completed

    async def _execute(self, task: CoordinationTask) -> EvidenceReport:
        evidence = self._read_for(task)
        references = tuple(self._to_ref(item) for item in evidence)
        if self._specialist is not None:
            return await self._specialist.execute(
                task=task,
                evidence=CoordinationEvidencePacket(
                    task_id=task.task_id,
                    items=tuple(
                        CoordinationEvidenceItem(reference=reference, summary=item.content[:1_000])
                        for reference, item in zip(references, evidence, strict=True)
                    ),
                ),
            )
        return EvidenceReport(
            task_id=task.task_id,
            expected_revision=task.expected_revision,
            evidence=references,
            provenance="synthetic local fixture reader",
            limitation="The result is limited to the selected read-only fixture sources.",
            coverage=tuple(sorted({item.source_kind for item in evidence})),
            completed_at=self._now(),
        )

    def _read_for(self, task: CoordinationTask) -> Sequence[FixtureEvidenceView]:
        if task.profile is SubagentProfile.CI_ANALYST:
            self._require_scope(task, "read_ci_summary")
            return [self._reader.read_ci_summary("1842")]
        if task.profile is SubagentProfile.CHANGE_ANALYST:
            self._require_scope(task, "search_commits")
            return self._reader.search_commits("session")
        self._require_scope(task, "query_error_logs")
        logs = self._reader.query_error_logs(status_code=500, feature_flag="payment_return_v2")
        if task.profile is SubagentProfile.SINGLE_INVESTIGATOR:
            self._require_scope(task, "search_commits")
            return [*self._reader.search_commits("session"), *logs]
        return logs

    def _new_run(self, scenario: CoordinationScenario) -> CoordinationRun:
        now = self._now()
        return CoordinationRun(
            scenario=scenario,
            deadline=now + timedelta(seconds=self._run_timeout_seconds),
            created_at=now,
            updated_at=now,
        )

    def _task(
        self,
        run: CoordinationRun,
        profile: SubagentProfile,
        read_scope: tuple[str, ...],
        budget_steps: int,
        depends_on: tuple[UUID, ...] = (),
    ) -> CoordinationTask:
        return CoordinationTask(
            profile=profile,
            read_scope=read_scope,
            budget_steps=budget_steps,
            deadline=run.deadline,
            expected_revision=run.revision,
            depends_on=depends_on,
            status=CoordinationTaskState.PENDING,
        )

    def _start_all(self, current: CoordinationRun) -> CoordinationRun:
        """Dispatch only work that has first been durably reserved as pending."""

        running = current
        for task in current.tasks:
            if task.status is not CoordinationTaskState.PENDING:
                continue
            parent_tasks = [item for item in running.tasks if item.task_id in task.depends_on]
            if any(parent.status is not CoordinationTaskState.COMPLETED for parent in parent_tasks):
                continue
            started = task.model_copy(
                update={
                    "status": CoordinationTaskState.RUNNING,
                    "expected_revision": running.revision + 1,
                    "revision": task.revision + 1,
                }
            )
            tasks = tuple(
                started if item.task_id == task.task_id else item for item in running.tasks
            )
            running = self._advance(running, tasks=tasks)
        return running

    def _accept_report(self, current: CoordinationRun, report: EvidenceReport) -> CoordinationRun:
        """CAS one task completion, preserving validity across other-task updates."""

        task = next((item for item in current.tasks if item.task_id == report.task_id), None)
        if task is None:
            raise ValueError("resultado pertence a uma tarefa ausente do quadro")
        rejection = self._policy.decide_report_acceptance(current, task, report)
        if rejection is not None:
            raise ValueError(rejection.reason)
        completed_task = task.model_copy(
            update={
                "status": CoordinationTaskState.COMPLETED,
                "revision": task.revision + 1,
                "result": report,
            }
        )
        tasks = tuple(
            completed_task if item.task_id == task.task_id else item for item in current.tasks
        )
        accepted = self._advance(
            current,
            tasks=tasks,
            spent_steps=current.spent_steps + task.budget_steps,
            reserved_steps=current.reserved_steps - task.budget_steps,
        )
        self._observer.record_task_completed(
            run=accepted, task=completed_task, report=report, occurred_at=self._now()
        )
        return accepted

    @staticmethod
    def _require_scope(task: CoordinationTask, operation: str) -> None:
        if operation not in task.read_scope:
            raise PermissionError(
                f"perfil {task.profile.value} não recebeu permissão para {operation}"
            )

    def _advance(
        self,
        current: CoordinationRun,
        *,
        tasks: tuple[CoordinationTask, ...] | None = None,
        spent_steps: int | None = None,
        reserved_steps: int | None = None,
        state: CoordinationRunState | None = None,
        decision: CoordinationDecision | None = None,
    ) -> CoordinationRun:
        proposed = current.model_copy(
            update={
                "revision": current.revision + 1,
                "tasks": current.tasks if tasks is None else tasks,
                "spent_steps": current.spent_steps if spent_steps is None else spent_steps,
                "reserved_steps": current.reserved_steps
                if reserved_steps is None
                else reserved_steps,
                "state": current.state if state is None else state,
                "decision": current.decision if decision is None else decision,
                "updated_at": self._now(),
            }
        )
        self._policy.enforce_task_board_transition(current, proposed)
        self._run_policy.enforce_transition(current, proposed)
        return self._store.compare_and_swap(expected_revision=current.revision, run=proposed)

    def _record_decision(self, run: CoordinationRun, decision: CoordinationDecision) -> None:
        self._event(run, f"coordination_decision_{decision.kind.value}")
        self._observer.record_decision(run=run, decision=decision, occurred_at=self._now())

    def _event(self, run: CoordinationRun, event_type: str) -> None:
        payload = {
            "revision": run.revision,
            "state": run.state.value,
            "scenario": run.scenario.value,
            "task_count": len(run.tasks),
        }
        self._events.append(
            run_id=run.run_id,
            event_type=event_type,
            payload_json=json.dumps(payload, sort_keys=True),
            occurred_at=self._now(),
        )

    @staticmethod
    def _to_ref(item: FixtureEvidenceView) -> EvidenceRef:
        return EvidenceRef(
            evidence_id=uuid5(NAMESPACE_URL, item.source_uri + item.content_sha256),
            source=item.source_kind,
            artifact_id=item.source_uri,
            content_sha256=item.content_sha256,
            captured_at=item.retrieved_at,
        )
