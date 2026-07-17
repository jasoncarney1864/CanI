"""D2 revocation semantics (docs/07 §7.7): tokens/sessions issued at or before the
user's revocation epoch must die, new ones issued after must live, and legacy tokens
without an iat claim must fail closed once any revocation exists.
"""

import time

import pytest
from cani_shared.auth import entitlements as ent_mod
from cani_shared.auth.entitlements import (
    is_issued_before_revocation,
    make_principal_dependency,
)
from cani_shared.auth.tokens import (
    create_access_token,
    create_session_token,
    verify_access_token,
    verify_session_token,
)
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

SECRET = "unit-test-secret-0123456789abcdef-xyz"


# --- boundary truth table ---------------------------------------------------------


@pytest.mark.parametrize(
    ("iat", "epoch", "expected"),
    [
        (100, None, False),  # never revoked
        (100, 99, False),  # issued after revocation — lives
        (100, 100, True),  # same-second boundary — dies (deliberate <=)
        (100, 101, True),  # issued before revocation — dies
        (0, 5, True),  # legacy token without iat — fails closed
        (0, None, False),  # legacy token, user never revoked — lives
    ],
)
def test_is_issued_before_revocation(iat, epoch, expected):
    assert is_issued_before_revocation(iat, epoch) is expected


# --- tokens carry iat -------------------------------------------------------------


def test_access_and_session_tokens_carry_iat():
    now = int(time.time())
    access = verify_access_token(create_access_token(user_id="u1", entitlements=[], secret=SECRET), SECRET)
    session = verify_session_token(create_session_token(user_id="u1", secret=SECRET), SECRET)
    assert abs(access.iat - now) <= 2
    assert abs(session.iat - now) <= 2


# --- principal dependency enforces the epoch --------------------------------------


class _FakeConn:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakePool:
    def connection(self):
        return _FakeConn()


@pytest.fixture
def revocation_app(monkeypatch):
    """App whose principal dependency runs the real revocation code path against a
    monkeypatched pool + epoch lookup."""
    state = {"epoch": None}

    monkeypatch.setattr("cani_shared.db.pool.get_pool", lambda dsn: _FakePool())
    monkeypatch.setattr(
        "cani_shared.db.repositories.get_auth_revoked_epoch", lambda conn, user_id: state["epoch"]
    )

    get_principal = make_principal_dependency(token_signing_secret=SECRET, postgres_dsn="fake-dsn")
    app = FastAPI()

    @app.get("/protected")
    def protected(principal=Depends(get_principal)):
        return {"user_id": principal.user_id}

    return TestClient(app), state


def test_valid_token_allowed_when_never_revoked(revocation_app):
    client, state = revocation_app
    state["epoch"] = None
    token = create_access_token(user_id="u1", entitlements=[], secret=SECRET)
    assert client.get("/protected", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_preexisting_token_rejected_after_revocation(revocation_app):
    client, state = revocation_app
    token = create_access_token(user_id="u1", entitlements=[], secret=SECRET)
    state["epoch"] = int(time.time()) + 5  # revocation stamped after issuance
    response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert "revoked" in response.json()["detail"]


def test_token_issued_after_revocation_allowed(revocation_app):
    client, state = revocation_app
    state["epoch"] = int(time.time()) - 60  # old revocation
    token = create_access_token(user_id="u1", entitlements=[], secret=SECRET)
    assert client.get("/protected", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_dependency_without_dsn_skips_revocation_lookup(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("revocation lookup must not run without a dsn")

    monkeypatch.setattr("cani_shared.db.pool.get_pool", _boom)
    get_principal = make_principal_dependency(token_signing_secret=SECRET)
    app = FastAPI()

    @app.get("/protected")
    def protected(principal=Depends(get_principal)):
        return {"user_id": principal.user_id}

    token = create_access_token(user_id="u1", entitlements=[], secret=SECRET)
    assert TestClient(app).get("/protected", headers={"Authorization": f"Bearer {token}"}).status_code == 200


# keep a reference so linters see the module import used for monkeypatch targets
_ = ent_mod
