"""Read-only bridge from synthetic fixtures to application and agent ports."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from aula12_agents.agent.contracts import EvidenceItem, EvidencePack
from aula12_agents.domain.models import Evidence, Incident

from .reader import FixtureEvidence, FixtureReader


class FixtureGateway:
    """No fixture operation is exposed as a write-capable tool."""

    def __init__(self, reader: FixtureReader) -> None:
        self._reader = reader

    async def collect_evidence(self, *, incident: Incident) -> tuple[Evidence, ...]:
        raw = [
            self._reader.read_bug_report(),
            self._reader.read_ci_summary("1842"),
            *self._reader.query_error_logs(status_code=500),
        ]
        return tuple(self._as_domain(item) for item in raw)

    async def read_evidence(self, incident_id: str, *, limit: int) -> EvidencePack:
        raw = [self._reader.read_bug_report(), *self._reader.query_error_logs(status_code=500)]
        items = tuple(
            EvidenceItem(
                source=item.source_kind, artifact_id=item.source_uri, summary=item.content[:500]
            )
            for item in raw[:limit]
        )
        return EvidencePack(incident_id=incident_id, items=items, truncated=len(raw) > limit)

    @staticmethod
    def _as_domain(item: FixtureEvidence) -> Evidence:
        return Evidence(
            evidence_id=uuid5(NAMESPACE_URL, item.source_uri + item.content_sha256),
            source=item.source_kind,
            artifact_id=item.source_uri,
            content_sha256=item.content_sha256,
            captured_at=item.retrieved_at,
            summary=item.content[:1_000],
            trust="observed",
        )
