"""Brings up the full docker-compose dev stack once per test session and tears it down
afterward. This is the closest thing to a real "dev deployment" available without a live
AKS cluster — the same compose file docker-compose.yml used for local development.
"""

from __future__ import annotations

import os
import pathlib
import secrets
import subprocess
import time

import httpx
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
HUB_URL = "http://localhost:8001"
DOCS_URL = "http://localhost:8002"
RETRIEVAL_URL = "http://localhost:8003"

STARTUP_TIMEOUT_SECONDS = 240


def _ensure_env_file() -> None:
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        return
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    generated = example.replace("CANI_TOKEN_SIGNING_SECRET=", f"CANI_TOKEN_SIGNING_SECRET={secrets.token_urlsafe(48)}")
    generated = generated.replace("CANI_SESSION_SECRET=", f"CANI_SESSION_SECRET={secrets.token_urlsafe(48)}")
    env_path.write_text(generated, encoding="utf-8")


def _wait_healthy(url: str, timeout: int) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            response = httpx.get(f"{url}/healthz", timeout=5.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(2)
    raise TimeoutError(f"{url} did not become healthy within {timeout}s (last error: {last_error})")


@pytest.fixture(scope="session")
def docker_stack():
    if os.environ.get("CANI_SKIP_COMPOSE") == "1":
        # Allows running these tests against an already-running stack (e.g. during local
        # iteration) without paying the build/teardown cost every run.
        yield
        return

    _ensure_env_file()
    subprocess.run(["docker", "compose", "up", "-d", "--build"], cwd=REPO_ROOT, check=True)
    try:
        for url in (HUB_URL, DOCS_URL, RETRIEVAL_URL):
            _wait_healthy(url, STARTUP_TIMEOUT_SECONDS)
        yield
    finally:
        subprocess.run(["docker", "compose", "down", "-v"], cwd=REPO_ROOT, check=False)


@pytest.fixture
def hub_client():
    with httpx.Client(base_url=HUB_URL, timeout=30.0) as client:
        yield client


@pytest.fixture
def docs_client():
    with httpx.Client(base_url=DOCS_URL, timeout=60.0) as client:
        yield client


def login(hub_client: httpx.Client, idp_subject: str) -> str:
    """Full dev-mode auth flow: login -> csrf -> mint access token. Returns a bearer
    access token ready to use against docs-api, mirroring what a real browser client
    would do against hub-api after an Entra External ID sign-in."""
    login_response = hub_client.post("/auth/dev-login", json={"idp_subject": idp_subject})
    login_response.raise_for_status()

    csrf_token = hub_client.cookies.get("cani_csrf")
    token_response = hub_client.post("/auth/token", headers={"x-cani-csrf-token": csrf_token})
    token_response.raise_for_status()
    return token_response.json()["access_token"]
