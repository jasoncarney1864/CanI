"""Tests for the local-test-runner preflight checks.

These exist because the checks shipped with two bugs in a row, both of which produced a
*confident, plausible-looking* wrong answer rather than an obvious crash:

  1. platform.machine() was used to detect the interpreter architecture. It reports the
     host CPU, so a correctly emulated x64 Python on Windows on ARM answered 'ARM64' and
     the guard rejected the exact environment it was written to recommend.
  2. The checkout comparison walked parents[2] off __init__.py, which lands on `apps/`
     rather than `apps/shared-lib/cani_shared`. It reported a real-looking path, so the
     error read as a genuine finding instead of a bug in the check.

A guard that is wrong is worse than no guard, because it is trusted.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

_RUNNER = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "run_local_tests.py"


def _load_runner():
    # scripts/ is deliberately not a package, so import it by path.
    spec = importlib.util.spec_from_file_location("_cani_run_local_tests", _RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def test_matches_when_package_is_inside_the_checkout():
    repo = pathlib.Path("/repo")
    package_file = "/repo/apps/shared-lib/cani_shared/__init__.py"
    assert runner.shared_lib_is_this_checkout(package_file, repo) is True


def test_rejects_a_package_from_a_different_checkout():
    """The failure this guard exists for: a venv carried over from another directory."""
    repo = pathlib.Path("/repo")
    package_file = "/elsewhere/CanI/apps/shared-lib/cani_shared/__init__.py"
    assert runner.shared_lib_is_this_checkout(package_file, repo) is False


def test_rejects_a_site_packages_install():
    repo = pathlib.Path("/repo")
    package_file = "/usr/lib/python3.13/site-packages/cani_shared/__init__.py"
    assert runner.shared_lib_is_this_checkout(package_file, repo) is False


def test_does_not_confuse_the_apps_directory_with_the_package():
    """Regression: parents[2] resolved to apps/, which compared unequal for the wrong
    reason and would compare *equal* to a repo root that happened to be apps/."""
    repo = pathlib.Path("/repo")
    assert runner.shared_lib_is_this_checkout("/repo/apps/__init__.py", repo) is False
    assert runner.shared_lib_is_this_checkout("/repo/apps/shared-lib/__init__.py", repo) is False


def test_accepts_a_relative_repo_root():
    """preflight() passes an already-resolved root, but the helper shouldn't depend on
    that — resolve() is applied to both sides."""
    repo = pathlib.Path("/repo/sub/..")
    package_file = "/repo/apps/shared-lib/cani_shared/__init__.py"
    assert runner.shared_lib_is_this_checkout(package_file, repo) is True
