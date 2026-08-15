"""LiveAvatar (HeyGen) session-token exchange, Lite integration mode — pure avatar
streaming, bring-your-own-LLM (we only mint the token; grounded answers still come from
retrieval-worker). Unrelated to the public-law corpus work in docs/20 despite living in
the same service; kept as its own module the way uploads.py is its own module, since
nothing else in the monorepo needs to call LiveAvatar.

Mints a short-lived session token server-side so LIVEAVATAR_API_KEY never reaches the
browser — the frontend uses the returned token to open the WebRTC avatar session directly
with LiveAvatar. Mirrors the token-remint pattern main.py already uses before calling
retrieval-worker: the raw secret stays on this side of the network boundary.

Endpoint contract confirmed against docs.liveavatar.com (2026-08-15): POST
/v1/sessions/token, `X-API-KEY` header, body `{"mode": "LITE", "avatar_id": <uuid>}`,
response `{"code": ..., "data": {"session_id": ..., "session_token": ...}, "message": ...}`.
HeyGen owns this contract, not us — reverify at
docs.liveavatar.com/api-reference/sessions/create-session-token if this ever starts
4xxing unexpectedly.
"""

from __future__ import annotations

import httpx

_SESSION_TOKEN_URL = "https://api.liveavatar.com/v1/sessions/token"
_TIMEOUT_SECONDS = 10.0


class LiveAvatarError(Exception):
    """The token-mint call to LiveAvatar failed, or returned something we can't use."""


async def create_session_token(*, api_key: str, avatar_id: str) -> str:
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        try:
            response = await client.post(
                _SESSION_TOKEN_URL,
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"mode": "LITE", "avatar_id": avatar_id},
            )
        except httpx.HTTPError as exc:
            raise LiveAvatarError(f"request to LiveAvatar failed: {exc}") from exc

    if response.status_code != 200:
        raise LiveAvatarError(f"LiveAvatar session-token request failed with status {response.status_code}")

    try:
        token = response.json()["data"]["session_token"]
    except (KeyError, TypeError, ValueError) as exc:
        raise LiveAvatarError("LiveAvatar response did not contain a session_token") from exc

    if not token:
        raise LiveAvatarError("LiveAvatar response contained an empty session_token")

    return token
