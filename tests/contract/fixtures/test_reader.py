from __future__ import annotations

import json
from pathlib import Path

import pytest

from aula12_agents.infrastructure.fixtures import FixtureReader, FixtureValidationError


def test_bug_report_has_stable_provenance() -> None:
    evidence = FixtureReader().read_bug_report()

    assert evidence.evidence_id == "BUG-204"
    assert evidence.source_uri == "fixture://bug-report.md"
    assert evidence.content_sha256
    assert "Safari is the first sensor" in evidence.content


def test_commit_and_successful_ci_expose_the_coverage_gap() -> None:
    reader = FixtureReader()

    commits = reader.search_commits("session")
    ci = json.loads(reader.read_ci_summary("1842").content)

    assert commits[0].source_kind == "commit"
    assert "missing `session_id`" in commits[0].content
    assert ci["status"] == "success"
    assert any("without session_id" in note for note in ci["coverage_notes"])


def test_timeout_ci_is_distinct_from_product_evidence() -> None:
    ci = json.loads(FixtureReader().read_ci_summary("1843").content)

    assert ci["status"] == "timed_out"
    assert ci["retry_hint"] == "retry_once_after_checkpoint"


def test_log_query_is_bounded_and_preserves_provenance() -> None:
    results = FixtureReader().query_error_logs(
        status_code=500, browser_family="Safari", feature_flag="payment_return_v2"
    )

    assert [result.evidence_id for result in results] == ["log-7001", "log-7002"]
    assert all(result.source_uri == "fixture://logs/checkout-errors.jsonl" for result in results)
    assert all("session_id was absent" in result.content for result in results)


def test_historical_issue_is_context_not_current_proof() -> None:
    issue = FixtureReader().search_issues("Safari")[0]

    assert "not proof" in issue.content
    assert issue.source_kind == "issue"


def test_reader_rejects_unknown_or_unbounded_access() -> None:
    reader = FixtureReader()

    with pytest.raises(FixtureValidationError):
        reader.read_ci_summary("anything")
    with pytest.raises(FixtureValidationError):
        reader.query_error_logs(browser_family="Opera")
    with pytest.raises(FixtureValidationError):
        reader.search_commits("x" * 81)


def test_json_content_is_sanitized_before_returning(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    (root / "ci").mkdir(parents=True)
    (root / "ci" / "run-1842.json").write_text(
        '{"token":"sk-not-a-real-secret","summary":"safe"}', encoding="utf-8"
    )
    reader = FixtureReader(root)

    evidence = reader.read_ci_summary("1842")

    assert "sk-not-a-real-secret" not in evidence.content
    assert "[REDACTED]" in evidence.content
