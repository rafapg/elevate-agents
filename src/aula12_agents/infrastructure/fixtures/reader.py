"""Read-only fixture adapter with bounded, provenance-carrying responses.

It deliberately exposes individual evidence artefacts rather than a directory
walk. That makes context selection visible in the lab and prevents a caller
from receiving the whole incident packet by accident.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, ClassVar

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SENSITIVE_KEY = re.compile(r"(?:api[_-]?key|authorization|cookie|password|secret|token)", re.I)
_SENSITIVE_VALUE = re.compile(r"(?:sk-[A-Za-z0-9_-]+|Bearer\s+\S+)", re.I)


class FixtureValidationError(ValueError):
    """Raised when a fixture identifier or filter is outside the allowlist."""


@dataclass(frozen=True, slots=True)
class FixtureEvidence:
    """A bounded, sanitized fixture result and enough provenance to audit it."""

    evidence_id: str
    source_kind: str
    source_uri: str
    retrieved_at: datetime
    content: str
    content_sha256: str
    byte_count: int
    trust_level: str = "synthetic_fixture"


class FixtureReader:
    """Adapter for the intentionally small synthetic incident corpus.

    The adapter has no write API, accepts only known fixture identifiers, and
    performs redaction before returning any field. ``fixture_root`` can be
    passed by tests; the default resolves to ``lab/fixtures``.
    """

    _MAX_CONTENT_CHARS = 4_000
    _FIXED_RETRIEVED_AT = datetime(2026, 8, 8, 9, 20, tzinfo=UTC)
    _CI_RUNS: ClassVar[dict[str, str]] = {
        "1842": "ci/run-1842.json",
        "1843": "ci/run-1843-timeout.json",
    }
    _RUNBOOKS: ClassVar[dict[str, str]] = {
        "checkout-investigation": "runbooks/checkout-investigation.md"
    }
    _COMMITS: ClassVar[dict[str, str]] = {"8f3a": "repo/commits/8f3a-session-resume.md"}
    _ISSUES: ClassVar[dict[str, str]] = {"ISSUE-91": "issues/ISSUE-91.md"}

    def __init__(self, fixture_root: Path | None = None) -> None:
        self._root = fixture_root or Path(__file__).resolve().parents[4] / "fixtures"

    def read_bug_report(self) -> FixtureEvidence:
        return self._evidence("BUG-204", "bug_report", "bug-report.md")

    def search_commits(self, query: str) -> list[FixtureEvidence]:
        self._validate_query(query)
        artifact = self._read_text(self._COMMITS["8f3a"])
        return (
            [self._evidence("commit-8f3a", "commit", self._COMMITS["8f3a"], artifact)]
            if query.lower() in artifact.lower()
            or query.lower() in {"checkout", "session", "resume", "2026.08.1"}
            else []
        )

    def read_ci_summary(self, run_id: str) -> FixtureEvidence:
        path = self._CI_RUNS.get(run_id)
        if path is None:
            raise FixtureValidationError(f"unknown synthetic CI run: {run_id}")
        payload = json.loads(self._read_text(path))
        return self._evidence(f"ci-{run_id}", "ci", path, json.dumps(payload, sort_keys=True))

    def search_issues(self, query: str) -> list[FixtureEvidence]:
        self._validate_query(query)
        artifact = self._read_text(self._ISSUES["ISSUE-91"])
        return (
            [self._evidence("issue-91", "issue", self._ISSUES["ISSUE-91"], artifact)]
            if query.lower() in artifact.lower()
            or query.lower() in {"safari", "checkout", "cookie"}
            else []
        )

    def query_error_logs(
        self,
        *,
        status_code: int | None = None,
        browser_family: str | None = None,
        feature_flag: str | None = None,
    ) -> list[FixtureEvidence]:
        """Return one sanitized evidence item per matching synthetic log event."""

        allowed_browsers = {None, "Safari", "Chrome"}
        allowed_flags = {None, "payment_return_v2"}
        if browser_family not in allowed_browsers or feature_flag not in allowed_flags:
            raise FixtureValidationError("unsupported log filter")
        if status_code is not None and status_code not in {200, 500, 502}:
            raise FixtureValidationError("unsupported synthetic status code")

        rows = (
            json.loads(line)
            for line in self._read_text("logs/checkout-errors.jsonl").splitlines()
            if line
        )
        matches = [
            row for row in rows if self._matches_log(row, status_code, browser_family, feature_flag)
        ]
        return [
            self._evidence(
                str(row["event_id"]),
                "log",
                "logs/checkout-errors.jsonl",
                json.dumps(row, sort_keys=True),
            )
            for row in matches
        ]

    def read_runbook(self, slug: str) -> FixtureEvidence:
        path = self._RUNBOOKS.get(slug)
        if path is None:
            raise FixtureValidationError(f"unknown synthetic runbook: {slug}")
        return self._evidence("runbook-checkout-investigation", "runbook", path)

    def _evidence(
        self, evidence_id: str, source_kind: str, relative_path: str, raw: str | None = None
    ) -> FixtureEvidence:
        raw_content = self._read_text(relative_path) if raw is None else raw
        content = self._sanitize(raw_content)
        return FixtureEvidence(
            evidence_id=evidence_id,
            source_kind=source_kind,
            source_uri=f"fixture://{relative_path}",
            retrieved_at=self._FIXED_RETRIEVED_AT,
            content=content,
            content_sha256=sha256(content.encode("utf-8")).hexdigest(),
            byte_count=len(content.encode("utf-8")),
        )

    def _read_text(self, relative_path: str) -> str:
        candidate = (self._root / relative_path).resolve()
        root = self._root.resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise FixtureValidationError("fixture path is not available")
        return candidate.read_text(encoding="utf-8")

    @staticmethod
    def _matches_log(
        row: Mapping[str, Any],
        status_code: int | None,
        browser_family: str | None,
        feature_flag: str | None,
    ) -> bool:
        return (
            (status_code is None or row["status_code"] == status_code)
            and (browser_family is None or row["browser_family"] == browser_family)
            and (feature_flag is None or row["feature_flag"] == feature_flag)
        )

    @staticmethod
    def _validate_query(query: str) -> None:
        if not query or len(query) > 80 or _CONTROL_CHARS.search(query):
            raise FixtureValidationError("query must be a short printable string")

    @classmethod
    def _sanitize(cls, value: str) -> str:
        value = _CONTROL_CHARS.sub("", value)
        value = _SENSITIVE_VALUE.sub("[REDACTED]", value)
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value[: cls._MAX_CONTENT_CHARS]
        return json.dumps(cls._redact_mapping(parsed), sort_keys=True)[: cls._MAX_CONTENT_CHARS]

    @classmethod
    def _redact_mapping(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else cls._redact_mapping(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._redact_mapping(item) for item in value]
        if isinstance(value, str):
            return _SENSITIVE_VALUE.sub("[REDACTED]", _CONTROL_CHARS.sub("", value))
        return value
