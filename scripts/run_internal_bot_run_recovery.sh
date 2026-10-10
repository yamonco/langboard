#!/bin/bash -l

cd /app || exit 1
flock -n -E 0 /tmp/langboard-internal-bot-run-recovery.lock /app/.venv/bin/langboard run:internal-bot-runs:recover
