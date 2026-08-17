from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).parents[3]
SCRIPT = LAB_ROOT / "scripts" / "show_coordination_scenario.py"


def test_scenario_viewer_displays_the_cancellation_outcome() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "cancelamento"],
        cwd=LAB_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Nenhum agente, modelo ou serviço externo foi iniciado." in result.stdout
    assert "coordination.task.cancelled" in result.stdout
    assert "resultado recusado" in result.stdout
