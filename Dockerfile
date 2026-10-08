FROM ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa AS uv
FROM python:3.12@sha256:7ad6d21a25a94b2c00e685e82c2fd298de814353d9ee0e3f7f2cd4fca063df60 AS base

WORKDIR /app

ENV PIP_DISABLE_PIP_VERSION_CHECK=on
ENV UV_HTTP_TIMEOUT=120

COPY --from=uv /uv /uvx /bin/

RUN apt-get update \
    && apt-get upgrade -y \
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

RUN cd /app && uv sync --locked --no-dev --extra document-retrieval

FROM base AS with-aws

RUN cd /app && uv sync --locked --no-dev --extra aws --extra document-retrieval

FROM base AS with-azure-vault

RUN cd /app && uv sync --locked --no-dev --extra azure-vault --extra document-retrieval

FROM base AS with-document-processing

# PDF font substitution requires installed CJK glyphs, even with remote inference.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fontconfig fonts-noto-cjk \
    && fc-cache -f \
    && fc-match -f '%{family}\n' ':lang=ko' | grep -q 'Noto.*CJK' \
    && rm -rf /var/lib/apt/lists/*

RUN cd /app && uv sync --locked --no-dev --extra document-processing --extra document-retrieval

FROM base AS with-cron

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/* \
    && printf '' | crontab -

# Runtime writes stay in the dedicated application data directory.
RUN groupadd --gid 10001 langboard \
    && useradd --uid 10001 --gid 10001 --create-home langboard \
    && mkdir -p /app/local /app/.fastmcp \
    && chown -R langboard:langboard /app/local /app/.fastmcp
ENV UV_NO_SYNC=1
USER 10001:10001
