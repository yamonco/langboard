# ruff: noqa: F811
"""Optional disposable Redis + PostgreSQL worker boundary integration."""

import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4
import pytest
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import GitHubHealthJob
from redis import Redis
from sqlalchemy import text
from test_github_lifecycle import board, health_job, installation, lifecycle, receipt_storage, secrets  # noqa: F401


WORKER = """
import json, os
from pathlib import Path
from redis import Redis
from celery.signals import worker_ready
from langboard_shared.core.broker import Broker
from langboard.commands.RunBrokerCommand import RunBrokerCommand
from langboard.apps import GitHubResources
redis=Redis.from_url(os.environ['CACHE_URL'],decode_responses=True)
@worker_ready.connect
def ready(**kwargs): redis.set(os.environ['TEST_READY_KEY'],'ready')
def inspect(*args,**kwargs):
    redis.rpush(os.environ['TEST_CALLS_KEY'],json.dumps({'project_uid':args[2],'ids':kwargs['repository_ids']}))
    if os.environ['TEST_BLOCK_API']=='true':
        redis.set(os.environ['TEST_BLOCK_KEY'],'blocked')
        redis.blpop(os.environ['TEST_RELEASE_KEY'],timeout=30)
    return {'repositories':[{'id':value,'archived':False} for value in kwargs['repository_ids']]}
GitHubResources.inspect_installation=inspect
start=Broker.start
def start_private(argv):
    start(argv + ['--queues',os.environ['TEST_QUEUE'],'--hostname','github-proof@%h','--without-gossip','--without-mingle'])
Broker.start=start_private
Broker.celery.conf.task_default_queue=os.environ['TEST_QUEUE']
RunBrokerCommand().execute(None)
"""


PRODUCER = """
import os
from langboard_shared.core.broker import Broker
Broker.celery.conf.task_default_queue=os.environ['TEST_QUEUE']
from langboard.apps.GitHubHealthWorker import enqueue,recover_pending
if os.environ['TEST_RECOVERY']=='true':
    assert recover_pending()==1
else:
    enqueue(os.environ['TEST_JOB_UID'])
"""


@pytest.mark.parametrize("delivery", ["queued", "recovery", "crash"])
def test_real_redis_worker_processes_durable_pages(health_job, tmp_path, delivery):
    worker, service, board, connection, job, dispatched, receive, migration, engine = health_job
    url = os.environ.get("LANGBOARD_GITHUB_TEST_REDIS_URL")
    if not url or engine.dialect.name != "postgresql":
        pytest.skip("Set disposable Redis and PostgreSQL test URLs")
    redis = Redis.from_url(url, decode_responses=True)
    redis.ping()
    with engine.connect() as db:
        schema = db.execute(text("SELECT current_schema()")).scalar_one()
    database_url = engine.url.update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(
        hide_password=False
    )
    queue = "langboard-github-proof-" + uuid4().hex
    ready_key, calls_key = queue + ":ready", queue + ":calls"
    block_key, release_key = queue + ":blocked", queue + ":release"
    env = {
        **os.environ,
        "PROJECT_NAME": "langboard-shared",
        "CACHE_TYPE": "redis",
        "CACHE_URL": url,
        "BROKER_URL": url,
        "MAIN_DATABASE_URL": database_url,
        "READONLY_DATABASE_URL": database_url,
        "PYTHONPATH": "src/shared/py:src/api",
        "TEST_QUEUE": queue,
        "TEST_READY_KEY": ready_key,
        "TEST_CALLS_KEY": calls_key,
        "TEST_JOB_UID": job.get_uid(),
        "TEST_RECOVERY": "true" if delivery == "recovery" else "false",
        "TEST_BLOCK_API": "true" if delivery == "crash" else "false",
        "TEST_BLOCK_KEY": block_key,
        "TEST_RELEASE_KEY": release_key,
    }
    root = Path(__file__).resolve().parents[4]
    # Publish before a worker exists: delivery survives the absent consumer.
    producer = subprocess.run(
        [sys.executable, "-c", PRODUCER], cwd=root, env=env, capture_output=True, text=True, timeout=30
    )
    assert producer.returncode == 0, producer.stdout + producer.stderr
    assert redis.llen(queue) == 1
    logfile = tmp_path / "github-worker.log"
    with logfile.open("w") as output:
        process = subprocess.Popen(
            [sys.executable, "-c", WORKER], cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT
        )
        try:
            if delivery == "crash":
                deadline = monotonic() + 30
                while not redis.get(block_key):
                    assert process.poll() is None, logfile.read_text()[-10000:]
                    assert monotonic() < deadline, "Worker never reached API call"
                    sleep(0.1)
                process.kill()
                process.wait(timeout=5)
                with DbSession.use(readonly=False) as db:
                    current = db.exec(
                        SqlBuilder.select.table(GitHubHealthJob).where(GitHubHealthJob.id == job.id)
                    ).first()
                    assert current.state == "processing" and current.attempts == 1
                    assert current.project_id == 10 and current.resource_after is None
                    assert current.lease_token
                    # Advance the persisted lease expiry instead of waiting five minutes.
                    current.available_at = SafeDateTime.now() - timedelta(seconds=1)
                    db.update(current)
                env["TEST_RECOVERY"], env["TEST_BLOCK_API"] = "true", "false"
                producer = subprocess.run(
                    [sys.executable, "-c", PRODUCER], cwd=root, env=env, capture_output=True, text=True, timeout=30
                )
                assert producer.returncode == 0, producer.stdout + producer.stderr
                process = subprocess.Popen(
                    [sys.executable, "-c", WORKER], cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT
                )
            deadline = monotonic() + 40
            while monotonic() < deadline:
                assert process.poll() is None, logfile.read_text()[-10000:]
                with DbSession.use(readonly=False) as db:
                    current = db.exec(
                        SqlBuilder.select.table(GitHubHealthJob).where(GitHubHealthJob.id == job.id)
                    ).first()
                    if current.state == "blocked":
                        break
                sleep(0.1)
            else:
                pytest.fail("Redis worker did not complete bounded job: " + logfile.read_text()[-10000:])
            assert redis.get(ready_key) == "ready"
            assert current.blocked_boards == 1 and current.board_after == 11 and current.attempts == 0
            calls = [json.loads(value) for value in redis.lrange(calls_key, 0, -1)]
            assert [len(item["ids"]) for item in calls] == ([25, 25, 15] if delivery == "crash" else [25, 15])
            assert all(item["project_uid"] == board[2].get_uid() for item in calls)
            assert redis.llen(queue) == 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            redis.delete(queue, ready_key, calls_key, block_key, release_key, "_kombu.binding." + queue)
