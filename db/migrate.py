"""Minimal, dependency-free migration runner: applies db/migrations/*.sql in order,
tracking applied filenames in a schema_migrations table. No ORM/Alembic dependency —
this is the whole tool, kept intentionally small for a solo-operated MVP (§9.11/§11.7).
"""

from __future__ import annotations

import os
import pathlib
import sys

import psycopg

MIGRATIONS_DIR = pathlib.Path(__file__).parent / "migrations"


def build_dsn() -> str:
    # Use psycopg's own conninfo builder rather than manual string formatting: it
    # correctly quotes/escapes values (e.g. passwords containing spaces or other
    # libpq-significant characters), which naive f-string concatenation does not.
    return psycopg.conninfo.make_conninfo(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def main() -> None:
    dsn = build_dsn()
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())"
        )
        applied = {row[0] for row in conn.execute("SELECT filename FROM schema_migrations").fetchall()}

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                print(f"skip (already applied): {path.name}")
                continue
            print(f"applying: {path.name}")
            sql = path.read_text(encoding="utf-8")
            conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))

    print("migrations complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - top-level CLI entrypoint
        print(f"migration failed: {exc}", file=sys.stderr)
        sys.exit(1)
