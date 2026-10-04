#!/usr/bin/env bash

set -u

export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

project_name=$(sed -n 's/^PROJECT_NAME=//p' .env | tail -n 1)
if [ -z "$project_name" ]; then
    echo "PROJECT_NAME is missing from .env." >&2
    exit 1
fi
max_file_size_mb=$(sed -n 's/^MAX_FILE_SIZE_MB=//p' .env | tail -n 1)
case "$max_file_size_mb" in
    ''|*[!0-9]*|0) echo "MAX_FILE_SIZE_MB must be a positive integer." >&2; exit 1 ;;
esac
proxy_port="${PHOENIX_BROWSER_PROXY_PORT:-15693}"
case "$proxy_port" in
    ''|*[!0-9]*) echo "PHOENIX_BROWSER_PROXY_PORT must be a valid TCP port." >&2; exit 1 ;;
    *)
        if [ "$proxy_port" -lt 1 ] || [ "$proxy_port" -gt 65535 ]; then
            echo "PHOENIX_BROWSER_PROXY_PORT must be a valid TCP port." >&2
            exit 1
        fi
        ;;
esac
if ! uv run python -c 'import socket, sys; socket.create_server(("127.0.0.1", int(sys.argv[1]))).close()' "$proxy_port"; then
    echo "PHOENIX_BROWSER_PROXY_PORT is already in use." >&2
    exit 1
fi

if [ ! -f docker/envs/.socket.env ]; then
    echo "docker/envs/.socket.env is missing; run make update_docker_settings first." >&2
    exit 1
fi

run_id=$(uv run python -c 'from uuid import uuid4; print(uuid4())')
probe_id=$$
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) workspace_root=$(pwd -W) ;;
    *) workspace_root=$(pwd) ;;
esac
node_a="${project_name}_socket_phoenix_browser_a"
node_b="${project_name}_socket_phoenix_browser_b"
api_worker="${project_name}_phoenix_browser_api"
graph_probe="${project_name}_phoenix_browser_graph"
ollama_broker="${project_name}_phoenix_browser_ollama_broker"
ollama_worker="${project_name}_phoenix_browser_ollama_worker"
network_name="${project_name}_network"
cluster_alias="${project_name}_socket_phoenix_browser_${probe_id}"
group_id="${project_name}-phoenix-browser-${run_id}"
dlq_topic="socket_publish_dead_letter_browser_probe_${run_id}"
mode_file="local/socket-migration/phoenix-browser-proxy-${run_id}.mode"
signal_file="local/socket-migration/phoenix-browser-${run_id}.signal"
proxy_log="local/socket-migration/phoenix-browser-proxy-${run_id}.log"
probe_log="local/socket-migration/phoenix-browser-${run_id}.log"
runtime_dir="${workspace_root}/local/socket-migration/browser-runtime-${run_id}"
generated_ui_build=false
keep_artifacts="${PHOENIX_BROWSER_KEEP_ARTIFACTS:-false}"
configured_ui_build="${PHOENIX_BROWSER_UI_BUILD:-${BOARD_CHAT_UI_BUILD:-}}"
if [ -n "$configured_ui_build" ]; then
    ui_build=$(uv run python -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$configured_ui_build")
else
    ui_build="${workspace_root}/local/socket-migration/ui-build-browser-${run_id}"
    generated_ui_build=true
fi
fixture_container_path="/tmp/test-phoenix-browser-fixture-${run_id}.py"
inspect_container_path="/tmp/test-phoenix-browser-inspect-${run_id}.py"
cutover_check_container_path="/tmp/check-phoenix-cutover-${run_id}.py"
graph_probe_path="${workspace_root}/src/socket/test/browser/test-phoenix-browser-graph.py"
probe_kind="${PHOENIX_BROWSER_PROBE:-board-chat}"
editor_ai_scenario="${PHOENIX_EDITOR_AI_SCENARIO:-approve}"
failover_stage="${PHOENIX_BROWSER_FAILOVER_STAGE:-connected}"
reconnect_rounds="${PHOENIX_BROWSER_RECONNECT_ROUNDS:-6}"
if [ "$failover_stage" = canary ] && [ "$probe_kind" != board-chat ]; then
    echo "PHOENIX_BROWSER_FAILOVER_STAGE=canary requires PHOENIX_BROWSER_PROBE=board-chat." >&2
    exit 1
fi
if [ "$failover_stage" = worker ] && [ "$probe_kind" != editor-ai ]; then
    echo "PHOENIX_BROWSER_FAILOVER_STAGE=worker requires PHOENIX_BROWSER_PROBE=editor-ai." >&2
    exit 1
fi
if [ "$failover_stage" = socket-reconnect ] && [ "$probe_kind" != editor-ai ]; then
    echo "PHOENIX_BROWSER_FAILOVER_STAGE=socket-reconnect requires PHOENIX_BROWSER_PROBE=editor-ai." >&2
    exit 1
fi
case "$failover_stage" in
    connected|canary|cancel|socket-reconnect|repeated|resume|worker|accepted-api-outage) ;;
    *) echo "PHOENIX_BROWSER_FAILOVER_STAGE must be connected, canary, cancel, socket-reconnect, repeated, resume, worker, or accepted-api-outage." >&2; exit 1 ;;
esac
case "$reconnect_rounds" in
    ''|*[!0-9]*) echo "PHOENIX_BROWSER_RECONNECT_ROUNDS must be an integer from 1 to 20." >&2; exit 1 ;;
    *)
        if [ "$reconnect_rounds" -lt 1 ] || [ "$reconnect_rounds" -gt 20 ]; then
            echo "PHOENIX_BROWSER_RECONNECT_ROUNDS must be an integer from 1 to 20." >&2
            exit 1
        fi
        ;;
esac
case "$probe_kind" in
    board-chat)
        inspect_source="src/socket/test/browser/test-phoenix-board-chat-inspect.py"
        browser_probe_script="src/socket/test/browser/test-phoenix-browser-ui.cjs"
        editor_ai_enabled=false
        ;;
    socket-ui)
        inspect_source="src/socket/test/browser/test-phoenix-board-chat-inspect.py"
        browser_probe_script="src/socket/test/browser/test-phoenix-socket-ui.cjs"
        editor_ai_enabled=false
        if [ "$failover_stage" != connected ]; then
            echo "PHOENIX_BROWSER_PROBE=socket-ui requires PHOENIX_BROWSER_FAILOVER_STAGE=connected." >&2
            exit 1
        fi
        ;;
    ollama|ollama-worker-loss)
        inspect_source="src/socket/test/browser/test-phoenix-board-chat-inspect.py"
        browser_probe_script="src/socket/test/browser/test-phoenix-ollama-ui.cjs"
        editor_ai_enabled=false
        if [ "$failover_stage" != connected ]; then
            echo "PHOENIX_BROWSER_PROBE=ollama requires PHOENIX_BROWSER_FAILOVER_STAGE=connected." >&2
            exit 1
        fi
        ;;
    board-chat-attachment)
        inspect_source="src/socket/test/browser/test-phoenix-board-chat-inspect.py"
        browser_probe_script="src/socket/test/browser/test-phoenix-browser-ui.cjs"
        editor_ai_enabled=false
        ;;
    editor-ai)
        inspect_source="src/socket/test/browser/test-phoenix-editor-ai-inspect.py"
        browser_probe_script="src/socket/test/browser/test-phoenix-editor-ai-ui.cjs"
        if [ "$editor_ai_scenario" = sync ]; then
            editor_ai_enabled=false
        else
            editor_ai_enabled=true
        fi
        if [ "$failover_stage" = cancel ] || [ "$failover_stage" = accepted-api-outage ] || \
           { [ "$failover_stage" = repeated ] && [ "$editor_ai_scenario" != sync ]; }; then
            echo "Editor AI browser probes do not support the selected PHOENIX_BROWSER_FAILOVER_STAGE." >&2
            exit 1
        fi
        case "$editor_ai_scenario" in
            approve|reject|copilot|revocation|cancel|sync) ;;
            *) echo "PHOENIX_EDITOR_AI_SCENARIO must be approve, reject, copilot, revocation, cancel, or sync." >&2; exit 1 ;;
        esac
        if { [ "$failover_stage" = socket-reconnect ] || [ "$failover_stage" = resume ] || [ "$failover_stage" = worker ]; } && \
           [ "$editor_ai_scenario" != approve ]; then
            echo "Editor AI socket reconnect, resume, and worker failover require PHOENIX_EDITOR_AI_SCENARIO=approve." >&2
            exit 1
        fi
        ;;
    *) echo "PHOENIX_BROWSER_PROBE must be board-chat, socket-ui, ollama, ollama-worker-loss, board-chat-attachment, or editor-ai." >&2; exit 1 ;;
esac
node_b_kafka_enabled=false
if { [ "$probe_kind" = board-chat ] && \
     { [ "$failover_stage" = connected ] || [ "$failover_stage" = resume ]; }; } || \
   { [ "$probe_kind" = ollama ] || [ "$probe_kind" = ollama-worker-loss ]; }; then
    node_b_kafka_enabled=true
fi
playwright_module_path="${PLAYWRIGHT_MODULE_PATH:-playwright}"
if ! node -e 'require.resolve(process.argv[1])' "$playwright_module_path" >/dev/null 2>&1; then
    playwright_module_path="$(npm root -g)/@playwright/cli/node_modules/playwright"
fi
if ! node -e 'require.resolve(process.argv[1])' "$playwright_module_path" >/dev/null 2>&1; then
    echo "Playwright is unavailable; set PLAYWRIGHT_MODULE_PATH to the installed module." >&2
    exit 1
fi
proxy_pid=""
probe_pid=""
metrics_pid=""
status=0

secret_key_base=$(uv run python -c 'import secrets; print(secrets.token_hex(64))')
cluster_cookie=$(uv run python -c 'import secrets; print(secrets.token_hex(32))')

cleanup() {
    cleanup_status=$?
    if [ -n "${probe_pid:-}" ]; then
        kill "$probe_pid" >/dev/null 2>&1 || true
        wait "$probe_pid" >/dev/null 2>&1 || true
    fi
    if [ -n "${proxy_pid:-}" ]; then
        kill "$proxy_pid" >/dev/null 2>&1 || true
        wait "$proxy_pid" >/dev/null 2>&1 || true
    fi
    if [ -n "${metrics_pid:-}" ]; then
        kill "$metrics_pid" >/dev/null 2>&1 || true
        wait "$metrics_pid" >/dev/null 2>&1 || true
    fi
    if [ "$probe_kind" = ollama ] || [ "$probe_kind" = ollama-worker-loss ]; then
        for model in "phoenix-browser-${run_id}:latest" \
                     "phoenix-browser-polled-${run_id}:latest" \
                     "phoenix-browser-recovered-${run_id}:latest"; do
            curl.exe --silent --show-error --output NUL --request DELETE \
                --header 'Content-Type: application/json' \
                --data "{\"model\":\"${model}\"}" \
                http://127.0.0.1:11434/api/delete || cleanup_status=1
        done
    fi
    docker logs "$node_a" > "${probe_log}.node-a" 2>&1 || true
    docker logs "$node_b" > "${probe_log}.node-b" 2>&1 || true
    docker exec "$node_a" curl --fail --silent \
        -H "X-Socket-Internal-Secret: $phoenix_internal_secret" \
        http://127.0.0.1:5690/internal/metrics > "${probe_log}.node-a.metrics" 2>/dev/null || true
    docker exec "$node_b" curl --fail --silent \
        -H "X-Socket-Internal-Secret: $phoenix_internal_secret" \
        http://127.0.0.1:5690/internal/metrics > "${probe_log}.node-b.metrics" 2>/dev/null || true
    docker logs "$graph_probe" > "${probe_log}.graph" 2>&1 || true
    docker logs "$api_worker" > "${probe_log}.api" 2>&1 || true
    if [ "$probe_kind" = ollama ] || [ "$probe_kind" = ollama-worker-loss ]; then
        docker logs "$ollama_worker" > "${probe_log}.ollama-worker" 2>&1 || true
        docker rm -f "$ollama_worker" >/dev/null 2>&1 || true
    fi
    docker rm -f "$node_a" "$node_b" >/dev/null 2>&1 || true
    bash src/socket/test/integration/delete-consumer-group.sh "$project_name" "$group_id" || cleanup_status=1
    if [ "$probe_kind" = editor-ai ]; then
        docker exec -i "${project_name}_api" uv run --no-sync python \
            "$inspect_container_path" "$run_id" --cancel-pending \
            >/dev/null 2>&1 || true
    fi
    docker exec --env PHOENIX_SOCKET_DLQ_TOPIC="$dlq_topic" -i "${project_name}_api" \
        sh -lc 'cd /app && uv run --no-sync python - delete_dead_letter' \
        < src/socket/test/integration/test-phoenix-cluster-topics.py >/dev/null 2>&1 || true
    if [ "$(docker inspect --format '{{.State.Running}}' "$api_worker" 2>/dev/null)" = "true" ]; then
        if docker cp "local/socket-migration/editor-access-${run_id}.json" \
            "$api_worker:/app/local/socket-migration/editor-access-${run_id}.json" >/dev/null 2>&1 && \
            docker exec -i "$api_worker" sh -lc "cd /app && uv run --no-sync python - cleanup '$run_id'" \
                < src/socket/test/browser/test-phoenix-browser-fixture.py > "${probe_log}.cleanup" 2>&1; then
            rm -f -- "local/socket-migration/editor-access-${run_id}.json"
        else
            cleanup_status=1
        fi
    else
        docker exec -i "${project_name}_api" uv run --no-sync python \
            "$fixture_container_path" cleanup "$run_id" \
            > "${probe_log}.cleanup" 2>&1 || cleanup_status=1
    fi
    if [ "$probe_kind" = ollama ] || [ "$probe_kind" = ollama-worker-loss ]; then
        docker rm -f "$ollama_broker" >/dev/null 2>&1 || true
    fi
    docker rm -f "$graph_probe" "$api_worker" >/dev/null 2>&1 || true
    docker exec "${project_name}_api" rm -f \
        "$fixture_container_path" "$inspect_container_path" "$cutover_check_container_path" \
        >/dev/null 2>&1 || true
    if [ "$keep_artifacts" != "true" ] && [ "$cleanup_status" -eq 0 ]; then
        rm -f "$mode_file" "$signal_file" "$signal_file.ready" "$signal_file.disconnected" "$signal_file.recovered" \
            "${signal_file}.ready."* "${signal_file}.disconnected."* "${signal_file}.recovered."* \
            "$proxy_log" "$probe_log" "${probe_log}.cleanup" \
            "${probe_log}.node-a.metrics" "${probe_log}.node-b.metrics" \
            "${probe_log}.node-a.metrics.samples"
        case "$runtime_dir" in
            "${workspace_root}/local/socket-migration/browser-runtime-"*) rm -rf -- "$runtime_dir" ;;
        esac
        if [ "$generated_ui_build" = true ]; then
            case "$ui_build" in
                "${workspace_root}/local/socket-migration/ui-build-browser-"*) rm -rf -- "$ui_build" ;;
            esac
        fi
    else
        echo "Browser probe artifacts preserved: $probe_log" >&2
    fi
    trap - EXIT
    exit "$cleanup_status"
}

trap cleanup EXIT

docker exec \
    --env PHOENIX_FANOUT_GROUP_ID="$group_id" \
    -i "${project_name}_api" \
    sh -lc 'cd /app && uv run --no-sync python -' \
    < scripts/bootstrap-phoenix-kafka-group.py || exit 1

mkdir -p "$runtime_dir/editor-sync" "$runtime_dir/logs" "$runtime_dir/schemas" "$runtime_dir/socket-migration" || exit 1
cp local/api_config.json local/graph_config.json "$runtime_dir/" || exit 1
cp -R local/schemas/. "$runtime_dir/schemas/" || exit 1

if [ "$generated_ui_build" = true ]; then
    (
        cd src/ui || exit 1
        if [ "$probe_kind" = ollama ] || [ "$probe_kind" = ollama-worker-loss ]; then
            export IS_OLLAMA_RUNNING=true
        fi
        SOCKET_URL="http://127.0.0.1:$proxy_port" \
        API_URL=http://127.0.0.1:15694 \
        PUBLIC_UI_URL=http://127.0.0.1:1100 \
        MAX_FILE_SIZE_MB="$max_file_size_mb" \
        yarn build --outDir "$ui_build" --emptyOutDir
    ) || exit 1
elif [ ! -f "$ui_build/index.html" ]; then
    echo "BOARD_CHAT_UI_BUILD must point to a built diagnostic UI directory." >&2
    exit 1
fi

docker cp src/socket/test/browser/test-phoenix-browser-fixture.py \
    "${project_name}_api:${fixture_container_path}" >/dev/null || exit 1
docker cp "$inspect_source" \
    "${project_name}_api:${inspect_container_path}" >/dev/null || exit 1
docker cp scripts/check-phoenix-cutover.py \
    "${project_name}_api:${cutover_check_container_path}" >/dev/null || exit 1

docker exec -i "${project_name}_api" uv run --no-sync python \
    "$cutover_check_container_path" --celery-only >/dev/null || exit 1

fixture_create_args=()
if [ "$probe_kind" = socket-ui ] || [ "$probe_kind" = ollama ] || [ "$probe_kind" = ollama-worker-loss ]; then
    fixture_create_args+=(--admin-owner)
fi
docker exec -i "${project_name}_api" uv run --no-sync python \
    "$fixture_container_path" create "$run_id" "${fixture_create_args[@]}" >/dev/null || exit 1
if [ "$probe_kind" = socket-ui ]; then
    docker exec -i "${project_name}_api" uv run --no-sync python \
        "$fixture_container_path" create-wiki "$run_id" >/dev/null || exit 1
fi
langflow_api_key=""
if [ "$probe_kind" = board-chat-attachment ]; then
    langflow_api_key=$(uv run python -c 'import secrets; print(secrets.token_hex(32))')
    docker exec -i "${project_name}_api" uv run --no-sync python \
        "$fixture_container_path" configure-langflow "$run_id" \
        --api-url "http://${graph_probe}:5020" --api-key "$langflow_api_key" >/dev/null || exit 1
elif [ "$probe_kind" = editor-ai ] && [ "$editor_ai_scenario" != sync ]; then
    docker exec -i "${project_name}_api" uv run --no-sync python \
        "$fixture_container_path" configure-editor-ai "$run_id" >/dev/null || exit 1
fi

docker rm -f "$node_a" "$node_b" >/dev/null 2>&1 || true
docker rm -f "$graph_probe" "$api_worker" >/dev/null 2>&1 || true
if [ "$probe_kind" = ollama ] || [ "$probe_kind" = ollama-worker-loss ]; then
    docker rm -f "$ollama_worker" "$ollama_broker" >/dev/null 2>&1 || true
fi
printf 'a\n' > "$mode_file"

config_dir="$runtime_dir"

start_api_worker() {
    api_image=$(docker inspect --format '{{.Config.Image}}' "${project_name}_api")
    api_args=(run --detach --pull never --name "$api_worker" --network "$network_name" --init
        --volumes-from "${project_name}_api"
        --mount "type=bind,source=${config_dir},target=/app/local"
        --add-host host.docker.internal:host-gateway
        --publish 127.0.0.1:15694:5381 --workdir /app/src/api)
    while IFS= read -r entry; do
        if [ -n "$entry" ]; then
            api_args+=(--env "$entry")
        fi
    done < <(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "${project_name}_api")
    if [ "$probe_kind" = board-chat-attachment ]; then
        api_args+=(--env CHAT_UPLOAD_MAX_CONCURRENCY=1)
    fi
    if [ "$probe_kind" = ollama ] || [ "$probe_kind" = ollama-worker-loss ]; then
        api_args+=(--env OLLAMA_API_URL=http://host.docker.internal:11434)
        api_args+=(--env "BROKER_URL=redis://${ollama_broker}:6379/0")
    fi
    api_args+=(--env "SOCKET_PHOENIX_INTERNAL_SECRET=$phoenix_internal_secret"
        --env SOCKET_EDITOR_INTERNAL_URL="http://host.docker.internal:$proxy_port"
        --env PUBLIC_UI_URL=http://127.0.0.1:1100
        --entrypoint uv "$api_image" run --no-sync uvicorn langboard.AppInstance:app
        --host 0.0.0.0 --port 5381)
    docker "${api_args[@]}" >/dev/null
}

start_graph_probe() {
    graph_image=$(docker inspect --format '{{.Config.Image}}' "${project_name}_graph")
    graph_args=(run --detach --pull never --name "$graph_probe" --network "$network_name" --init
        --volumes-from "${project_name}_graph"
        --mount "type=bind,source=${config_dir},target=/app/local"
        --mount "type=bind,source=${graph_probe_path},target=/tmp/test_phoenix_browser_graph.py,readonly"
        --workdir /app/src/graph)
    while IFS= read -r entry; do
        if [ -n "$entry" ]; then
            graph_args+=(--env "$entry")
        fi
    done < <(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "${project_name}_graph")
    if [ "$failover_stage" = socket-reconnect ] || [ "$failover_stage" = resume ] || [ "$failover_stage" = worker ] || \
       [ "$failover_stage" = accepted-api-outage ]; then
        graph_args+=(--env "PHOENIX_BROWSER_HOLD_MARKER=$run_id")
    fi
    if [ "$editor_ai_scenario" = revocation ]; then
        graph_args+=(--env "PHOENIX_BROWSER_HOLD_BEFORE_TOOL_MARKER=$run_id")
    fi
    if [ "$editor_ai_scenario" = cancel ] || [ "$failover_stage" = cancel ]; then
        graph_args+=(--env "PHOENIX_BROWSER_HOLD_MODEL_MARKER=$run_id")
    fi
    if [ "$probe_kind" = editor-ai ] || [ "$failover_stage" = cancel ]; then
        graph_args+=(--env PHOENIX_BROWSER_DETERMINISTIC_EDITOR_AI=true)
    fi
    if [ "$probe_kind" = board-chat-attachment ]; then
        graph_args+=(--env "PHOENIX_BROWSER_LANGFLOW_API_KEY=$langflow_api_key")
    fi
    if [ "$probe_kind" = ollama-worker-loss ]; then
        graph_args+=(--env "PHOENIX_BROWSER_OLLAMA_WORKER_LOSS_ID=$run_id")
    fi
    graph_args+=(--env "API_INTERNAL_URL=http://${api_worker}:5381"
        --entrypoint uv "$graph_image" run --no-sync uvicorn --app-dir /tmp test_phoenix_browser_graph:app
        --host 0.0.0.0 --port 5020)
    docker "${graph_args[@]}" >/dev/null
}

phoenix_internal_secret=$(uv run python -c 'import secrets; print(secrets.token_hex(32))')
if [ "$probe_kind" = ollama ] || [ "$probe_kind" = ollama-worker-loss ]; then
    docker run --detach --pull never --name "$ollama_broker" --network "$network_name" \
        redis:7.2-alpine redis-server --save '' --appendonly no >/dev/null || exit 1
fi
start_api_worker || exit 1
start_graph_probe || exit 1
if [ "$probe_kind" = ollama ] || [ "$probe_kind" = ollama-worker-loss ]; then
    worker_image=$(docker inspect --format '{{.Config.Image}}' "${project_name}_celeryworker")
    worker_args=(run --detach --pull never --name "$ollama_worker" --network "$network_name" --init
        --volumes-from "${project_name}_celeryworker"
        --mount "type=bind,source=${config_dir},target=/app/local" --add-host host.docker.internal:host-gateway
        --workdir /app/src/api)
    while IFS= read -r entry; do
        if [ -n "$entry" ]; then
            worker_args+=(--env "$entry")
        fi
    done < <(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "${project_name}_celeryworker")
    worker_ollama_url=http://host.docker.internal:11434
    if [ "$probe_kind" = ollama-worker-loss ]; then
        worker_ollama_url="http://${graph_probe}:5020/diagnostic/ollama"
    fi
    worker_args+=(--env "BROKER_URL=redis://${ollama_broker}:6379/0"
        --env "OLLAMA_API_URL=$worker_ollama_url"
        --entrypoint uv "$worker_image" run --no-sync "${project_name}" run:broker)
    docker "${worker_args[@]}" >/dev/null || exit 1
fi

api_ready=0
for attempt in $(seq 1 180); do
    if curl.exe --fail --silent http://127.0.0.1:15694/health >/dev/null; then
        api_ready=1
        break
    fi
    sleep 1
done
if [ "$api_ready" -ne 1 ]; then
    docker logs "$api_worker" 2>&1 || true
    echo "Isolated Phoenix browser API did not become ready." >&2
    exit 1
fi

graph_ready=0
for attempt in $(seq 1 180); do
    if docker exec "$graph_probe" uv run --no-sync python -c \
        'import httpx; assert httpx.get("http://127.0.0.1:5020/health", timeout=3).status_code == 200' \
        >/dev/null 2>&1; then
        graph_ready=1
        break
    fi
    sleep 1
done
if [ "$graph_ready" -ne 1 ]; then
    docker logs "$graph_probe" 2>&1 || true
    echo "Isolated Phoenix browser Graph did not become ready." >&2
    exit 1
fi

start_node() {
    node_name="$1"
    host_port="$2"
    kafka_enabled="$3"
    docker run --detach \
        --name "$node_name" \
        --network "$network_name" \
        --network-alias "$cluster_alias" \
        --mount "type=bind,source=${runtime_dir}/editor-sync,target=/tmp/langboard-editor-sync" \
        --publish "127.0.0.1:${host_port}:5690" \
        --env-file docker/envs/.socket.env \
        --env SECRET_KEY_BASE="$secret_key_base" \
        --env PHX_HOST=localhost \
        --env SOCKET_PHOENIX_CLUSTER_MINIMUM_SIZE=1 \
        --env SOCKET_PHOENIX_CLUSTER_COOKIE="$cluster_cookie" \
        --env RELEASE_DISTRIBUTION=name \
        --env RELEASE_COOKIE="$cluster_cookie" \
        --env SOCKET_PHOENIX_INTERNAL_SECRET="$phoenix_internal_secret" \
        --env API_INTERNAL_URL="http://${api_worker}:5381" \
        --env DEFAULT_GRAPH_URL="http://${graph_probe}:5020" \
        --env SOCKET_PHOENIX_KAFKA_ENABLED="$kafka_enabled" \
        --env SOCKET_PHOENIX_BOARD_CHAT_SEND_ENABLED=true \
        --env SOCKET_PHOENIX_BOARD_CHAT_RESUME_ENABLED=true \
        --env SOCKET_PHOENIX_BOARD_CHAT_RECOVERY_ENABLED=true \
        --env SOCKET_PHOENIX_EDITOR_AI_ENABLED="$editor_ai_enabled" \
        --env SOCKET_PHOENIX_EDITOR_SYNC_ENABLED=true \
        --env SOCKET_PHOENIX_EDITOR_SYNC_STORAGE_DIR=/tmp/langboard-editor-sync \
        --env SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES=1 \
        --env BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP="$group_id" \
        --env BROADCAST_PHOENIX_DEAD_LETTER_TOPIC="$dlq_topic" \
        --entrypoint sh \
        "${project_name}-socket-phoenix:dev" \
        -c 'mkdir -p /tmp/langboard-editor-sync; export RELEASE_NODE="langboard_socket@$(hostname -i | cut -d " " -f 1)"; exec /app/bin/langboard_socket start' \
        >/dev/null
}

start_node "$node_a" 5692 true || exit 1
if [ "$node_b_kafka_enabled" = true ]; then
    node_a_assigned=0
    for attempt in $(seq 1 180); do
        if docker exec "$node_a" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null; then
            node_a_assigned=1
            break
        fi
        sleep 1
    done
    if [ "$node_a_assigned" -ne 1 ]; then
        echo "The primary Phoenix browser node did not acquire its Kafka assignment." >&2
        docker logs "$node_a" 2>&1 || true
        exit 1
    fi
fi
start_node "$node_b" 5693 "$node_b_kafka_enabled" || exit 1

ready=0
for attempt in $(seq 1 180); do
    if [ "$(docker inspect --format '{{.State.Running}}' "$node_a" 2>/dev/null)" != "true" ] || \
       [ "$(docker inspect --format '{{.State.Running}}' "$node_b" 2>/dev/null)" != "true" ]; then
        docker logs "$node_a" 2>&1 || true
        docker logs "$node_b" 2>&1 || true
        break
    fi
    if docker exec "$node_a" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null && \
       { [ "$node_b_kafka_enabled" = true ] && \
         docker exec "$node_b" curl --fail --silent http://127.0.0.1:5690/health >/dev/null || \
         docker exec "$node_b" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null; }; then
        ready=1
        break
    fi
    sleep 1
done
if [ "$ready" -ne 1 ]; then
    echo "Phoenix browser cluster did not become ready." >&2
    docker logs "$node_a" 2>&1 || true
    docker logs "$node_b" 2>&1 || true
    exit 1
fi

sample_node_a_metrics() {
    while :; do
        printf 'sample_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        docker exec "$node_a" curl --fail --silent \
            -H "X-Socket-Internal-Secret: $phoenix_internal_secret" \
            http://127.0.0.1:5690/internal/metrics | \
            grep -E '^(langboard_socket_runtime_readiness_failure_count|langboard_socket_kafka_lag_available|langboard_socket_authorization_request_count)' || true
        sleep 5
    done
}
sample_node_a_metrics > "${probe_log}.node-a.metrics.samples" 2>&1 &
metrics_pid=$!

start_proxy() {
    uv run python src/socket/test/browser/phoenix-failover-proxy.py \
        --port "$proxy_port" --mode-file "$mode_file" --target-a 5692 --target-b 5693 \
        > "$proxy_log" 2>&1 &
    proxy_pid=$!
    sleep 1
    if ! kill -0 "$proxy_pid" >/dev/null 2>&1; then
        echo "Browser failover proxy failed to start:" >&2
        cat "$proxy_log" >&2
        return 1
    fi
}

start_proxy || exit 1

PLAYWRIGHT_MODULE_PATH="$playwright_module_path" \
BOARD_CHAT_RUN_ID="$run_id" \
BOARD_CHAT_UI_BUILD="$ui_build" \
PHOENIX_BROWSER_RUN_ID="$run_id" \
PHOENIX_BROWSER_UI_BUILD="$ui_build" \
PHOENIX_EDITOR_AI_SCENARIO="$editor_ai_scenario" \
PHOENIX_BROWSER_API_CONTAINER="${project_name}_api" \
PHOENIX_BROWSER_RUNTIME_API_CONTAINER="$api_worker" \
PHOENIX_BROWSER_FIXTURE_PATH="$fixture_container_path" \
PHOENIX_BROWSER_INSPECT_PATH="$inspect_container_path" \
PHOENIX_BROWSER_API_ORIGIN=http://127.0.0.1:15694 \
PHOENIX_BROWSER_UI_ORIGIN=http://127.0.0.1:1100 \
PHOENIX_BROWSER_FAILOVER_SIGNAL="$signal_file" \
PHOENIX_BROWSER_FAILOVER_STAGE="$failover_stage" \
PHOENIX_BROWSER_RECONNECT_ROUNDS="$reconnect_rounds" \
PHOENIX_BROWSER_PROXY_PORT="$proxy_port" \
PHOENIX_BROWSER_GRAPH_CONTAINER="$graph_probe" \
PHOENIX_BROWSER_OLLAMA_WORKER_CONTAINER="$ollama_worker" \
PHOENIX_BROWSER_OLLAMA_WORKER_LOSS="$([ "$probe_kind" = ollama-worker-loss ] && printf true || printf false)" \
PHOENIX_BROWSER_NODE_A="$node_a" \
PHOENIX_BROWSER_PROXY_MODE_FILE="$mode_file" \
PHOENIX_BROWSER_DOCKER_NETWORK="$network_name" \
PHOENIX_BROWSER_ATTACHMENT_PROBE="$([ "$probe_kind" = board-chat-attachment ] && printf true || printf false)" \
PHOENIX_BROWSER_MAX_FILE_SIZE_MB="$max_file_size_mb" \
node "$browser_probe_script" > "$probe_log" 2>&1 &
probe_pid=$!


if [ "$probe_kind" = editor-ai ]; then
    if [ "$failover_stage" = connected ]; then
        wait "$probe_pid" || status=$?
        probe_pid=""
        if [ "$status" -ne 0 ]; then
            cat "$probe_log" >&2 || true
            exit "$status"
        fi

        echo "Phoenix Editor AI ${editor_ai_scenario} browser probe passed."
        exit 0
    fi
fi

if [ "$probe_kind" = board-chat-attachment ] && [ "$failover_stage" = connected ]; then
    wait "$probe_pid" || status=$?
    probe_pid=""
    if [ "$status" -ne 0 ]; then
        cat "$probe_log" >&2 || true
        exit "$status"
    fi

    echo "Phoenix Board chat attachment browser probe passed."
    exit 0
fi

if [ "$probe_kind" = socket-ui ] || [ "$probe_kind" = ollama ] || [ "$probe_kind" = ollama-worker-loss ]; then
    wait "$probe_pid" || status=$?
    probe_pid=""
    if [ "$status" -ne 0 ]; then
        cat "$probe_log" >&2 || true
        exit "$status"
    fi

    echo "Phoenix ${probe_kind} browser probe passed."
    exit 0
fi

if [ "$probe_kind" = board-chat ] && [ "$failover_stage" = canary ]; then
    wait "$probe_pid" || status=$?
    probe_pid=""
    if [ "$status" -ne 0 ]; then
        cat "$probe_log" >&2 || true
        exit "$status"
    fi

    echo "Phoenix Board chat canary browser probe passed."
    exit 0
fi

if { [ "$probe_kind" = board-chat ] || [ "$probe_kind" = board-chat-attachment ]; } && \
   [ "$failover_stage" = cancel ]; then
    wait "$probe_pid" || status=$?
    probe_pid=""
    if [ "$status" -ne 0 ]; then
        cat "$probe_log" >&2 || true
        exit "$status"
    fi

    echo "Phoenix Board chat cancellation browser probe passed."
    exit 0
fi

if [ "$failover_stage" = accepted-api-outage ]; then
    wait "$probe_pid" || status=$?
    probe_pid=""
    if [ "$status" -ne 0 ]; then
        cat "$probe_log" >&2 || true
        exit "$status"
    fi

    echo "Phoenix accepted-work API outage probe passed."
    exit 0
fi

browser_ready=0
for attempt in $(seq 1 420); do
    if [ -f "$signal_file.ready" ]; then
        browser_ready=1
        break
    fi
    if ! kill -0 "$probe_pid" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
if [ "$browser_ready" -ne 1 ]; then
    cat "$probe_log" >&2 || true
    echo "Browser probe did not reach the ${failover_stage} failover checkpoint; inspect the probe report for the failed step." >&2
    exit 1
fi

if [ "$failover_stage" = socket-reconnect ]; then
    kill "$proxy_pid" >/dev/null 2>&1 || exit 1
    wait "$proxy_pid" >/dev/null 2>&1 || true
    proxy_pid=""

    disconnected=0
    for attempt in $(seq 1 90); do
        if [ -f "$signal_file.disconnected" ]; then
            disconnected=1
            break
        fi
        sleep 1
    done
    if [ "$disconnected" -ne 1 ]; then
        cat "$probe_log" >&2 || true
        echo "Browser sockets did not close after the proxy stopped." >&2
        exit 1
    fi

    start_proxy || exit 1
    recovered=0
    for attempt in $(seq 1 90); do
        if [ -f "$signal_file.recovered" ]; then
            recovered=1
            break
        fi
        sleep 1
    done
    if [ "$recovered" -ne 1 ]; then
        cat "$probe_log" >&2 || true
        echo "Browser subscriptions did not recover after the proxy restarted." >&2
        exit 1
    fi

    wait "$probe_pid" || status=$?
    probe_pid=""
    if [ "$status" -ne 0 ]; then
        cat "$probe_log" >&2 || true
        exit "$status"
    fi

    echo "Phoenix Editor AI socket-reconnect browser probe passed."
    exit 0
fi

if [ "$failover_stage" = worker ]; then
    node_ip=$(docker inspect --format '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$node_a")
    if [ -z "$node_ip" ]; then
        echo "Could not resolve the Editor AI worker owner node address." >&2
        exit 1
    fi
    docker exec \
        --env RELEASE_DISTRIBUTION=name \
        --env RELEASE_COOKIE="$cluster_cookie" \
        --env RELEASE_NODE="langboard_socket@${node_ip}" \
        "$node_a" \
        /app/bin/langboard_socket rpc \
        'case Enum.find(DynamicSupervisor.which_children(LangboardSocket.EditorRunSupervisor), fn {_, _, _, modules} -> LangboardSocket.Editor.ResumeWorker in modules end) do {_, pid, :worker, _} -> :ok = DynamicSupervisor.terminate_child(LangboardSocket.EditorRunSupervisor, pid); nil -> raise "EditorResumeWorker was not found" end' \
        >/dev/null || exit 1
    docker exec "$node_a" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null || exit 1
    printf '{"worker":"terminated"}\n' > "$signal_file.recovered"

    wait "$probe_pid" || status=$?
    probe_pid=""
    if [ "$status" -ne 0 ]; then
        cat "$probe_log" >&2 || true
        exit "$status"
    fi

    echo "Phoenix Editor AI worker-loss browser probe passed."
    exit 0
fi

if [ "$failover_stage" = repeated ]; then
    active_node="$node_a"
    next_mode=b
    for round in $(seq 1 "$reconnect_rounds"); do
        if [ "$round" -gt 1 ]; then
            ready_signal="${signal_file}.ready.${round}"
            round_ready=0
            for attempt in $(seq 1 120); do
                if [ -f "$ready_signal" ]; then
                    round_ready=1
                    break
                fi
                if ! kill -0 "$probe_pid" >/dev/null 2>&1; then
                    break
                fi
                sleep 1
            done
            if [ "$round_ready" -ne 1 ]; then
                cat "$probe_log" >&2 || true
                echo "Browser probe did not reach reconnect round ${round}." >&2
                exit 1
            fi
        fi

        printf '%s\n' "$next_mode" > "$mode_file"
        docker stop --time 20 "$active_node" >/dev/null || exit 1

        disconnected_signal="$signal_file.disconnected"
        recovered_signal="$signal_file.recovered"
        if [ "$round" -gt 1 ]; then
            disconnected_signal="${disconnected_signal}.${round}"
            recovered_signal="${recovered_signal}.${round}"
        fi

        round_disconnected=0
        for attempt in $(seq 1 90); do
            if [ -f "$disconnected_signal" ]; then
                round_disconnected=1
                break
            fi
            if ! kill -0 "$probe_pid" >/dev/null 2>&1; then
                break
            fi
            sleep 1
        done
        if [ "$round_disconnected" -ne 1 ]; then
            cat "$probe_log" >&2 || true
            echo "Browser sockets did not disconnect during reconnect round ${round}." >&2
            exit 1
        fi

        docker start "$active_node" >/dev/null || exit 1
        restarted_ready=0
        for attempt in $(seq 1 180); do
            if docker exec "$active_node" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null 2>&1; then
                restarted_ready=1
                break
            fi
            sleep 1
        done
        if [ "$restarted_ready" -ne 1 ]; then
            docker logs "$active_node" >&2 || true
            echo "Restarted Phoenix node did not become ready during reconnect round ${round}." >&2
            exit 1
        fi

        round_recovered=0
        for attempt in $(seq 1 120); do
            if [ -f "$recovered_signal" ]; then
                round_recovered=1
                break
            fi
            if ! kill -0 "$probe_pid" >/dev/null 2>&1; then
                break
            fi
            sleep 1
        done
        if [ "$round_recovered" -ne 1 ]; then
            cat "$probe_log" >&2 || true
            echo "Browser subscriptions did not recover during reconnect round ${round}." >&2
            exit 1
        fi

        if [ "$active_node" = "$node_a" ]; then
            active_node="$node_b"
            next_mode=a
        else
            active_node="$node_a"
            next_mode=b
        fi
    done

    wait "$probe_pid" || status=$?
    probe_pid=""
    if [ "$status" -ne 0 ]; then
        cat "$probe_log" >&2 || true
        exit "$status"
    fi

    echo "Phoenix browser repeated reconnect probe passed (${reconnect_rounds} rounds)."
    exit 0
fi

if [ "$node_b_kafka_enabled" = true ]; then
    if [ "$failover_stage" = resume ]; then
        docker kill "$node_a" >/dev/null || exit 1
    else
        docker stop --time 20 "$node_a" >/dev/null || exit 1
    fi

    node_b_assigned=0
    for attempt in $(seq 1 180); do
        if docker exec "$node_b" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null; then
            node_b_assigned=1
            break
        fi
        sleep 1
    done
    if [ "$node_b_assigned" -ne 1 ]; then
        cat "$probe_log" >&2 || true
        docker logs "$node_b" 2>&1 || true
        echo "The standby Phoenix browser node did not acquire the Kafka assignment." >&2
        exit 1
    fi
    printf 'b\n' > "$mode_file"
else
    printf 'b\n' > "$mode_file"
    if [ "$failover_stage" = resume ]; then
        docker kill "$node_a" >/dev/null || exit 1
    else
        docker stop --time 20 "$node_a" >/dev/null || exit 1
    fi
fi

recovered=0
for attempt in $(seq 1 120); do
    if [ -f "$signal_file.recovered" ]; then
        recovered=1
        break
    fi
    if ! kill -0 "$probe_pid" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
if [ "$recovered" -ne 1 ]; then
    cat "$probe_log" >&2 || true
    echo "Browser subscriptions did not recover through Phoenix failover." >&2
    exit 1
fi

wait "$probe_pid" || status=$?
if [ "$status" -ne 0 ]; then
    cat "$probe_log" >&2 || true
    exit "$status"
fi

if [ "$probe_kind" = editor-ai ]; then
    echo "Phoenix Editor AI node-loss browser probe passed."
elif [ "$probe_kind" = board-chat-attachment ]; then
    echo "Phoenix Board chat attachment process-loss browser probe passed."
else
    echo "Phoenix browser failover probe passed."
fi
