"""Exercise native Celery registration, packing and task cleanup in an isolated process."""

import os
import subprocess
import sys
from pathlib import Path


def test_api_worker_registers_and_dispatches_health_task():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from langboard_shared.core.broker import Broker
from langboard.commands.RunBrokerCommand import RunBrokerCommand
Broker.start=lambda argv: None
RunBrokerCommand().execute(None)
assert 'langboard.apps.GitHubHealthTask.github_health_task' in Broker.celery.tasks
Broker.celery.conf.update(task_always_eager=True, task_eager_propagates=True)
import langboard.apps.GitHubHealthTask as module
from langboard.apps.GitHubHealthWorker import enqueue
closed=[]
class Service:
    def close(self): closed.append(True)
module.DomainService=Service
calls=[]
module.drain_one=lambda service,uid: calls.append(uid)
enqueue('test-job')
assert calls==['test-job'] and closed==[True]
def fail(service,uid): raise RuntimeError('worker failure')
module.drain_one=fail
try: enqueue('test-job')
except RuntimeError: pass
else: raise AssertionError('task failure swallowed')
assert closed==[True,True]
print('native Celery dispatch and cleanup passed')
""",
        ],
        cwd=Path(__file__).resolve().parents[4],
        env={
            **os.environ,
            "PROJECT_NAME": "langboard-shared",
            "CACHE_TYPE": "redis",
            "CACHE_URL": "redis://127.0.0.1:6379/0",
            "BROKER_URL": "memory://",
            "PYTHONPATH": "src/shared/py:src/api",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "native Celery dispatch and cleanup passed" in result.stdout
