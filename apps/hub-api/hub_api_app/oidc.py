"""Entra External ID OIDC — authorization code + PKCE, per docs/07 §7.2/§7.5.

hub-api is the confidential client: it redirects the browser to Entra's authorize
endpoint and exchanges the returned code server-side. Cross-request flow state
(state, nonce, PKCE verifier) travels in a short-lived signed cookie rather than
server-side storage, so hub-api stays stateless.

Every function is parameter-explicit (no Settings import) so the validation logic is
unit-testable with locally generated keys — no live tenant or network required.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlencode

import httpx
import jwt

FLOW_STATE_TTL_SECONDS = 10 * 60
_ALGORITHM = "HS256"  # for the flow-state cookie only; ID tokens are RS256 via JWKS


class OidcError(Exception):
    """Any failure in the OIDC flow. Callers must fail closed (reject the login)."""


@dataclass(frozen=True)
class ProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


@lru_cache(maxsize=4)
def discover(authority: str) -> ProviderMetadata:
    """Fetch and cache the provider's OIDC discovery document."""
    response = httpx.get(f"{authority}/.well-known/openid-configuration", timeout=10.0)
    response.raise_for_status()
    doc = response.json()
    return ProviderMetadata(
        issuer=doc["issuer"],
        authorization_endpoint=doc["authorization_endpoint"],
        token_endpoint=doc["token_endpoint"],
        jwks_uri=doc["jwks_uri"],
    )


@lru_cache(maxsize=4)
def _jwk_client(jwks_uri: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_uri, cache_keys=True)


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def create_flow_state(*, session_secret: str) -> tuple[str, str, str, str]:
    """Returns (signed_flow_token, state, nonce, code_challenge). The signed token is
    the only thing stored client-side; it carries everything the callback must match."""
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier, challenge = _pkce_pair()
    flow_token = jwt.encode(
        {
            "purpose": "oidc_flow",
            "state": state,
            "nonce": nonce,
            "cv": verifier,
            "exp": int(time.time()) + FLOW_STATE_TTL_SECONDS,
        },
        session_secret,
        algorithm=_ALGORITHM,
    )
    return flow_token, state, nonce, challenge


def verify_flow_state(flow_token: str, *, session_secret: str, state: str) -> dict:
    """Validates the flow cookie and that the returned `state` matches. Returns the
    claims (callers need `nonce` and `cv`)."""
    try:
        claims = jwt.decode(flow_token, session_secret, algorithms=[_ALGORITHM])
    except jwt.InvalidTokenError as exc:
        raise OidcError("login flow state invalid or expired — restart login") from exc
    if claims.get("purpose") != "oidc_flow":
        raise OidcError("flow token has wrong purpose")
    if not state or not secrets.compare_digest(claims.get("state", ""), state):
        raise OidcError("state mismatch — possible CSRF, login rejected")
    return claims


def build_authorize_url(
    *, authority: str, client_id: str, redirect_uri: str, state: str, nonce: str, code_challenge: str
) -> str:
    metadata = discover(authority)
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{metadata.authorization_endpoint}?{urlencode(params)}"


def exchange_code(
    *,
    authority: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    code_verifier: str,
) -> str:
    """Exchanges the authorization code for tokens; returns the raw ID token."""
    metadata = discover(authority)
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "scope": "openid profile email",
    }
    if client_secret:
        data["client_secret"] = client_secret
    response = httpx.post(metadata.token_endpoint, data=data, timeout=15.0)
    if response.status_code != 200:
        # Entra error bodies can include user-correlatable detail; log-side only.
        raise OidcError(f"token exchange failed with status {response.status_code}")
    id_token = response.json().get("id_token")
    if not id_token:
        raise OidcError("token response contained no id_token")
    return id_token


def validate_id_token(
    id_token: str,
    *,
    client_id: str,
    nonce: str,
    issuer: str,
    signing_key=None,
    jwks_uri: str = "",
) -> tuple[str, str | None]:
    """Full ID-token validation: RS256 signature (via JWKS unless a key is injected for
    tests), audience, issuer, expiry, and nonce. Returns (idp_subject, display_name).

    Uses `oid` (tenant-global object id) over `sub` (pairwise per app) so a future
    second client app maps to the same CanI user — docs/07 §7.3.

    Display name extracted from claims in priority order: preferred_username, email, name.
    """
    key = signing_key
    if key is None:
        if not jwks_uri:
            raise OidcError("no signing key source provided")
        key = _jwk_client(jwks_uri).get_signing_key_from_jwt(id_token).key
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.InvalidTokenError as exc:
        raise OidcError(f"id_token rejected: {exc}") from exc

    token_nonce = claims.get("nonce", "")
    if not nonce or not secrets.compare_digest(token_nonce, nonce):
        raise OidcError("nonce mismatch — possible replay, login rejected")

    stable_id = claims.get("oid") or claims["sub"]
    tenant_id = claims.get("tid", "")
    idp_subject = f"entra:{tenant_id}:{stable_id}" if tenant_id else f"entra:{stable_id}"

    # Extract user-friendly display name from claims (priority order)
    display_name = claims.get("preferred_username") or claims.get("email") or claims.get("name")

    # Log available claims to help diagnose missing display_name
    import structlog

    log = structlog.get_logger()
    log.info(
        "id_token_claims_parsed",
        available_claims=list(claims.keys()),
        has_preferred_username=bool(claims.get("preferred_username")),
        has_email=bool(claims.get("email")),
        has_name=bool(claims.get("name")),
        extracted_display_name=display_name,
    )

    return (idp_subject, display_name)
