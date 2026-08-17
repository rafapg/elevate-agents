from __future__ import annotations

import json
from types import SimpleNamespace

from aula12_agents.interfaces.cli import _coordination_run_projection, build_parser, main


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


def test_coordination_run_parser_accepts_only_the_four_teaching_scenarios() -> None:
    parser = build_parser()

    args = parser.parse_args(["coordination", "run", "supervisor"])

    assert args.command == "coordination"
    assert args.coordination_command == "run"
    assert args.scenario == "supervisor"


def test_coordination_run_projection_is_safe_and_compact() -> None:
    output = _coordination_run_projection(
        SimpleNamespace(
            run_id="coordination-run-1",
            scenario="supervisor",
            state="completed",
            revision=4,
            decision="aggregate",
            tasks=(
                SimpleNamespace(
                    task_id="task-ci",
                    profile="ci-reader",
                    status="completed",
                    budget_steps=3,
                    result=object(),
                ),
            ),
        )
    )

    assert output == {
        "run_id": "coordination-run-1",
        "scenario": "supervisor",
        "state": "completed",
        "revision": 4,
        "decision": "aggregate",
        "tasks": [
            {
                "task_id": "task-ci",
                "profile": "ci-reader",
                "status": "completed",
                "budget_steps": 3,
                "result_available": True,
            }
        ],
    }


def test_coordination_inspection_commands_show_a_read_only_safe_projection(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("RUN_DB_PATH", str(tmp_path / "runs.sqlite3"))
    monkeypatch.setenv("TRACE_DIR", str(tmp_path / "traces"))

    assert main(["coordination", "run", "supervisor"]) == 0
    started = json.loads(capsys.readouterr().out)
    run_id = started["run_id"]
    database_bytes_before = (tmp_path / "runs.sqlite3").read_bytes()

    assert main(["coordination", "show-board", run_id]) == 0
    board = json.loads(capsys.readouterr().out)
    assert board["run_id"] == run_id
    assert board["scenario"] == "supervisor"
    assert board["budget"] == {"steps": 6, "spent_steps": 4, "reserved_steps": 0}
    assert {task["profile"] for task in board["tasks"]} == {"ci_analyst", "change_analyst"}
    assert all(task["result"]["available"] for task in board["tasks"])
    assert "artifact_id" not in json.dumps(board)

    assert main(["coordination", "show-events", run_id]) == 0
    timeline = json.loads(capsys.readouterr().out)
    assert timeline["run_id"] == run_id
    assert timeline["events"]
    assert timeline["events"][0]["board"]["available"] is True
    assert "payload_json" not in json.dumps(timeline)
    assert (tmp_path / "runs.sqlite3").read_bytes() == database_bytes_before


def test_coordination_inspection_parser_keeps_run_and_read_only_commands_distinct() -> None:
    parser = build_parser()

    board = parser.parse_args(
        ["coordination", "show-board", "11111111-1111-1111-1111-111111111111"]
    )
    events = parser.parse_args(
        ["coordination", "show-events", "11111111-1111-1111-1111-111111111111"]
    )

    assert board.coordination_command == "show-board"
    assert events.coordination_command == "show-events"
