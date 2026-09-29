import os
from unittest.mock import Mock, patch

from sqlalchemy.dialects import postgresql

os.environ.setdefault("PROJECT_NAME", "langboard")

from langboard_shared.infrastructure.repositories.factory.CardRepository import CardRepository  # noqa: E402


def test_reordering_a_card_does_not_refresh_neighbor_timestamps() -> None:
    repository = CardRepository(lambda *_: None, lambda *_: None)
    database = Mock()
    with patch("langboard_shared.core.domain.BaseOrderRepository.DbSession.use") as use:
        use.return_value.__enter__.return_value = database
        repository.update_row_order(10, 20, 0, 0, 21, preserve_shifted_updated_at=True)

    statements = [str(call.args[0].compile(dialect=postgresql.dialect())) for call in database.exec.call_args_list]
    assert len(statements) == 3
    assert all("updated_at=card.updated_at" in statement for statement in statements)
