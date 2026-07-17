"""Operator revocation tool (D2, docs/07 §7.7). Deliberately a script, not an HTTP
endpoint: there is no admin RBAC yet (§7.4 support-admin/platform-admin is unbuilt), so
an admin API would be an unauthenticated privilege hole. Runs anywhere the POSTGRES_*
env vars point at the target database — locally against compose, or inside a pod via
the same kubectl-exec pattern as aks_apply_core_schema.sh.

Usage:
  python scripts/revoke_user_access.py --user-id <uuid> --entitlement can_access_docs \
      --revoke-sessions --actor jason --reason "support case 123"
  python scripts/revoke_user_access.py --user-id <uuid> --all-auth \
      --actor jason --reason "suspected credential compromise"

--revoke-sessions / --all-auth stamp the user's revocation epoch: every session and
access token issued up to that instant dies on its next use, immediately.
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "shared-lib"))
from cani_shared.db.repositories import revoke_all_user_auth, revoke_entitlement  # noqa: E402


def build_dsn() -> str:
    return (
        f"host={os.environ['POSTGRES_HOST']} port={os.environ.get('POSTGRES_PORT', '5432')} "
        f"dbname={os.environ['POSTGRES_DB']} user={os.environ['POSTGRES_USER']} "
        f"password={os.environ['POSTGRES_PASSWORD']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Revoke a user's entitlement and/or live credentials.")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--actor", required=True, help="who is performing this action (for the audit event)")
    parser.add_argument("--reason", required=True, help="why (for the audit event)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--entitlement", help="entitlement name to revoke (e.g. can_access_docs)")
    group.add_argument(
        "--all-auth",
        action="store_true",
        help="kill every live session/token WITHOUT touching entitlements (compromise containment)",
    )
    parser.add_argument(
        "--revoke-sessions",
        action="store_true",
        help="with --entitlement: also kill live sessions/tokens (critical removals, §7.7)",
    )
    args = parser.parse_args()

    with psycopg.connect(build_dsn()) as conn:
        if args.all_auth:
            revoke_all_user_auth(conn, args.user_id, actor=args.actor, reason=args.reason)
            print(f"all live sessions/tokens revoked for user {args.user_id}")
        else:
            revoke_entitlement(
                conn,
                args.user_id,
                args.entitlement,
                revoke_sessions=args.revoke_sessions,
                actor=args.actor,
                reason=args.reason,
            )
            suffix = " and live sessions/tokens revoked" if args.revoke_sessions else ""
            print(f"entitlement {args.entitlement} revoked for user {args.user_id}{suffix}")


if __name__ == "__main__":
    main()
