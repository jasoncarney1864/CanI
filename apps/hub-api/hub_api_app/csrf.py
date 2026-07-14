"""Double-submit-cookie CSRF protection for hub-api's cookie-authenticated endpoints
(§7.9/§14.8). The session cookie is HttpOnly; this token is a separate, readable cookie
that the browser client must echo back in a header on state-changing requests."""

from __future__ import annotations

import hmac
import secrets

from fastapi import HTTPException, Request, status

CSRF_COOKIE_NAME = "cani_csrf"
CSRF_HEADER_NAME = "x-cani-csrf-token"


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def verify_csrf(request: Request) -> None:
    cookie_value = request.cookies.get(CSRF_COOKIE_NAME)
    header_value = request.headers.get(CSRF_HEADER_NAME)
    if not cookie_value or not header_value or not hmac.compare_digest(cookie_value, header_value):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")
