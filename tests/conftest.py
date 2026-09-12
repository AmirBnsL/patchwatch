"""Shared pytest configuration."""


def pytest_configure(config: object) -> None:
    # Marker declared in pyproject.toml; registering here keeps editors happy.
    config.addinivalue_line("markers", "integration: requires running Postgres")  # type: ignore[attr-defined]
