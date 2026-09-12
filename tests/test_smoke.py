"""Smoke tests — package imports and config defaults (no DB required)."""

from patchwatch import __version__
from patchwatch.config import get_settings


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_settings_defaults() -> None:
    settings = get_settings()
    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.embedding_dim == 1536
    assert settings.llm_model == "gpt-4o-mini"
    assert "patchwatch" in settings.database_url


def test_cli_entrypoint_importable() -> None:
    import patchwatch.__main__  # noqa: F401
