"""LiveAvatar (HeyGen) session-token exchange (docs_api_app/liveavatar.py). The HTTP call
is mocked throughout — this must never make a real request to LiveAvatar, and never uses
a real API key (CLAUDE.md: LIVEAVATAR_API_KEY is a real secret in the user's local .env
and must never appear in test fixtures or output)."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from docs_api_app import liveavatar

_FAKE_API_KEY = "fake-test-key-not-real"
_FAKE_AVATAR_ID = "3c90c3cc-0d44-4b50-8888-8dd25736052a"


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json


class _FakeAsyncClient:
    def __init__(self, calls, *, response=None, raise_exc=None):
        self._calls = calls
        self._response = response
        self._raise_exc = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, headers, json):
        self._calls.append({"url": url, "headers": headers, "json": json})
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._response


def _patch_client(monkeypatch, *, response=None, raise_exc=None):
    calls = []
    monkeypatch.setattr(
        liveavatar.httpx,
        "AsyncClient",
        lambda *a, **k: _FakeAsyncClient(calls, response=response, raise_exc=raise_exc),
    )
    return calls


def _run(coro):
    return asyncio.run(coro)


def test_success_returns_session_token(monkeypatch):
    response = _FakeResponse(
        200, {"code": 100, "data": {"session_id": "s-1", "session_token": "tok-abc"}, "message": "ok"}
    )
    calls = _patch_client(monkeypatch, response=response)

    token = _run(liveavatar.create_session_token(api_key=_FAKE_API_KEY, avatar_id=_FAKE_AVATAR_ID))

    assert token == "tok-abc"
    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.liveavatar.com/v1/sessions/token"
    assert calls[0]["headers"]["X-API-KEY"] == _FAKE_API_KEY
    assert calls[0]["json"] == {"mode": "LITE", "avatar_id": _FAKE_AVATAR_ID}


def test_non_200_status_raises_liveavatar_error(monkeypatch):
    response = _FakeResponse(401, {"code": 401, "message": "invalid api key"})
    _patch_client(monkeypatch, response=response)

    with pytest.raises(liveavatar.LiveAvatarError, match="401"):
        _run(liveavatar.create_session_token(api_key="bad-key", avatar_id=_FAKE_AVATAR_ID))


def test_missing_session_token_field_raises_liveavatar_error(monkeypatch):
    response = _FakeResponse(200, {"code": 100, "data": {"session_id": "s-1"}, "message": "ok"})
    _patch_client(monkeypatch, response=response)

    with pytest.raises(liveavatar.LiveAvatarError, match="session_token"):
        _run(liveavatar.create_session_token(api_key=_FAKE_API_KEY, avatar_id=_FAKE_AVATAR_ID))


def test_empty_session_token_raises_liveavatar_error(monkeypatch):
    response = _FakeResponse(
        200, {"code": 100, "data": {"session_id": "s-1", "session_token": ""}, "message": "ok"}
    )
    _patch_client(monkeypatch, response=response)

    with pytest.raises(liveavatar.LiveAvatarError, match="empty"):
        _run(liveavatar.create_session_token(api_key=_FAKE_API_KEY, avatar_id=_FAKE_AVATAR_ID))


def test_network_error_raises_liveavatar_error(monkeypatch):
    _patch_client(monkeypatch, raise_exc=httpx.ConnectError("boom"))

    with pytest.raises(liveavatar.LiveAvatarError, match="request to LiveAvatar failed"):
        _run(liveavatar.create_session_token(api_key=_FAKE_API_KEY, avatar_id=_FAKE_AVATAR_ID))
