"""Spoke-side authorization middleware: FastAPI dependencies that validate the access
token and re-check entitlement on every call, per docs/07-identity-and-access.md §7.4:
"Spokes must re-check entitlement and ownership on every API call." Hub-issued claims
are trusted only after signature+expiry verification here — never trust an unverified
token or a client-supplied user_id.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from cani_shared.auth.tokens import (
    RequestPrincipal,
    TokenError,
    verify_access_token,
)
from cani_shared.logging import get_logger

logger = get_logger(__name__)

CAN_ACCESS_DOCS = "can_access_docs"
CAN_ACCESS_LEGAL = "can_access_legal"
CAN_ACCESS_HEALTH = "can_access_health"

_bearer_scheme = HTTPBearer(auto_error=False)


def make_principal_dependency(*, token_signing_secret: str):
    """Bind the deployment's signing secret once at app startup and return a FastAPI
    dependency that resolves the caller's RequestPrincipal, denying by default."""

    async def get_principal(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    ) -> RequestPrincipal:
        if credentials is None:
            logger.warning("authz_denied", reason="missing_bearer_token")
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
        try:
            claims = verify_access_token(credentials.credentials, token_signing_secret)
        except TokenError as exc:
            logger.warning("authz_denied", reason="invalid_token", detail=str(exc))
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token") from exc
        return RequestPrincipal(user_id=claims.sub, entitlements=claims.entitlements)

    return get_principal


def require_entitlement(entitlement: str, get_principal):
    """FastAPI dependency-of-a-dependency: deny the request unless the principal holds
    the named entitlement. `get_principal` must be the output of make_principal_dependency
    so this composes into the same request-scoped principal resolution (FastAPI caches
    dependency results per request, so get_principal only runs once)."""

    def _check(principal: RequestPrincipal = Depends(get_principal)) -> RequestPrincipal:
        if not principal.has_entitlement(entitlement):
            logger.warning(
                "authz_denied",
                reason="missing_entitlement",
                entitlement=entitlement,
            )
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing entitlement: {entitlement}")
        return principal

    return _check
