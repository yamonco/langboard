"""Fresh processes catch cycles hidden by already-initialized test modules."""

import os
import subprocess
import sys
import pytest


@pytest.mark.parametrize(
    "module",
    [
        "langboard_shared.tasks.webhooks.ExecutionReadinessUow",
        "langboard_shared.tasks.webhooks.ExecutionOutboxWorker",
        "langboard_shared.tasks.webhooks.ExecutionOutboxTask",
        "langboard_shared.domain.services",
    ],
)
def test_execution_modules_import_in_fresh_process(module: str) -> None:
    env = {**os.environ, "SENTRY_DSN": ""}
    result = subprocess.run(
        [sys.executable, "-c", f"import importlib; importlib.import_module({module!r})"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
