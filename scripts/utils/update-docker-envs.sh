#!/bin/bash
set -e

# Source utility functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/utils.sh"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "$ROOT_DIR"

source .env

if [[ ! "${MAX_FILE_SIZE_MB:-}" =~ ^[1-9][0-9]*$ ]]; then
    echo "MAX_FILE_SIZE_MB must be a positive integer." >&2
    exit 1
fi

# Leave room for multipart fields while preserving the configured per-file limit.
MAX_REQUEST_BODY_SIZE_BYTES=$(((MAX_FILE_SIZE_MB + 1) * 1024 * 1024))
export MAX_REQUEST_BODY_SIZE_BYTES

case "${SOCKET_OWNER:-node}" in
    node)
        SOCKET_HOST="${PROJECT_NAME}_socket"
        SOCKET_PORT="${SOCKET_PORT}"
        ;;
    phoenix)
        if [[ -z "${SOCKET_PHOENIX_INTERNAL_SECRET:-}" || ${#SOCKET_PHOENIX_INTERNAL_SECRET} -lt 32 ]]; then
            echo "SOCKET_PHOENIX_INTERNAL_SECRET must contain at least 32 characters before Phoenix can own the socket ingress." >&2
            exit 1
        fi
        if [[ "${SOCKET_RUNTIME:-node}" != "phoenix" ]]; then
            echo "SOCKET_RUNTIME must be phoenix when SOCKET_OWNER is phoenix." >&2
            exit 1
        fi
        if [[ "${SOCKET_PHOENIX_KAFKA_ENABLED:-false}" != "true" ]]; then
            echo "SOCKET_PHOENIX_KAFKA_ENABLED must be true before Phoenix can own the socket ingress." >&2
            exit 1
        fi
        if [[ "${NOTIFICATION_EMAIL_OUTBOX_ENABLED:-false}" != "true" ]]; then
            echo "NOTIFICATION_EMAIL_OUTBOX_ENABLED must be true before Phoenix can own the socket ingress." >&2
            exit 1
        fi
        for required_mail_setting in MAIL_SERVER MAIL_FROM; do
            if [[ -z "${!required_mail_setting:-}" ]]; then
                echo "${required_mail_setting} is required before Phoenix can own the socket ingress." >&2
                exit 1
            fi
        done
        if [[ ! "${MAIL_PORT:-}" =~ ^[1-9][0-9]*$ ]]; then
            echo "MAIL_PORT must be a positive integer before Phoenix can own the socket ingress." >&2
            exit 1
        fi
        if [[ -z "${BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP:-}" ]]; then
            echo "BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP is required before Phoenix can own the socket ingress." >&2
            exit 1
        fi
        for node_group_variable in \
            BROADCAST_NODE_FANOUT_CONSUMER_GROUP \
            BROADCAST_NODE_SIDE_EFFECT_CONSUMER_GROUP; do
            node_group="${!node_group_variable:-}"
            if [[ -n "${node_group}" && "${BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP}" == "${node_group}" ]]; then
                echo "BROADCAST_PHOENIX_FANOUT_CONSUMER_GROUP must differ from ${node_group_variable}." >&2
                exit 1
            fi
        done
        for required_flag in \
            SOCKET_PHOENIX_BOARD_CHAT_SEND_ENABLED \
            SOCKET_PHOENIX_BOARD_CHAT_RESUME_ENABLED \
            SOCKET_PHOENIX_BOARD_CHAT_RECOVERY_ENABLED \
            SOCKET_PHOENIX_EDITOR_AI_ENABLED; do
            if [[ "${!required_flag:-false}" != "true" ]]; then
                echo "${required_flag} must be true before Phoenix can own the socket ingress." >&2
                exit 1
            fi
        done
        if [[ "${EDITOR_SYNC_OWNER:-node}" != "phoenix" ]]; then
            echo "EDITOR_SYNC_OWNER must be phoenix before Phoenix can own the socket ingress." >&2
            exit 1
        fi
        if [[ "${SOCKET_PHOENIX_EDITOR_SYNC_ENABLED:-false}" != "true" ]]; then
            echo "SOCKET_PHOENIX_EDITOR_SYNC_ENABLED must be true before Phoenix can own the socket ingress." >&2
            exit 1
        fi
        if [[ ! "${SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES:-}" =~ ^[1-9][0-9]*$ ]]; then
            echo "SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES must be a positive integer before Phoenix can own the socket ingress." >&2
            exit 1
        fi
        SOCKET_HOST="${PROJECT_NAME}_socket_phoenix"
        SOCKET_PORT="5690"
        ;;
    *)
        echo "SOCKET_OWNER must be node or phoenix." >&2
        exit 1
        ;;
esac

case "${EDITOR_SYNC_OWNER:-node}" in
    node)
        SOCKET_EDITOR_HOST="${PROJECT_NAME}_socket"
        SOCKET_EDITOR_PORT="${SOCKET_PORT}"
        ;;
    phoenix)
        if [[ "${SOCKET_PHOENIX_EDITOR_SYNC_ENABLED:-false}" != "true" ]]; then
            echo "SOCKET_PHOENIX_EDITOR_SYNC_ENABLED must be true before Phoenix can own editor sync." >&2
            exit 1
        fi
        if [[ ! "${SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES:-}" =~ ^[1-9][0-9]*$ ]]; then
            echo "SOCKET_PHOENIX_EDITOR_SYNC_EXPECTED_NODES must be a positive integer before Phoenix can own editor sync." >&2
            exit 1
        fi
        SOCKET_EDITOR_HOST="${PROJECT_NAME}_socket_phoenix"
        SOCKET_EDITOR_PORT="5690"
        ;;
    *)
        echo "EDITOR_SYNC_OWNER must be node or phoenix." >&2
        exit 1
        ;;
esac

# Validate external postgres URLs if they are set
if [ -n "$POSTGRES_EXTERNAL_MAIN_URL" ]; then
    validate_postgres_url "$POSTGRES_EXTERNAL_MAIN_URL" "POSTGRES_EXTERNAL_MAIN_URL"

    if [ -n "$POSTGRES_EXTERNAL_REPLICA_URL" ]; then
        validate_postgres_url "$POSTGRES_EXTERNAL_REPLICA_URL" "POSTGRES_EXTERNAL_REPLICA_URL"
    fi
fi

# Set OpenBao URL if using openbao-local
if [[ "$KEY_PROVIDER_TYPE" == "openbao-local" ]]; then
    export KEY_PROVIDER_OPENBAO_URL="http://${PROJECT_NAME}_vault:8200"
    echo "OpenBao URL set to: $KEY_PROVIDER_OPENBAO_URL"
fi

declare -A service_envs=(
  [nginx]="server-common"
  [api]="server-common server"
  [ui]="server-common"
  [socket]="server-common server"
  [graph]="server-common server"
  [db_backup]="db-backup"
)

echo ${service_envs[@]}

for service in "${!service_envs[@]}"; do
  output_file="docker/envs/.${service}.env"
  echo "Generating $output_file from templates: ${service_envs[$service]}"

  : > "$output_file"

  for template in ${service_envs[$service]}; do
    template_path="docker/envs/${template}.env.template"

    if [[ -f "$template_path" ]]; then
      eval "$(cat "$template_path")"
      while read -r line; do
        if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)= ]]; then
          var_name="${BASH_REMATCH[1]}"
          echo "$var_name=${!var_name}" >> "$output_file"
        fi
      done < "$template_path"
    else
      echo "⚠️ Warning: template '$template_path' not found"
    fi
  done
done
