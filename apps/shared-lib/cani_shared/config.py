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
    # Empty for a local/self-hosted Qdrant with no auth; required for Qdrant Cloud.
    qdrant_api_key: str = Field(default="", alias="QDRANT_API_KEY")

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

    azure_speech_endpoint: str = Field(default="", alias="AZURE_SPEECH_ENDPOINT")
    azure_speech_api_key: str = Field(default="", alias="AZURE_SPEECH_API_KEY")
    azure_speech_region: str = Field(default="eastus2", alias="AZURE_SPEECH_REGION")

    retrieval_worker_url: str = Field(default="http://retrieval-worker:8003", alias="RETRIEVAL_WORKER_URL")

    # LiveAvatar (HeyGen) streaming avatar — voices RAG answers on the website via
    # WebRTC, Lite integration mode (bring-your-own-LLM, we only mint session tokens).
    # Free tier: 10 credits, 2 min/session, 1 concurrency, watermarked. avatar_id is
    # required by LiveAvatar's own session-token API — there's no sane default to ship,
    # pick one from the LiveAvatar dashboard (app.liveavatar.com/developers). Both unset
    # -> docs-api's /avatar/session-token endpoint returns 503 rather than crashing: no
    # fake fallback here, unlike the other providers, because a placeholder session token
    # can't open a real WebRTC session so failing loud is the only useful behavior.
    liveavatar_api_key: str = Field(default="", alias="LIVEAVATAR_API_KEY")
    liveavatar_avatar_id: str = Field(default="", alias="LIVEAVATAR_AVATAR_ID")

    @property
    def liveavatar_configured(self) -> bool:
        return bool(self.liveavatar_api_key and self.liveavatar_avatar_id)

    # Malware scanning (docs/08 §8.11). When clamav_host is set, ingestion scans each file
    # against that clamd daemon before extraction; unset, dev/CI fall back to the
    # EICAR-only scanner (see cani_shared.providers.scanner). Never leaves a document
    # unscanned — the fallback still runs, it just detects less.
    clamav_host: str = Field(default="", alias="CLAMAV_HOST")
    clamav_port: int = Field(default=3310, alias="CLAMAV_PORT")

    @property
    def clamav_configured(self) -> bool:
        return bool(self.clamav_host)

    # Rate limiting for externally reachable APIs (docs/14 §14.8). Token bucket per client:
    # capacity `rate_limit_requests`, refilled over `rate_limit_window_seconds`.
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    rate_limit_requests: int = Field(default=60, alias="RATE_LIMIT_REQUESTS")
    rate_limit_window_seconds: int = Field(default=60, alias="RATE_LIMIT_WINDOW_SECONDS")

    # Application Insights (docs/13 §13.7). Optional everywhere: when unset,
    # cani_shared.telemetry.configure_telemetry is a no-op, so local compose runs and
    # tests emit nothing to Azure. Set in dev/prod via the cani-secrets Secret.
    app_insights_connection_string: str = Field(default="", alias="APPLICATIONINSIGHTS_CONNECTION_STRING")
    # 1.0 = sample every trace (dev default, full visibility). Lower it to trim ingestion
    # cost as traffic grows (§13.7 sampling guidance, §15 cost control).
    telemetry_sampling_ratio: float = Field(default=1.0, alias="TELEMETRY_SAMPLING_RATIO")

    @property
    def telemetry_enabled(self) -> bool:
        return bool(self.app_insights_connection_string)

    # Entra External ID (hub-api only; docs/07 §7.2). Optional in dev — the dev-login
    # stub carries local auth — but hub-api refuses to start outside dev without these
    # (enforced in its lifespan, not here, since the other services never use them).
    entra_oidc_authority: str = Field(default="", alias="ENTRA_OIDC_AUTHORITY")
    entra_oidc_client_id: str = Field(default="", alias="ENTRA_OIDC_CLIENT_ID")
    entra_oidc_client_secret: str = Field(default="", alias="ENTRA_OIDC_CLIENT_SECRET")
    entra_oidc_redirect_uri: str = Field(
        default="http://localhost:8001/auth/callback", alias="ENTRA_OIDC_REDIRECT_URI"
    )

    @property
    def entra_oidc_configured(self) -> bool:
        return bool(self.entra_oidc_authority and self.entra_oidc_client_id)

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
        # Use psycopg's own conninfo builder rather than manual string formatting: it
        # correctly quotes/escapes values (e.g. passwords containing spaces or other
        # libpq-significant characters), which naive f-string concatenation does not.
        import psycopg

        return psycopg.conninfo.make_conninfo(
            host=self.postgres_host,
            port=self.postgres_port,
            dbname=self.postgres_db,
            user=self.postgres_user,
            password=self.postgres_password,
        )

    @property
    def azure_ai_providers_configured(self) -> bool:
        """False in environments (e.g. CI) where real Azure AI calls should be skipped/faked."""
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)

    # Public-law corpus (docs/20-public-law-corpus-design.md §20.9). law_fetch_enabled is
    # deliberately explicit rather than inferred from config presence — there are no
    # credentials to infer from (NRS is an unauthenticated public page), and the
    # fakes-in-prod incident (CLAUDE.md) happened precisely because an absent-config check
    # silently chose "fake" with no flag to catch in review. law_qdrant_collection empty
    # means the feature ships dark: retrieval-worker never constructs PublicLawQdrant.
    law_fetch_enabled: bool = Field(default=False, alias="CANI_LAW_FETCH_ENABLED")
    law_qdrant_collection: str = Field(default="", alias="CANI_LAW_QDRANT_COLLECTION")
    law_default_jurisdictions: str = Field(default="us-nv", alias="CANI_LAW_DEFAULT_JURISDICTIONS")


@lru_cache
def get_settings() -> Settings:
    return Settings()
