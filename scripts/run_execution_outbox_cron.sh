#!/bin/bash
set -e
cd /app
/app/.venv/bin/python -m langboard_shared.tasks.webhooks.ExecutionOutboxWorker drain
