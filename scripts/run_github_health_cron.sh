#!/bin/bash
set -e
cd /app
/app/.venv/bin/python -m langboard.apps.GitHubHealthWorker
