"""Environment-driven configuration. No defaults for secret values — missing secrets
must fail startup loudly rather than silently falling back to something insecure.

Pydantic's "required string field" check is not enough on its own: an env file that sets
`CANI_TOKEN_SIGNING_SECRET=` (present but empty, exactly what a naive copy of
.env.example produces) satisfies `str` validation while leaving the app signing/verifying
tokens with an empty HMAC key. The validators below turn that into a hard startup failure
instead of a silent, trivially-forgeable-token vulnerability.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = Field(default="dev", alias="ENV")

    postgres_host: str = Field(alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(alias="POSTGRES_DB")
    postgres_user: str = Field(alias="POSTGRES_USER")
    postgres_password: str = Field(alias="POSTGRES_PASSWORD")

    qdrant_url: str = Field(alias="QDRANT_URL")
    qdrant_collection: str = Field(alias="QDRANT_COLLECTION")

    azure_storage_connection_string: str = Field(alias="AZURE_STORAGE_CONNECTION_STRING")

    cani_token_signing_secret: str = Field(alias="CANI_TOKEN_SIGNING_SECRET")
    cani_session_secret: str = Field(alias="CANI_SESSION_SECRET")

    azure_openai_endpoint: str = Field(default="", alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_api_key: str = Field(default="", alias="AZURE_OPENAI_API_KEY")
    azure_openai_api_version: str = Field(default="2024-10-21", alias="AZURE_OPENAI_API_VERSION")
    azure_openai_embedding_deployment: str = Field(default="", alias="AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    azure_openai_chat_deployment: str = Field(default="", alias="AZURE_OPENAI_CHAT_DEPLOYMENT")

    azure_documentintelligence_endpoint: str = Field(default="", alias="AZURE_DOCUMENTINTELLIGENCE_ENDPOINT")
    azure_documentintelligence_api_key: str = Field(default="", alias="AZURE_DOCUMENTINTELLIGENCE_API_KEY")

    retrieval_worker_url: str = Field(default="http://retrieval-worker:8003", alias="RETRIEVAL_WORKER_URL")

    @field_validator("cani_token_signing_secret", "cani_session_secret")
    @classmethod
    def _require_strong_secret(cls, value: str, info) -> str:
        if len(value) < MIN_SECRET_LENGTH:
            raise ValueError(
                f"{info.field_name} must be at least {MIN_SECRET_LENGTH} characters "
                "(got empty/short value — generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"). '
                "Refusing to start with a weak or empty signing secret."
            )
        return value

    @field_validator("postgres_password")
    @classmethod
    def _require_non_empty_db_password(cls, value: str) -> str:
        if not value:
            raise ValueError("POSTGRES_PASSWORD must not be empty.")
        return value

    @property
    def postgres_dsn(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"dbname={self.postgres_db} user={self.postgres_user} password={self.postgres_password}"
        )

    @property
    def azure_ai_providers_configured(self) -> bool:
        """False in environments (e.g. CI) where real Azure AI calls should be skipped/faked."""
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
