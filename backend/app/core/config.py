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

    gemini_api_key: SecretStr = SecretStr("dev-gemini-key-change-me")
    gemini_model: str = "gemini-2.0-flash"
    gemini_embedding_model: str = "text-embedding-004"
    agent_max_iterations: int = 5
    agent_max_tokens_per_turn: int = 1024
    retrieval_top_k: int = 5
    reranker_candidate_k: int = 20


settings = Settings()
