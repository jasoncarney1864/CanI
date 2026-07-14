import asyncio

from cani_shared.auth.entitlements import make_principal_dependency, require_entitlement
from cani_shared.auth.tokens import RequestPrincipal, create_access_token
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

SECRET = "unit-test-secret-32-characters-long"
OTHER_SECRET = "unit-test-secret-32-characters-other"

get_principal = make_principal_dependency(token_signing_secret=SECRET)
require_docs = require_entitlement("can_access_docs", get_principal)

app = FastAPI()


@app.get("/protected")
def protected(principal: RequestPrincipal = Depends(get_principal), _=Depends(require_docs)):
    return {"user_id": principal.user_id}


async def _request_protected(headers: dict[str, str] | None = None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        return await client.get("/protected", headers=headers)


def request_protected(headers: dict[str, str] | None = None):
    return asyncio.run(_request_protected(headers=headers))


def test_missing_token_denied():
    response = request_protected()
    assert response.status_code == 401


def test_missing_entitlement_denied():
    token = create_access_token(user_id="user-1", entitlements=[], secret=SECRET)
    response = request_protected(headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_valid_entitlement_allowed():
    token = create_access_token(user_id="user-1", entitlements=["can_access_docs"], secret=SECRET)
    response = request_protected(headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"user_id": "user-1"}


def test_wrong_secret_denied():
    other_token = create_access_token(user_id="user-1", entitlements=["can_access_docs"], secret=OTHER_SECRET)
    response = request_protected(headers={"Authorization": f"Bearer {other_token}"})
    assert response.status_code == 401
