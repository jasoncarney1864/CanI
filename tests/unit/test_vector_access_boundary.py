"""Guards the single chokepoint for tenant isolation.

Every Qdrant call must go through ``OwnerScopedQdrant``, which is the only place the
``owner_id`` payload filter is applied. Similarity search has no notion of ownership: a
query vector matches its nearest neighbours regardless of who uploaded them, so that
filter is the entire isolation guarantee. A raw ``QdrantClient`` constructed anywhere
else bypasses it, and nothing but this test would catch that in review.

This is deliberately a build failure rather than a convention.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER = REPO_ROOT / "apps" / "shared-lib" / "cani_shared" / "vector" / "qdrant_client.py"
SEARCH_ROOTS = ("apps", "scripts")

# Vendored and generated trees. Walking apps/web/node_modules is both pointless and slow
# enough to look like a hang.
PRUNE = {
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    ".git",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}


def _python_files() -> list[Path]:
    found: list[Path] = []
    for root in SEARCH_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in PRUNE]
            found.extend(Path(dirpath) / f for f in filenames if f.endswith(".py"))
    return found


def _imports_qdrant_sdk(path: Path) -> bool:
    """True if the module imports the ``qdrant_client`` SDK package itself.

    Absolute imports only. ``from .qdrant_client import OwnerScopedQdrant`` is a relative
    import of our own wrapper module, which happens to share the SDK's name, and is fine.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == "qdrant_client" or a.name.startswith("qdrant_client.") for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import, not the SDK
                continue
            mod = node.module or ""
            if mod == "qdrant_client" or mod.startswith("qdrant_client."):
                return True
    return False


def test_only_owner_scoped_wrapper_touches_the_qdrant_sdk() -> None:
    wrapper = WRAPPER.resolve()
    offenders = sorted(
        p.relative_to(REPO_ROOT).as_posix()
        for p in _python_files()
        if p.resolve() != wrapper and _imports_qdrant_sdk(p)
    )
    assert offenders == [], (
        "These modules import the Qdrant SDK directly, bypassing OwnerScopedQdrant and the "
        "owner_id filter that is the whole of our tenant isolation: " + ", ".join(offenders)
    )


def test_the_wrapper_itself_is_where_we_think_it_is() -> None:
    # If the wrapper moves, the test above silently stops guarding anything.
    assert WRAPPER.is_file(), f"expected the Qdrant wrapper at {WRAPPER}"
