"""Read-only PydanticAI tools exposed to the specialist."""

from __future__ import annotations

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.toolsets import FunctionToolset

from .contracts import EvidencePack
from .deps import AgentDeps, ToolObservation

READONLY_EVIDENCE_TOOLSET_ID = "readonly-evidence-v1"


def build_readonly_toolset() -> FunctionToolset[AgentDeps]:
    """Build a stable-ID toolset suitable for a future durable runtime."""

    async def read_evidence(ctx: RunContext[AgentDeps], incident_id: str) -> EvidencePack:
        """Read compact incident evidence. This tool cannot modify external systems.

        Args:
            incident_id: Stable identifier of the incident under investigation.
        """
        if not ctx.deps.policy.allow_read_evidence:
            raise ModelRetry("Evidence reads are disabled by the explicit run policy.")

        pack = await ctx.deps.evidence_reader.read_evidence(
            incident_id,
            limit=ctx.deps.policy.max_evidence_items,
        )
        await ctx.deps.observe(
            ToolObservation(
                run_id=ctx.deps.run_id,
                tool_name="read_evidence",
                incident_id=incident_id,
                outcome="truncated" if pack.truncated else "ok",
                evidence_count=len(pack.items),
            )
        )
        return pack

    return FunctionToolset(
        [read_evidence],
        id=READONLY_EVIDENCE_TOOLSET_ID,
        sequential=True,
        require_parameter_descriptions=True,
    )
