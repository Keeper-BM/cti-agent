from functools import lru_cache
from typing import Literal

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
    llm_api_key: SecretStr = SecretStr("")
    llm_timeout_seconds: float = Field(default=45, ge=5, le=60)
    llm_max_tokens: int = Field(default=2200, ge=512, le=4096)
    nvd_api_key: SecretStr = SecretStr("")
    ssh_allowed_targets: str = ""
    ssh_key_directory: str = ".data/ssh-keys"
    ssh_key_password: SecretStr = SecretStr("")
    ssh_timeout_seconds: float = Field(default=45, ge=5, le=60)
    package_cache_directory: str = ".data/package-cache"
    package_cache_mib: int = Field(default=768, ge=256, le=4096)
    gpg_binary: str = ""
    auth_mode: Literal["token", "accounts"] = "token"
    session_hours: int = Field(default=8, ge=1, le=24)
    session_cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.app_env != "development":
        raise RuntimeError("This release supports APP_ENV=development only.")
    return settings
