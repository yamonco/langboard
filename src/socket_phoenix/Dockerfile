ARG ELIXIR_IMAGE=hexpm/elixir:1.19.5-erlang-28.5.0.5-debian-bookworm-20260824-slim@sha256:6eed5992d974265841fd43857e21236d3c5a700de70caaff234b74f6682921fd
ARG RUNTIME_IMAGE=debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171

FROM ${ELIXIR_IMAGE} AS build

ENV MIX_ENV=prod
WORKDIR /app/socket_phoenix

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

RUN mix local.hex --force && mix local.rebar --force

COPY socket_phoenix/mix.exs socket_phoenix/mix.lock ./
RUN mix deps.get --only prod && mix deps.compile

COPY socket_phoenix/config ./config
COPY socket_phoenix/lib ./lib
COPY socket_phoenix/rel ./rel
COPY shared/realtime /app/shared/realtime

RUN mix compile --warnings-as-errors && mix release

FROM ${RUNTIME_IMAGE} AS runtime

ARG PROJECT_NAME=langboard

LABEL com.docker.compose.project=${PROJECT_NAME}

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl libncurses6 libstdc++6 openssl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system langboard \
    && useradd --system --gid langboard --home-dir /app langboard

WORKDIR /app

COPY --from=build --chown=langboard:langboard /app/socket_phoenix/_build/prod/rel/langboard_socket ./

ENV HOME=/app \
    LANG=C.UTF-8 \
    OTEL_SERVICE_NAME=langboard-socket \
    PHX_SERVER=true \
    PORT=5690

USER langboard

EXPOSE 5690

HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=12 \
    CMD curl --fail --silent --show-error --max-time 2 http://127.0.0.1:5690/health || exit 1

ENTRYPOINT ["/app/bin/langboard_socket"]
CMD ["start"]
