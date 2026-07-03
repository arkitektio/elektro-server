# syntax=docker/dockerfile:1
# ---- builder: pure wheels (py-ubjson, pulled via daphne→autobahn, falls back to
#      pure Python when no compiler is present, so no toolchain is needed) ----
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /workspace
# Dependency layer — cached until pyproject.toml / uv.lock change:
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
# Project layer:
COPY . .
RUN uv sync --frozen --no-dev

# ---- runtime: slim base + prebuilt venv; no compiler, psycopg[binary] bundles libpq ----
FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /workspace
COPY --from=builder /opt/venv /opt/venv
COPY . .
