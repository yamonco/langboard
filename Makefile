.PHONY: help init format lint start_docker stop_docker rebuild_docker update_docker clean_docker_build_cache

# Function to get compose args from script
get_compose_args = $(shell WITH_DOCS=$(WITH_DOCS) WITH_UI_WATCHER=$(WITH_UI_WATCHER) WITH_OLLAMA_CPU=$(WITH_OLLAMA_CPU) WITH_OLLAMA_GPU=$(WITH_OLLAMA_GPU) WITH_DB_BACKUP=$(WITH_DB_BACKUP) bash scripts/utils/get-compose-args.sh)

UI_DIR := src/ui
PY_CORE_DIR := src/shared/py
API_DIR := src/api
GRAPH_DIR := src/graph
SOCKET_DIR := src/socket
TS_SHARED_DIR := src/shared/ts
GREEN := \033[0;32m
RED := \033[0;31m
CYAN := \033[0;36m
DIM := \033[2m
BOLD := \033[1m
NC := \033[0m

WITH_DOCS ?= false
WITH_UI_WATCHER ?= false
WITH_OLLAMA_CPU ?= false
WITH_OLLAMA_GPU ?= false
WITH_DB_BACKUP ?= true
DOCKER_BUILD_CACHE_MAX ?= 40GB

# Get compose args from script
COMPOSE_ARGS := $(call get_compose_args)


check_tools:
	@command -v yarn >/dev/null 2>&1 || { echo >&2 "$(RED)Yarn is not installed. Aborting.$(NC)"; exit 1; }
	@command -v docker >/dev/null 2>&1 || { echo >&2 "$(RED)Docker is not installed. Aborting.$(NC)"; exit 1; }
	@command -v docker compose >/dev/null 2>&1 || { echo >&2 "$(RED)Docker Compose is not installed. Aborting.$(NC)"; exit 1; }
	@command -v pipx >/dev/null 2>&1 || { echo >&2 "$(RED)pipx is not installed. Aborting.$(NC)"; exit 1; }
	@command -v uv >/dev/null 2>&1 || { echo >&2 "$(RED)uv is not installed. Aborting.$(NC)"; exit 1; }
	@printf "$(GREEN)All required tools are installed.$(NC)"

help: ## show this help message
	@echo ''
	@printf '$(BOLD)Available targets$(NC):\n'
	@echo '----------------------------------------------------------------------'
	@grep -hE '^\S+:.*##' $(MAKEFILE_LIST) | \
	awk -F ':.*##' '{printf "$(CYAN) %s$(NC): $(DIM)%s$(NC)\n", $$1, $$2}' | \
	column -c2 -t -s :
	@echo '----------------------------------------------------------------------'
	@echo ''
	@printf 'Command: $(CYAN)$(BOLD)make <target> [options]$(NC)\n'

format: ## run code formatters
	uv run ruff check . --fix
	uv run ruff format .
	cd $(PY_CORE_DIR) && uv run ruff check . --fix
	cd $(PY_CORE_DIR) && uv run ruff format .
	cd $(GRAPH_DIR) && uv run ruff check . --fix
	cd $(GRAPH_DIR) && uv run ruff format .
	cd $(TS_SHARED_DIR) && yarn run format
	cd $(UI_DIR) && yarn run format
	cd $(SOCKET_DIR) && yarn run format

lint: ## run linters
	uv run ruff check .
	cd $(PY_CORE_DIR) && uv run ruff check .
	cd $(GRAPH_DIR) && uv run ruff check .
	cd $(TS_SHARED_DIR) && yarn run lint
	cd $(UI_DIR) && yarn run lint
	cd $(SOCKET_DIR) && yarn run lint

init: check_tools clean_python_cache clean_ts_core_cache clean_ui_cache clean_socket_cache ## initialize the project
	make install_py_core
	make install_api
	make install_graph
	make install_ts_core
	make install_ui
	make install_socket
	make init_env
	@printf "$(GREEN)All requirements are installed.$(NC)"

install_py_core: ## install the py core dependencies
	@echo 'Installing py core dependencies'
	cd $(PY_CORE_DIR) && uv venv && uv sync

install_api: ## install the api dependencies
	@echo 'Installing api dependencies'
	uv venv && uv sync

install_graph: ## install graph dependencies
	@echo 'Installing graph dependencies'
	cd $(GRAPH_DIR) && uv venv && uv sync

install_ts_core: ## install the ts core dependencies
	@echo 'Installing ts core dependencies'
	cd $(TS_SHARED_DIR) && yarn install
	cd $(TS_SHARED_DIR) && yarn run format
	cd $(TS_SHARED_DIR) && yarn run build

install_ui: ## install ui dependencies
	@echo 'Installing ui dependencies'
	cd $(UI_DIR) && yarn install
	cd $(UI_DIR) && yarn run format

install_socket: ## install socket dependencies
	@echo 'Installing socket dependencies'
	cd $(SOCKET_DIR) && yarn install
	cd $(SOCKET_DIR) && yarn run format

dev_openbao:
	@if [ -z "$$BAO_EXECUTABLE_PATH" ]; then \
		echo "$(RED)BAO_EXECUTABLE_PATH environment variable is not set. Please set it to the path of the bao executable file. Aborting.$(NC)"; \
		exit 1; \
	fi

	@if [ ! -f "$$BAO_EXECUTABLE_PATH" ]; then \
		echo "$(RED)Bao executable file not found at the specified path: $$BAO_EXECUTABLE_PATH. Please check the path and try again. Aborting.$(NC)"; \
		exit 1; \
	fi

	@ROOT_TOKEN=$$(grep "^KEY_PROVIDER_OPENBAO_ROOT_TOKEN=" .env 2>/dev/null | cut -d '=' -f2-); \
	if [ -n "$$ROOT_TOKEN" ]; then \
		echo "Starting OpenBao with custom root token from .env"; \
		$$BAO_EXECUTABLE_PATH server -dev -dev-root-token-id="$$ROOT_TOKEN"; \
	else \
		echo "Starting OpenBao with default root token"; \
		$$BAO_EXECUTABLE_PATH server -dev; \
	fi

dev_api: ## run the API in development environment
	@if grep -q "^KEY_PROVIDER_TYPE=openbao-local" .env; then \
		bash ./scripts/init-vault.sh; \
	fi

	langboard run -w

dev_ts_core_build: ## build the shared core in development environment
	cd $(TS_SHARED_DIR) && yarn run build -w

dev_ui: ## run the UI in development environment
	cd $(UI_DIR) && yarn run dev

dev_graph: ## run the Graph in development environment
	cd $(GRAPH_DIR) && uv run graph run -w


dev_socket: ## run the Socket in development environment
	cd $(SOCKET_DIR) && nodemon dist/index.js

dev_socket_build: ## build the Socket in development environment
	cd $(SOCKET_DIR) && yarn run build -w

update_ts_core:
	@cd $(UI_DIR) && yarn remove @langboard/core
	@cd $(UI_DIR) && yarn add @langboard/core@file:../shared/ts
	@cd $(SOCKET_DIR) && yarn remove @langboard/core
	@cd $(SOCKET_DIR) && yarn add @langboard/core@file:../shared/ts

start_docker: ## run Docker in the production environment
	make init_env
	mkdir -p ./docker/volumes
	make update_docker_settings
	docker compose $(COMPOSE_ARGS) up -d --build --remove-orphans
	make clean_docker_build_cache

rebuild_docker: ## run Docker in the production environment (e.g. make rebuild_docker IMAGES=image_name or IMAGES="image_name1 image_name2")
	if [ "$(IMAGES)" = "" ]; then \
		echo "$(RED)Please specify the IMAGES variable to rebuild (e.g. make rebuild_docker IMAGES=image_name or IMAGES=\"image_name1 image_name2\")$(NC)"; \
		exit 1; \
	fi

	make init_env
	mkdir -p ./docker/volumes
	make update_docker_settings
	docker compose $(COMPOSE_ARGS) up -d --build ${IMAGES} --remove-orphans
	make clean_docker_build_cache

clean_docker_build_cache: ## remove dangling images and cap unused Docker build cache
	docker image prune --force
	docker builder prune --all --force --max-used-space $(DOCKER_BUILD_CACHE_MAX)

update_docker: ## update Docker in the production environment
	make init_env
	make update_docker_settings
	docker compose $(COMPOSE_ARGS) up -d --no-deps --force-recreate --remove-orphans

stop_docker: ## stop Docker in the production environment
	docker compose $(COMPOSE_ARGS) down --rmi all --volumes --remove-orphans

unit_tests: ## run unit tests
	uv run pytest $(API_DIR)/tests

cov_unit_tests: ## run unit tests with coverage
	uv run pytest -vv --cov=$(API_DIR)/langboard $(API_DIR)/tests --cov-report=html:./$(API_DIR)/coverage
	@printf "$(GREEN)Coverage report generated in $(API_DIR)/coverage directory.$(NC)"

init_env: ## initialize the .env file from .env.example if it does not exist
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
	fi
	@if [ ! -d ./docker/volumes ]; then \
		mkdir -p ./docker/volumes; \
	fi
	@if [ ! -f ./docker/volumes/.vault-credentials ]; then \
		touch ./docker/volumes/.vault-credentials; \
	fi
	@if [ ! -f ./docker/volumes/vault-secret.json ]; then \
		touch ./docker/volumes/vault-secret.json; \
	fi

update_docker_settings: ## update Docker settings
	bash ./scripts/utils/update-docker-envs.sh

clean_python_cache: ## clean Python cache
	@echo "Cleaning Python cache..."
	find . -not -path "*/.venv/*" -type d -name '__pycache__' -exec rm -r {} +
	find . -not -path "*/.venv/*" -type f -name '*.py[cod]' -exec rm -f {} +
	find . -not -path "*/.venv/*" -type f -name '*~' -exec rm -f {} +
	find . -not -path "*/.venv/*" -type f -name '.*~' -exec rm -f {} +
	rm -rf ./.venv $(PY_CORE_DIR)/.venv $(API_DIR)/.venv $(GRAPH_DIR)/.venv
	@printf "$(GREEN)Python cache cleaned.$(NC)"

clean_ts_core_cache: ## clean Yarn cache
	@echo "Cleaning ts core cache..."
	cd $(TS_SHARED_DIR) && yarn cache clean --force
	rm -rf $(TS_SHARED_DIR)/node_modules $(TS_SHARED_DIR)/dist $(TS_SHARED_DIR)/.rollup.cache
	@printf "$(GREEN)Yarn cache and ts core directories cleaned.$(NC)"

clean_ui_cache: ## clean Yarn cache
	@echo "Cleaning ui cache..."
	cd $(UI_DIR) && yarn cache clean --force
	rm -rf $(UI_DIR)/node_modules $(UI_DIR)/build
	@printf "$(GREEN)Yarn cache and ui directories cleaned.$(NC)"

clean_socket_cache: ## clean Socket cache
	@echo "Cleaning socket cache..."
	cd $(SOCKET_DIR) && yarn cache clean --force
	rm -rf $(SOCKET_DIR)/node_modules $(SOCKET_DIR)/dist $(SOCKET_DIR)/.rollup.cache
	@printf "$(GREEN)Socket cache and directories cleaned.$(NC)"
