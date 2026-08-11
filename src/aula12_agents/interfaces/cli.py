"""Small async CLI for the reproducible local laboratory."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from aula12_agents.agent.deps import AgentDeps, AgentPolicy, CriticDeps
from aula12_agents.agent.factory import build_critic_agent, build_hypothesis_agent
from aula12_agents.application.coordinator import CoordinatorPolicy, RunCoordinator
from aula12_agents.application.ports import AgentExecutor, CriticExecutor
from aula12_agents.domain.models import (
    CritiqueCard,
    CritiqueOutcome,
    Decision,
    Evidence,
    HypothesisCard,
    HypothesisDraft,
    Incident,
)
from aula12_agents.infrastructure.agent_executor import (
    PydanticAIAgentExecutor,
    PydanticAICriticExecutor,
)
from aula12_agents.infrastructure.fixtures import FixtureGateway, FixtureReader
from aula12_agents.infrastructure.persistence import CheckpointNotFound, SQLitePersistence
from aula12_agents.infrastructure.providers import build_model
from aula12_agents.infrastructure.trace import (
    ObservabilityBootstrap,
    ToolTraceObserver,
    WorkflowTraceObserver,
    build_observability,
)
from aula12_agents.interfaces.inspection import LocalRunInspector
from aula12_agents.settings import LabSettings, load_settings


class LocalRetryScheduler:
    """Makes scheduled retries visible; automatic background delivery is intentionally absent."""

    def schedule(self, *, run_id: UUID, retry_at: datetime) -> None:
        del run_id, retry_at


class OfflineFixtureExecutor:
    """Deterministic executor for the offline CLI path.

    The PydanticAI FunctionModel remains covered by its unit tests, but this
    narrow adapter keeps the default CLI reproducible while preserving the
    same application port and evidence gate used by real providers.
    """

    async def decide(
        self, *, run_id: UUID, incident: Incident, evidence: tuple[Evidence, ...]
    ) -> HypothesisCard:
        del run_id
        if not evidence:
            return HypothesisCard(
                decision=Decision.ESCALATE,
                uncertainty="The offline fixture returned no evidence.",
                next_action="Request bounded, read-only evidence collection from a human reviewer.",
            )
        return HypothesisCard(
            decision=Decision.CONCLUDE,
            hypothesis=HypothesisDraft(
                statement=(
                    f"Synthetic evidence for {incident.incident_id} indicates a reviewable "
                    "checkout regression."
                ),
                rationale="Offline fixture executor; this is not a production diagnosis.",
                uncertainty="The conclusion is limited to the supplied synthetic fixture packet.",
                evidence=tuple(evidence),
            ),
            uncertainty="The conclusion is limited to the supplied synthetic fixture packet.",
            next_action="Escalate the evidence card for human review; make no changes.",
            evidence=tuple(evidence),
        )


class OfflineFixtureCritic:
    """Deterministic reviewer for the offline path; it has no tool capability."""

    async def review(
        self,
        *,
        run_id: UUID,
        incident: Incident,
        evidence: tuple[Evidence, ...],
        proposal: HypothesisCard,
    ) -> CritiqueCard:
        del run_id, incident, evidence
        return CritiqueCard(
            outcome=CritiqueOutcome.APPROVE,
            rationale="The deterministic fixture proposal cites its bounded evidence.",
            next_action=proposal.next_action,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aula12-agents")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("doctor", help="show safe configuration status")
    run = subcommands.add_parser("run", help="start a synthetic, read-only incident run")
    run.add_argument("--incident-id", default="BUG-204")
    run.add_argument("--title", default="Checkout errors after deployment")
    run.add_argument("--description", default="Synthetic incident from the lab fixture packet.")
    run.add_argument("--service", default="checkout")
    run.add_argument("--severity", choices=("low", "medium", "high", "critical"), default="high")
    resume = subcommands.add_parser("resume", help="resume a run waiting for its bounded retry")
    resume.add_argument("run_id", type=UUID)
    show = subcommands.add_parser("show-run", help="print an export-safe checkpoint JSON")
    show.add_argument("run_id", type=UUID)
    subcommands.add_parser("list-runs", help="list locally persisted runs without incident content")
    events = subcommands.add_parser("show-events", help="show a redacted local event timeline")
    events.add_argument("run_id", type=UUID)
    trace = subcommands.add_parser(
        "show-trace", help="show redacted local JSONL trace events; no Langfuse connection is made"
    )
    trace.add_argument("run_id", type=UUID)
    return parser


async def dispatch(args: argparse.Namespace, settings: LabSettings) -> dict[str, object]:
    if args.command == "doctor":
        report = settings.doctor_report()
        report["workflow_execution"] = "local CLI supports mock, Ollama, and OpenRouter adapters"
        report["retry_delivery"] = "manual: run `resume <run_id>` after a waiting_retry checkpoint"
        report["trace_wiring"] = "workflow events emit to local JSONL; Langfuse export is optional"
        return report

    if args.command == "list-runs":
        return {
            "runs": LocalRunInspector(
                database_path=settings.run_db_path, trace_dir=settings.trace_dir
            ).list_runs()
        }

    store = SQLitePersistence(settings.run_db_path)
    if args.command == "show-run":
        checkpoint = store.load(args.run_id)
        return checkpoint.model_dump(mode="json")
    if args.command == "show-events":
        return {
            "run_id": str(args.run_id),
            "events": LocalRunInspector(
                database_path=settings.run_db_path, trace_dir=settings.trace_dir
            ).events_for(args.run_id),
        }
    if args.command == "show-trace":
        return {
            "run_id": str(args.run_id),
            "events": LocalRunInspector(
                database_path=settings.run_db_path, trace_dir=settings.trace_dir
            ).trace_for(args.run_id),
        }

    coordinator, observability = _build_coordinator(settings, store)
    try:
        if args.command == "resume":
            checkpoint = await coordinator.resume(args.run_id)
        else:
            incident = Incident(
                incident_id=args.incident_id,
                title=args.title,
                description=args.description,
                reported_at=datetime.now(UTC),
                service=args.service,
                severity=args.severity,
            )
            checkpoint = await coordinator.start(incident)
    finally:
        observability.sink.flush()
    return {
        "run_id": str(checkpoint.run_id),
        "state": checkpoint.state.value,
        "revision": checkpoint.revision,
        "next_step": checkpoint.next_step,
    }


def _build_coordinator(
    settings: LabSettings, store: SQLitePersistence
) -> tuple[RunCoordinator, ObservabilityBootstrap]:
    gateway = FixtureGateway(FixtureReader())
    observability = build_observability(settings.trace_settings())
    executor: AgentExecutor
    critic: CriticExecutor
    if settings.model_provider == "mock":
        executor = OfflineFixtureExecutor()
        critic = OfflineFixtureCritic()
    else:
        model = observability.instrument_pydantic_ai_model(
            build_model(settings.provider_settings())
        )
        agent = build_hypothesis_agent(model)
        executor = PydanticAIAgentExecutor(
            agent,
            AgentDeps(
                run_id="assigned-by-coordinator",
                evidence_reader=gateway,
                policy=AgentPolicy(),
                observation_sink=ToolTraceObserver(
                    sink=observability.local_sink,
                    workflow_name="aula12-agents",
                    workflow_version="aula12-cli-v1",
                    environment=settings.langfuse_environment,
                    now=lambda: datetime.now(UTC),
                ),
            ),
        )
        critic = PydanticAICriticExecutor(
            build_critic_agent(model),
            CriticDeps(run_id="assigned-by-coordinator", policy=AgentPolicy()),
        )
    input_hash = hashlib.sha256(b"aula12-cli-input-v1").hexdigest()
    coordinator = RunCoordinator(
        checkpoints=store,
        tools=gateway,
        agent=executor,
        critic=critic,
        scheduler=LocalRetryScheduler(),
        events=store,
        policy=CoordinatorPolicy(
            workflow_version="aula12-cli-v1",
            input_sha256=input_hash,
            max_attempts=2,
            retry_delay=timedelta(seconds=1),
        ),
        now=lambda: datetime.now(UTC),
        observer=WorkflowTraceObserver(
            sink=observability.sink,
            workflow_name="aula12-agents",
            environment=settings.langfuse_environment,
        ),
    )
    return coordinator, observability


async def async_main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = await dispatch(args, load_settings())
    except (CheckpointNotFound, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
