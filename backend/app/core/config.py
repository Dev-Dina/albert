from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Minimal backend service configuration."""

    model_config = SettingsConfigDict(env_prefix="ALBERT_")

    app_name: str = "albert"
    service_name: str = "backend"


settings = Settings()
