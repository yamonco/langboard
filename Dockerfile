FROM ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa AS uv
FROM python:3.12@sha256:7ad6d21a25a94b2c00e685e82c2fd298de814353d9ee0e3f7f2cd4fca063df60 AS base

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=on
ENV UV_HTTP_TIMEOUT=120

COPY --from=uv /uv /uvx /bin/

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        libssl-dev \
        libuv1-dev \
        tar \
    && rm -rf /var/lib/apt/lists/*

RUN uv --version

COPY ./src/shared/py ./src/shared/py
COPY pyproject.toml uv.lock README.md alembic.ini ./

RUN cd /app/src/shared/py && uv venv && uv sync --locked --no-dev
RUN cd /app && uv venv && uv sync --locked --no-dev --no-install-project

COPY ./src/api ./src/api

RUN cd /app && uv sync --locked --no-dev

FROM base AS with-document-processing

RUN cd /app && uv sync --locked --no-dev --extra document-processing

FROM base AS with-cron

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/* \
    && printf '' | crontab -
