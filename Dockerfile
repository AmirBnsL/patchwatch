FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src ./src
COPY README.md ./

RUN uv sync --no-dev --frozen

ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-m", "patchwatch", "--help"]