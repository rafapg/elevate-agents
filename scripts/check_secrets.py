"""Fail safely when common credentials appear in tracked project files.

This intentionally scans ``git ls-files`` rather than the working tree: local
``.env`` files and generated traces are excluded by design, while anything
about to become public is checked both locally and in CI.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_VALUES = frozenset({"sk-not-a-real-secret", "sk-lf-synthetic"})
SECRET_PATTERNS = (
    re.compile(r"\bsk-(?!not-a-real-secret\b)[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b(?:pk|sk)-lf-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def tracked_files() -> tuple[Path, ...]:
    """Return tracked regular files, without walking ignored local artefacts."""

    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return tuple(
        ROOT / entry.decode("utf-8")
        for entry in result.stdout.split(b"\0")
        if entry and (ROOT / entry.decode("utf-8")).is_file()
    )


def findings() -> tuple[str, ...]:
    """Return file and line references only; never reproduce a potential secret."""

    matches: list[str] = []
    for path in tracked_files():
        if path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".whl"}:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            for pattern in SECRET_PATTERNS:
                found = pattern.search(line)
                if found is not None and found.group() not in SYNTHETIC_VALUES:
                    matches.append(f"{path.relative_to(ROOT)}:{line_number}")
                    break
    return tuple(matches)


def main() -> int:
    matches = findings()
    if not matches:
        print("Secret scan passed: no common credential patterns in tracked files.")
        return 0
    print("Potential credential pattern found in tracked files (value redacted):", file=sys.stderr)
    print("\n".join(matches), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
