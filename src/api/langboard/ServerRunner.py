from langboard_shared import FastAPIRunner
from langboard_shared.Env import Env
from .Constants import APP_CONFIG_FILE, BASE_DIR


def run():
    from langboard_shared.ai import BotScheduleHelper

    cron_utils = BotScheduleHelper.utils
    cron = cron_utils.get_cron()
    interval = "* * * * *"
    for command, comment in (
        ("/app/scripts/run_notification_recovery.sh", "notification-web-fanout-recovery"),
        ("/app/scripts/run_ollama_pull_recovery.sh", "ollama-pull-recovery"),
        ("/app/scripts/run_internal_bot_run_recovery.sh", "internal-bot-run-recovery"),
    ):
        existing_jobs = list(cron.find_comment(comment))
        if (
            len(existing_jobs) == 1
            and str(existing_jobs[0].command) == command
            and str(existing_jobs[0].slices) == interval
        ):
            continue
        if existing_jobs:
            cron_utils.remove_job(cron, comment)
        cron_utils.create_job(cron, interval, command, comment)
        cron_utils.save_cron(cron)
    cron_utils.reload_cron()
    FastAPIRunner.run(f"{Env.PROJECT_NAME}.AppInstance:app", APP_CONFIG_FILE, BASE_DIR)
