#!/usr/bin/env bash

set -u

export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

project_name="$1"
group_id="$2"

case "$group_id" in
    "${project_name}-phoenix-browser-"*|"${project_name}-phoenix-cluster-"*|"${project_name}-phoenix-probe-"*|"${project_name}-phoenix-dlq-recovery-"*) ;;
    *) echo "Refusing to delete a non-probe consumer group." >&2; exit 2 ;;
esac

for attempt in $(seq 1 15); do
    docker exec "${project_name}_kafka0" /opt/kafka/bin/kafka-consumer-groups.sh \
        --bootstrap-server localhost:9092 --delete --group "$group_id" >/dev/null 2>&1 || true
    if groups=$(docker exec "${project_name}_kafka0" /opt/kafka/bin/kafka-consumer-groups.sh \
        --bootstrap-server localhost:9092 --list 2>/dev/null) && ! printf '%s\n' "$groups" | grep -Fxq "$group_id"; then
        exit 0
    fi
    if [ "$attempt" -lt 15 ]; then sleep 5; fi
done

echo "Could not delete probe consumer group $group_id." >&2
exit 1
