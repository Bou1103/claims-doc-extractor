"""Application configuration, loaded from environment / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "claims-doc-extractor"
    environment: str = "local"

    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "sqlite:///./claims.db"
    upload_dir: str = "./data/uploads"

    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5"
    llm_max_attempts: int = 3
    llm_timeout_seconds: float = 60.0
    llm_max_output_tokens: int = 4096
    llm_max_reasks: int = 1  # re-asks with validation feedback before failing the job

    text_layer_min_chars: int = 100  # below this, a page is treated as image-only


@lru_cache
def get_settings() -> Settings:
    return Settings()
