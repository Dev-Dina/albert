from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Environments treated as local/dev where a placeholder service token is allowed.
# Anything else is "non-dev" and must have a real service token configured.
_DEV_ENVS = {"local", "dev", "development", "test", "testing", "ci"}


def _is_dev_env(app_env: str) -> bool:
    return app_env.strip().lower() in _DEV_ENVS


class Settings(BaseSettings):
    """Backend configuration. Values load from environment / .env with safe defaults.

    Tests do not require a real .env: every field has a default. Secret-typed fields
    are masked in ``repr`` so settings are safe to log accidentally.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )

    app_name: str = "albert"
    app_env: str = "local"
    log_level: str = "INFO"

    database_url: str | None = None
    redis_url: str | None = None

    vault_addr: str = "http://vault:8200"
    vault_token: SecretStr = SecretStr("dev-root-token")
    vault_mount: str = "secret"
    # KV v2 path holding the runtime app-role DB credentials (e.g. "database/albert_app").
    # When set, the runtime DATABASE_URL is resolved from Vault; when unset, the
    # env DATABASE_URL is used as-is (local dev fallback). Migrations always use
    # MIGRATION_DATABASE_URL (alembic/env.py), never this.
    vault_db_secret_path: str | None = None

    jwt_secret: SecretStr = SecretStr("dev-jwt-secret-change-me")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    modelserver_url: str = "http://modelserver:8020"
    guardrails_url: str = "http://guardrails:8010"
    service_auth_token: SecretStr = SecretStr("dev-service-token")
    # KV v2 path holding the service-to-service auth token (e.g. "service/albert").
    # When set, the bearer credential the backend sends to modelserver/guardrails
    # is resolved from Vault; when unset, the env SERVICE_AUTH_TOKEN is used as-is
    # (local dev fallback). The sidecars themselves read SERVICE_AUTH_TOKEN from
    # env (platform-injected from this same secret) and do not call Vault.
    vault_service_auth_secret_path: str | None = None

    otel_enabled: bool = False
    otel_service_name: str = "albert-backend"
    otel_exporter_otlp_endpoint: str | None = None
    otel_environment: str = "local"
    otel_traces_exporter: str = "otlp"
    jaeger_ui_base_url: str = "http://localhost:16686"
    jaeger_query_base_url: str = "http://localhost:16686"

    # Widget auth (spec 001-widget-auth-admin-cicd). Restored after a prior
    # main-merge dropped them; still referenced by app.core.security and
    # app.services.widget_session_service.
    widget_session_ttl_seconds: int = 900
    widget_clock_skew_seconds: int = 60
    widget_rate_limit_per_ip_per_min: int = 30
    widget_rate_limit_per_tenant_per_min: int = 120
    widget_loader_url: str = "http://localhost:8000/widget.js"

    gemini_api_key: SecretStr = SecretStr("dev-gemini-key-change-me")
    # Backend agent/RAG runtime LLM (Owner B; used by app.adapters.llm). This is
    # NOT the Owner C classifier baseline — that is recorded separately as
    # gemini-2.5-flash-lite in training/intent_classifier/artifacts + MODEL_CARD.md
    # (precomputed; not read from this setting; never called in CI). Changing this
    # value changes the live agent model.
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_embedding_model: str = "text-embedding-004"
    groq_api_key: SecretStr | None = None
    groq_model: str = "llama-3.1-8b-instant"
    agent_max_iterations: int = 5
    agent_max_tokens_per_turn: int = 1024
    retrieval_top_k: int = 5
    reranker_candidate_k: int = 20

    redis_session_ttl: int = 1800
    router_confidence_threshold: float = 0.7
    minio_endpoint: str = "minio:9000"
    minio_access_key: SecretStr = SecretStr("minioadmin")
    minio_secret_key: SecretStr = SecretStr("minioadmin")
    minio_secure: bool = False

    @model_validator(mode="after")
    def _resolve_vault_db_url(self) -> "Settings":
        """Prefer Vault for the runtime DB URL when ``vault_db_secret_path`` is set.

        No-op (no network) unless the operator opts in by setting
        ``VAULT_DB_SECRET_PATH`` — so local dev, unit tests, and CI keep using the
        plain ``DATABASE_URL`` env fallback. Resolver falls back to the env URL if
        Vault is unreachable or the secret is missing.
        """
        if self.vault_db_secret_path:
            # Deferred import avoids an import cycle (db_credentials must not import config).
            from app.core.db_credentials import resolve_database_url

            self.database_url = resolve_database_url(
                vault_addr=self.vault_addr,
                vault_token=self.vault_token.get_secret_value(),
                vault_mount=self.vault_mount,
                vault_db_secret_path=self.vault_db_secret_path,
                fallback_url=self.database_url,
            )
        return self

    @model_validator(mode="after")
    def _resolve_vault_service_auth(self) -> "Settings":
        """Prefer Vault for the service auth token when the path is configured.

        No-op (no network) unless ``VAULT_SERVICE_AUTH_SECRET_PATH`` is set, so
        local dev, unit tests, and CI keep using the env ``SERVICE_AUTH_TOKEN``.
        Falls back to the env token if Vault is unreachable or the secret is
        missing. Fails closed in non-dev environments when no token is configured
        at all (empty), so a misconfigured deploy cannot silently disable
        service-to-service auth.
        """
        if self.vault_service_auth_secret_path:
            # Deferred import keeps config import-cycle free.
            from app.core.service_credentials import resolve_service_auth_token

            resolved = resolve_service_auth_token(
                vault_addr=self.vault_addr,
                vault_token=self.vault_token.get_secret_value(),
                vault_mount=self.vault_mount,
                vault_service_auth_secret_path=self.vault_service_auth_secret_path,
                fallback_token=self.service_auth_token.get_secret_value(),
            )
            if resolved:
                self.service_auth_token = SecretStr(resolved)

        if not self.service_auth_token.get_secret_value().strip() and not _is_dev_env(self.app_env):
            raise ValueError(
                "SERVICE_AUTH_TOKEN is not configured. Set it via env or "
                "VAULT_SERVICE_AUTH_SECRET_PATH for non-dev environments."
            )
        return self


settings = Settings()
