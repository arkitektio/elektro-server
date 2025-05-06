FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y gcc libffi-dev libpq-dev
# Install App
RUN mkdir /workspace
ADD . /workspace
WORKDIR /workspace
RUN uv sync


