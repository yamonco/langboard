from secrets import token_urlsafe
from typing import Any
from ..core.broker import Broker
from ..core.caching import Cache
from ..Env import Env


_CACHE_PREFIX = "board-chat-attachment:"
_TICKET_USE_TTL_SECONDS = Env.AI_REQUEST_TIMEOUT + 10 * 60
_TICKET_RETENTION_SECONDS = _TICKET_USE_TTL_SECONDS + 10 * 60
LANGFLOW_BOARD_CHAT_ATTACHMENT_CLEANUP_TASK = (
    "langboard_shared.tasks.bots.LangflowBoardChatAttachmentCleanupTask.cleanup_board_chat_attachment"
)
LANGFLOW_BOARD_CHAT_ATTACHMENT_RECONCILIATION_TASK = (
    "langboard_shared.tasks.bots.LangflowBoardChatAttachmentCleanupTask.reconcile_board_chat_attachment"
)


def create_board_chat_attachment_token(ticket: dict[str, Any]) -> str:
    token = token_urlsafe(48)
    Cache.set(f"{_CACHE_PREFIX}{token}", ticket, _TICKET_RETENTION_SECONDS)
    return token


def schedule_board_chat_attachment_cleanup(token: str, delay_seconds: int = _TICKET_USE_TTL_SECONDS) -> None:
    Broker.celery.send_task(
        LANGFLOW_BOARD_CHAT_ATTACHMENT_CLEANUP_TASK,
        args=[token],
        countdown=max(1, delay_seconds),
    )


def schedule_board_chat_attachment_reconciliation(run_uid: str, delay_seconds: int = 1) -> None:
    Broker.celery.send_task(
        LANGFLOW_BOARD_CHAT_ATTACHMENT_RECONCILIATION_TASK,
        args=[run_uid],
        countdown=max(1, delay_seconds),
    )


def get_board_chat_attachment_ticket(token: str) -> dict[str, Any] | None:
    value = Cache.get(f"{_CACHE_PREFIX}{token}")
    return value if isinstance(value, dict) else None


def set_board_chat_attachment_ticket(token: str, ticket: dict[str, Any]) -> None:
    Cache.set(f"{_CACHE_PREFIX}{token}", ticket, _TICKET_RETENTION_SECONDS)


def delete_board_chat_attachment_ticket(token: str) -> None:
    Cache.delete(f"{_CACHE_PREFIX}{token}")
