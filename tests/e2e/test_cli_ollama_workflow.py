"""Opt-in end-to-end contract for the real Ollama CLI path."""

from __future__ import annotations

import asyncio
import json
import os
from uuid import UUID

import pytest

from aula12_agents.infrastructure.persistence import SQLitePersistence
from aula12_agents.interfaces.cli import async_main
from aula12_agents.settings import load_settings

pytestmark = [pytest.mark.provider, pytest.mark.slow]


def _requires_ollama_or_skip() -> None:
    settings = load_settings()
    if settings.model_provider != "ollama" or not settings.ollama_model:
        pytest.skip("configure MODEL_PROVIDER=ollama and OLLAMA_MODEL in the lab .env")


@pytest.mark.asyncio
async def test_cli_ollama_persists_a_gated_checkpoint_and_jsonl_trace(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path
) -> None:
    """Exercise the CLI boundary through the real provider, never the default suite.

    The temporary paths make the assertions independent from a developer's prior
    runs.  Langfuse is explicitly disabled here: its own smoke test verifies the
    remote exporter, while this contract verifies the local-safe workflow path.
    """
    if os.environ.get("RUN_OLLAMA_WORKFLOW_CONTRACT") != "1":
        pytest.skip("set RUN_OLLAMA_WORKFLOW_CONTRACT=1 to run the real CLI workflow")
    _requires_ollama_or_skip()
    database_path = tmp_path / "workflow.sqlite3"
    trace_dir = tmp_path / "traces"
    monkeypatch.setenv("RUN_DB_PATH", str(database_path))
    monkeypatch.setenv("TRACE_DIR", str(trace_dir))
    monkeypatch.setenv("OBSERVABILITY_BACKEND", "jsonl")

    try:
        exit_code = await asyncio.wait_for(async_main(["run"]), timeout=180)
    except TimeoutError:
        pytest.fail("CLI workflow timed out after 180s; inspect the local Ollama server")

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    run_id = UUID(result["run_id"])
    checkpoint = SQLitePersistence(database_path).load(run_id)

    assert checkpoint.state.value == result["state"]
    assert checkpoint.decision is not None, "the evidence gate did not produce a decision card"
    assert checkpoint.evidence_refs, "fixture evidence was not persisted in the checkpoint"
    assert checkpoint.decision.evidence, "the accepted decision does not cite fixture evidence"
    assert checkpoint.decision.decision.value in {"conclude", "escalate", "retry"}

    trace_files = list(trace_dir.glob("*.jsonl"))
    assert len(trace_files) == 1
    trace_lines = trace_files[0].read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in trace_lines]
    event_types = {event["event_type"] for event in events}
    assert "workflow.checkpoint_created" in event_types
    assert event_types & {
        "workflow.gate_concluded",
        "workflow.concluded",
        "workflow.escalated",
        "workflow.retry_scheduled",
    }
    assert {event["run_id"] for event in events} == {str(run_id)}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cli_ollama_exports_workflow_to_langfuse_and_keeps_jsonl_fallback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path
) -> None:
    """Exercise the real CLI with the local and remote observability paths together.

    This remains opt-in because it needs a local Ollama server and Langfuse
    credentials. The CLI flushes Langfuse before returning; a remote exporter
    failure is observable as a local fallback event rather than being hidden.
    """
    if os.environ.get("RUN_OLLAMA_LANGFUSE_WORKFLOW_CONTRACT") != "1":
        pytest.skip("set RUN_OLLAMA_LANGFUSE_WORKFLOW_CONTRACT=1 to run Ollama + Langfuse E2E")
    _requires_ollama_or_skip()
    if not load_settings().trace_settings().has_langfuse_credentials:
        pytest.skip("configure LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in the lab .env")

    database_path = tmp_path / "workflow.sqlite3"
    trace_dir = tmp_path / "traces"
    monkeypatch.setenv("RUN_DB_PATH", str(database_path))
    monkeypatch.setenv("TRACE_DIR", str(trace_dir))
    monkeypatch.setenv("OBSERVABILITY_BACKEND", "both")

    try:
        exit_code = await asyncio.wait_for(async_main(["run"]), timeout=240)
    except TimeoutError:
        pytest.fail("CLI workflow timed out after 240s; inspect Ollama and Langfuse connectivity")

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    run_id = UUID(result["run_id"])
    checkpoint = SQLitePersistence(database_path).load(run_id)
    assert checkpoint.decision is not None
    assert checkpoint.evidence_refs

    trace_files = list(trace_dir.glob("*.jsonl"))
    assert len(trace_files) == 1
    events = [json.loads(line) for line in trace_files[0].read_text(encoding="utf-8").splitlines()]
    event_types = {event["event_type"] for event in events}
    assert "workflow.checkpoint_created" in event_types
    assert "workflow.hypothesis_checkpointed" in event_types
    assert "workflow.gate.decided" in event_types
    assert "telemetry.remote_export_failed" not in event_types
    assert {event["run_id"] for event in events} == {str(run_id)}
