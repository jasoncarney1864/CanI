"""CanI Hub API — authentication, session handling, and entitlements (docs/07).

Dev-mode note: /auth/dev-login is a stub identity provider for local development. It
issues the exact same session/access-token shapes a real Entra External ID OIDC callback
would produce. Swapping in real Entra later means replacing this one router with an OIDC
authorization-code+PKCE callback handler — nothing downstream (session validation, token
minting, entitlement checks) changes.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from cani_shared.auth.tokens import (
    ACCESS_TOKEN_TTL_SECONDS,
    TokenError,
    create_access_token,
    create_session_token,
    verify_session_token,
)
from cani_shared.config import get_settings
from cani_shared.db.pool import get_pool
from cani_shared.db.repositories import get_entitlements, get_or_create_user, record_audit_event
from cani_shared.logging import configure_logging, get_logger, hash_user_id
from cani_shared.middleware import TraceIdMiddleware
from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel

from hub_api_app.csrf import CSRF_COOKIE_NAME, generate_csrf_token, verify_csrf

SESSION_COOKIE_NAME = "cani_session"

configure_logging("hub-api")
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_pool(settings.postgres_dsn)
    yield


app = FastAPI(title="CanI Hub API", lifespan=lifespan)
app.add_middleware(TraceIdMiddleware)


def _cookie_kwargs() -> dict:
    # Secure cookies require HTTPS; dev docker-compose runs over plain HTTP on localhost.
    # This relaxation is dev-only — production behind real ingress TLS must set secure=True.
    return {"httponly": True, "secure": settings.env != "dev", "samesite": "lax"}


class DevLoginRequest(BaseModel):
    idp_subject: str


class DevLoginResponse(BaseModel):
    user_id: str
    entitlements: list[str]


class TokenResponse(BaseModel):
    access_token: str
    expires_in: int


def _get_session_user_id(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no active session")
    try:
        claims = verify_session_token(token, settings.cani_session_secret)
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session invalid or expired") from exc
    return claims.sub


@app.post("/auth/dev-login", response_model=DevLoginResponse)
def dev_login(payload: DevLoginRequest, response: Response) -> DevLoginResponse:
    if settings.env != "dev":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        user = get_or_create_user(conn, payload.idp_subject)
        entitlements = get_entitlements(conn, str(user["user_id"]))
        record_audit_event(
            conn,
            event_type="auth_login_success",
            actor_user_id=str(user["user_id"]),
            detail={"idp_subject": payload.idp_subject},
        )

    session_token = create_session_token(user_id=str(user["user_id"]), secret=settings.cani_session_secret)
    response.set_cookie(SESSION_COOKIE_NAME, session_token, **_cookie_kwargs())
    response.set_cookie(CSRF_COOKIE_NAME, generate_csrf_token(), httponly=False, samesite="lax")

    logger.info("auth_login_success", user_id_hash=hash_user_id(str(user["user_id"])))
    return DevLoginResponse(user_id=str(user["user_id"]), entitlements=entitlements)


@app.get("/auth/whoami", response_model=DevLoginResponse)
def whoami(request: Request) -> DevLoginResponse:
    user_id = _get_session_user_id(request)
    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        entitlements = get_entitlements(conn, user_id)
    return DevLoginResponse(user_id=user_id, entitlements=entitlements)


@app.post("/auth/token", response_model=TokenResponse)
def issue_access_token(request: Request) -> TokenResponse:
    verify_csrf(request)
    user_id = _get_session_user_id(request)

    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        entitlements = get_entitlements(conn, user_id)
        record_audit_event(conn, event_type="access_token_issued", actor_user_id=user_id, detail={})

    token = create_access_token(
        user_id=user_id, entitlements=entitlements, secret=settings.cani_token_signing_secret
    )
    logger.info("access_token_issued", user_id_hash=hash_user_id(user_id))
    return TokenResponse(access_token=token, expires_in=ACCESS_TOKEN_TTL_SECONDS)


@app.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    verify_csrf(request)
    user_id = _get_session_user_id(request)

    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        record_audit_event(conn, event_type="auth_logout", actor_user_id=user_id, detail={})

    response.delete_cookie(SESSION_COOKIE_NAME)
    response.delete_cookie(CSRF_COOKIE_NAME)
    logger.info("auth_logout", user_id_hash=hash_user_id(user_id))
    return {"status": "logged_out"}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
