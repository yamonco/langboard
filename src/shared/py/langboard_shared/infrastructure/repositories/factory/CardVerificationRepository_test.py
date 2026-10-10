from contextlib import contextmanager
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ....core.db import DbSession
from ....domain.models.CardVerificationRecord import CardVerificationRecord
from .CardVerificationRepository import CardVerificationRepository


def test_latest_record_query_is_scoped_and_sql_rejects_unattributed_or_invalid_decisions(monkeypatch):
    engine = create_engine("sqlite://")
    CardVerificationRecord.metadata.create_all(engine, tables=[CardVerificationRecord.__table__])
    now = datetime.now(timezone.utc)
    rows = [
        {"id": 1, "card_id": 10, "decision": "unverified", "source_change_seq": 1},
        {"id": 2, "card_id": 10, "decision": "verified", "source_change_seq": 2},
        {"id": 3, "card_id": 20, "decision": "verified", "source_change_seq": 4},
    ]
    with engine.begin() as connection:
        connection.execute(
            CardVerificationRecord.__table__.insert(),
            [
                {
                    **row,
                    "created_at": now,
                    "updated_at": now,
                    "recorded_by_user_id": 7,
                    "recorded_by_bot_id": None,
                    "evidence": [{"reference": "run:1"}],
                    "required_checkitem_uids": [],
                }
                for row in rows
            ],
        )

    @contextmanager
    def use(*, readonly):
        assert readonly is True
        with Session(engine, expire_on_commit=False) as session:
            yield DbSession(session, readonly=True)

    monkeypatch.setattr(DbSession, "use", use)
    repo = CardVerificationRepository(lambda _: None, lambda _: None)
    assert repo.get_latest_by_card_ids([]) == {}
    latest = repo.get_latest_by_card_ids([10])
    assert list(latest) == [10]
    assert latest[10].decision == "verified" and int(latest[10].id) == 2
    assert set(repo.get_latest_by_card_ids([10, 20])) == {10, 20}

    for decision, user_id, bot_id in [("made_up", 7, None), ("verified", None, None), ("verified", 7, 8)]:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                CardVerificationRecord.__table__.insert().values(
                    id=100 if decision == "made_up" else 101 if user_id is None else 102,
                    card_id=10,
                    decision=decision,
                    source_change_seq=5,
                    created_at=now,
                    updated_at=now,
                    recorded_by_user_id=user_id,
                    recorded_by_bot_id=bot_id,
                    evidence=[],
                    required_checkitem_uids=[],
                )
            )
