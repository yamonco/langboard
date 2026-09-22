from unittest.mock import Mock
import pytest
from langboard_shared.core.broker import Broker
from pytest import MonkeyPatch


def test_required_broker_tasks_must_exist_on_every_worker(monkeypatch: MonkeyPatch) -> None:
    inspector = Mock()
    inspector.registered.return_value = {
        "celery@current": ["task.cleanup", "task.reconcile"],
        "celery@stale": ["task.cleanup"],
    }
    monkeypatch.setattr(Broker.celery.control, "inspect", Mock(return_value=inspector))

    with pytest.raises(RuntimeError, match=r"celery@stale: task\.reconcile"):
        Broker.require_registered_tasks(("task.cleanup", "task.reconcile"))


def test_required_broker_tasks_return_registered_workers(monkeypatch: MonkeyPatch) -> None:
    registrations = {"celery@current": ["task.cleanup", "task.reconcile"]}
    inspector = Mock()
    inspector.registered.return_value = registrations
    inspect = Mock(return_value=inspector)
    monkeypatch.setattr(Broker.celery.control, "inspect", inspect)

    assert Broker.require_registered_tasks(("task.cleanup", "task.reconcile"), timeout=3) == registrations
    inspect.assert_called_once_with(timeout=3)


def test_required_broker_tasks_require_a_responsive_worker(monkeypatch: MonkeyPatch) -> None:
    inspector = Mock()
    inspector.registered.return_value = None
    monkeypatch.setattr(Broker.celery.control, "inspect", Mock(return_value=inspector))

    with pytest.raises(RuntimeError, match="No Celery workers responded"):
        Broker.require_registered_tasks(("task.cleanup",))
