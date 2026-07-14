"""Token issuance and verification per docs/07-identity-and-access.md §7.5.

Two token types:
- Session token: long-lived (browser cookie), identifies the signed-in user to hub-api only.
- Access token: short-lived (10-15 min), carries entitlement claims, validated by every
  spoke (docs-api, retrieval-worker) on every call. Ownership filtering happens
  independently of these claims at the data layer (defense in depth, §7.4/§9.8) —
  a valid access token is necessary but never sufficient for a data read.

Dev-mode note: these are issued by hub-api's dev-login stub, not a real Entra External ID
token exchange. The claims shape and validation logic are identical to what a real Entra
flow would need, so swapping the issuer later does not change this module or its callers.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

import jwt
from pydantic import BaseModel

ACCESS_TOKEN_TTL_SECONDS = 15 * 60
SESSION_TOKEN_TTL_SECONDS = 12 * 60 * 60
ALGORITHM = "HS256"


class TokenError(Exception):
    """Base class for token validation failures. Callers must fail closed on any of these."""


class TokenExpiredError(TokenError):
    pass


class TokenInvalidError(TokenError):
    pass


class AccessTokenClaims(BaseModel):
    sub: str
    entitlements: list[str]
    auth_time: int
    exp: int
    jti: str


class SessionClaims(BaseModel):
    sub: str
    jti: str
    exp: int


def create_access_token(*, user_id: str, entitlements: list[str], secret: str, auth_time: int | None = None) -> str:
    now = int(time.time())
    claims = {
        "sub": user_id,
        "entitlements": entitlements,
        "auth_time": auth_time if auth_time is not None else now,
        "exp": now + ACCESS_TOKEN_TTL_SECONDS,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def verify_access_token(token: str, secret: str) -> AccessTokenClaims:
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("access token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError("access token invalid") from exc
    return AccessTokenClaims.model_validate(payload)


def create_session_token(*, user_id: str, secret: str) -> str:
    now = int(time.time())
    claims = {"sub": user_id, "jti": uuid.uuid4().hex, "exp": now + SESSION_TOKEN_TTL_SECONDS}
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def verify_session_token(token: str, secret: str) -> SessionClaims:
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("session expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError("session invalid") from exc
    return SessionClaims.model_validate(payload)


@dataclass
class RequestPrincipal:
    """The authenticated + entitled caller, resolved once per request by spoke middleware."""

    user_id: str
    entitlements: list[str] = field(default_factory=list)

    def has_entitlement(self, name: str) -> bool:
        return name in self.entitlements
