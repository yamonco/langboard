from collections.abc import Iterator
from datetime import timedelta
from unittest.mock import Mock
import orjson
import pytest
from fastapi import Request
from langboard.routes.auth import SocketAuthApi
from langboard.routes.settings import OllamaApi
from langboard.routes.settings.Form import OllamaModelForm
from langboard_shared.core.broker import Broker
from langboard_shared.core.db.DbEngine import DbEngine
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.publisher import BaseSocketPublisher
from langboard_shared.core.routing import ApiException, JsonResponse
from langboard_shared.core.types import SafeDateTime, SnowflakeID
from langboard_shared.domain.models import OllamaModelPull, SettingRole, User
from langboard_shared.domain.models.OllamaModelPull import OllamaModelPullStatus
from langboard_shared.domain.models.SettingRole import SettingRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.filter import RoleFilter
from langboard_shared.infrastructure.repositories.factory.OllamaModelPullRepository import OllamaModelPullRepository
from langboard_shared.tasks.ollama import OllamaModelPullTask
from langboard_shared.tasks.ollama.OllamaModelPullTask import pull_model
from pytest import MonkeyPatch
from sqlalchemy import create_engine


@pytest.fixture
def pull_repository(monkeypatch: MonkeyPatch) -> Iterator[OllamaModelPullRepository]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    OllamaModelPull.__table__.create(engine)
    monkeypatch.setattr(DbEngine, "get_main_engine", lambda: engine)
    monkeypatch.setattr(DbEngine, "get_readonly_engine", lambda: engine)
    yield OllamaModelPullRepository(lambda repository_type: None, lambda name: None)
    engine.dispose()


def test_pull_acceptance_deduplicates_and_fences_old_attempts(pull_repository: OllamaModelPullRepository) -> None:
    first, accepted = pull_repository.accept("model:latest")
    assert accepted
    assert first.status == OllamaModelPullStatus.Pending

    duplicate, accepted = pull_repository.accept("model:latest")
    assert not accepted
    assert duplicate.id == first.id

    assert pull_repository.reserve_dispatch(first.id, first.attempt)
    assert not pull_repository.reserve_dispatch(first.id, first.attempt)
    assert pull_repository.claim(first.id, first.attempt)
    assert not pull_repository.claim(first.id, first.attempt)
    assert pull_repository.report(first.id, first.attempt, 42.0, "downloading")
    assert pull_repository.finish(first.id, first.attempt, OllamaModelPullStatus.Failed, "network")

    second, accepted = pull_repository.accept("model:latest")
    assert accepted
    assert second.id == first.id
    assert second.attempt == first.attempt + 1
    assert not pull_repository.report(first.id, first.attempt, 99.0, "stale")
    assert not pull_repository.finish(first.id, first.attempt, OllamaModelPullStatus.Success)
    assert pull_repository.reserve_dispatch(second.id, second.attempt)
    assert pull_repository.claim(second.id, second.attempt)
    assert pull_repository.finish(second.id, second.attempt, OllamaModelPullStatus.Success)
    saved = pull_repository.get_by_id(second.id)
    assert saved is not None
    assert saved.status == OllamaModelPullStatus.Success


def test_stale_queue_and_worker_are_fenced(pull_repository: OllamaModelPullRepository) -> None:
    pull, _ = pull_repository.accept("model:latest")
    assert pull_repository.reserve_dispatch(pull.id, pull.attempt)
    assert pull_repository.mark_stale_queued_pending(SafeDateTime.now() + timedelta(seconds=1), 1) == 1
    assert not pull_repository.claim(pull.id, pull.attempt)

    assert pull_repository.reserve_dispatch(pull.id, pull.attempt)
    assert pull_repository.claim(pull.id, pull.attempt)
    stale = pull_repository.mark_stale_uncertain(SafeDateTime.now() + timedelta(seconds=1), 1)
    assert [item.id for item in stale] == [pull.id]
    assert not pull_repository.report(pull.id, pull.attempt, 75.0, "late")
    assert not pull_repository.finish(pull.id, pull.attempt, OllamaModelPullStatus.Success)
    saved = pull_repository.get_by_id(pull.id)
    assert saved is not None
    assert saved.status == OllamaModelPullStatus.Uncertain


def test_active_pull_remains_visible_after_newer_completed_pulls(pull_repository: OllamaModelPullRepository) -> None:
    active, _ = pull_repository.accept("active:latest")
    for model_name in ("completed:first", "completed:second"):
        completed, _ = pull_repository.accept(model_name)
        assert pull_repository.reserve_dispatch(completed.id, completed.attempt)
        assert pull_repository.claim(completed.id, completed.attempt)
        assert pull_repository.finish(completed.id, completed.attempt, OllamaModelPullStatus.Success)

    recent = pull_repository.get_recent(2)
    assert [pull.model_name for pull in recent] == ["active:latest", "completed:second"]


def test_accepted_pull_survives_queue_failure(monkeypatch: MonkeyPatch, pull_repository: OllamaModelPullRepository) -> None:
    monkeypatch.setattr(Broker.celery, "send_task", Mock(side_effect=RuntimeError("queue unavailable")))
    with DomainService.use() as service:
        pull = service.ollama_model_pull.request_pull("  model:latest  ")
    assert pull.model_name == "model:latest"
    saved = pull_repository.get_by_id(pull.id)
    assert saved is not None
    assert saved.status == OllamaModelPullStatus.Pending

    queued = Mock()
    monkeypatch.setattr(Broker.celery, "send_task", queued)
    with DomainService.use() as service:
        assert service.ollama_model_pull.recover() == (0, 1)
    assert queued.call_args.args[0].endswith(".pull_model")
    assert queued.call_args.kwargs["args"] == [int(pull.id), pull.attempt]


def test_pull_api_keeps_admin_and_role_filters(monkeypatch: MonkeyPatch) -> None:
    assert AuthFilter.get_filtered(OllamaApi.pull_ollama_model) == "admin"
    role_model, actions, _finder, allowed_all_admin = RoleFilter.get_filtered(OllamaApi.pull_ollama_model)
    assert role_model is SettingRole
    assert actions == [SettingRoleAction.OllamaRead.value]
    assert allowed_all_admin is False

    monkeypatch.setattr(type(Env), "OLLAMA_API_URL", property(lambda self: "http://ollama.example.invalid"))
    pull = OllamaModelPull.model_construct(
        id=SnowflakeID(1), model_name="model:latest", status=OllamaModelPullStatus.Queued, percent=0.0, attempt=1
    )
    service = Mock()
    service.ollama_model_pull.request_pull.return_value = pull
    response = OllamaApi.pull_ollama_model(OllamaModelForm(model="model:latest"), service)
    assert orjson.loads(response.body) == {
        "uid": pull.get_uid(),
        "model": "model:latest",
        "status": "queued",
        "percent": 0.0,
        "attempt": 1,
    }


def test_socket_pull_uses_bearer_and_rechecks_ollama_role(monkeypatch: MonkeyPatch) -> None:
    user = User.model_construct(
        id=SnowflakeID(1), email="socket-ollama@example.invalid", is_admin=True, activated_at=SafeDateTime.now()
    )
    monkeypatch.setattr(SocketAuthApi.AuthSecurity, "decode_access_token", lambda token: {"sub": "1"})
    monkeypatch.setattr(SocketAuthApi.Auth, "get_user_by_id", lambda user_id: user)
    accepted = Mock(return_value=JsonResponse({"status": "queued"}))
    monkeypatch.setattr(SocketAuthApi, "pull_ollama_model", accepted)
    service = Mock()
    role = Mock()
    role.is_granted.return_value = True
    service.user.get_setting_role.return_value = role
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer access-token")]})
    form = OllamaModelForm(model="model:latest")

    response = SocketAuthApi.pull_socket_ollama_model(request, form, service)
    assert orjson.loads(response.body) == {"status": "queued"}
    accepted.assert_called_once_with(form, service)
    role.is_granted.assert_called_once_with(SettingRoleAction.OllamaRead)

    role.is_granted.return_value = False
    with pytest.raises(ApiException.Forbidden_403):
        SocketAuthApi.pull_socket_ollama_model(request, form, service)
    accepted.assert_called_once()


class _PullResponse:
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        assert chunk_size == 8192
        yield from self.chunks


@pytest.mark.parametrize(
    ("chunks", "expected_status"),
    [
        ([b'{"status":"pull', b'ing","completed":1,"total":2}\n', b'{"status":"success"}\n'], OllamaModelPullStatus.Success),
        ([b'{"status":"pulling"}\n{"error":"upstream failed"}\n'], OllamaModelPullStatus.Failed),
        ([b'{"status":"pulling"}\n'], OllamaModelPullStatus.Failed),
        ([b'{"status":"' + b"x" * (64 * 1024) + b'"}\n'], OllamaModelPullStatus.Failed),
    ],
)
def test_worker_records_only_explicit_terminal_outcomes(
    monkeypatch: MonkeyPatch,
    pull_repository: OllamaModelPullRepository,
    chunks: list[bytes],
    expected_status: OllamaModelPullStatus,
) -> None:
    monkeypatch.setattr(Broker.celery, "send_task", Mock())
    monkeypatch.setattr(BaseSocketPublisher, "put_dispather", Mock())
    monkeypatch.setattr(type(Env), "OLLAMA_API_URL", property(lambda self: "http://ollama.example.invalid"))
    response = _PullResponse(chunks)
    monkeypatch.setattr(OllamaModelPullTask.requests, "post", Mock(return_value=response))
    with DomainService.use() as service:
        pull = service.ollama_model_pull.request_pull("model:latest")

    pull_model(int(pull.id), pull.attempt)
    saved = pull_repository.get_by_id(pull.id)
    assert saved is not None
    assert saved.status == expected_status
