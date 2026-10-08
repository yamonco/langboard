"""Run the existing cron tab without a privileged OS daemon."""

import fcntl
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from sys import argv
from time import sleep
from crontab import CronTab


class CronScheduler:
    def __init__(self, path: Path):
        self.path = path
        self.started_at = datetime.now()
        self.last_run: dict[tuple[str, str], datetime] = {}
        self.running: dict[tuple[str, str], Future] = {}

    def tick(self, pool: ThreadPoolExecutor, now: datetime):
        # Reload each tick so API workers can add/remove schedules atomically.
        with self.path.with_suffix(self.path.suffix + ".lock").open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
            tab = CronTab(user=False, tabfile=str(self.path))
        keys = set()
        for job in tab:
            if not job.is_enabled():
                continue
            # Existing shared tabs use /bin/bash as the system-tab user field.
            # OS user crontab interprets it as the command's interpreter.
            if job.user == "/bin/bash":
                job.command = f"/bin/bash {job.command}"
            key = (job.slices.special or str(job.slices), job.command)
            keys.add(key)
            previous = self.last_run.get(key, self.started_at)
            future = self.running.get(key)
            if future is not None:
                if not future.done():
                    continue
                try:
                    future.result()
                except Exception:
                    logging.exception("Cron job failed: %s", job.comment)
                del self.running[key]
            due = (
                key not in self.last_run
                if job.slices.special == "@reboot"
                else job.schedule(previous).get_next() <= now
            )
            if due and sum(not result.done() for result in self.running.values()) < 4:
                self.last_run[key] = now
                self.running[key] = pool.submit(job.run)
        self.last_run = {key: value for key, value in self.last_run.items() if key in keys}
        self.running = {key: future for key, future in self.running.items() if key in keys or not future.done()}


def run(path: Path):
    # API processes share one tab. Only one scheduler may own it at a time.
    with path.with_suffix(path.suffix + ".scheduler.lock").open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        scheduler = CronScheduler(path)
        with ThreadPoolExecutor(max_workers=4) as pool:
            while True:
                try:
                    scheduler.tick(pool, datetime.now())
                except Exception:
                    logging.exception("Cron tab refresh failed")
                sleep(10)


if __name__ == "__main__":
    run(Path(argv[1]))
