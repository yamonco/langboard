from asyncio import run
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
import orjson
import pytest
from fastapi import UploadFile
from langboard.middlewares.ChatUploadConcurrencyMiddleware import ChatUploadConcurrencyMiddleware
from langboard.routes.board import BoardChatApi
from langboard_shared.ai import BoardChatAttachment
from langboard_shared.core.routing import ApiException
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from langboard_shared.domain.models.InternalBotRun import InternalBotRunStatus
from langboard_shared.domain.models.User import User
from langboard_shared.domain.services import DomainService
from langboard_shared.tasks.bots import LangflowBoardChatAttachmentCleanupTask


PROJECT_UID = SnowflakeID(2).to_short_code()


def make_service() -> Mock:
    service = Mock(spec=DomainService)
    project = SimpleNamespace(id=SnowflakeID(2))
    bot = SimpleNamespace(
        id=SnowflakeID(3),
        platform=BotPlatform.Default,
        platform_running_type=BotPlatformRunningType.Default,
    )
    assignment = SimpleNamespace(project_id=SnowflakeID(2))
    service.project.get_by_id_like.return_value = project
    service.project.get_assigned_internal_bot_by_type.return_value = (bot, assignment)
    return service


def test_upload_returns_only_a_server_owned_attachment_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(BoardChatApi, "Env", SimpleNamespace(CACHE_TYPE="redis"))
    service = make_service()
    bot, assignment = service.project.get_assigned_internal_bot_by_type.return_value
    bot.platform = BotPlatform.Langflow
    bot.platform_running_type = BotPlatformRunningType.Endpoint
    assignment.project_id = SnowflakeID(2)
    uploaded = SimpleNamespace(file_id="file-id", path="user/file.pdf")
    upload_file = UploadFile(file=BytesIO(b"file contents"), filename="file.pdf")
    user = User.model_construct(id=SnowflakeID(1))
    upload = Mock(return_value=uploaded)
    create_ticket = Mock(return_value="opaque-token")
    schedule_cleanup = Mock()
    monkeypatch.setattr(BoardChatApi.LangflowFileClient, "upload", upload)
    monkeypatch.setattr(BoardChatApi, "create_board_chat_attachment_token", create_ticket)
    monkeypatch.setattr(BoardChatApi, "schedule_board_chat_attachment_cleanup", schedule_cleanup)

    response = BoardChatApi.upload_project_chat_attachment(
        PROJECT_UID,
        uuid4(),
        upload_file,
        user,
        service,
    )

    assert response.status_code == 201
    assert orjson.loads(response.body) == {"file_token": "opaque-token"}
    assert upload.call_args.args[:3] == (bot, upload_file.file, "file.pdf")
    create_ticket.assert_called_once()
    schedule_cleanup.assert_called_once_with("opaque-token")


def test_upload_rejects_non_langflow_project_chat_bots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(BoardChatApi, "Env", SimpleNamespace(CACHE_TYPE="redis"))
    service = make_service()
    upload_file = UploadFile(file=BytesIO(b"file contents"), filename="file.pdf")
    user = User.model_construct(id=SnowflakeID(1))

    with pytest.raises(ApiException.NotAcceptable_406):
        BoardChatApi.upload_project_chat_attachment(PROJECT_UID, uuid4(), upload_file, user, service)


def test_upload_concurrency_limit_rejects_before_reading_the_request_body() -> None:
    downstream = AsyncMock()
    receive = AsyncMock()
    send = AsyncMock()
    middleware = ChatUploadConcurrencyMiddleware(downstream)
    middleware._slots = Mock()
    middleware._slots.acquire.return_value = False
    scope = {"type": "http", "method": "POST", "path": f"/board/{PROJECT_UID}/chat/upload"}

    run(middleware(scope, receive, send))

    middleware._slots.acquire.assert_called_once_with(blocking=False)
    receive.assert_not_awaited()
    downstream.assert_not_awaited()
    start_message = send.await_args_list[0].args[0]
    assert start_message["status"] == 503


def test_upload_concurrency_slot_wraps_the_entire_request_body_lifecycle() -> None:
    receive = AsyncMock(return_value={"type": "http.request", "body": b"contents", "more_body": False})
    send = AsyncMock()

    async def downstream(scope, receive_request, send_response) -> None:
        assert scope["path"].endswith("/chat/upload")
        await receive_request()
        await send_response({"type": "http.response.start", "status": 201, "headers": []})
        await send_response({"type": "http.response.body", "body": b"", "more_body": False})

    middleware = ChatUploadConcurrencyMiddleware(downstream)
    middleware._slots = Mock()
    middleware._slots.acquire.return_value = True
    scope = {"type": "http", "method": "POST", "path": f"/board/{PROJECT_UID}/chat/upload"}

    run(middleware(scope, receive, send))

    receive.assert_awaited_once_with()
    middleware._slots.release.assert_called_once_with()


def test_cleanup_keeps_completed_attachment_for_history(monkeypatch: pytest.MonkeyPatch) -> None:
    service = make_service()
    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(status=InternalBotRunStatus.Completed)
    delete_ticket = Mock()
    delete_file = Mock()
    monkeypatch.setattr(LangflowBoardChatAttachmentCleanupTask, "DomainService", lambda: service)
    monkeypatch.setattr(
        LangflowBoardChatAttachmentCleanupTask,
        "get_board_chat_attachment_ticket",
        lambda token: {"run_uid": "run-uid", "file_id": "file-id"},
    )
    monkeypatch.setattr(LangflowBoardChatAttachmentCleanupTask, "delete_board_chat_attachment_ticket", delete_ticket)
    monkeypatch.setattr(LangflowBoardChatAttachmentCleanupTask.LangflowFileClient, "delete", delete_file)

    LangflowBoardChatAttachmentCleanupTask.cleanup_board_chat_attachment("opaque-token")

    delete_ticket.assert_called_once_with("opaque-token")
    delete_file.assert_not_called()
    service.close.assert_called_once()


def test_cleanup_retries_active_run_and_deletes_failed_attachment(monkeypatch: pytest.MonkeyPatch) -> None:
    service = make_service()
    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(status=InternalBotRunStatus.Failed)
    service.internal_bot.get_by_id_like.return_value = SimpleNamespace(id=SnowflakeID(3))
    schedule_cleanup = Mock()
    delete_ticket = Mock()
    delete_file = Mock(return_value=True)
    monkeypatch.setattr(LangflowBoardChatAttachmentCleanupTask, "DomainService", lambda: service)
    monkeypatch.setattr(
        LangflowBoardChatAttachmentCleanupTask,
        "get_board_chat_attachment_ticket",
        lambda token: {"run_uid": "run-uid", "bot_id": 3, "file_id": "file-id"},
    )
    monkeypatch.setattr(
        LangflowBoardChatAttachmentCleanupTask, "schedule_board_chat_attachment_cleanup", schedule_cleanup
    )
    monkeypatch.setattr(LangflowBoardChatAttachmentCleanupTask, "delete_board_chat_attachment_ticket", delete_ticket)
    monkeypatch.setattr(LangflowBoardChatAttachmentCleanupTask.LangflowFileClient, "delete", delete_file)

    LangflowBoardChatAttachmentCleanupTask.cleanup_board_chat_attachment("opaque-token")

    delete_file.assert_called_once_with(service.internal_bot.get_by_id_like.return_value, "file-id")
    delete_ticket.assert_called_once_with("opaque-token")
    schedule_cleanup.assert_not_called()


def test_cleanup_reschedules_an_active_run(monkeypatch: pytest.MonkeyPatch) -> None:
    service = make_service()
    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(status=InternalBotRunStatus.Streaming)
    schedule_cleanup = Mock()
    monkeypatch.setattr(LangflowBoardChatAttachmentCleanupTask, "DomainService", lambda: service)
    monkeypatch.setattr(
        LangflowBoardChatAttachmentCleanupTask,
        "get_board_chat_attachment_ticket",
        lambda token: {"run_uid": "run-uid", "file_id": "file-id"},
    )
    monkeypatch.setattr(
        LangflowBoardChatAttachmentCleanupTask, "schedule_board_chat_attachment_cleanup", schedule_cleanup
    )

    LangflowBoardChatAttachmentCleanupTask.cleanup_board_chat_attachment("opaque-token")

    schedule_cleanup.assert_called_once_with("opaque-token", 60)


def test_attachment_ticket_outlives_its_first_cleanup_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    cache_set = Mock()
    monkeypatch.setattr(BoardChatAttachment.Cache, "set", cache_set)

    BoardChatAttachment.create_board_chat_attachment_token({"file_id": "file-id"})

    assert cache_set.call_args.args[2] > BoardChatAttachment._TICKET_USE_TTL_SECONDS


def test_reconciliation_deletes_an_uncertain_attachment_from_the_durable_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = make_service()
    run = SimpleNamespace(
        status=InternalBotRunStatus.Uncertain,
        internal_bot_id=SnowflakeID(3),
        request_payload={"attachment": {"file_id": "file-id", "path": "user/file.pdf", "token": "token"}},
    )
    service.internal_bot_run.get_board_chat_run.return_value = run
    service.internal_bot.get_by_id_like.return_value = SimpleNamespace(id=SnowflakeID(3))
    delete_ticket = Mock()
    delete_file = Mock(return_value=True)
    monkeypatch.setattr(LangflowBoardChatAttachmentCleanupTask, "DomainService", lambda: service)
    monkeypatch.setattr(LangflowBoardChatAttachmentCleanupTask, "delete_board_chat_attachment_ticket", delete_ticket)
    monkeypatch.setattr(LangflowBoardChatAttachmentCleanupTask.LangflowFileClient, "delete", delete_file)

    LangflowBoardChatAttachmentCleanupTask.reconcile_board_chat_attachment(SnowflakeID(4).to_short_code())

    delete_file.assert_called_once_with(service.internal_bot.get_by_id_like.return_value, "file-id")
    delete_ticket.assert_called_once_with("token")
    service.close.assert_called_once()


def test_reconciliation_preserves_a_completed_attachment(monkeypatch: pytest.MonkeyPatch) -> None:
    service = make_service()
    service.internal_bot_run.get_board_chat_run.return_value = SimpleNamespace(
        status=InternalBotRunStatus.Completed,
        internal_bot_id=SnowflakeID(3),
        request_payload={"attachment": {"file_id": "file-id", "path": "user/file.pdf", "token": "token"}},
    )
    delete_ticket = Mock()
    delete_file = Mock()
    monkeypatch.setattr(LangflowBoardChatAttachmentCleanupTask, "DomainService", lambda: service)
    monkeypatch.setattr(LangflowBoardChatAttachmentCleanupTask, "delete_board_chat_attachment_ticket", delete_ticket)
    monkeypatch.setattr(LangflowBoardChatAttachmentCleanupTask.LangflowFileClient, "delete", delete_file)

    LangflowBoardChatAttachmentCleanupTask.reconcile_board_chat_attachment(SnowflakeID(4).to_short_code())

    delete_ticket.assert_called_once_with("token")
    delete_file.assert_not_called()
    service.close.assert_called_once()
