#!/bin/bash

# Get Docker Compose arguments based on environment variables
# Usage: source scripts/utils/get-compose-args.sh or bash scripts/utils/get-compose-args.sh

# Source utility functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/utils.sh"

# Load .env file if it exists
if [ -f .env ]; then
    source .env
fi

# Validate external postgres URLs if they are set
if [ -n "$POSTGRES_EXTERNAL_MAIN_URL" ]; then
    validate_postgres_url "$POSTGRES_EXTERNAL_MAIN_URL" "POSTGRES_EXTERNAL_MAIN_URL"

    if [ -n "$POSTGRES_EXTERNAL_REPLICA_URL" ]; then
        validate_postgres_url "$POSTGRES_EXTERNAL_REPLICA_URL" "POSTGRES_EXTERNAL_REPLICA_URL"
    fi
fi

COMPOSE_PREFIX="./docker/docker-compose"

# Base compose args (include the main compose file)
COMPOSE_ARGS="-f ${COMPOSE_PREFIX}.yaml -f ${COMPOSE_PREFIX}.kafka.yaml"

# Check if we should use external postgres (skip postgres compose files)
if [ -z "${POSTGRES_EXTERNAL_MAIN_URL}" ]; then
    COMPOSE_ARGS+=" -f ${COMPOSE_PREFIX}.pg.yaml"
fi

# Backup service is enabled by default
WITH_DB_BACKUP="${WITH_DB_BACKUP:-true}"
WITH_DB_BACKUP="${WITH_DB_BACKUP,,}"
if [ "${WITH_DB_BACKUP}" = "true" ]; then
    COMPOSE_ARGS+=" -f ${COMPOSE_PREFIX}.backup.yaml"
fi

COMPOSE_ARGS+=" -f ${COMPOSE_PREFIX}.redis.yaml -f ${COMPOSE_PREFIX}.server.yaml --env-file ./.env"

if [ "${SOCKET_OWNER:-node}" = "phoenix" ]; then
    COMPOSE_ARGS+=" -f ${COMPOSE_PREFIX}.phoenix-owner.yaml --profile socket-phoenix"
elif [ "${EDITOR_SYNC_OWNER:-node}" = "phoenix" ]; then
    COMPOSE_ARGS+=" -f ${COMPOSE_PREFIX}.phoenix-editor-owner.yaml --profile socket-phoenix"
fi

# Optional compose args
VAULT_COMPOSE_ARGS="-f ${COMPOSE_PREFIX}.vault.yaml"
DOCS_COMPOSE_ARGS="-f ${COMPOSE_PREFIX}.docs.yaml"
UI_WATCHER_COMPOSE_ARGS="-f ${COMPOSE_PREFIX}.ui-watcher.yaml"
OLLAMA_SHARED_COMPOSE_ARGS="-f ${COMPOSE_PREFIX}.ollama.shared.yaml"
OLLAMA_CPU_COMPOSE_ARGS="-f ${COMPOSE_PREFIX}.ollama.cpu.yaml ${OLLAMA_SHARED_COMPOSE_ARGS}"
OLLAMA_GPU_COMPOSE_ARGS="-f ${COMPOSE_PREFIX}.ollama.gpu.yaml ${OLLAMA_SHARED_COMPOSE_ARGS}"
OTEL_COMPOSE_ARGS="-f ${COMPOSE_PREFIX}.otel.yaml --profile socket-phoenix --profile socket-phoenix-otel"

# Append optional compose args based on environment variables
if [ "${WITH_DOCS}" = "true" ]; then
    COMPOSE_ARGS+=" ${DOCS_COMPOSE_ARGS}"
fi

if [ "${WITH_UI_WATCHER}" = "true" ]; then
    COMPOSE_ARGS+=" ${UI_WATCHER_COMPOSE_ARGS}"
fi

if [ "${WITH_OLLAMA_CPU}" = "true" ]; then
    COMPOSE_ARGS+=" ${OLLAMA_CPU_COMPOSE_ARGS}"
fi

if [ "${WITH_OLLAMA_GPU}" = "true" ]; then
    COMPOSE_ARGS+=" ${OLLAMA_GPU_COMPOSE_ARGS}"
fi

if [ "${WITH_OTEL}" = "true" ]; then
    COMPOSE_ARGS+=" ${OTEL_COMPOSE_ARGS}"
fi

# Check if vault is needed based on KEY_PROVIDER_TYPE in .env file
if [ -f .env ] && grep -q "^KEY_PROVIDER_TYPE=openbao-local" .env; then
    COMPOSE_ARGS+=" ${VAULT_COMPOSE_ARGS}"
fi

# Output the compose args
echo "${COMPOSE_ARGS}"
