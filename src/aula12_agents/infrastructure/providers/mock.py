"""Deterministic FunctionModel used by default in tests and offline demos."""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel


def _deterministic_response(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    tool_returns = [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    ]
    if not tool_returns:
        return ModelResponse(
            parts=[ToolCallPart("read_evidence", {"incident_id": "demo-incident"})]
        )

    evidence_text = tool_returns[-1].model_response_str()
    output_tool = info.output_tools[0].name
    payload: dict[str, Any]
    if '"items":[]' in evidence_text.replace(" ", ""):
        payload = {
            "decision": "escalate",
            "hypothesis": None,
            "uncertainty": "No evidence was returned by the read-only source.",
            "next_action": "Escalate with a request for bounded, read-only evidence collection.",
            "evidence": [],
        }
    else:
        payload = {
            "decision": "conclude",
            "hypothesis": "The available evidence indicates a likely regression requiring review.",
            "uncertainty": (
                "This is a deterministic fixture conclusion, not a production diagnosis."
            ),
            "next_action": "Escalate the evidence card for human review; make no changes.",
            "evidence": [
                {
                    "source": "fixture",
                    "artifact_id": "demo-evidence",
                    "summary": "Deterministic mock received a non-empty evidence pack.",
                }
            ],
        }
    return ModelResponse(parts=[ToolCallPart(output_tool, payload)])


def build_mock_model() -> FunctionModel:
    return FunctionModel(_deterministic_response, model_name="deterministic-offline")
