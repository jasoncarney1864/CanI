"""CanI Hub API — authentication, session handling, and entitlements (docs/07).

Two login paths mint identical sessions:
- /auth/login → /auth/callback: real Entra External ID OIDC (authorization code + PKCE,
  hub_api_app.oidc). The only path outside dev.
- /auth/dev-login: local stub for dev/compose/tests; 404s outside ENV=dev.

Everything downstream (session validation, access-token minting, entitlement checks) is
shared — the IdP swap ends at the session cookie.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from cani_shared.auth.entitlements import is_issued_before_revocation
from cani_shared.auth.tokens import (
    ACCESS_TOKEN_TTL_SECONDS,
    TokenError,
    create_access_token,
    create_session_token,
    verify_session_token,
)
from cani_shared.config import get_settings
from cani_shared.db.pool import get_pool
from cani_shared.db.repositories import (
    get_auth_revoked_epoch,
    get_entitlements,
    get_or_create_user,
    get_user,
    record_audit_event,
)
from cani_shared.logging import configure_logging, get_logger, hash_user_id
from cani_shared.middleware import RateLimitMiddleware, TraceIdMiddleware
from cani_shared.telemetry import configure_telemetry, instrument_fastapi
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from hub_api_app import oidc
from hub_api_app.csrf import CSRF_COOKIE_NAME, generate_csrf_token, verify_csrf

SESSION_COOKIE_NAME = "cani_session"
OIDC_FLOW_COOKIE_NAME = "cani_oidc_flow"

configure_logging("hub-api")
logger = get_logger(__name__)
settings = get_settings()
configure_telemetry("hub-api", settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.env != "dev" and not settings.entra_oidc_configured:
        # Fail closed (§7.1 deny-by-default): outside dev there is no dev-login, so an
        # unconfigured IdP would mean a service with no working authentication at all.
        raise RuntimeError("ENTRA_OIDC_AUTHORITY/ENTRA_OIDC_CLIENT_ID must be configured when ENV != dev")
    get_pool(settings.postgres_dsn)
    yield


app = FastAPI(title="CanI Hub API", lifespan=lifespan)
app.add_middleware(TraceIdMiddleware)
instrument_fastapi(app)
# Added last -> outermost -> runs first, so abusive traffic (e.g. auth brute-forcing) is
# rejected before any downstream work or telemetry spend (§14.8).
if settings.rate_limit_enabled:
    app.add_middleware(
        RateLimitMiddleware,
        capacity=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )


def _cookie_kwargs() -> dict:
    # Secure cookies require HTTPS; dev docker-compose runs over plain HTTP on localhost.
    # This relaxation is dev-only — production behind real ingress TLS must set secure=True.
    return {"httponly": True, "secure": settings.env != "dev", "samesite": "lax"}


class DevLoginRequest(BaseModel):
    idp_subject: str


class DevLoginResponse(BaseModel):
    user_id: str
    idp_subject: str
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

    # D2 (§7.7): a session issued before the user's revocation epoch is dead even
    # though its signature and expiry are valid — revocation must not wait out the
    # 12-hour session TTL.
    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        revoked_epoch = get_auth_revoked_epoch(conn, claims.sub)
    if is_issued_before_revocation(claims.iat, revoked_epoch):
        logger.warning("session_rejected", reason="issued_before_revocation")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session revoked — sign in again")
    return claims.sub


def _establish_session(response: Response, *, idp_subject: str) -> DevLoginResponse:
    """Shared session minting for both login paths: map IdP subject to internal user,
    set session + CSRF cookies, emit the audit event."""
    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        user = get_or_create_user(conn, idp_subject)
        entitlements = get_entitlements(conn, str(user["user_id"]))
        record_audit_event(
            conn,
            event_type="auth_login_success",
            actor_user_id=str(user["user_id"]),
            detail={"idp_subject": idp_subject},
        )

    session_token = create_session_token(user_id=str(user["user_id"]), secret=settings.cani_session_secret)
    response.set_cookie(SESSION_COOKIE_NAME, session_token, **_cookie_kwargs())
    response.set_cookie(CSRF_COOKIE_NAME, generate_csrf_token(), httponly=False, samesite="lax")
    logger.info("auth_login_success", user_id_hash=hash_user_id(str(user["user_id"])))
    return DevLoginResponse(
        user_id=str(user["user_id"]), idp_subject=str(user["idp_subject"]), entitlements=entitlements
    )


@app.get("/auth/login")
def oidc_login() -> RedirectResponse:
    if not settings.entra_oidc_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "OIDC login is not configured")

    flow_token, state, nonce, challenge = oidc.create_flow_state(session_secret=settings.cani_session_secret)
    authorize_url = oidc.build_authorize_url(
        authority=settings.entra_oidc_authority,
        client_id=settings.entra_oidc_client_id,
        redirect_uri=settings.entra_oidc_redirect_uri,
        state=state,
        nonce=nonce,
        code_challenge=challenge,
    )
    response = RedirectResponse(authorize_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        OIDC_FLOW_COOKIE_NAME, flow_token, max_age=oidc.FLOW_STATE_TTL_SECONDS, **_cookie_kwargs()
    )
    return response


@app.get("/auth/callback", response_model=DevLoginResponse)
def oidc_callback(request: Request, response: Response, code: str = "", state: str = "") -> DevLoginResponse:
    if not settings.entra_oidc_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "OIDC login is not configured")
    flow_token = request.cookies.get(OIDC_FLOW_COOKIE_NAME, "")
    if not code or not flow_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing code or login flow state — restart login")

    try:
        flow = oidc.verify_flow_state(flow_token, session_secret=settings.cani_session_secret, state=state)
        id_token = oidc.exchange_code(
            authority=settings.entra_oidc_authority,
            client_id=settings.entra_oidc_client_id,
            client_secret=settings.entra_oidc_client_secret,
            redirect_uri=settings.entra_oidc_redirect_uri,
            code=code,
            code_verifier=flow["cv"],
        )
        metadata = oidc.discover(settings.entra_oidc_authority)
        idp_subject = oidc.validate_id_token(
            id_token,
            client_id=settings.entra_oidc_client_id,
            nonce=flow["nonce"],
            issuer=metadata.issuer,
            jwks_uri=metadata.jwks_uri,
        )
    except oidc.OidcError as exc:
        logger.warning("oidc_login_rejected", reason=str(exc))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login failed — restart login") from exc

    response.delete_cookie(OIDC_FLOW_COOKIE_NAME)
    return _establish_session(response, idp_subject=idp_subject)


@app.post("/auth/dev-login", response_model=DevLoginResponse)
def dev_login(payload: DevLoginRequest, response: Response) -> DevLoginResponse:
    if settings.env != "dev":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    return _establish_session(response, idp_subject=payload.idp_subject)


@app.get("/auth/whoami", response_model=DevLoginResponse)
def whoami(request: Request) -> DevLoginResponse:
    user_id = _get_session_user_id(request)
    pool = get_pool(settings.postgres_dsn)
    with pool.connection() as conn:
        user = get_user(conn, user_id)
        entitlements = get_entitlements(conn, user_id)
    return DevLoginResponse(user_id=user_id, idp_subject=user["idp_subject"], entitlements=entitlements)


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
