"""OIDC flow security tests (hub_api_app.oidc) — every rejection path that protects the
login: bad signature, wrong audience/issuer, expiry, nonce replay, state CSRF, and
flow-cookie tampering. Tokens are RS256-signed with a locally generated key; no network
or live tenant involved.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from hub_api_app.oidc import (
    OidcError,
    create_flow_state,
    validate_id_token,
    verify_flow_state,
)

SESSION_SECRET = "unit-test-session-secret-0123456789abcdef"
CLIENT_ID = "11111111-2222-3333-4444-555555555555"
ISSUER = "https://caniauth.ciamlogin.com/tenant-id/v2.0"


@pytest.fixture(scope="module")
def rsa_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def _make_id_token(private_key, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "pairwise-sub-value",
        "oid": "object-id-123",
        "tid": "tenant-id",
        "nonce": "expected-nonce",
        "exp": now + 600,
        "iat": now,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private_key, algorithm="RS256")


# --- ID token validation -----------------------------------------------------------


def test_valid_token_returns_tenant_scoped_oid_subject(rsa_keys):
    private_key, public_key = rsa_keys
    token = _make_id_token(private_key)
    subject = validate_id_token(
        token, client_id=CLIENT_ID, nonce="expected-nonce", issuer=ISSUER, signing_key=public_key
    )
    assert subject == "entra:tenant-id:object-id-123"


def test_falls_back_to_sub_when_oid_missing(rsa_keys):
    private_key, public_key = rsa_keys
    token = _make_id_token(private_key, oid=None)
    subject = validate_id_token(
        token, client_id=CLIENT_ID, nonce="expected-nonce", issuer=ISSUER, signing_key=public_key
    )
    assert subject == "entra:tenant-id:pairwise-sub-value"


def test_wrong_signature_rejected(rsa_keys):
    _, public_key = rsa_keys
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = _make_id_token(other_key)
    with pytest.raises(OidcError, match="id_token rejected"):
        validate_id_token(
            token, client_id=CLIENT_ID, nonce="expected-nonce", issuer=ISSUER, signing_key=public_key
        )


def test_wrong_audience_rejected(rsa_keys):
    private_key, public_key = rsa_keys
    token = _make_id_token(private_key, aud="some-other-app")
    with pytest.raises(OidcError, match="id_token rejected"):
        validate_id_token(
            token, client_id=CLIENT_ID, nonce="expected-nonce", issuer=ISSUER, signing_key=public_key
        )


def test_wrong_issuer_rejected(rsa_keys):
    private_key, public_key = rsa_keys
    token = _make_id_token(private_key, iss="https://evil.example.com/v2.0")
    with pytest.raises(OidcError, match="id_token rejected"):
        validate_id_token(
            token, client_id=CLIENT_ID, nonce="expected-nonce", issuer=ISSUER, signing_key=public_key
        )


def test_expired_token_rejected(rsa_keys):
    private_key, public_key = rsa_keys
    token = _make_id_token(private_key, exp=int(time.time()) - 60)
    with pytest.raises(OidcError, match="id_token rejected"):
        validate_id_token(
            token, client_id=CLIENT_ID, nonce="expected-nonce", issuer=ISSUER, signing_key=public_key
        )


def test_nonce_mismatch_rejected(rsa_keys):
    private_key, public_key = rsa_keys
    token = _make_id_token(private_key, nonce="replayed-different-nonce")
    with pytest.raises(OidcError, match="nonce mismatch"):
        validate_id_token(
            token, client_id=CLIENT_ID, nonce="expected-nonce", issuer=ISSUER, signing_key=public_key
        )


def test_alg_none_token_rejected(rsa_keys):
    _, public_key = rsa_keys
    now = int(time.time())
    unsigned = jwt.encode(
        {"iss": ISSUER, "aud": CLIENT_ID, "sub": "x", "nonce": "expected-nonce", "exp": now + 600},
        key=None,
        algorithm="none",
    )
    with pytest.raises(OidcError, match="id_token rejected"):
        validate_id_token(
            unsigned, client_id=CLIENT_ID, nonce="expected-nonce", issuer=ISSUER, signing_key=public_key
        )


# --- Flow state (state/nonce/PKCE cookie) --------------------------------------------


def test_flow_state_roundtrip():
    flow_token, state, nonce, challenge = create_flow_state(session_secret=SESSION_SECRET)
    assert state and nonce and challenge
    claims = verify_flow_state(flow_token, session_secret=SESSION_SECRET, state=state)
    assert claims["nonce"] == nonce
    assert claims["cv"]  # PKCE verifier travels only inside the signed cookie


def test_flow_state_rejects_state_mismatch():
    flow_token, _, _, _ = create_flow_state(session_secret=SESSION_SECRET)
    with pytest.raises(OidcError, match="state mismatch"):
        verify_flow_state(flow_token, session_secret=SESSION_SECRET, state="attacker-chosen-state")


def test_flow_state_rejects_tampered_token():
    flow_token, state, _, _ = create_flow_state(session_secret=SESSION_SECRET)
    with pytest.raises(OidcError, match="invalid or expired"):
        verify_flow_state(flow_token, session_secret="different-secret", state=state)


def test_flow_state_rejects_wrong_purpose_token():
    # A session-shaped token signed with the same secret must not pass as flow state.
    imposter = jwt.encode(
        {"sub": "user-1", "exp": int(time.time()) + 600, "state": "s"},
        SESSION_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(OidcError, match="wrong purpose"):
        verify_flow_state(imposter, session_secret=SESSION_SECRET, state="s")
