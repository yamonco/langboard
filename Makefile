.PHONY: help init format lint start_docker stop_docker rebuild_docker update_docker clean_docker_images clean_docker_build_cache bootstrap_socket_phoenix_group require_socket_phoenix_group validate_socket_phoenix_cutover_evidence check_socket_phoenix_cutover check_socket_phoenix_otel record_socket_phoenix_otel_soak prepare_socket_phoenix_otel prepare_socket_phoenix_owner start_socket_phoenix_canary stop_socket_phoenix_canary test_broadcast_kafka test_socket_phoenix_kafka test_socket_phoenix_dlq_recovery test_socket_phoenix_cluster test_socket_phoenix_browser_cluster test_socket_phoenix_browser_attachment test_socket_phoenix_browser_attachment_process_loss test_socket_phoenix_browser_reconnect_stability test_socket_phoenix_editor_ai_browser test_socket_phoenix_editor_ai_approve_browser test_socket_phoenix_editor_ai_reject_browser test_socket_phoenix_editor_ai_copilot_browser test_socket_phoenix_editor_ai_revocation_browser test_socket_phoenix_editor_ai_cancel_browser test_socket_phoenix_editor_ai_socket_reconnect_browser test_socket_phoenix_editor_ai_worker_loss_browser test_socket_phoenix_editor_ai_node_loss_browser test_socket_phoenix_editor_sync_reconnect_browser test_socket_phoenix_editor_cluster test_socket_protocol_parity

# Function to get compose args from script
ifeq ($(ComSpec),)
get_compose_args = $(shell WITH_DOCS=$(WITH_DOCS) WITH_UI_WATCHER=$(WITH_UI_WATCHER) WITH_OLLAMA_CPU=$(WITH_OLLAMA_CPU) WITH_OLLAMA_GPU=$(WITH_OLLAMA_GPU) WITH_OTEL=$(WITH_OTEL) WITH_DB_BACKUP=$(WITH_DB_BACKUP) bash scripts/utils/get-compose-args.sh)
else
get_compose_args = $(shell powershell -NoProfile -ExecutionPolicy Bypass -File scripts/utils/get-compose-args.ps1 -WithDocs $(WITH_DOCS) -WithUiWatcher $(WITH_UI_WATCHER) -WithOllamaCpu $(WITH_OLLAMA_CPU) -WithOllamaGpu $(WITH_OLLAMA_GPU) -WithOtel $(WITH_OTEL) -WithDbBackup $(WITH_DB_BACKUP))
endif

UI_DIR := src/ui
PY_CORE_DIR := src/shared/py
API_DIR := src/api
GRAPH_DIR := src/graph
SOCKET_DIR := src/socket
SOCKET_PHOENIX_DIR := src/socket_phoenix
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
WITH_OTEL ?= false
WITH_DB_BACKUP ?= true
DOCKER_BUILD_CACHE_MAX ?= 40GB
PHOENIX_CUTOVER_EDITOR_MANIFEST ?=
PHOENIX_CUTOVER_OTEL_SOAK_REPORT ?=
PHOENIX_OTEL_SOAK_THRESHOLDS ?=
PHOENIX_OTEL_SOAK_LOAD_PROFILE ?=
PHOENIX_OTEL_SOAK_REPORT ?=
PHOENIX_OTEL_SOAK_DURATION_SECONDS ?= 86400
PHOENIX_OTEL_SOAK_WARMUP_SECONDS ?= 3600
PHOENIX_OTEL_SOAK_SAMPLE_INTERVAL_SECONDS ?= 10
SOCKET_PHOENIX_OTEL_COLLECTOR_IMAGE ?= otel/opentelemetry-collector-contrib:0.161.0
SOCKET_PHOENIX_OTEL_COLLECTOR_DIGEST ?= sha256:fd328de2552466ad78385e1b1289c3f2402b1c45f265b252aab1955b42845ac1

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

install_socket_phoenix: ## install Phoenix socket dependencies
	cd $(SOCKET_PHOENIX_DIR) && mix deps.get

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

dev_socket_phoenix: ## run the Phoenix socket migration runtime on port 5691
	cd $(SOCKET_PHOENIX_DIR) && PORT=5691 mix phx.server

test_socket_phoenix: ## verify the isolated Phoenix migration runtime and shared contract
	uv run python scripts/test-phoenix-config.py "$(SHELL)"
	uv run pytest -q scripts/test_phoenix_cutover.py
	uv run ruff check scripts/test_phoenix_cutover.py
	uv run ruff format --check scripts/bootstrap-phoenix-kafka-group.py scripts/check-phoenix-cutover.py scripts/test_phoenix_cutover.py
	$(SHELL) -n scripts/test-phoenix-browser-cluster.sh
	node --check scripts/test-phoenix-browser-ui.cjs
	node --check scripts/test-phoenix-editor-ai-ui.cjs
	uv run ruff check scripts/test-phoenix-browser-fixture.py scripts/test-phoenix-board-chat-inspect.py scripts/test-phoenix-editor-ai-inspect.py scripts/test-phoenix-browser-graph.py
	uv run ruff format --check scripts/test-phoenix-browser-fixture.py scripts/test-phoenix-board-chat-inspect.py scripts/test-phoenix-editor-ai-inspect.py scripts/test-phoenix-browser-graph.py
	cd $(SOCKET_PHOENIX_DIR) && mix format --check-formatted
	cd $(SOCKET_PHOENIX_DIR) && mix compile --warnings-as-errors
	cd $(SOCKET_PHOENIX_DIR) && mix test
	cd $(SOCKET_PHOENIX_DIR) && mix deps.unlock --check-unused
	cd $(TS_SHARED_DIR) && yarn test
	cd $(SOCKET_DIR) && yarn test
	cd $(SOCKET_DIR) && node scripts/verify-yjs-phoenix-interop.mjs
	cd $(SOCKET_DIR) && yarn eslint scripts/verify-yjs-phoenix-interop.mjs
	cd $(SOCKET_DIR) && yarn tsc -p tsconfig.json --noEmit
	cd $(SOCKET_DIR) && yarn eslint src/events/Ollama.ts src/core/server/EventManager.ts src/core/server/SocketClient.ts src/core/server/SocketManager.ts src/core/server/Subscription.ts
	cd $(SOCKET_DIR) && yarn eslint src/core/ai/requests/DefaultRequest.ts
	cd $(SOCKET_DIR) && yarn eslint src/events/Editor.ts
	cd $(SOCKET_DIR) && yarn eslint src/bots/EditorChatBot.ts src/bots/EditorCopilotBot.ts
	cd $(UI_DIR) && yarn tsc -p tsconfig.app.json --noEmit
	cd $(UI_DIR) && yarn tsc -p tsconfig.node.json --noEmit
	cd $(UI_DIR) && yarn prettier --check ../../scripts/test-phoenix-browser-ui.cjs ../../scripts/test-phoenix-editor-ai-ui.cjs
	cd $(UI_DIR) && yarn test:board-chat-store
	cd $(UI_DIR) && node --experimental-strip-types src/components/Editor/prepareRichDraftPatch.test.ts
	cd $(UI_DIR) && yarn eslint src/pages/SettingsPage/OllamaPage.tsx src/pages/SettingsPage/components/ollama/OllamaPullModelButton.tsx src/pages/SettingsPage/components/ollama/OllamaModelTracker.tsx src/controllers/api/settings/ollama/usePullOllamaModel.ts src/controllers/api/settings/ollama/useGetOllamaModelPulls.ts src/controllers/api/settings/ollama/useGetOllamaModelList.ts src/core/constants/OllamaModelPull.ts src/core/stores/OllamaModelStore.ts
	cd $(UI_DIR) && yarn eslint src/pages/BoardPage/components/chat/ChatInput.tsx src/controllers/socket/board/chat/useBoardChatSentHandlers.ts src/core/providers/BoardChatProvider.tsx src/controllers/api/board/chat/useGetProjectChatRun.ts src/core/constants/BoardChatRun.ts src/core/stores/BoardChatStore.ts src/core/stores/BoardChatStore.test.ts
	cd $(UI_DIR) && yarn eslint src/components/Editor/plate-editor.tsx src/components/Editor/useChat.tsx src/components/Editor/plugins/copilot-kit.tsx src/controllers/socket/shared/useEditorAIRunStatusHandlers.ts src/core/constants/InternalBotRun.ts src/core/models/GraphApprovalRequestModel.ts
	uv run ruff check $(API_DIR)/langboard/middlewares/CollaborativeEditMiddleware.py $(API_DIR)/langboard/routes/auth/SocketAuthApi.py $(API_DIR)/langboard/routes/auth/SocketAuthorization.py $(API_DIR)/langboard/routes/auth/forms/Socket.py $(API_DIR)/langboard/routes/auth/forms/__init__.py $(API_DIR)/langboard/routes/editor/EditorSyncApi.py $(API_DIR)/langboard/routes/editor/EditorSyncPayload.py $(API_DIR)/langboard/routes/notification/NotificationApi.py $(API_DIR)/tests/runtime/test_board_chat_availability.py $(API_DIR)/tests/runtime/test_broadcast_envelope.py $(API_DIR)/tests/runtime/test_broker_registration.py $(API_DIR)/tests/runtime/test_collaborative_edit_middleware.py $(API_DIR)/tests/runtime/test_editor_sync_rich_patch.py $(API_DIR)/tests/runtime/test_notification_commands.py $(API_DIR)/tests/runtime/test_realtime_contract.py $(API_DIR)/tests/runtime/test_socket_auth.py $(PY_CORE_DIR)/langboard_shared/Env.py $(PY_CORE_DIR)/langboard_shared/core/broadcast/DispatcherModel.py $(PY_CORE_DIR)/langboard_shared/core/broadcast/kafka/KafkaDispatcherQueue.py $(PY_CORE_DIR)/langboard_shared/core/broker/Broker.py $(PY_CORE_DIR)/langboard_shared/domain/services/factory/GraphApprovalRequestService.py $(PY_CORE_DIR)/langboard_shared/domain/services/factory/ProjectService.py scripts/bootstrap-phoenix-kafka-group.py scripts/check-phoenix-cutover.py scripts/create-socket-protocol-credentials.py scripts/test-broadcast-kafka.py scripts/test-phoenix-kafka-ingress.py scripts/test-phoenix-kafka-dlq-recovery.py scripts/test-phoenix-cluster-reconnect.py scripts/test-phoenix-cluster-topics.py scripts/test-socket-protocol.py
	uv run pytest -q $(API_DIR)/tests/runtime/test_broker_registration.py
	uv run ruff check $(API_DIR)/langboard/commands/EditorSyncNameInventoryCommand.py $(API_DIR)/tests/runtime/test_editor_sync_name_inventory.py scripts/editor_sync_name_inventory.py
	uv run pytest -q $(API_DIR)/tests/runtime/test_editor_sync_name_inventory.py
	uv run ruff check $(API_DIR)/langboard/commands/ValidatePhoenixCutoverEvidenceCommand.py $(API_DIR)/tests/runtime/test_phoenix_cutover_evidence.py scripts/test_phoenix_otel_soak.py
	uv run pytest -q $(API_DIR)/tests/runtime/test_phoenix_cutover_evidence.py scripts/test_phoenix_otel_soak.py
	uv run ruff check scripts/phoenix_otel_metrics.py scripts/check-phoenix-otel.py scripts/phoenix_otel_soak.py
	uv run ruff format --check scripts/phoenix_otel_metrics.py scripts/check-phoenix-otel.py scripts/phoenix_otel_soak.py scripts/test_phoenix_otel_soak.py
	uv run ruff check $(API_DIR)/tests/runtime/test_editor_sync_owner_routing.py
	uv run pytest -q $(API_DIR)/tests/runtime/test_editor_sync_owner_routing.py
	uv run ruff check $(API_DIR)/langboard/ServerRunner.py $(API_DIR)/langboard/commands/ReviewNotificationEmailCommand.py $(API_DIR)/langboard/commands/RunNotificationWebFanoutCommand.py $(API_DIR)/tests/email/test_email_service.py $(API_DIR)/tests/runtime/test_notification_delivery.py $(PY_CORE_DIR)/langboard_shared/core/publisher/NotificationPublisher.py $(PY_CORE_DIR)/langboard_shared/domain/models/NotificationEmailDelivery.py $(PY_CORE_DIR)/langboard_shared/domain/models/UserNotification.py $(PY_CORE_DIR)/langboard_shared/domain/services/factory/EmailService.py $(PY_CORE_DIR)/langboard_shared/domain/services/factory/NotificationService.py $(PY_CORE_DIR)/langboard_shared/domain/services/factory/UserNotificationSettingService.py $(PY_CORE_DIR)/langboard_shared/infrastructure/repositories/factory/NotificationEmailDeliveryRepository.py $(PY_CORE_DIR)/langboard_shared/infrastructure/repositories/factory/UserNotificationRepository.py $(PY_CORE_DIR)/langboard_shared/infrastructure/repositories/factory/UserNotificationSettingRepository.py $(PY_CORE_DIR)/langboard_shared/publishers/UserPublisher.py $(PY_CORE_DIR)/langboard_shared/tasks/notifications/NotificationWebFanoutTask.py
	uv run pytest -q $(API_DIR)/tests/email/test_email_service.py $(API_DIR)/tests/runtime/test_board_chat_availability.py $(API_DIR)/tests/runtime/test_broadcast_envelope.py $(API_DIR)/tests/runtime/test_collaborative_edit_middleware.py $(API_DIR)/tests/runtime/test_editor_sync_rich_patch.py $(API_DIR)/tests/runtime/test_notification_commands.py $(API_DIR)/tests/runtime/test_notification_delivery.py $(API_DIR)/tests/runtime/test_realtime_contract.py $(API_DIR)/tests/runtime/test_socket_auth.py
	uv run ruff check $(API_DIR)/langboard/routes/settings/Form.py $(API_DIR)/langboard/routes/settings/OllamaApi.py $(API_DIR)/tests/runtime/test_ollama_model_commands.py
	uv run pytest -q $(API_DIR)/tests/runtime/test_ollama_model_commands.py
	uv run ruff check $(API_DIR)/langboard/commands/RunOllamaModelPullRecoveryCommand.py $(API_DIR)/tests/runtime/test_ollama_model_pull.py $(PY_CORE_DIR)/langboard_shared/domain/models/OllamaModelPull.py $(PY_CORE_DIR)/langboard_shared/domain/services/factory/OllamaModelPullService.py $(PY_CORE_DIR)/langboard_shared/infrastructure/repositories/factory/OllamaModelPullRepository.py $(PY_CORE_DIR)/langboard_shared/tasks/ollama/OllamaModelPullTask.py
	uv run pytest -q $(API_DIR)/tests/runtime/test_ollama_model_pull.py
	uv run ruff check $(PY_CORE_DIR)/langboard_shared/core/security/AuthSecurity.py $(PY_CORE_DIR)/langboard_shared/ai/InternalBotGraphRequest.py $(API_DIR)/tests/runtime/test_internal_bot_graph_request.py
	uv run pytest -q $(API_DIR)/tests/runtime/test_internal_bot_graph_request.py
	uv run ruff check $(PY_CORE_DIR)/langboard_shared/ai/BoardChatAttachment.py $(PY_CORE_DIR)/langboard_shared/ai/LangflowFileClient.py $(PY_CORE_DIR)/langboard_shared/domain/models/InternalBotRun.py $(PY_CORE_DIR)/langboard_shared/domain/services/factory/InternalBotRunService.py $(PY_CORE_DIR)/langboard_shared/infrastructure/repositories/factory/InternalBotRunRepository.py $(PY_CORE_DIR)/langboard_shared/tasks/bots/LangflowBoardChatAttachmentCleanupTask.py $(API_DIR)/langboard/App.py $(API_DIR)/langboard/commands/RunInternalBotRunRecoveryCommand.py $(API_DIR)/langboard/middlewares/ChatUploadConcurrencyMiddleware.py $(API_DIR)/langboard/middlewares/__init__.py $(API_DIR)/langboard/routes/board/BoardChatApi.py $(API_DIR)/tests/runtime/test_app.py $(API_DIR)/tests/runtime/test_board_chat_attachment_upload.py $(API_DIR)/tests/runtime/test_internal_bot_run.py $(API_DIR)/tests/runtime/test_langflow_file_client.py $(API_DIR)/tests/runtime/test_socket_board_chat_run.py $(API_DIR)/tests/runtime/test_socket_editor_run.py
	uv run pytest -q $(API_DIR)/tests/runtime/test_app.py $(API_DIR)/tests/runtime/test_board_chat_attachment_upload.py $(API_DIR)/tests/runtime/test_internal_bot_run.py $(API_DIR)/tests/runtime/test_langflow_file_client.py $(API_DIR)/tests/runtime/test_socket_board_chat_run.py $(API_DIR)/tests/runtime/test_socket_editor_run.py

.PHONY: lint_socket_phoenix
lint_socket_phoenix: ## run strict Phoenix code and type analysis
	cd $(SOCKET_PHOENIX_DIR) && mix credo --strict
	cd $(SOCKET_PHOENIX_DIR) && mix dialyzer

test_socket_phoenix_editor_cluster: ## verify distributed editor ownership and persistence
	cd $(SOCKET_PHOENIX_DIR) && elixir --sname editor_cluster_probe -S mix run scripts/editor_cluster_probe.exs

test_broadcast_kafka: ## verify inline broadcast delivery without the Redis fallback
	@project_name=$$(sed -n 's/^PROJECT_NAME=//p' .env | tail -n 1); \
	if [ -z "$$project_name" ]; then \
		echo "$(RED)PROJECT_NAME is missing from .env.$(NC)"; \
		exit 1; \
	fi; \
	docker exec -i "$${project_name}_api" sh -lc 'cd /app && uv run --no-sync python -' < scripts/test-broadcast-kafka.py

bootstrap_socket_phoenix_group: ## initialize a new fanout group before starting Phoenix (GROUP_ID required)
	@if [ -z "$(GROUP_ID)" ]; then \
		echo "$(RED)GROUP_ID is required.$(NC)"; \
		exit 1; \
	fi
	@project_name=$$(sed -n 's/^PROJECT_NAME=//p' .env | tail -n 1); \
		docker exec \
		--env PHOENIX_FANOUT_GROUP_ID="$(GROUP_ID)" \
		-i "$${project_name}_api" \
		sh -lc 'cd /app && uv run --no-sync python -' \
		< scripts/bootstrap-phoenix-kafka-group.py

require_socket_phoenix_group: ## require retained fanout offsets before Phoenix ownership (GROUP_ID required)
	@if [ -z "$(GROUP_ID)" ]; then \
		echo "$(RED)GROUP_ID is required.$(NC)"; \
		exit 1; \
	fi
	@project_name=$$(sed -n 's/^PROJECT_NAME=//p' .env | tail -n 1); \
		docker exec \
		--env PHOENIX_FANOUT_GROUP_ID="$(GROUP_ID)" \
		--env PHOENIX_FANOUT_REQUIRE_EXISTING=1 \
		-i "$${project_name}_api" \
		sh -lc 'cd /app && uv run --no-sync python -' \
		< scripts/bootstrap-phoenix-kafka-group.py

validate_socket_phoenix_cutover_evidence: ## verify restore, soak, and deployment image evidence
	@project_name=$$(sed -n 's/^PROJECT_NAME=//p' .env | tail -n 1); \
	if [ -z "$$project_name" ]; then \
		echo "$(RED)PROJECT_NAME is missing from .env.$(NC)"; \
		exit 1; \
	fi; \
	if [ -z "$(PHOENIX_CUTOVER_EDITOR_MANIFEST)" ] || [ -z "$(PHOENIX_CUTOVER_OTEL_SOAK_REPORT)" ]; then \
		echo "$(RED)PHOENIX_CUTOVER_EDITOR_MANIFEST and PHOENIX_CUTOVER_OTEL_SOAK_REPORT are required.$(NC)"; \
		exit 1; \
	fi; \
	runtime_image=$$(docker image inspect "$${project_name}-socket-phoenix:dev" --format '{{.Id}}' 2>/dev/null || true); \
	if [ -z "$$runtime_image" ]; then \
		echo "$(RED)Build the Phoenix deployment image before running the cutover check.$(NC)"; \
		exit 1; \
	fi; \
	uv run python -m langboard.commands.ValidatePhoenixCutoverEvidenceCommand \
		"$(PHOENIX_CUTOVER_EDITOR_MANIFEST)" \
		"$(PHOENIX_CUTOVER_OTEL_SOAK_REPORT)" \
		"$$runtime_image"

check_socket_phoenix_cutover: ## verify the legacy Node groups are stopped and drained
	@project_name=$$(sed -n 's/^PROJECT_NAME=//p' .env | tail -n 1); \
	if [ -z "$$project_name" ]; then \
		echo "$(RED)PROJECT_NAME is missing from .env.$(NC)"; \
		exit 1; \
	fi; \
	docker exec -i "$${project_name}_api" \
		sh -lc 'cd /app && uv run --no-sync python -' \
		< scripts/check-phoenix-cutover.py

check_socket_phoenix_otel: ## verify local Phoenix metrics and traces reach the OTel Collector
	uv run python -m scripts.check-phoenix-otel \
		--metrics-url "http://127.0.0.1:$${SOCKET_PHOENIX_OTEL_METRICS_EXPOSE_PORT:-9464}/metrics" \
		--collector-metrics-url "http://127.0.0.1:$${SOCKET_PHOENIX_OTEL_INTERNAL_METRICS_EXPOSE_PORT:-8888}/metrics"

record_socket_phoenix_otel_soak: ## record an evidence-backed Phoenix OTel soak
	@if [ -z "$(PHOENIX_OTEL_SOAK_THRESHOLDS)" ] || [ -z "$(PHOENIX_OTEL_SOAK_LOAD_PROFILE)" ] || [ -z "$(PHOENIX_OTEL_SOAK_REPORT)" ]; then \
		echo "$(RED)PHOENIX_OTEL_SOAK_THRESHOLDS, PHOENIX_OTEL_SOAK_LOAD_PROFILE, and PHOENIX_OTEL_SOAK_REPORT are required.$(NC)"; \
		exit 1; \
	fi; \
	project_name=$$(sed -n 's/^PROJECT_NAME=//p' .env | tail -n 1); \
	runtime_image=$$(docker inspect --format '{{.Image}}' "$${project_name}_socket_phoenix"); \
	uv run python -m scripts.phoenix_otel_soak \
		--metrics-url "http://127.0.0.1:$${SOCKET_PHOENIX_OTEL_METRICS_EXPOSE_PORT:-9464}/metrics" \
		--collector-metrics-url "http://127.0.0.1:$${SOCKET_PHOENIX_OTEL_INTERNAL_METRICS_EXPOSE_PORT:-8888}/metrics" \
		--runtime-image "$$runtime_image" \
		--thresholds "$(PHOENIX_OTEL_SOAK_THRESHOLDS)" \
		--load-profile "$(PHOENIX_OTEL_SOAK_LOAD_PROFILE)" \
		--output "$(PHOENIX_OTEL_SOAK_REPORT)" \
		--duration-seconds "$(PHOENIX_OTEL_SOAK_DURATION_SECONDS)" \
		--warmup-seconds "$(PHOENIX_OTEL_SOAK_WARMUP_SECONDS)" \
		--sample-interval-seconds "$(PHOENIX_OTEL_SOAK_SAMPLE_INTERVAL_SECONDS)"

prepare_socket_phoenix_otel: ## pull, verify, and tag the pinned OTel Collector image
	@if [ "$(WITH_OTEL)" != "true" ]; then exit 0; fi; \
	image="$(SOCKET_PHOENIX_OTEL_COLLECTOR_IMAGE)"; \
	digest="$(SOCKET_PHOENIX_OTEL_COLLECTOR_DIGEST)"; \
	docker pull "$$image@$$digest" >/dev/null; \
	docker image tag "$$image@$$digest" "$$image"; \
	tagged_id=$$(docker image inspect "$$image" --format '{{.Id}}'); \
	pinned_id=$$(docker image inspect "$$image@$$digest" --format '{{.Id}}'); \
	if [ "$$tagged_id" != "$$pinned_id" ]; then \
		echo "$(RED)OTel Collector tag does not match the pinned digest.$(NC)"; \
		exit 1; \
	fi

prepare_socket_phoenix_owner: ## validate existing Phoenix ownership state before starting Docker
	@owner="$${SOCKET_OWNER:-$$(sed -n 's/^SOCKET_OWNER=//p' .env | tail -n 1)}"; \
	if [ "$$owner" != "phoenix" ]; then \
		exit 0; \
	fi; \
	internal_secret="$${SOCKET_PHOENIX_INTERNAL_SECRET:-$$(sed -n 's/^SOCKET_PHOENIX_INTERNAL_SECRET=//p' .env | tail -n 1)}"; \
	if [ "$${#internal_secret}" -lt 32 ]; then \
		echo "$(RED)SOCKET_PHOENIX_INTERNAL_SECRET must contain at least 32 characters before Phoenix ownership.$(NC)"; \
		exit 1; \
	fi; \
	group_id="$${BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP:-$$(sed -n 's/^BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP=//p' .env | tail -n 1)}"; \
	if [ -z "$$group_id" ]; then \
		echo "$(RED)BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP is required before Phoenix ownership.$(NC)"; \
		exit 1; \
	fi; \
	$(MAKE) validate_socket_phoenix_cutover_evidence || exit $$?; \
	$(MAKE) require_socket_phoenix_group GROUP_ID="$$group_id" || exit $$?; \
	$(MAKE) check_socket_phoenix_cutover

start_socket_phoenix_canary: ## start isolated Phoenix fanout on localhost after offset bootstrap
	@project_name=$$(sed -n 's/^PROJECT_NAME=//p' .env | tail -n 1); \
	if [ -z "$$project_name" ]; then \
		echo "$(RED)PROJECT_NAME is missing from .env.$(NC)"; \
		exit 1; \
	fi; \
	if [ -n "$$(docker ps --filter "name=^/$${project_name}_socket_phoenix$$" --format '{{.ID}}')" ]; then \
		echo "$(RED)Phoenix canary is already running. Stop it before rebuilding.$(NC)"; \
		exit 1; \
	fi; \
	group_id=$$(sed -n 's/^BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP=//p' .env | tail -n 1); \
	export BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP="$${group_id:-$${project_name}-phoenix-canary-fanout}"; \
	internal_secret="$${SOCKET_PHOENIX_INTERNAL_SECRET:-$$(sed -n 's/^SOCKET_PHOENIX_INTERNAL_SECRET=//p' .env | tail -n 1)}"; \
	if [ "$${#internal_secret}" -lt 32 ]; then \
		echo "$(RED)SOCKET_PHOENIX_INTERNAL_SECRET must contain at least 32 characters and match the API before starting a Phoenix canary.$(NC)"; \
		exit 1; \
	fi; \
	export SOCKET_PHOENIX_INTERNAL_SECRET="$$internal_secret"; \
	make build_socket_phoenix_image || exit $$?; \
	make bootstrap_socket_phoenix_group GROUP_ID="$$BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP" || exit $$?; \
	if [ -z "$$SOCKET_PHOENIX_SECRET_KEY_BASE" ]; then \
		export SOCKET_PHOENIX_SECRET_KEY_BASE=$$(uv run python -c 'import secrets; print(secrets.token_hex(64))'); \
	fi; \
	$(MAKE) prepare_socket_phoenix_otel || exit $$?; \
	if [ "$(WITH_OTEL)" = "true" ]; then \
		docker compose $(COMPOSE_ARGS) up -d --no-deps socket-phoenix-otel-collector || exit $$?; \
	fi; \
	docker compose $(COMPOSE_ARGS) --profile socket-phoenix up -d --no-deps socket-phoenix || exit $$?; \
	make clean_docker_images || { make stop_socket_phoenix_canary; exit 1; }; \
	for attempt in $$(seq 1 30); do \
		if docker exec "$${project_name}_socket_phoenix" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null; then break; fi; \
		if [ "$$attempt" -eq 30 ]; then make stop_socket_phoenix_canary; exit 1; fi; \
		sleep 1; \
	done; \
	docker exec --env PHOENIX_FANOUT_GROUP_ID="$$BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP" \
		--env PHOENIX_FANOUT_WAIT_FOR_CATCH_UP=1 -i "$${project_name}_api" \
		sh -lc 'cd /app && uv run --no-sync python -' \
		< scripts/bootstrap-phoenix-kafka-group.py || { make stop_socket_phoenix_canary; exit 1; }; \
	metrics=$$(docker exec "$${project_name}_socket_phoenix" sh -lc 'curl --fail --silent --header "x-socket-internal-secret: $$SOCKET_PHOENIX_INTERNAL_SECRET" http://127.0.0.1:5690/internal/metrics') || { make stop_socket_phoenix_canary; exit 1; }; \
	printf '%s\n' "$$metrics" | grep -q '^langboard_socket_kafka_lag_available 1$$' || { make stop_socket_phoenix_canary; exit 1; }; \
	printf '%s\n' "$$metrics" | grep -q '^langboard_socket_kafka_lag_count 0$$' || { make stop_socket_phoenix_canary; exit 1; }

stop_socket_phoenix_canary: ## stop the isolated Phoenix canary without touching Node
	@services="socket-phoenix"; \
	if [ "$(WITH_OTEL)" = "true" ]; then services="$$services socket-phoenix-otel-collector"; fi; \
	docker compose $(COMPOSE_ARGS) --profile socket-phoenix stop $$services; \
	docker compose $(COMPOSE_ARGS) --profile socket-phoenix rm --force $$services

test_socket_protocol_parity: ## run one raw WebSocket contract suite against Node and Phoenix
	@project_name=$$(sed -n 's/^PROJECT_NAME=//p' .env | tail -n 1); \
	credentials=$$(docker exec -i "$${project_name}_api" \
		sh -lc 'cd /app && uv run --no-sync python -' \
		< scripts/create-socket-protocol-credentials.py); \
	status=$$?; \
	if [ "$$status" -eq 0 ]; then \
		access_token=$$(printf '%s\n' "$$credentials" | sed -n '1p'); \
		user_uid=$$(printf '%s\n' "$$credentials" | sed -n '2p'); \
		$(MAKE) start_socket_phoenix_canary || status=$$?; \
	fi; \
	if [ "$$status" -eq 0 ]; then \
		SOCKET_PROTOCOL_ACCESS_TOKEN="$$access_token" SOCKET_PROTOCOL_USER_UID="$$user_uid" \
			uv run python scripts/test-socket-protocol.py \
			--target node=ws://127.0.0.1:1101 \
			--target phoenix=ws://127.0.0.1:5691 || status=$$?; \
	fi; \
	$(MAKE) stop_socket_phoenix_canary || true; \
	exit $$status

test_socket_phoenix_kafka: build_socket_phoenix_image ## verify Phoenix WebSocket fanout, Redis fallback, and dead-letter delivery
	@project_name=$$(sed -n 's/^PROJECT_NAME=//p' .env | tail -n 1); \
	if [ -z "$$project_name" ]; then \
		echo "$(RED)PROJECT_NAME is missing from .env.$(NC)"; \
		exit 1; \
	fi; \
	if [ ! -f docker/envs/.socket.env ]; then \
		echo "$(RED)docker/envs/.socket.env is missing; run make update_docker_settings first.$(NC)"; \
		exit 1; \
	fi; \
	container_name="$${project_name}_socket_phoenix_probe"; \
	network_name="$${project_name}_network"; \
	probe_id=$$$$; \
	group_id="$${project_name}-phoenix-probe-$${probe_id}"; \
	dlq_topic="socket_publish_dead_letter_probe_$${probe_id}"; \
	secret_key_base=$$(uv run python -c 'import secrets; print(secrets.token_hex(64))'); \
	docker exec \
		--env PHOENIX_FANOUT_GROUP_ID="$$group_id" \
		-i "$${project_name}_api" \
		sh -lc 'cd /app && uv run --no-sync python -' \
		< scripts/bootstrap-phoenix-kafka-group.py || exit 1; \
	docker rm -f "$$container_name" >/dev/null 2>&1 || true; \
	cleanup() { \
		docker rm -f "$$container_name" >/dev/null 2>&1 || true; \
		docker exec --env PHOENIX_SOCKET_DLQ_TOPIC="$$dlq_topic" -i "$${project_name}_api" \
			sh -lc 'cd /app && uv run --no-sync python - delete_dead_letter' \
			< scripts/test-phoenix-cluster-topics.py >/dev/null 2>&1 || true; \
	}; \
	trap cleanup EXIT; \
	docker run --detach \
		--name "$$container_name" \
		--network "$$network_name" \
		--env-file docker/envs/.socket.env \
		--env SECRET_KEY_BASE="$$secret_key_base" \
		--env PHX_HOST=localhost \
		--env SOCKET_PHOENIX_KAFKA_ENABLED=true \
		--env BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP="$$group_id" \
		--env BROADCAST_PHOENIX_DEAD_LETTER_TOPIC="$$dlq_topic" \
		"$${project_name}-socket-phoenix:dev" >/dev/null || exit 1; \
	status=0; \
	for attempt in $$(seq 1 30); do \
		if [ "$$(docker inspect --format '{{.State.Running}}' "$$container_name" 2>/dev/null)" != "true" ]; then \
			status=1; \
			break; \
		fi; \
		if docker exec "$$container_name" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null; then \
			break; \
		fi; \
		if [ "$$attempt" -eq 30 ]; then \
			status=1; \
		else \
			sleep 1; \
		fi; \
	done; \
	if [ "$$status" -eq 0 ]; then \
		docker exec \
			--env PHOENIX_SOCKET_URL="ws://$${container_name}:5690" \
			--env PHOENIX_SOCKET_DLQ_TOPIC="$$dlq_topic" \
			-i "$${project_name}_api" \
			sh -lc 'cd /app && uv run --no-sync python -' \
			< scripts/test-phoenix-kafka-ingress.py || status=$$?; \
	fi; \
	if [ "$$status" -ne 0 ]; then \
		docker logs "$$container_name"; \
	else \
		docker stop --time 20 "$$container_name" >/dev/null || status=$$?; \
		container_exit_code=$$(docker inspect --format '{{.State.ExitCode}}' "$$container_name" 2>/dev/null); \
		if [ "$$container_exit_code" != "0" ]; then \
			echo "$(RED)Phoenix probe did not stop gracefully (exit $$container_exit_code).$(NC)"; \
			docker logs "$$container_name"; \
			status=1; \
		fi; \
	fi; \
	exit "$$status"

test_socket_phoenix_dlq_recovery: build_socket_phoenix_image ## verify a rejected Kafka record survives dead-letter outage and restart
	@set -eu; \
	project_name=$$(sed -n 's/^PROJECT_NAME=//p' .env | tail -n 1); \
	if [ -z "$$project_name" ] || [ ! -f docker/envs/.socket.env ]; then \
		echo "$(RED)Phoenix probe requires PROJECT_NAME and docker/envs/.socket.env.$(NC)"; \
		exit 1; \
	fi; \
	probe_id=$$(uv run python -c 'import secrets; print(secrets.token_hex(5))'); \
	container_name="$${project_name}_socket_phoenix_dlq_probe_$${probe_id}"; \
	group_id="$${project_name}-phoenix-dlq-recovery-$${probe_id}"; \
	source_topic="socket_publish_dlq_recovery_$${probe_id}"; \
	valid_topic="socket_publish_dead_letter_recovery_$${probe_id}"; \
	secret_key_base=$$(uv run python -c 'import secrets; print(secrets.token_hex(64))'); \
	stage=setup; \
	cleanup() { \
		docker rm -f "$$container_name" >/dev/null 2>&1 || true; \
		docker exec \
			--env PHOENIX_DLQ_TEST_PHASE=delete_topic \
			--env PHOENIX_DLQ_TEST_ID="$$probe_id" \
			--env PHOENIX_DLQ_TEST_SOURCE_TOPIC="$$source_topic" \
			--env PHOENIX_DLQ_TEST_TOPIC="$$valid_topic" \
			-i "$${project_name}_api" \
			sh -lc 'cd /app && uv run --no-sync python -' \
			< scripts/test-phoenix-kafka-dlq-recovery.py >/dev/null 2>&1 || true; \
	}; \
	report_and_cleanup() { \
		status=$$?; \
		if [ "$$status" -ne 0 ]; then echo "$(RED)Phoenix DLQ recovery probe failed during $$stage (exit $$status).$(NC)"; fi; \
		cleanup; \
	}; \
	trap report_and_cleanup EXIT; \
	stage=create-source-topic; \
	docker exec \
		--env PHOENIX_DLQ_TEST_PHASE=create_topic \
		--env PHOENIX_DLQ_TEST_ID="$$probe_id" \
		--env PHOENIX_DLQ_TEST_SOURCE_TOPIC="$$source_topic" \
		--env PHOENIX_DLQ_TEST_TOPIC="$$valid_topic" \
		-i "$${project_name}_api" \
		sh -lc 'cd /app && uv run --no-sync python -' \
		< scripts/test-phoenix-kafka-dlq-recovery.py; \
	start_probe() { \
		docker run --detach \
			--name "$$container_name" \
			--network "$${project_name}_network" \
			--env-file docker/envs/.socket.env \
			--env SECRET_KEY_BASE="$$secret_key_base" \
			--env PHX_HOST=localhost \
			--env SOCKET_PHOENIX_KAFKA_ENABLED=true \
			--env SOCKET_PHOENIX_KAFKA_SOURCE_TOPIC="$$source_topic" \
			--env BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP="$$group_id" \
			--env BROADCAST_PHOENIX_DEAD_LETTER_TOPIC="$$1" \
			"$${project_name}-socket-phoenix:dev" >/dev/null; \
	}; \
	wait_ready() { \
		for attempt in $$(seq 1 30); do \
			if docker exec "$$container_name" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null 2>&1; then \
				return 0; \
			fi; \
			sleep 1; \
		done; \
		docker logs "$$container_name"; \
		return 1; \
	}; \
	stage=produce-backlog; \
	record=$$(docker exec \
		--env PHOENIX_DLQ_TEST_PHASE=produce \
		--env PHOENIX_DLQ_TEST_ID="$$probe_id" \
		--env PHOENIX_DLQ_TEST_SOURCE_TOPIC="$$source_topic" \
		-i "$${project_name}_api" \
		sh -lc 'cd /app && uv run --no-sync python -' \
		< scripts/test-phoenix-kafka-dlq-recovery.py); \
	partition=$${record%%:*}; \
	offset=$${record#*:}; \
	stage=start-blocked-probe; \
	start_probe "invalid/dead_letter_$${probe_id}"; \
	stage=wait-for-liveness; \
	for attempt in $$(seq 1 30); do \
		if docker exec "$$container_name" curl --fail --silent http://127.0.0.1:5690/health/live >/dev/null 2>&1; then break; fi; \
		if [ "$$attempt" -eq 30 ]; then docker logs "$$container_name"; exit 1; fi; \
		sleep 1; \
	done; \
	stage=observe-dead-letter-failure; \
	failed=0; \
	for attempt in $$(seq 1 30); do \
		if docker logs "$$container_name" 2>&1 | grep -q 'could not persist a rejected record'; then \
			failed=1; \
			break; \
		fi; \
		sleep 1; \
	done; \
	if [ "$$failed" -ne 1 ]; then \
		docker logs "$$container_name"; \
		echo "$(RED)Dead-letter failure was not observed.$(NC)"; \
		exit 1; \
	fi; \
	stage=verify-readiness-blocked; \
	ready_status=$$(docker exec "$$container_name" sh -lc 'curl --silent --output /dev/null --write-out "%{http_code}" http://127.0.0.1:5690/health/ready'); \
	if [ "$$ready_status" != "503" ]; then \
		docker logs "$$container_name"; \
		echo "$(RED)Phoenix admitted traffic before its Kafka backlog was durably handled (HTTP $$ready_status).$(NC)"; \
		exit 1; \
	fi; \
	stage=stop-blocked-probe; \
	docker rm -f "$$container_name" >/dev/null; \
	stage=verify-source-uncommitted; \
	docker exec \
		--env PHOENIX_DLQ_TEST_PHASE=assert_uncommitted \
		--env PHOENIX_DLQ_TEST_ID="$$probe_id" \
		--env PHOENIX_DLQ_TEST_SOURCE_TOPIC="$$source_topic" \
		--env PHOENIX_DLQ_TEST_GROUP="$$group_id" \
		--env PHOENIX_DLQ_TEST_PARTITION="$$partition" \
		--env PHOENIX_DLQ_TEST_OFFSET="$$offset" \
		-i "$${project_name}_api" \
		sh -lc 'cd /app && uv run --no-sync python -' \
		< scripts/test-phoenix-kafka-dlq-recovery.py; \
	stage=start-recovery-probe; \
	start_probe "$$valid_topic"; \
	stage=wait-for-recovery-readiness; \
	wait_ready; \
	stage=verify-dead-letter-recovery; \
	docker exec \
		--env PHOENIX_DLQ_TEST_PHASE=assert_delivered \
		--env PHOENIX_DLQ_TEST_ID="$$probe_id" \
		--env PHOENIX_DLQ_TEST_SOURCE_TOPIC="$$source_topic" \
		--env PHOENIX_DLQ_TEST_PARTITION="$$partition" \
		--env PHOENIX_DLQ_TEST_OFFSET="$$offset" \
		--env PHOENIX_DLQ_TEST_TOPIC="$$valid_topic" \
		-i "$${project_name}_api" \
		sh -lc 'cd /app && uv run --no-sync python -' \
		< scripts/test-phoenix-kafka-dlq-recovery.py; \
	stage=complete

test_socket_phoenix_cluster: build_socket_phoenix_image ## verify Kafka fanout across two clustered Phoenix nodes
	@$(SHELL) scripts/test-phoenix-cluster.sh

test_socket_phoenix_browser_cluster: build_socket_phoenix_image ## verify browser reconnect and subscription restoration across Phoenix nodes
	@$(SHELL) scripts/test-phoenix-browser-cluster.sh

test_socket_phoenix_browser_attachment: build_socket_phoenix_image ## verify browser attachment upload, Langflow execution, and cleanup through Phoenix
	@PHOENIX_BROWSER_PROBE=board-chat-attachment $(SHELL) scripts/test-phoenix-browser-cluster.sh

test_socket_phoenix_browser_attachment_process_loss: build_socket_phoenix_image ## verify durable attachment cleanup after Phoenix process loss
	@PHOENIX_BROWSER_PROBE=board-chat-attachment PHOENIX_BROWSER_FAILOVER_STAGE=resume $(SHELL) scripts/test-phoenix-browser-cluster.sh

test_socket_phoenix_browser_reconnect_stability: build_socket_phoenix_image ## verify repeated browser reconnect, reload, and subscription restoration
	@PHOENIX_BROWSER_FAILOVER_STAGE=repeated PHOENIX_BROWSER_RECONNECT_ROUNDS=6 $(SHELL) scripts/test-phoenix-browser-cluster.sh

test_socket_phoenix_editor_ai_browser: test_socket_phoenix_editor_ai_approve_browser test_socket_phoenix_editor_ai_reject_browser test_socket_phoenix_editor_ai_copilot_browser test_socket_phoenix_editor_ai_revocation_browser test_socket_phoenix_editor_ai_cancel_browser test_socket_phoenix_editor_ai_socket_reconnect_browser test_socket_phoenix_editor_ai_worker_loss_browser test_socket_phoenix_editor_ai_node_loss_browser test_socket_phoenix_editor_sync_reconnect_browser ## verify Editor AI and HITL through real browsers

test_socket_phoenix_editor_ai_approve_browser: build_socket_phoenix_image ## verify Editor AI approval and rich patch persistence
	@PHOENIX_BROWSER_PROBE=editor-ai PHOENIX_EDITOR_AI_SCENARIO=approve $(SHELL) scripts/test-phoenix-browser-cluster.sh

test_socket_phoenix_editor_ai_reject_browser: build_socket_phoenix_image ## verify Editor AI rejection without a tool side effect
	@PHOENIX_BROWSER_PROBE=editor-ai PHOENIX_EDITOR_AI_SCENARIO=reject $(SHELL) scripts/test-phoenix-browser-cluster.sh

test_socket_phoenix_editor_ai_copilot_browser: build_socket_phoenix_image ## verify Editor copilot suggestion acceptance and persistence
	@PHOENIX_BROWSER_PROBE=editor-ai PHOENIX_EDITOR_AI_SCENARIO=copilot $(SHELL) scripts/test-phoenix-browser-cluster.sh

test_socket_phoenix_editor_ai_revocation_browser: build_socket_phoenix_image ## verify in-flight Editor AI authorization revocation
	@PHOENIX_BROWSER_PROBE=editor-ai PHOENIX_EDITOR_AI_SCENARIO=revocation $(SHELL) scripts/test-phoenix-browser-cluster.sh

test_socket_phoenix_editor_ai_cancel_browser: build_socket_phoenix_image ## verify Editor AI cancellation ownership and persistence
	@PHOENIX_BROWSER_PROBE=editor-ai PHOENIX_EDITOR_AI_SCENARIO=cancel $(SHELL) scripts/test-phoenix-browser-cluster.sh

test_socket_phoenix_editor_ai_socket_reconnect_browser: build_socket_phoenix_image ## verify in-flight Editor AI recovery after a browser socket reconnect
	@PHOENIX_BROWSER_PROBE=editor-ai PHOENIX_EDITOR_AI_SCENARIO=approve PHOENIX_BROWSER_FAILOVER_STAGE=socket-reconnect $(SHELL) scripts/test-phoenix-browser-cluster.sh

test_socket_phoenix_editor_ai_worker_loss_browser: build_socket_phoenix_image ## verify accepted Editor AI work across worker loss
	@PHOENIX_BROWSER_PROBE=editor-ai PHOENIX_EDITOR_AI_SCENARIO=approve PHOENIX_BROWSER_FAILOVER_STAGE=worker $(SHELL) scripts/test-phoenix-browser-cluster.sh

test_socket_phoenix_editor_ai_node_loss_browser: build_socket_phoenix_image ## verify accepted Editor AI work across Phoenix node loss
	@PHOENIX_BROWSER_PROBE=editor-ai PHOENIX_EDITOR_AI_SCENARIO=approve PHOENIX_BROWSER_FAILOVER_STAGE=resume $(SHELL) scripts/test-phoenix-browser-cluster.sh

test_socket_phoenix_editor_sync_reconnect_browser: build_socket_phoenix_image ## verify repeated Editor synchronization across Phoenix node changes
	@PHOENIX_BROWSER_PROBE=editor-ai PHOENIX_EDITOR_AI_SCENARIO=sync PHOENIX_BROWSER_FAILOVER_STAGE=repeated PHOENIX_BROWSER_RECONNECT_ROUNDS=6 $(SHELL) scripts/test-phoenix-browser-cluster.sh

build_socket_phoenix_image: ## build the isolated Phoenix image and clean replaced project images
	@set -eu; \
	project_name=$$(sed -n 's/^PROJECT_NAME=//p' .env | tail -n 1); \
	if [ -z "$$project_name" ]; then \
		echo "$(RED)PROJECT_NAME is missing from .env.$(NC)"; \
		exit 1; \
	fi; \
	image_ref="$$project_name-socket-phoenix:dev"; \
	previous_image_id=$$(docker image inspect "$$image_ref" --format '{{.Id}}' 2>/dev/null || true); \
	docker build --file $(SOCKET_PHOENIX_DIR)/Dockerfile \
		--build-arg PROJECT_NAME="$$project_name" \
		--tag "$$image_ref" src; \
	new_image_id=$$(docker image inspect "$$image_ref" --format '{{.Id}}'); \
	if [ -n "$$previous_image_id" ] && [ "$$previous_image_id" != "$$new_image_id" ]; then \
		owners=$$(docker ps -a --filter "ancestor=$$previous_image_id" --format '{{.ID}} {{.Names}}'); \
		other_tags=$$(docker image inspect "$$previous_image_id" --format '{{range .RepoTags}}{{println .}}{{end}}'); \
		if [ -n "$$owners" ] || [ -n "$$other_tags" ]; then \
			echo "$(DIM)Preserving replaced Phoenix image $$previous_image_id; referenced by:$(NC)"; \
			if [ -n "$$owners" ]; then echo "$$owners"; fi; \
			if [ -n "$$other_tags" ]; then echo "Other tags: $$other_tags"; fi; \
		else \
			docker image rm "$$previous_image_id" >/dev/null; \
			echo "$(GREEN)Removed unreferenced replaced Phoenix image $$previous_image_id.$(NC)"; \
		fi; \
	fi
	$(MAKE) clean_docker_images

update_ts_core:
	@cd $(UI_DIR) && yarn remove @langboard/core
	@cd $(UI_DIR) && yarn add @langboard/core@file:../shared/ts
	@cd $(SOCKET_DIR) && yarn remove @langboard/core
	@cd $(SOCKET_DIR) && yarn add @langboard/core@file:../shared/ts

start_docker: ## run Docker in the production environment
	make init_env
	mkdir -p ./docker/volumes
	make update_docker_settings
	docker compose $(COMPOSE_ARGS) build
	$(MAKE) prepare_socket_phoenix_otel
	$(MAKE) prepare_socket_phoenix_owner || { $(MAKE) clean_docker_images; exit 1; }
	docker compose $(COMPOSE_ARGS) up -d --remove-orphans
	make clean_docker_images

rebuild_docker: ## run Docker in the production environment (e.g. make rebuild_docker IMAGES=image_name or IMAGES="image_name1 image_name2")
	if [ "$(IMAGES)" = "" ]; then \
		echo "$(RED)Please specify the IMAGES variable to rebuild (e.g. make rebuild_docker IMAGES=image_name or IMAGES=\"image_name1 image_name2\")$(NC)"; \
		exit 1; \
	fi

	make init_env
	mkdir -p ./docker/volumes
	make update_docker_settings
	docker compose $(COMPOSE_ARGS) build ${IMAGES}
	$(MAKE) prepare_socket_phoenix_otel
	$(MAKE) prepare_socket_phoenix_owner || { $(MAKE) clean_docker_images; exit 1; }
	docker compose $(COMPOSE_ARGS) up -d --no-deps ${IMAGES} --remove-orphans
	make clean_docker_images

clean_docker_images: ## remove unused images created by this Compose project
	@project_name=$$(sed -n 's/^PROJECT_NAME=//p' .env | tail -n 1); \
	if [ -z "$$project_name" ]; then \
		echo "$(RED)PROJECT_NAME is missing from .env.$(NC)"; \
		exit 1; \
	fi; \
	docker image prune --force --filter "label=com.docker.compose.project=$$project_name"

clean_docker_build_cache: clean_docker_images ## explicitly cap the shared Docker builder cache
	docker builder prune --all --force --max-used-space $(DOCKER_BUILD_CACHE_MAX)

update_docker: ## update Docker in the production environment
	make init_env
	make update_docker_settings
	$(MAKE) prepare_socket_phoenix_otel
	$(MAKE) prepare_socket_phoenix_owner
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
ifneq ($(ComSpec),)
	powershell -NoProfile -ExecutionPolicy Bypass -File ./scripts/utils/update-docker-envs.ps1
else
	bash ./scripts/utils/update-docker-envs.sh
endif

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
