"""Environment-driven configuration. No defaults for secret values — missing secrets
must fail startup loudly rather than silently falling back to something insecure."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
