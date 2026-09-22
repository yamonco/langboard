#!/bin/bash -l

cd /app || exit 1
/app/.venv/bin/langboard run:notification:recover
