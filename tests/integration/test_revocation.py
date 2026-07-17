"""D2 done-criteria proof against the real compose stack: after revocation, a user's
already-issued access token and session stop working everywhere immediately — no
waiting out the 15-minute token TTL or 12-hour session TTL — and a fresh login gets a
token without the revoked entitlement (§7.7 "effective immediately for new requests").
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time

from conftest import REPO_ROOT, login


def _read_env_value(key: str) -> str:
    for line in (pathlib.Path(REPO_ROOT) / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"')
    raise KeyError(key)


def _run_revocation_script(user_id: str) -> None:
    env = {
        **os.environ,
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": _read_env_value("POSTGRES_DB"),
        "POSTGRES_USER": _read_env_value("POSTGRES_USER"),
        "POSTGRES_PASSWORD": _read_env_value("POSTGRES_PASSWORD"),
    }
    result = subprocess.run(
        [
            sys.executable,
            str(pathlib.Path(REPO_ROOT) / "scripts" / "revoke_user_access.py"),
            "--user-id",
            user_id,
            "--entitlement",
            "can_access_docs",
            "--revoke-sessions",
            "--actor",
            "integration-test",
            "--reason",
            "D2 done-criteria verification",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, f"revocation script failed: {result.stderr}"


def test_revocation_kills_live_credentials_and_new_tokens_lose_entitlement(
    docker_stack, hub_client, docs_client
):
    token = login(hub_client, "revocation-test-user")
    headers = {"Authorization": f"Bearer {token}"}

    # Live credentials work before revocation.
    assert docs_client.get("/documents", headers=headers).status_code == 200
    assert hub_client.get("/auth/whoami").status_code == 200

    user_id = hub_client.get("/auth/whoami").json()["user_id"]
    _run_revocation_script(user_id)
    time.sleep(1.5)  # step past the same-second revocation boundary

    # The already-issued access token dies on the spoke, mid-TTL.
    assert docs_client.get("/documents", headers=headers).status_code == 401

    # The live session dies at the hub: whoami and token minting both refuse.
    assert hub_client.get("/auth/whoami").status_code == 401
    csrf = hub_client.cookies.get("cani_csrf")
    assert hub_client.post("/auth/token", headers={"x-cani-csrf-token": csrf}).status_code == 401

    # Re-login works (identity isn't dead, credentials are) — but the new token no
    # longer carries the revoked entitlement, so docs access is now 403.
    new_token = login(hub_client, "revocation-test-user")
    new_headers = {"Authorization": f"Bearer {new_token}"}
    assert docs_client.get("/documents", headers=new_headers).status_code == 403
