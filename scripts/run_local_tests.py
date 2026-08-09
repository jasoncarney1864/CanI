#!/usr/bin/env python3
"""Run local tests in a stable order: unit first, then integration."""

from __future__ import annotations

import pathlib
import subprocess
import sys
import sysconfig


def run_step(cmd: list[str], cwd: pathlib.Path) -> int:
    print("+", " ".join(cmd))
    completed = subprocess.run(cmd, cwd=cwd)
    return completed.returncode


def preflight(repo_root: pathlib.Path) -> str | None:
    """Return an error message if the interpreter can't produce a trustworthy run.

    Both checks exist because their natural failure mode is a *misleading* one.
    """
    # A venv-less run silently uses (and installs into) the user site-packages, so
    # `pytest` and `ruff` appear to be "missing from PATH" when the real problem is
    # that no environment was ever created.
    if sys.prefix == sys.base_prefix:
        return (
            "not running inside a virtualenv.\n"
            "  Create and activate .venv-test first — see README 'Setup (clean machine)'."
        )

    # Windows on ARM: grpcio, grpcio-tools and tiktoken publish no win_arm64 wheels at
    # all, so an ARM64 interpreter falls back to source builds that need Rust + MSVC and
    # abort partway, leaving an incomplete environment.
    #
    # Probe with sysconfig.get_platform(), which reports what the interpreter was *built*
    # for ('win-amd64' / 'win-arm64') and is the same value pip derives wheel tags from.
    # platform.machine() is wrong here: it reports the host CPU, so an emulated x64
    # Python on an ARM64 machine still answers 'ARM64' and would fail a correct setup.
    if sys.platform == "win32":
        build_platform = sysconfig.get_platform()
        if build_platform != "win-amd64":
            return (
                f"this venv is {build_platform} Python; x64 (win-amd64) is required.\n"
                "  grpcio, grpcio-tools and tiktoken ship no win_arm64 wheels.\n"
                "  Rebuild .venv-test from an x64 interpreter — see README 'Windows on ARM'."
            )

    # An editable install left over from a different checkout resolves imports to the
    # *old* tree, so you edit one copy and test another with nothing to signal it.
    try:
        import cani_shared
    except ImportError:
        return "cani_shared is not importable. Run: pip install -r requirements-dev.txt"

    installed_from = pathlib.Path(cani_shared.__file__).resolve().parents[2]
    if installed_from != (repo_root / "apps" / "shared-lib").resolve():
        return (
            f"cani_shared resolves to {installed_from}, not this checkout.\n"
            "  The venv was built elsewhere and carries absolute paths. Delete it and\n"
            "  reinstall: pip install -r requirements-dev.txt"
        )

    return None


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parents[1]

    problem = preflight(repo_root)
    if problem is not None:
        print(f"error: {problem}", file=sys.stderr)
        return 2

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
