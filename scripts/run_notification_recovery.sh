#!/bin/bash -l

cd /app || exit 1
flock -n -E 0 /tmp/langboard-notification-recovery.lock /app/.venv/bin/langboard run:notification:recover
