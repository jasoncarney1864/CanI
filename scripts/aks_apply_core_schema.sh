#!/usr/bin/env bash
# Apply database migrations to the dev AKS environment by shipping the repo's REAL
# migration runner (db/migrate.py) and migrations directory into a running docs-api pod
# and executing it there. Single source of truth: db/migrations/*.sql — this script
# contains no schema of its own, and schema_migrations tracking works exactly as it does
# locally/in compose.
#
# Requirements: kubectl context pointed at the dev cluster; a Running docs-api pod
# (it has psycopg installed, the Postgres env vars, and a writable /tmp emptyDir).
#
# Note: an earlier version of this script inlined a copy of 0001_core_schema.sql and
# bypassed schema_migrations. If it was ever run, the first execution of this version
# will harmlessly re-apply 0001 (every statement is IF NOT EXISTS) and then record it,
# self-healing the tracking table.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE=docs-platform

POD=$(kubectl -n "$NAMESPACE" get pod -l app=docs-api \
  --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}')

echo "Applying migrations via pod $POD"

tar -C "$REPO_ROOT" -cf - db/migrate.py db/migrations \
  | kubectl -n "$NAMESPACE" exec -i "$POD" -- tar -xf - -C /tmp

kubectl -n "$NAMESPACE" exec "$POD" -- python /tmp/db/migrate.py

kubectl -n "$NAMESPACE" exec "$POD" -- rm -rf /tmp/db
