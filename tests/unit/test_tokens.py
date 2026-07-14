import time

import jwt
import pytest
from cani_shared.auth.tokens import (
    ALGORITHM,
    TokenExpiredError,
    TokenInvalidError,
    create_access_token,
    verify_access_token,
)

SECRET = "unit-test-secret-32-characters-long"
WRONG_SECRET = "unit-test-secret-wrong-value-32-chars"


def test_access_token_roundtrip():
    token = create_access_token(user_id="user-1", entitlements=["can_access_docs"], secret=SECRET)
    claims = verify_access_token(token, SECRET)
    assert claims.sub == "user-1"
    assert claims.entitlements == ["can_access_docs"]
    assert claims.jti


def test_expired_access_token_rejected():
    expired_payload = {
        "sub": "user-1",
        "entitlements": [],
        "auth_time": int(time.time()) - 1000,
        "exp": int(time.time()) - 1,
        "jti": "expired-jti",
    }
    token = jwt.encode(expired_payload, SECRET, algorithm=ALGORITHM)
    with pytest.raises(TokenExpiredError):
        verify_access_token(token, SECRET)


def test_tampered_token_rejected():
    token = create_access_token(user_id="user-1", entitlements=[], secret=SECRET)
    with pytest.raises(TokenInvalidError):
        verify_access_token(token, WRONG_SECRET)


def test_malformed_token_rejected():
    with pytest.raises(TokenInvalidError):
        verify_access_token("not-a-jwt", SECRET)
