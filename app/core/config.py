"""Application configuration, loaded from environment / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- app ---
    app_name: str = "claims-doc-extractor"
    environment: str = "local"

    # --- logging ---
    log_level: str = "INFO"
    log_json: bool = True

    # --- storage / persistence ---
    database_url: str = "sqlite:///./claims.db"
    upload_dir: str = "./data/uploads"

    # --- llm interaction ---
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5"
    llm_max_attempts: int = 3
    llm_timeout_seconds: float = 60.0
    llm_max_output_tokens: int = 4096
    # When true, the LLM client returns a deterministic fake result instead of
    # calling the API. Lets the whole pipeline run offline / in CI.
    mock_llm: bool = True

    # --- pdf handling ---
    # A page yielding fewer than this many characters of embedded text is
    # treated as image-only and routed to the vision path.
    text_layer_min_chars: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()
