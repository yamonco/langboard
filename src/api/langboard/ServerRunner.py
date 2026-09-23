from langboard_shared import FastAPIRunner
from langboard_shared.Env import Env
from .Constants import APP_CONFIG_FILE, BASE_DIR


def run():
    from langboard_shared.ai import BotScheduleHelper

    cron = BotScheduleHelper.utils.get_cron()
    BotScheduleHelper.utils.create_job(
        cron,
        "* * * * *",
        "/app/.venv/bin/python -m langboard_shared.tasks.webhooks.ExecutionOutboxWorker drain",
        "execution-outbox-recovery",
    )
    BotScheduleHelper.utils.save_cron(cron)
    FastAPIRunner.run(f"{Env.PROJECT_NAME}.AppInstance:app", APP_CONFIG_FILE, BASE_DIR)
