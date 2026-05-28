from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    jwt_secret: SecretStr = SecretStr("dev-jwt-secret-change-me")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    modelserver_url: str = "http://modelserver:8020"
    guardrails_url: str = "http://guardrails:8010"
    service_auth_token: SecretStr = SecretStr("dev-service-token")

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
    gemini_model: str = "gemini-2.0-flash"
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


settings = Settings()
