"""Cron changes remain visible and jobs cannot overlap in a non-root runtime."""

import fcntl
import importlib
from concurrent.futures import Future
from datetime import datetime, timedelta
import pytest


module = importlib.import_module("langboard_shared.core.utils.CronScheduler")
utils = importlib.import_module("langboard_shared.core.utils.CronTabUtils")


class Pool:
    def __init__(self):
        self.jobs = []
        self.functions = []

    def submit(self, fn):
        future = Future()
        self.jobs.append((fn.__self__.command, future))
        self.functions.append(fn)
        return future


def test_refresh_removal_and_no_overlapping_job(tmp_path):
    path = tmp_path / "cron.tab"
    path.write_text("* * * * * /bin/bash echo first\n")
    runner = module.CronScheduler(path)
    runner.started_at = datetime(2026, 10, 8, 12, 0)
    pool = Pool()
    runner.tick(pool, runner.started_at + timedelta(minutes=1))
    runner.tick(pool, runner.started_at + timedelta(minutes=2))
    assert len(pool.jobs) == 1
    pool.jobs[0][1].set_result(None)
    path.write_text("* * * * * /bin/bash echo replacement\n")
    runner.tick(pool, runner.started_at + timedelta(minutes=3))
    assert [command for command, _ in pool.jobs] == ["echo first", "echo replacement"]
    assert all("first" not in command for _, command in runner.last_run)


def test_real_job_execution_and_reboot_only_once(tmp_path):
    output = tmp_path / "ran"
    path = tmp_path / "cron.tab"
    path.write_text(f"@reboot /bin/bash printf success > {output}\n")
    runner = module.CronScheduler(path)
    pool = Pool()
    runner.tick(pool, datetime.now())
    assert len(pool.jobs) == 1
    assert pool.functions[0]().returncode == 0
    assert output.read_text() == "success"
    pool.jobs[0][1].set_result(None)
    runner.tick(pool, datetime.now() + timedelta(minutes=1))
    assert len(pool.jobs) == 1


def test_non_root_reload_avoids_system_cron(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(utils, "_scheduler_process", None)
    monkeypatch.setattr(utils.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(utils, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(utils, "subprocess_run", lambda *args, **kwargs: pytest.fail("OS cron requires root"))
    cron = utils.CronTabUtils(tmp_path / "cron.tab")
    cron._CronTabUtils__reload_cron()
    assert calls[0][0][0][-1] == str(tmp_path / "cron.tab")
    assert calls[0][1]["start_new_session"] is True


def test_shared_tab_has_one_scheduler_and_bounded_work(tmp_path, monkeypatch):
    path = tmp_path / "cron.tab"
    path.write_text("".join(f"* * * * * /bin/bash echo {i}\n" for i in range(6)))
    runner = module.CronScheduler(path)
    pool = Pool()
    runner.tick(pool, runner.started_at + timedelta(minutes=1))
    assert len(pool.jobs) == 4
    with path.with_suffix(".tab.scheduler.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setattr(module, "sleep", lambda _: pytest.fail("Duplicate scheduler started"))
        module.run(path)
