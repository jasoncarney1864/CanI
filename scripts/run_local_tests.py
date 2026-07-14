#!/usr/bin/env python3
"""Run local tests in a stable order: unit first, then integration."""

from __future__ import annotations

import pathlib
import subprocess
import sys


def run_step(cmd: list[str], cwd: pathlib.Path) -> int:
    print("+", " ".join(cmd))
    completed = subprocess.run(cmd, cwd=cwd)
    return completed.returncode


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    steps = [
        [sys.executable, "-m", "pytest", "tests/unit", "-v"],
        [sys.executable, "-m", "pytest", "tests/integration", "-v"],
    ]

    for step in steps:
        code = run_step(step, repo_root)
        if code != 0:
            return code

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
