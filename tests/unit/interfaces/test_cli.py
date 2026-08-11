from __future__ import annotations

import json

from aula12_agents.interfaces.cli import main


def test_doctor_is_safe_and_reports_mock(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("RUN_DB_PATH", str(tmp_path / "runs.sqlite3"))

    assert main(["doctor"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["model_provider"] == "mock"
    assert report["trace_wiring"].startswith("workflow events emit")


def test_mock_run_and_show_run(monkeypatch, capsys, tmp_path) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("RUN_DB_PATH", str(tmp_path / "runs.sqlite3"))
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))

    assert main(["run"]) == 0
    started = json.loads(capsys.readouterr().out)
    assert started["state"] in {"completed", "escalated", "waiting_retry"}

    assert main(["show-run", started["run_id"]]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["run_id"] == started["run_id"]
    traces = list((tmp_path / "traces").glob("*.jsonl"))
    assert len(traces) == 1
    trace_text = traces[0].read_text(encoding="utf-8")
    assert "workflow.checkpoint_created" in trace_text
    assert "workflow.stage.started" in trace_text
    assert "workflow.stage.completed" in trace_text
    assert "workflow.gate.decided" in trace_text


def test_offline_inspection_commands_expose_safe_local_projections(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("RUN_DB_PATH", str(tmp_path / "runs.sqlite3"))
    trace_dir = tmp_path / "traces"
    monkeypatch.setenv("TRACE_DIR", str(trace_dir))

    assert main(["run", "--description", "do not print this incident body"]) == 0
    started = json.loads(capsys.readouterr().out)
    run_id = started["run_id"]

    assert main(["list-runs"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["runs"] == [
        {
            "run_id": run_id,
            "revision": started["revision"],
            "state": started["state"],
            "created_at": listed["runs"][0]["created_at"],
            "updated_at": listed["runs"][0]["updated_at"],
        }
    ]

    assert main(["show-events", run_id]) == 0
    events = json.loads(capsys.readouterr().out)
    assert events["run_id"] == run_id
    assert events["events"]
    assert events["events"][0]["checkpoint"]["available"] is True
    assert "do not print this incident body" not in json.dumps(events)

    trace_path = trace_dir / "manual.jsonl"
    trace_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "event_id": "11111111-1111-1111-1111-111111111111",
                "event_type": "teaching.trace",
                "occurred_at": "2026-01-01T00:00:00Z",
                "trace_id": "a" * 32,
                "span_id": "b" * 16,
                "run_id": run_id,
                "workflow_name": "aula12-agents",
                "workflow_version": "test",
                "attributes": {"prompt": "must not reach the terminal", "api_key": "secret"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert main(["show-trace", run_id]) == 0
    trace = json.loads(capsys.readouterr().out)
    manual = next(event for event in trace["events"] if event["event_type"] == "teaching.trace")
    assert manual["attributes"] == {"prompt": "[CONTENT_NOT_CAPTURED]", "api_key": "[REDACTED]"}
