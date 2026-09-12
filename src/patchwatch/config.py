"""Application settings.

All model/embedding/dimension/DB pins live here so a model change is a config
change, and re-running the eval suite is the only required follow-up.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, sourced from environment / ``.env``."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://patchwatch:patchwatch@localhost:5432/patchwatch"

    # Pinned embedding model + dimension. Pin BEFORE any migration that uses
    # ``vector(dim)`` — changing the dimension requires a migration.
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # Pinned LLM. Swapping this re-runs the full eval suite.
    llm_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    """Return the (cached) application settings."""
    return Settings()
