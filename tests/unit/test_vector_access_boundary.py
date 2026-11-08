"""Guards the chokepoints for vector isolation.

Every user-corpus vector read or write must go through ``OwnerScopedVectorStore``, which is
the only place the ``owner_user_id`` filter is applied. Similarity search has no notion of
ownership: a query vector matches its nearest neighbours regardless of who uploaded them,
so that filter is the entire isolation guarantee for user documents. With the vectors in
Postgres (migration 0009) the bypass is no longer "a raw SDK client" but "a raw SQL
statement against the embeddings table" written anywhere else — and nothing but this test
would catch that in review.

``PublicLawVectorStore`` (docs/20-public-law-corpus-design.md §20.3) is the one deliberate
second wrapper: the public-law table has no owner concept at all — it's a shared corpus,
not user content — so there is nothing for it to bypass. It has its own analogous
fail-closed guarantee (a mandatory jurisdiction filter instead of owner), guarded the same
way by tests/unit/test_public_law_store.py. Any *other* reference to either embeddings
table from application code is exactly the bug this test exists to catch.

This is deliberately a build failure rather than a convention.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_VECTOR_DIR = REPO_ROOT / "apps" / "shared-lib" / "cani_shared" / "vector"
ALLOWED_WRAPPERS = (_VECTOR_DIR / "store.py", _VECTOR_DIR / "public_law_store.py")
SEARCH_ROOTS = ("apps", "scripts")

# The tables only the wrappers may name. Word-bounded so e.g. a docstring saying
# "chunk_embeddings table" in a wrapper is fine but a stray SELECT elsewhere is not.
_TABLE_RE = re.compile(r"\b(chunk_embeddings|law_chunk_embeddings)\b")

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


def _names_embeddings_table(path: Path) -> bool:
    try:
        return bool(_TABLE_RE.search(path.read_text(encoding="utf-8")))
    except UnicodeDecodeError:
        return False


def test_only_the_wrappers_touch_the_embeddings_tables() -> None:
    allowed = {w.resolve() for w in ALLOWED_WRAPPERS}
    offenders = sorted(
        p.relative_to(REPO_ROOT).as_posix()
        for p in _python_files()
        if p.resolve() not in allowed and _names_embeddings_table(p)
    )
    assert offenders == [], (
        "These modules reference the embeddings tables directly, bypassing "
        "OwnerScopedVectorStore/PublicLawVectorStore and the filter that is the whole of our "
        "tenant/jurisdiction isolation: " + ", ".join(offenders)
    )


def test_the_wrappers_are_where_we_think_they_are() -> None:
    # If a wrapper moves, the test above silently stops guarding anything.
    for wrapper in ALLOWED_WRAPPERS:
        assert wrapper.is_file(), f"expected the vector wrapper at {wrapper}"


def test_no_vector_sdk_crept_back() -> None:
    # The Qdrant client was removed in migration 0009's change set; a reintroduced SDK
    # import anywhere would mean a second vector path outside the wrappers.
    offenders = sorted(
        p.relative_to(REPO_ROOT).as_posix()
        for p in _python_files()
        if re.search(r"^\s*(from|import)\s+qdrant_client\b", p.read_text(encoding="utf-8"), re.M)
    )
    assert offenders == []
