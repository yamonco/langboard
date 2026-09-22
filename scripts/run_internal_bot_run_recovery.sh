#!/bin/bash -l

cd /app || exit 1
/app/.venv/bin/langboard run:internal-bot-runs:recover
