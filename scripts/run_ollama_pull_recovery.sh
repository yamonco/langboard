#!/bin/bash -l

cd /app || exit 1
flock -n -E 0 /tmp/langboard-ollama-pull-recovery.lock /app/.venv/bin/langboard run:ollama-pulls:recover
