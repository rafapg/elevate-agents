#!/usr/bin/env python3
"""Display a pre-executed coordination scenario without any external service."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCENARIOS = {
    "supervisor": "01-supervisor-fixo.jsonl",
    "spawn": "02-spawn-saudavel.jsonl",
    "no-spawn": "03-no-spawn.jsonl",
    "cancelamento": "04-cancelamento-resultado-tardio.jsonl",
}
FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "coordination"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mostra um cenário sintético de coordenação da Aula 12."
    )
    parser.add_argument("scenario", choices=SCENARIOS, help="cenário a apresentar")
    args = parser.parse_args()

    path = FIXTURES_DIR / SCENARIOS[args.scenario]
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    print(f"Cenário pré-executado: {args.scenario} ({path.name})")
    print("Nenhum agente, modelo ou serviço externo foi iniciado.\n")
    for index, event in enumerate(events, start=1):
        attributes = event["attributes"]
        print(f"{index}. {event['event_type']} — {_summary(attributes)}")


def _summary(attributes: dict[str, Any]) -> str:
    decision = attributes.get("decision")
    task_id = attributes.get("task_id")
    reason = attributes.get("reason")
    parts: list[str] = []

    if task_id:
        parts.append(f"tarefa {task_id}")
    if decision:
        parts.append(f"decisão: {decision}")
    if reason:
        parts.append(f"motivo: {reason}")
    if "coverage_valid" in attributes:
        parts.append(
            f"cobertura: {attributes['coverage_valid']}/{attributes.get('coverage_target', '?')}"
        )
    if "deadline_seconds" in attributes:
        parts.append(f"prazo: {attributes['deadline_seconds']} s")
    if "result_aggregated" in attributes:
        parts.append(
            "resultado agregado" if attributes["result_aggregated"] else "resultado recusado"
        )
    if not parts:
        parts.append("início do cenário")
    return "; ".join(parts)


if __name__ == "__main__":
    main()
