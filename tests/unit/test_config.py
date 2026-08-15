"""Guards against the "insecure default" class of bug: an env file that sets a secret
key to an empty/short value should fail application startup, not run with a forgeable
token signing key or an empty database password.
"""

import pytest
from cani_shared.config import Settings
from pydantic import ValidationError

_VALID_BASE = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_DB": "cani",
    "POSTGRES_USER": "cani",
    "POSTGRES_PASSWORD": "a-real-password",
    "QDRANT_URL": "http://localhost:6333",
    "QDRANT_COLLECTION": "cani_docs_test",
    "AZURE_STORAGE_CONNECTION_STRING": "UseDevelopmentStorage=true",
    "CANI_TOKEN_SIGNING_SECRET": "x" * 32,
    "CANI_SESSION_SECRET": "y" * 32,
}


def _settings(**overrides) -> Settings:
    values = {**_VALID_BASE, **overrides}
    return Settings(_env_file=None, **values)


def test_valid_config_constructs():
    settings = _settings()
    assert settings.cani_token_signing_secret == "x" * 32


def test_empty_token_signing_secret_rejected():
    with pytest.raises(ValidationError, match="CANI_TOKEN_SIGNING_SECRET"):
        _settings(CANI_TOKEN_SIGNING_SECRET="")


def test_short_token_signing_secret_rejected():
    with pytest.raises(ValidationError, match="CANI_TOKEN_SIGNING_SECRET"):
        _settings(CANI_TOKEN_SIGNING_SECRET="too-short")


def test_empty_session_secret_rejected():
    with pytest.raises(ValidationError, match="CANI_SESSION_SECRET"):
        _settings(CANI_SESSION_SECRET="")


def test_empty_postgres_password_rejected():
    with pytest.raises(ValidationError, match="POSTGRES_PASSWORD"):
        _settings(POSTGRES_PASSWORD="")


def test_azure_ai_providers_not_configured_without_keys():
    settings = _settings()
    assert settings.azure_ai_providers_configured is False


def test_azure_ai_providers_configured_with_keys():
    settings = _settings(AZURE_OPENAI_ENDPOINT="https://example.openai.azure.com", AZURE_OPENAI_API_KEY="key")
    assert settings.azure_ai_providers_configured is True


def test_liveavatar_not_configured_by_default():
    settings = _settings()
    assert settings.liveavatar_configured is False


def test_liveavatar_not_configured_with_only_api_key():
    settings = _settings(LIVEAVATAR_API_KEY="fake-key-not-real")
    assert settings.liveavatar_configured is False


def test_liveavatar_not_configured_with_only_avatar_id():
    settings = _settings(LIVEAVATAR_AVATAR_ID="3c90c3cc-0d44-4b50-8888-8dd25736052a")
    assert settings.liveavatar_configured is False


def test_liveavatar_configured_with_key_and_avatar_id():
    settings = _settings(
        LIVEAVATAR_API_KEY="fake-key-not-real",
        LIVEAVATAR_AVATAR_ID="3c90c3cc-0d44-4b50-8888-8dd25736052a",
    )
    assert settings.liveavatar_configured is True
