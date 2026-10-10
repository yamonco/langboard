import os
from datetime import timedelta
from types import SimpleNamespace


os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.core.types import SafeDateTime  # noqa: E402
from langboard_shared.domain.models.Checkitem import CheckitemStatus  # noqa: E402
from langboard_shared.domain.services.factory.CardService import CardService  # noqa: E402


def test_active_worker_projection_deduplicates_people_and_keeps_each_timer() -> None:
    now = SafeDateTime.now()
    user_id = SimpleNamespace(to_short_code=lambda: "worker")
    first = SimpleNamespace(
        user_id=user_id,
        id=1,
        title="Write",
        status=CheckitemStatus.Started,
        accumulated_seconds=30,
        get_uid=lambda: "one",
    )
    second = SimpleNamespace(
        user_id=user_id,
        id=2,
        title="Review",
        status=CheckitemStatus.Paused,
        accumulated_seconds=70,
        get_uid=lambda: "two",
    )
    checklist = SimpleNamespace(card_id=42)
    repo = SimpleNamespace(
        checkitem=SimpleNamespace(
            get_active_workers_by_project=lambda *_args: [
                (first, checklist, now - timedelta(seconds=10)),
                (second, checklist, None),
            ]
        )
    )

    projected = CardService.get_active_workers(SimpleNamespace(repo=repo), SimpleNamespace())
    assert len(projected[42]) == 1
    worker = projected[42][0]
    assert worker["user_uid"] == "worker"
    assert worker["status"] == "started"
    assert [item["uid"] for item in worker["checkitems"]] == ["one", "two"]
    assert worker["elapsed_seconds"] >= 110
