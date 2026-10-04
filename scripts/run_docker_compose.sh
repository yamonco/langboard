#!/bin/bash -l

case "$(uname -s)" in
    Linux*)   CURRENT_OS="linux" ;;
    Darwin*)  CURRENT_OS="mac" ;;
    CYGWIN*|MINGW*|MSYS*|Windows*) CURRENT_OS="windows" ;;
    *)        CURRENT_OS="linux" ;;
esac

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    echo Docker is not installed or not found in PATH. Please install Docker to proceed.
    if [ "$CURRENT_OS" = "linux" ]; then
        DOCKER_URL="https://docs.docker.com/desktop/setup/install/linux/"
    else
        DOCKER_URL="https://docs.docker.com/desktop/setup/install/$CURRENT_OS-install/"
    fi
    echo You can download it from $DOCKER_URL
    exit 1
fi

cd ../

if [ ! -f .env ]; then
    cp .env.example .env
fi

# Set environment variables for get-compose-args.sh
export WITH_DOCS="false"
export WITH_UI_WATCHER="false"
export WITH_OLLAMA_CPU="false"
export WITH_OLLAMA_GPU="false"

# Parse arguments to set compose options
for arg in "$@"; do
    if [[ "$arg" == "docs" ]]; then
        export WITH_DOCS="true"
    elif [[ "$arg" == "ui-watcher" ]]; then
        export WITH_UI_WATCHER="true"
    elif [[ "$arg" == "ollama-cpu" ]]; then
        export WITH_OLLAMA_CPU="true"
    elif [[ "$arg" == "ollama-gpu" ]]; then
        export WITH_OLLAMA_GPU="true"
    fi
done

make start_docker \
    WITH_DOCS="$WITH_DOCS" \
    WITH_UI_WATCHER="$WITH_UI_WATCHER" \
    WITH_OLLAMA_CPU="$WITH_OLLAMA_CPU" \
    WITH_OLLAMA_GPU="$WITH_OLLAMA_GPU" \
    WITH_OTEL=true
