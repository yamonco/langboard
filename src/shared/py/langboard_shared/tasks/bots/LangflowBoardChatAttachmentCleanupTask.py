from typing import Any
from ...ai.BoardChatAttachment import (
    delete_board_chat_attachment_ticket,
    get_board_chat_attachment_ticket,
    schedule_board_chat_attachment_cleanup,
    schedule_board_chat_attachment_reconciliation,
)
from ...ai.LangflowFileClient import LangflowFileClient
from ...core.broker import Broker
from ...core.logger import Logger
from ...core.types import SnowflakeID
from ...domain.models.InternalBot import InternalBot
from ...domain.models.InternalBotRun import InternalBotRun, InternalBotRunStatus
from ...domain.services import DomainService


_logger = Logger.use("board-chat-attachment-cleanup")
_RETRY_SECONDS = 60


@Broker.wrap_sync_task_decorator
def cleanup_board_chat_attachment(token: str) -> None:
    ticket = get_board_chat_attachment_ticket(token)
    if ticket is None:
        return

    service = DomainService()
    try:
        run = _get_run(service, ticket)
        if run is not None and run.status == InternalBotRunStatus.Completed:
            delete_board_chat_attachment_ticket(token)
            return

        if run is not None and run.status not in {
            InternalBotRunStatus.Failed,
            InternalBotRunStatus.Cancelled,
            InternalBotRunStatus.Uncertain,
        }:
            schedule_board_chat_attachment_cleanup(token, _RETRY_SECONDS)
            return

        bot = _get_bot(service, ticket)
        file_id = ticket.get("file_id")
        if bot is None or not isinstance(file_id, str) or not file_id:
            schedule_board_chat_attachment_cleanup(token, _RETRY_SECONDS)
            return

        if LangflowFileClient.delete(bot, file_id):
            delete_board_chat_attachment_ticket(token)
        else:
            schedule_board_chat_attachment_cleanup(token, _RETRY_SECONDS)
    except Exception:
        _logger.exception("Langflow board chat attachment cleanup failed")
        schedule_board_chat_attachment_cleanup(token, _RETRY_SECONDS)
    finally:
        service.close()


@Broker.wrap_sync_task_decorator
def reconcile_board_chat_attachment(run_uid: str) -> None:
    service = DomainService()
    try:
        run = service.internal_bot_run.get_board_chat_run(SnowflakeID.from_short_code(run_uid))
        if run is None:
            return

        request_payload = run.request_payload
        attachment = request_payload.get("attachment") if isinstance(request_payload, dict) else None
        if not isinstance(attachment, dict):
            return

        token = attachment.get("token")
        file_id = attachment.get("file_id")
        if not isinstance(token, str) or not token or not isinstance(file_id, str) or not file_id:
            return

        if run.status == InternalBotRunStatus.Completed:
            delete_board_chat_attachment_ticket(token)
            return
        if run.status not in {
            InternalBotRunStatus.Failed,
            InternalBotRunStatus.Cancelled,
            InternalBotRunStatus.Uncertain,
        }:
            schedule_board_chat_attachment_reconciliation(run_uid, _RETRY_SECONDS)
            return

        bot = service.internal_bot.get_by_id_like(run.internal_bot_id)
        if bot is not None and LangflowFileClient.delete(bot, file_id):
            delete_board_chat_attachment_ticket(token)
        else:
            schedule_board_chat_attachment_reconciliation(run_uid, _RETRY_SECONDS)
    except Exception:
        _logger.exception("Langflow board chat attachment reconciliation failed")
        schedule_board_chat_attachment_reconciliation(run_uid, _RETRY_SECONDS)
    finally:
        service.close()


def _get_run(service: DomainService, ticket: dict[str, Any]) -> InternalBotRun | None:
    run_uid = ticket.get("run_uid")
    if not isinstance(run_uid, str) or not run_uid:
        return None
    try:
        return service.internal_bot_run.get_board_chat_run(SnowflakeID.from_short_code(run_uid))
    except ValueError:
        return None


def _get_bot(service: DomainService, ticket: dict[str, Any]) -> InternalBot | None:
    bot_id = ticket.get("bot_id")
    if not isinstance(bot_id, int) or isinstance(bot_id, bool):
        return None
    return service.internal_bot.get_by_id_like(SnowflakeID(bot_id))
