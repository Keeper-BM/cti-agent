from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    dev_api_token: SecretStr = Field(min_length=32)
    database_url: str = "sqlite:///./.data/dev.db"
    worker_poll_seconds: float = Field(default=2, ge=0.1, le=60)
    supported_ubuntu_release: str = ""
    llm_base_url: str = ""
    llm_model: str = ""


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.app_env != "development":
        raise RuntimeError(
            "This starter supports local development only. Implement user auth first."
        )
    return settings
