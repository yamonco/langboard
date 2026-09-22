#!/usr/bin/env bash

set -u

export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

failure_mode="${PHOENIX_CLUSTER_FAILURE_MODE:-graceful}"
case "$failure_mode" in
    graceful|kill|partition) ;;
    *) echo "Expected PHOENIX_CLUSTER_FAILURE_MODE=graceful, kill, or partition"; exit 1 ;;
esac

project_name=$(sed -n 's/^PROJECT_NAME=//p' .env | tail -n 1)
if [ -z "$project_name" ]; then
    echo "\033[0;31mPROJECT_NAME is missing from .env.\033[0m"
    exit 1
fi

if [ ! -f docker/envs/.socket.env ]; then
    echo "\033[0;31mdocker/envs/.socket.env is missing; run make update_docker_settings first.\033[0m"
    exit 1
fi

network_name="${project_name}_network"
probe_id=$(uv run python -c 'import secrets; print(secrets.token_hex(8))')
node_a="${project_name}_socket_phoenix_cluster_${probe_id}_a"
node_b="${project_name}_socket_phoenix_cluster_${probe_id}_b"
source_topic="socket_publish_cluster_probe_${probe_id}"
group_id="${project_name}-phoenix-cluster-${probe_id}"
cluster_alias="${project_name}_socket_phoenix_cluster_${probe_id}"
dlq_topic="socket_publish_dead_letter_cluster_probe_${probe_id}"
reconnect_log="/tmp/phoenix-cluster-reconnect-${probe_id}.log"
reconnect_script="/tmp/phoenix-cluster-reconnect-${probe_id}.py"
secret_key_base=$(uv run python -c 'import secrets; print(secrets.token_hex(64))')
cluster_cookie=$(uv run python -c 'import secrets; print(secrets.token_hex(32))')
status=0

change_topics() {
    docker exec \
        --env SOCKET_PHOENIX_KAFKA_SOURCE_TOPIC="$source_topic" \
        --env PHOENIX_SOCKET_DLQ_TOPIC="$dlq_topic" \
        --env PHOENIX_FANOUT_GROUP_ID="$group_id" \
        -i "${project_name}_api" \
        sh -lc "cd /app && uv run --no-sync python - $1" \
        < scripts/test-phoenix-cluster-topics.py
}

cleanup() {
    docker rm -f "$node_a" "$node_b" >/dev/null 2>&1 || true
    docker exec "${project_name}_api" rm -f "$reconnect_log" "$reconnect_script" >/dev/null 2>&1 || true
    change_topics delete || status=1
    trap - EXIT
    exit "$status"
}

trap cleanup EXIT
change_topics create || { status=1; exit "$status"; }

docker exec \
    --env SOCKET_PHOENIX_KAFKA_SOURCE_TOPIC="$source_topic" \
    --env PHOENIX_FANOUT_GROUP_ID="$group_id" \
    -i "${project_name}_api" \
    sh -lc 'cd /app && uv run --no-sync python -' \
    < scripts/bootstrap-phoenix-kafka-group.py || { status=1; exit "$status"; }

docker rm -f "$node_a" "$node_b" >/dev/null 2>&1 || true

start_node() {
    node_name="$1"
    kafka_enabled="$2"
    docker run --detach \
        --name "$node_name" \
        --network "$network_name" \
        --network-alias "$cluster_alias" \
        --env-file docker/envs/.socket.env \
        --env SECRET_KEY_BASE="$secret_key_base" \
        --env PHX_HOST=localhost \
        --env SOCKET_PHOENIX_CLUSTER_DNS_QUERY="$cluster_alias" \
        --env SOCKET_PHOENIX_CLUSTER_MINIMUM_SIZE=2 \
        --env SOCKET_PHOENIX_CLUSTER_COOKIE="$cluster_cookie" \
        --env SOCKET_PHOENIX_KAFKA_ENABLED="$kafka_enabled" \
        --env SOCKET_PHOENIX_KAFKA_SOURCE_TOPIC="$source_topic" \
        --env BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP="$group_id" \
        --env BROADCAST_PHOENIX_DEAD_LETTER_TOPIC="$dlq_topic" \
        --entrypoint sh \
        "${project_name}-socket-phoenix:dev" \
        -c 'export RELEASE_NODE="langboard_socket@$(hostname -i | cut -d " " -f 1)"; exec /app/bin/langboard_socket start' \
        >/dev/null
}

start_node "$node_a" true || status=$?
if [ "$status" -eq 0 ]; then
    start_node "$node_b" true || status=$?
fi

if [ "$status" -eq 0 ]; then
    cluster_ready=0
    for attempt in $(seq 1 45); do
        if [ "$(docker inspect --format '{{.State.Running}}' "$node_a" 2>/dev/null)" != "true" ] || \
           [ "$(docker inspect --format '{{.State.Running}}' "$node_b" 2>/dev/null)" != "true" ]; then
            status=1
            break
        fi
        if docker exec "$node_a" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null && \
           docker exec "$node_b" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null; then
            cluster_ready=1
            break
        fi
        sleep 1
    done
    if [ "$cluster_ready" -ne 1 ]; then
        echo "\033[0;31mPhoenix cluster did not become ready.\033[0m"
        status=1
    fi
fi

if [ "$status" -eq 0 ]; then
    change_topics verify || status=$?
fi

if [ "$status" -eq 0 ]; then
    docker exec \
        --env PHOENIX_SOCKET_URL="ws://${node_b}:5690" \
        --env SOCKET_PHOENIX_KAFKA_SOURCE_TOPIC="$source_topic" \
        --env PHOENIX_SOCKET_DLQ_TOPIC="$dlq_topic" \
        -i "${project_name}_api" \
        sh -lc 'cd /app && uv run --no-sync python -' \
        < scripts/test-phoenix-kafka-ingress.py || status=$?
fi

if [ "$status" -eq 0 ]; then
    docker exec "${project_name}_api" rm -f "$reconnect_log" >/dev/null 2>&1 || true
    docker cp scripts/test-phoenix-cluster-reconnect.py "${project_name}_api:${reconnect_script}" || status=$?
fi

if [ "$status" -eq 0 ]; then
    docker exec -d \
        --env PHOENIX_SOCKET_URLS="ws://${node_a}:5690,ws://${node_b}:5690" \
        --env SOCKET_PHOENIX_KAFKA_SOURCE_TOPIC="$source_topic" \
        "${project_name}_api" \
        sh -lc "cd /app && uv run --no-sync python $reconnect_script > $reconnect_log 2>&1" || status=$?
fi

if [ "$status" -eq 0 ]; then
    reconnect_ready=0
    for attempt in $(seq 1 30); do
        if docker exec "${project_name}_api" grep -q 'received initial event' "$reconnect_log"; then
            reconnect_ready=1
            break
        fi
        if docker exec "${project_name}_api" grep -q 'Traceback\|RuntimeError' "$reconnect_log"; then
            break
        fi
        sleep 1
    done
    if [ "$reconnect_ready" -ne 1 ]; then
        docker exec "${project_name}_api" cat "$reconnect_log" || true
        echo "\033[0;31mPhoenix reconnect client did not establish its initial subscription.\033[0m"
        status=1
    fi
fi

if [ "$status" -eq 0 ]; then
    if [ "$failure_mode" = "kill" ]; then
        docker kill --signal KILL "$node_a" >/dev/null || status=$?
        expected_exit=137
    else
        docker stop --time 20 "$node_a" >/dev/null || status=$?
        expected_exit=0
    fi
    node_a_exit=$(docker inspect --format '{{.State.ExitCode}}' "$node_a" 2>/dev/null)
    if [ "$node_a_exit" != "$expected_exit" ]; then
        echo "\033[0;31mCluster ingress $failure_mode exit was $node_a_exit, expected $expected_exit.\033[0m"
        status=1
    else
        echo "Phoenix cluster ingress stopped (exit $node_a_exit)"
    fi
fi

if [ "$status" -eq 0 ]; then
    reconnect_closed=0
    for attempt in $(seq 1 20); do
        if docker exec "${project_name}_api" grep -q 'detected disconnect' "$reconnect_log"; then
            reconnect_closed=1
            break
        fi
        sleep 1
    done
    if [ "$reconnect_closed" -ne 1 ]; then
        docker exec "${project_name}_api" cat "$reconnect_log" || true
        echo "\033[0;31mPhoenix reconnect client did not observe the ingress disconnect.\033[0m"
        status=1
    fi
fi

if [ "$status" -eq 0 ]; then
    docker rm "$node_a" >/dev/null || status=$?
    if [ "$status" -eq 0 ]; then
        start_node "$node_a" true || status=$?
    fi
fi

if [ "$status" -eq 0 ]; then
    reconnect_passed=0
    for attempt in $(seq 1 90); do
        if docker exec "${project_name}_api" grep -q 'cluster reconnect probe passed' "$reconnect_log"; then
            reconnect_passed=1
            break
        fi
        if docker exec "${project_name}_api" grep -q 'Traceback\|RuntimeError' "$reconnect_log"; then
            break
        fi
        sleep 1
    done
    if [ "$reconnect_passed" -ne 1 ]; then
        docker exec "${project_name}_api" cat "$reconnect_log" || true
        echo "\033[0;31mPhoenix reconnect client did not restore its subscription after node recovery.\033[0m"
        status=1
    fi
fi

if [ "$status" -eq 0 ]; then
    if [ "$failure_mode" = "partition" ]; then
        node_a_started=$(docker inspect --format '{{.State.StartedAt}}' "$node_a")
        node_a_ip=$(docker inspect --format "{{(index .NetworkSettings.Networks \"$network_name\").IPAddress}}" "$node_a")
        docker network disconnect "$network_name" "$node_a" || status=$?
    else
        docker stop --time 20 "$node_a" >/dev/null || status=$?
        node_a_exit=$(docker inspect --format '{{.State.ExitCode}}' "$node_a" 2>/dev/null)
        if [ "$node_a_exit" != "0" ]; then
            echo "\033[0;31mCluster loss node did not stop gracefully (exit $node_a_exit).\033[0m"
            status=1
        fi
    fi
fi

if [ "$status" -eq 0 ]; then
    cluster_loss_detected=0
    for attempt in $(seq 1 90); do
        if ! docker exec "$node_b" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null; then
            cluster_loss_detected=1
            break
        fi
        sleep 1
    done
    if [ "$cluster_loss_detected" -ne 1 ]; then
        echo "\033[0;31mRemaining Phoenix node stayed ready after losing required cluster membership.\033[0m"
        status=1
    fi
    if ! docker exec "$node_b" curl --fail --silent http://127.0.0.1:5690/health/live >/dev/null; then
        echo "\033[0;31mRemaining Phoenix node failed liveness after cluster loss.\033[0m"
        status=1
    fi
    if [ "$failure_mode" = "partition" ]; then
        if docker exec "$node_a" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null; then
            echo "Isolated Phoenix node stayed ready during network partition."
            status=1
        fi
        if ! docker exec "$node_a" curl --fail --silent http://127.0.0.1:5690/health/live >/dev/null; then
            echo "Isolated Phoenix node failed liveness during network partition."
            status=1
        fi
    fi
fi

if [ "$status" -eq 0 ]; then
    if [ "$failure_mode" = "partition" ]; then
        docker network connect --ip "$node_a_ip" --alias "$cluster_alias" "$network_name" "$node_a" || status=$?
        if [ "$(docker inspect --format '{{.State.StartedAt}}' "$node_a")" != "$node_a_started" ]; then
            echo "Partitioned node restarted instead of recovering its network."
            status=1
        fi
    else
        docker rm "$node_a" >/dev/null || status=$?
        if [ "$status" -eq 0 ]; then
            start_node "$node_a" true || status=$?
        fi
    fi
fi

if [ "$status" -eq 0 ]; then
    cluster_restored=0
    for attempt in $(seq 1 45); do
        if docker exec "$node_a" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null && \
           docker exec "$node_b" curl --fail --silent http://127.0.0.1:5690/health/ready >/dev/null; then
            cluster_restored=1
            break
        fi
        sleep 1
    done
    if [ "$cluster_restored" -ne 1 ]; then
        echo "\033[0;31mPhoenix cluster did not recover readiness after node restart.\033[0m"
        status=1
    fi
fi

if [ "$status" -eq 0 ]; then
    change_topics verify || status=$?
fi

if [ "$status" -eq 0 ]; then
    docker exec \
        --env PHOENIX_SOCKET_URL="ws://${node_b}:5690" \
        --env SOCKET_PHOENIX_KAFKA_SOURCE_TOPIC="$source_topic" \
        --env PHOENIX_SOCKET_DLQ_TOPIC="$dlq_topic" \
        -i "${project_name}_api" \
        sh -lc 'cd /app && uv run --no-sync python -' \
        < scripts/test-phoenix-kafka-ingress.py || status=$?
fi

if [ "$status" -eq 0 ]; then
    docker stop --time 20 "$node_a" >/dev/null || status=$?
    node_a_exit=$(docker inspect --format '{{.State.ExitCode}}' "$node_a" 2>/dev/null)
    if [ "$node_a_exit" != "0" ]; then
        echo "\033[0;31mRestarted cluster ingress node did not stop gracefully (exit $node_a_exit).\033[0m"
        status=1
    fi
fi

if [ "$(docker inspect --format '{{.State.Running}}' "$node_b" 2>/dev/null)" = "true" ]; then
    docker stop --time 20 "$node_b" >/dev/null || status=$?
    node_b_exit=$(docker inspect --format '{{.State.ExitCode}}' "$node_b" 2>/dev/null)
    if [ "$node_b_exit" != "0" ]; then
        echo "\033[0;31mCluster WebSocket node did not stop gracefully (exit $node_b_exit).\033[0m"
        status=1
    fi
fi

if [ "$status" -ne 0 ]; then
    docker logs "$node_a" 2>/dev/null || true
    docker logs "$node_b" 2>/dev/null || true
else
    docker exec "${project_name}_api" cat "$reconnect_log" || status=$?
    echo "\033[0;32mPhoenix two-node cluster probe passed ($failure_mode).\033[0m"
fi

exit "$status"
